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
        self.usage: Dict[str, Dict[int, int]] = {lk.link_id: {} for lk in site.links}

    def reserve(self, link_id: str, earliest: int, duration: int) -> int:
        duration = max(1, int(duration))
        start = max(0, int(earliest))
        cap = self.capacity[link_id]
        used = self.usage[link_id]
        while any(used.get(t, 0) >= cap for t in range(start, start + duration)):
            start += 1
        for t in range(start, start + duration):
            used[t] = used.get(t, 0) + 1
        return start


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
                 effects=None, completed_activities=frozenset(), start_step=0):
    """층내 이동+계단 대기+계단 통과를 시간축 궤적으로 확장한다."""
    segments, _cost = site.plan_path(start, goal, rho, rng, effects,
                                     completed_activities)
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

