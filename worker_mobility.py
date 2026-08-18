"""다층 작업자 통근 계획과 계단 용량 예약.

기존 2D 이동 커널은 건드리지 않는다. 이 모듈은 작업 시작 전의 층간 통근만
SiteModel.plan_path로 계획하고, 계단을 유한 용량 자원으로 예약한다.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import config as C

Cell = Tuple[int, int]


@dataclass(frozen=True)
class MobilityPoint:
    step: int
    level: str
    cell: Cell
    state: str                 # commute / stair_wait / stair
    link_id: Optional[str] = None


@dataclass
class CommutePlan:
    points: List[MobilityPoint]
    arrival_step: int
    arrival_level: str
    arrival_cell: Cell
    links_used: List[str]


class LinkReservationTable:
    """계단별 매 스텝 점유를 예약한다. 같은 시드·요청 순서면 비트 재현된다."""

    def __init__(self, site):
        self.capacity = {lk.link_id: max(1, int(lk.capacity)) for lk in site.links}
        # 각 capacity lane의 (start, end) 예약. 기존 구현은 후보 start마다 전체
        # duration 구간을 다시 훑어 대기열이 길면 O(wait * duration)이었다.
        self.lanes = {lk.link_id: [[] for _ in range(max(1, int(lk.capacity)))]
                      for lk in site.links}

    def reserve(self, link_id: str, earliest: int, duration: int) -> int:
        duration = max(1, int(duration))
        start = max(0, int(earliest))
        best = None
        for lane_i, intervals in enumerate(self.lanes[link_id]):
            candidate = start
            insert_at = len(intervals)
            for i, (a, b) in enumerate(intervals):
                if candidate + duration <= a:
                    insert_at = i
                    break
                if candidate < b:
                    candidate = b
            item = (candidate, lane_i, insert_at)
            if best is None or item < best:
                best = item
        candidate, lane_i, insert_at = best
        self.lanes[link_id][lane_i].insert(
            insert_at, (candidate, candidate + duration))
        return candidate


class RouteTemplateCache:
    """같은 OD의 층내 Theta* 결과를 소수의 확률적 대안으로 재사용한다.

    보행자 경로선택의 개인차를 하나의 결정론적 최단경로로 없애지 않기 위해 OD·ρ구간당
    ``variants``개의 대안을 유지한다. 캐시는 하루/MC 반복 안에서만 공유하도록 호출부가
    수명을 관리한다. 계단 대기시간은 포함하지 않아 용량 경쟁은 작업자별로 계속 계산된다.
    """

    def __init__(self, variants: int = 3, rho_bin: float = 0.10):
        self.variants = max(1, int(variants))
        self.rho_bin = max(0.01, float(rho_bin))
        self._plans = {}
        self.hits = 0
        self.misses = 0

    def key(self, site, start, goal, rho, completed_activities, rng):
        available = tuple(lk.link_id for lk in site.usable_links(completed_activities))
        rho_group = int(float(rho) / self.rho_bin)
        variant = rng.randrange(self.variants)
        return (start, goal, rho_group, available, variant)

    def get_or_plan(self, site, start, goal, rho, rng, effects,
                    completed_activities):
        key = self.key(site, start, goal, rho, completed_activities, rng)
        if key in self._plans:
            self.hits += 1
            return self._plans[key]
        self.misses += 1
        value = site.plan_path(start, goal, rho, rng, effects,
                               completed_activities)
        self._plans[key] = value
        return value


def boundary_entrance(site, level_id: str = "L1") -> Cell:
    """별도 entrance 사실이 없을 때 쓰는 결정론적 파생 입구.

    주 연결 컴포넌트의 외곽 셀 중 (row, col)이 가장 작은 셀이다. 임의 좌표를
    하드코딩하지 않으며, 향후 site.json에 welfare/entrance zone이 생기면 그것을 우선한다.
    """
    level = site.level(level_id)
    for z in level.zones.values():
        if z.zone_type in ("welfare", "entrance"):
            cells = level.zone_cells(z.zone_id)
            if cells:
                return min(cells)
    comp = set(level.main_component())
    if not comp:
        raise ValueError(f"{level_id}: 통근 입구를 정할 walkable component가 없음")
    edge = [p for p in comp if any((p[0] + dr, p[1] + dc) not in comp
                                   for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)))]
    return min(edge or comp)


def work_access_cell(site, level_id: str, targets, entrance: Cell,
                     completed_activities=frozenset()) -> Cell:
    """작업구역 내부를 임의 선택하지 않고 통근 방향의 접근 셀을 반환한다.

    작업 중 POI 선택은 기존대로 개별 표집하지만, 출입구→작업구역 통근은 마지막
    계단 출구(같은 층이면 현장 출입구)에 가장 가까운 유효 작업 셀까지만 계획한다.
    이는 동일 크루가 같은 구역으로 갈 때 불필요하게 서로 다른 장거리 Theta*를 푸는 것을
    막고, '구역 접근'과 '구역 내부 작업 이동'을 분리한다.
    """
    if not targets:
        raise ValueError("작업 접근 셀을 고를 targets가 비어 있음")
    anchor = entrance
    if level_id != "L1":
        chain = site._link_chain("L1", level_id, completed_activities)
        if chain:
            endpoint = chain[-1].endpoint_on(level_id)
            if endpoint is not None:
                anchor = site._nearest_walkable(level_id, endpoint)
    ar, ac = anchor
    return min(targets, key=lambda rc: ((rc[0] - ar) ** 2 + (rc[1] - ac) ** 2,
                                        rc[0], rc[1]))


def _append_move(points, step, level, route, cells_per_step):
    accum = 0.0
    cur = points[-1].cell if points else (route[0] if route else (0, 0))
    for cell in route:
        if cell == cur:
            continue
        while accum < 1.0:
            points.append(MobilityPoint(step, level, cur, "commute"))
            step += 1
            accum += cells_per_step
        accum -= 1.0
        cur = cell
    return step, cur


def plan_commute(site, start, goal, rho, rng, reservations=None,
                 effects=None, completed_activities=frozenset(), start_step=0,
                 route_cache=None):
    """층내 이동+계단 대기+계단 통과를 시간축 궤적으로 확장한다."""
    if route_cache is None:
        segments, _cost = site.plan_path(start, goal, rho, rng, effects,
                                         completed_activities)
    else:
        segments, _cost = route_cache.get_or_plan(
            site, start, goal, rho, rng, effects, completed_activities)
    if segments is None:
        return None
    reservations = reservations or LinkReservationTable(site)
    link_by_id = {lk.link_id: lk for lk in site.links}
    cells_per_step = C.WORKER_SPEED_MPS * C.STEP_SECONDS / C.CELL_SIZE_M
    step = int(start_step)
    level, cell = start
    points = [MobilityPoint(step, level, cell, "commute")]
    links = []
    for seg in segments:
        if seg[0] == "move":
            _, level, route = seg
            step, cell = _append_move(points, step, level, route, cells_per_step)
            continue
        _, link_id, level_pair, duration = seg
        lk = link_by_id[link_id]
        enter = reservations.reserve(link_id, step, duration)
        while step < enter:
            points.append(MobilityPoint(step, level, cell, "stair_wait", link_id))
            step += 1
        next_level = level_pair[1]
        exit_cell = site._nearest_walkable(next_level, lk.endpoint_on(next_level))
        for t in range(duration):
            # 계단 내부에는 2D 셀이 없으므로 입구/출구를 전반·후반으로 사용한다.
            lv, rc = (level, cell) if t < duration / 2 else (next_level, exit_cell)
            points.append(MobilityPoint(step, lv, rc, "stair", link_id))
            step += 1
        level, cell = next_level, exit_cell
        links.append(link_id)
    return CommutePlan(points, step, level, cell, links)
