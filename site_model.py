"""
site_model.py — project/site.json 로더 + 다층 격자 + VerticalLink 경로 (Phase 2, P2-2)
====================================================================================
(모듈명 주의: 표준 라이브러리 `site` 와 충돌하므로 site_model 로 명명.)
8개 층 격자·zone·계단 링크를 읽어 층별 2D 격자로 보관하고, 층간 이동을
"층별 위험가중 Theta*(movement.theta_route) + 링크 traversal"로 계획한다.

경계 (§1-2, §3): site.json은 '프로젝트 사실'이다. 대책 효과·확률은 여기 없다.
층간 직접 점프 금지 — 반드시 VerticalLink 경유. availableFromActivity가 있으면
그 액티비티 완료 전엔 링크 비활성(영구계단 조기설치 TemporalRule 대비, Phase 3).
"""
import heapq
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

import config as C
from movement import theta_route, _octile
from random_streams import stable_seed

Cell = Tuple[int, int]


@dataclass
class Zone:
    zone_id: str
    zone_type: str                 # work / storage / route / restricted / welfare
    cells: List[Cell]


@dataclass
class Level:
    level_id: str
    elevation_m: float
    grid: np.ndarray               # (rows, cols) 셀타입 배열
    zones: Dict[str, Zone] = field(default_factory=dict)
    source_ifc_storey: Optional[str] = None

    @property
    def rows(self) -> int:
        return self.grid.shape[0]

    @property
    def cols(self) -> int:
        return self.grid.shape[1]

    def walkable_cells(self) -> List[Cell]:
        R, Co = self.grid.shape
        return [(r, c) for r in range(R) for c in range(Co)
                if self.grid[r, c] not in (C.WALL, C.FLOOR_OPENING)]

    def zone_cells(self, zone_id: str, walkable_only: bool = True) -> List[Cell]:
        z = self.zones.get(zone_id)
        if z is None:
            return []
        if not walkable_only:
            return list(z.cells)
        return [(r, c) for (r, c) in z.cells
                if self.grid[r, c] not in (C.WALL, C.FLOOR_OPENING)]

    def main_component(self) -> List[Cell]:
        """가장 큰 연결 walkable 컴포넌트(4방 인접). 워커 스폰·목적지 표집의 기준.
        (실제 IFC 래스터화에서 생기는 소수 고립 조각을 배제해 경로가 항상 유효하게 함.)"""
        cached = getattr(self, "_main_comp", None)
        if cached is not None:
            return cached
        R, Co = self.grid.shape
        blocked = (C.WALL, C.FLOOR_OPENING)
        seen = np.zeros((R, Co), dtype=bool)
        best: List[Cell] = []
        from collections import deque
        for r0 in range(R):
            for c0 in range(Co):
                if seen[r0, c0] or self.grid[r0, c0] in blocked:
                    continue
                comp: List[Cell] = []
                q = deque([(r0, c0)])
                seen[r0, c0] = True
                while q:
                    r, c = q.popleft()
                    comp.append((r, c))
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        nr, nc = r + dr, c + dc
                        if (0 <= nr < R and 0 <= nc < Co and not seen[nr, nc]
                                and self.grid[nr, nc] not in blocked):
                            seen[nr, nc] = True
                            q.append((nr, nc))
                if len(comp) > len(best):
                    best = comp
        self._main_comp = best
        return best


@dataclass
class VerticalLink:
    link_id: str
    link_type: str                 # stair / ramp / hoist / ladder
    connects: List[Tuple[str, Cell]]      # [(levelID, (r,c)), ...]
    capacity: int = 1
    traversal_steps: int = 1
    available_from_activity: Optional[str] = None

    def endpoint_on(self, level_id: str) -> Optional[Cell]:
        for lv, cell in self.connects:
            if lv == level_id:
                return cell
        return None

    def other_level(self, level_id: str) -> Optional[str]:
        for lv, _ in self.connects:
            if lv != level_id:
                return lv
        return None

    def is_available(self, completed_activities=frozenset()) -> bool:
        return (self.available_from_activity is None
                or self.available_from_activity in completed_activities)


class SiteModel:
    """다층 현장 모델. 층별 격자 + 계단 링크 그래프."""

    def __init__(self, site_id: str, grid_resolution_m: float,
                 levels: List[Level], links: List[VerticalLink]):
        self.site_id = site_id
        self.grid_resolution_m = grid_resolution_m
        self.levels: Dict[str, Level] = {lv.level_id: lv for lv in levels}
        self.links: List[VerticalLink] = links
        self.level_order = sorted(self.levels, key=lambda k: int(k.lstrip("L")))

    # ── 로딩 ──
    @classmethod
    def load(cls, path: str) -> "SiteModel":
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
        levels = []
        for lv in raw["levels"]:
            g = np.array(lv["grid"]["cells"], dtype=int)
            if g.shape != (lv["grid"]["rows"], lv["grid"]["cols"]):
                raise ValueError(f"{lv['levelID']}: grid rows/cols와 cells 배열 불일치")
            zones = {z["zoneID"]: Zone(z["zoneID"], z.get("zoneType", "work"),
                                       [tuple(cell) for cell in z["cells"]])
                     for z in lv.get("zones", [])}
            levels.append(Level(lv["levelID"], float(lv.get("elevation_m", 0.0)),
                                g, zones, lv.get("sourceIfcStorey")))
        links = []
        for lk in raw.get("verticalLinks", []):
            connects = [(c["level"], tuple(c["cell"])) for c in lk["connects"]]
            links.append(VerticalLink(
                lk["linkID"], lk.get("linkType", "stair"), connects,
                int(lk.get("capacity", 1)), int(lk.get("traversalSteps", 1)),
                lk.get("availableFromActivity")))
        return cls(raw.get("siteID", ""), float(raw.get("gridResolution_m", 1.0)),
                   levels, links)

    # ── 조회 ──
    def level(self, level_id: str) -> Level:
        return self.levels[level_id]

    def grid(self, level_id: str) -> np.ndarray:
        return self.levels[level_id].grid

    def below(self, level_id: str) -> Optional[str]:
        n = int(level_id.lstrip("L"))
        return f"L{n - 1}" if f"L{n - 1}" in self.levels else None

    def above(self, level_id: str) -> Optional[str]:
        n = int(level_id.lstrip("L"))
        return f"L{n + 1}" if f"L{n + 1}" in self.levels else None

    # ── 링크 그래프 ──
    def usable_links(self, completed_activities=frozenset()) -> List[VerticalLink]:
        return [lk for lk in self.links if lk.is_available(completed_activities)]

    def level_adjacency(self, completed_activities=frozenset()) -> Dict[str, List[str]]:
        adj: Dict[str, List[str]] = {lv: [] for lv in self.levels}
        for lk in self.usable_links(completed_activities):
            lvs = [lv for lv, _ in lk.connects]
            for a in lvs:
                for b in lvs:
                    if a != b and b not in adj[a]:
                        adj[a].append(b)
        return adj

    def _nearest_walkable(self, level_id: str, cell: Cell) -> Cell:
        """cell이 walkable이 아니면(계단/벽/개구부 마커) 가장 가까운 walkable 셀로 스냅.
        링크 엔드포인트가 격자상 non-walkable로 찍혀 있어도 접근 셀을 찾게 한다."""
        from collections import deque
        grid = self.grid(level_id)
        R, Co = grid.shape
        blocked = (C.WALL, C.FLOOR_OPENING)
        r0, c0 = cell
        if not (0 <= r0 < R and 0 <= c0 < Co):
            return cell
        if grid[r0, c0] not in blocked:
            return cell
        seen = {cell}
        q = deque([cell])
        while q:
            r, c = q.popleft()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < R and 0 <= nc < Co and (nr, nc) not in seen:
                    if grid[nr, nc] not in blocked:
                        return (nr, nc)
                    seen.add((nr, nc))
                    q.append((nr, nc))
        return cell

    def plan_path(self, start: Tuple[str, Cell], goal: Tuple[str, Cell],
                  rho: float, rng, effects=None, completed_activities=frozenset(),
                  noise_seed=None):
        """다층 경로. 반환: (segments, cost) 또는 (None, inf).

        segments: [("move", level, [cell,...]), ("link", link_id, from→to, steps), ...]
        층내 이동은 movement.theta_route(any-angle), 링크는 traversal_steps 비용.
        링크 체인은 traversal 비용 Dijkstra, 층내 실제 경로는 Theta*로 복원한다.
        링크 엔드포인트는 walkable 접근셀로 스냅해 사용한다.
        """
        (sl, sc), (gl, gc) = start, goal
        sc = self._nearest_walkable(sl, sc)
        gc = self._nearest_walkable(gl, gc)
        segment_index = 0

        def _theta(level_id, a, b):
            nonlocal segment_index
            keyed = (None if noise_seed is None else
                     stable_seed(noise_seed, "segment", segment_index,
                                 level_id, a, b))
            segment_index += 1
            return theta_route(self.grid(level_id), a, b, rho, rng, effects,
                               noise_seed=keyed)

        if sl == gl:
            route = _theta(sl, sc, gc)
            if not route and sc != gc:
                return None, float("inf")
            return [("move", sl, route)], _octile(sc, gc)

        # 층 시퀀스 탐색 (링크 그래프 위 BFS/Dijkstra) → 링크 체인
        link_chain = self._link_chain(sl, gl, completed_activities)
        if link_chain is None:
            return None, float("inf")

        segments, cost = [], 0.0
        cur_level, cur_cell = sl, sc
        for lk in link_chain:
            enter = self._nearest_walkable(cur_level, lk.endpoint_on(cur_level))
            nxt_level = lk.other_level(cur_level)
            exit_cell = self._nearest_walkable(nxt_level, lk.endpoint_on(nxt_level))
            route = _theta(cur_level, cur_cell, enter)
            segments.append(("move", cur_level, route))
            cost += _octile(cur_cell, enter)
            segments.append(("link", lk.link_id, (cur_level, nxt_level), lk.traversal_steps))
            cost += lk.traversal_steps
            cur_level, cur_cell = nxt_level, exit_cell
        route = _theta(cur_level, cur_cell, gc)
        segments.append(("move", cur_level, route))
        cost += _octile(cur_cell, gc)
        return segments, cost

    def _link_chain(self, start_level: str, goal_level: str,
                    completed_activities=frozenset()) -> Optional[List[VerticalLink]]:
        """start_level→goal_level 을 잇는 링크 시퀀스(최소 홉). Dijkstra(홉수+traversal)."""
        usable = self.usable_links(completed_activities)
        by_level: Dict[str, List[VerticalLink]] = {lv: [] for lv in self.levels}
        for lk in usable:
            for lv, _ in lk.connects:
                by_level[lv].append(lk)
        # (cost, tie, level, chain)
        pq = [(0.0, 0, start_level, [])]
        seen = set()
        tie = 1
        while pq:
            cost, _, lv, chain = heapq.heappop(pq)
            if lv == goal_level:
                return chain
            if lv in seen:
                continue
            seen.add(lv)
            for lk in by_level[lv]:
                nxt = lk.other_level(lv)
                if nxt is None or nxt in seen:
                    continue
                heapq.heappush(pq, (cost + lk.traversal_steps, tie, nxt, chain + [lk]))
                tie += 1
        return None


class LinkOccupancy:
    """링크 capacity 시행 — 동시 통행 인원 제한(호이스트/계단 병목). 초과 시 대기."""

    def __init__(self, site: SiteModel):
        self._cap = {lk.link_id: lk.capacity for lk in site.links}
        self._inuse: Dict[str, int] = {lk.link_id: 0 for lk in site.links}

    def try_enter(self, link_id: str) -> bool:
        if self._inuse[link_id] < self._cap[link_id]:
            self._inuse[link_id] += 1
            return True
        return False

    def leave(self, link_id: str):
        if self._inuse[link_id] > 0:
            self._inuse[link_id] -= 1


def load_site(path: str) -> SiteModel:
    return SiteModel.load(path)
