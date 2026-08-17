"""
fourd.py — 4D 코어: 공정 연동 일 루프 + 채널별 기대위험 λ (Phase 2, P2-3~P2-5)
==============================================================================
ROADMAP §1-1: "4D = 날마다 다른 격자·다른 크루로 2D 하루를 N번 도는 것".

매일:
  1) active = schedule.activeSet(d),  crews = schedule.crewsOnSite(d)
  2) hz = lifecycle.hazards(d)                       # 그날 활성 위험 인스턴스
  3) 층별 격자 = site 정적격자 + hz 오버레이(개구부/단부/적재물 / collapse·drop는 셀집합)
  4) 크루 생성(trade별 crewSize, rho는 crews.json 분포에서 시드 표집)
  5) 하루 커널을 mc_runs회 반복 → 채널별 노출 누적
  6) λ(level,cell,day,channel) = 평균노출 × 채널 per-step 확률  (사고 표집 아님, §1-5)

재사용 지점(실제 코드에 맞춰 확정):
  · 경로: movement.soft_route (층별 2D 소프트 위험가중 A*) — 그대로 사용
  · λ 공식: 기존 run_one_day 의 "노출스텝 × 채널 per-step 확률" 승계 + channel·day·level 축 추가
  · 2D 커널(run_one_day/step_world/make_workers)은 미변경 → Phase 5 2D 베이스라인 보존
대책 효과는 전혀 없음(controls=None = base). 대책 적용은 Phase 3.
"""
import csv
import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

import config as C
import movement
from movement import soft_route, fall_edge_cells, _get_context
from schedule import Schedule
from site_model import SiteModel
from lifecycle import LifecycleEngine
from controls import (resolve_all, HAZARD_CHANNEL,   # Phase 3 대책 계층
                      applicable_alternatives, ControlApplication)

Cell = Tuple[int, int]

# 위험 채널 (§2). fall=개구부 인접, edge=단부(셀타입6), collapse_zone/drop_zone=직하부 셀
CHANNELS = ("fall", "edge", "material", "narrow", "collapse_zone", "drop_zone")

# lifecycle HazardType → 오버레이 방식
_HAZ_OPENING = "H001"      # 개구부 → FLOOR_OPENING 오버레이 (fall 채널)
_HAZ_EDGE = "H007"         # 단부   → EDGE 오버레이 (edge 채널)
_HAZ_MATERIAL = "H004"     # 적재물 → MATERIAL 오버레이 (material 채널)
_HAZ_COLLAPSE = "H008"     # 동바리붕괴 직하부 → collapse_zone 셀집합 (바닥은 walkable 유지)
_HAZ_DROP = "H009"         # 낙하물 직하부   → drop_zone 셀집합

# [B-2 후방호환 확장] H002(협소통로)·H011(장비동선) 분기가 없어 hazard_zones.json 의
# 16 zone 이 격자에 오르지 못하고 노출이 항상 0이었다. 기존 5종 분기는 그대로 두고
# 두 유형을 NARROW 오버레이로 추가한다.
#
# 채널을 새로 만들지 않고 기존 `narrow` 에 싣는 이유: narrow 의 per-step 확률은
# §2 통계의 '부딪힘' 비중에서 나오는데(config.CHANNEL_PER_STEP), 장비동선 접촉도
# 같은 부딪힘 계열이고 이를 분리할 별도 계수가 원천(§2 통계·TTL)에 없다.
# 없는 계수를 지어내지 않기 위해 채널을 공유한다. 두 유형 모두
# hazard_zones.json 의 exposure_channel 은 passage_count 다.
_HAZ_NARROW = "H002"       # 협소통로   → NARROW 오버레이 (narrow 채널)
_HAZ_CORRIDOR = "H011"     # 장비동선   → NARROW 오버레이 (narrow 채널)

# controls.HAZARD_CHANNEL 의 4D 확장. controls.py 는 건드리지 않고 여기서 덧댄다.
HAZARD_CHANNEL_4D = dict(HAZARD_CHANNEL)
HAZARD_CHANNEL_4D[_HAZ_NARROW] = "narrow"
HAZARD_CHANNEL_4D[_HAZ_CORRIDOR] = "narrow"


@dataclass
class _Crew4D:
    """4D 작업자 1인. 자기 층의 메인 컴포넌트를 배회하며 노출을 누적."""
    __slots__ = ("trade", "rho", "pos", "route", "dwell")
    trade: str
    rho: float
    pos: Cell
    route: List[Cell]
    dwell: int


@dataclass
class LambdaResult:
    """run_project 산출. λ와 노출을 희소 딕셔너리로 보관."""
    days: int
    mc_runs: int
    seed: int
    # (level, r, c, day, channel) -> λ
    lam: Dict[Tuple[str, int, int, int, str], float] = field(default_factory=dict)
    # (day, trade) -> {"crew": int, "exposure_steps": float}
    exposure_by_trade: Dict[Tuple[int, str], Dict[str, float]] = field(default_factory=dict)

    def channel_total(self, channel: str, day: Optional[int] = None) -> float:
        return sum(v for (lv, r, c, d, ch), v in self.lam.items()
                   if ch == channel and (day is None or d == day))

    def daily_lambda(self) -> Dict[int, float]:
        out: Dict[int, float] = defaultdict(float)
        for (lv, r, c, d, ch), v in self.lam.items():
            out[d] += v
        return dict(out)


# ══════════════════════════════════════════════
# 격자 + 채널 셀 구성
# ══════════════════════════════════════════════
def build_day_grid(site: SiteModel, level_id: str, hazards):
    """정적 격자 + 그날 위험 오버레이. 반환: (grid, collapse_cells, drop_cells)."""
    grid = site.grid(level_id).copy()
    collapse_cells, drop_cells = set(), set()
    for h in hazards:
        if h.level != level_id:
            continue
        if h.hazard_type == _HAZ_OPENING:
            for (r, c) in h.cells:
                grid[r, c] = C.FLOOR_OPENING
        elif h.hazard_type == _HAZ_EDGE:
            for (r, c) in h.cells:
                if grid[r, c] != C.WALL:
                    grid[r, c] = C.EDGE
        elif h.hazard_type == _HAZ_MATERIAL:
            for (r, c) in h.cells:
                grid[r, c] = C.MATERIAL
        elif h.hazard_type in (_HAZ_NARROW, _HAZ_CORRIDOR):     # B-2
            for (r, c) in h.cells:
                if grid[r, c] not in (C.WALL, C.FLOOR_OPENING):
                    grid[r, c] = C.NARROW
        elif h.hazard_type == _HAZ_COLLAPSE:
            collapse_cells.update((int(r), int(c)) for (r, c) in h.cells)
        elif h.hazard_type == _HAZ_DROP:
            drop_cells.update((int(r), int(c)) for (r, c) in h.cells)
    return grid, collapse_cells, drop_cells


def channel_cells(grid: np.ndarray, collapse_cells, drop_cells) -> Dict[str, frozenset]:
    """그날 격자의 채널별 노출 셀 집합. collapse/drop은 바닥이 walkable이므로 별도 추적."""
    walkable = lambda r, c: grid[r, c] not in (C.WALL, C.FLOOR_OPENING)
    edge = frozenset(map(tuple, np.argwhere(grid == C.EDGE).tolist()))
    material = frozenset(map(tuple, np.argwhere(grid == C.MATERIAL).tolist()))
    narrow = frozenset(map(tuple, np.argwhere(grid == C.NARROW).tolist()))
    fall = frozenset(fall_edge_cells(grid))          # 개구부 인접 walkable 셀 (2D와 동일 정의)
    coll = frozenset((r, c) for (r, c) in collapse_cells if walkable(r, c))
    drop = frozenset((r, c) for (r, c) in drop_cells if walkable(r, c))
    return {"fall": fall, "edge": edge, "material": material,
            "narrow": narrow, "collapse_zone": coll, "drop_zone": drop}


# ══════════════════════════════════════════════
# 가설물(TS) 오버레이 — Phase 3 walkable 재조정
# ══════════════════════════════════════════════
# 정적 격자의 walkable 은 IFC 슬래브에서 나오는데, 거푸집 설치·배근 단계에는
# 슬래브가 아직 없다. 그 기간의 보행면은 거푸집 데크(TS1)다.
#   타설 전 → TS1 데크가 walkable (슬래브는 아직 없음)
#   타설 후 → 슬래브가 walkable, TS1 은 하부에서 존속
#   해체 후 → TS1·TS2 소멸
# temp_structures.json 이 없으면 아무것도 하지 않는다 — 기존 경로 후방호환.
_TS_CACHE = {"path": None, "by_level": None}


def load_temp_structures(path: str = None):
    """{level: [ts, ...]} 로 적재. 파일이 없으면 None (기존 동작 유지)."""
    path = path or os.path.join(os.path.dirname(__file__), "build",
                                "temp_structures.json")
    if _TS_CACHE["path"] == path:
        return _TS_CACHE["by_level"]
    by_level = None
    if os.path.exists(path):
        import json as _json
        with open(path, encoding="utf-8") as fp:
            doc = _json.load(fp)
        by_level = defaultdict(list)
        for t in doc.get("temp_structures", []):
            by_level[t["level"]].append(t)
        by_level = dict(by_level)
    _TS_CACHE["path"] = path
    _TS_CACHE["by_level"] = by_level
    return by_level


def _ts_active(t, day: int) -> bool:
    sp = (t.get("spawn") or {}).get("day")
    dp = (t.get("despawn") or {}).get("day")
    if sp is None:
        return False
    return sp <= day < (dp if dp is not None else float("inf"))


def apply_temp_structures(grid: np.ndarray, level_id: str, day: int,
                          temp_structures=None) -> dict:
    """그날 활성 TS 를 격자에 반영. 반환: 적용 통계(없으면 빈 dict).

    walkable=True 인 TS(거푸집 데크·비계)는 그 셀을 통행 가능하게 만들고,
    walkable=False 인 TS(동바리)는 통행 장애물(WALL)로 만든다.
    격자를 제자리에서 수정하므로 호출부는 복사본을 넘긴다."""
    if not temp_structures:
        return {}
    R, Co = grid.shape
    stat = {"walkable_added": 0, "blocked": 0, "types": Counter()}
    for t in temp_structures.get(level_id, ()):
        if not _ts_active(t, day):
            continue
        stat["types"][t["ts_type"]] += 1
        if t.get("walkable"):
            for r, c in t["cells"]:
                if 0 <= r < R and 0 <= c < Co and grid[r, c] in (C.WALL, C.FLOOR_OPENING):
                    grid[r, c] = C.WALKABLE       # 데크·비계가 보행면을 만든다
                    stat["walkable_added"] += 1
        else:
            for r, c in t["cells"]:
                if 0 <= r < R and 0 <= c < Co and grid[r, c] != C.WALL:
                    grid[r, c] = C.WALL           # 동바리 = 통행 장애물
                    stat["blocked"] += 1
    return stat


def build_level_day(site: SiteModel, level_id: str, hazards, effects_by_instance: dict,
                    day: int, temp_structures=None):
    """대책(controls) 반영 격자·채널·셀배율. 반환: (grid, ch_cells, cell_mult).
    effective_day 이후에만 대책 적용(그 전엔 무방호=base). 인스턴스 단위:
      remove → 오버레이·노출 제거 / block → 셀을 WALL(진입차단) / scale → 채널 λ 배율."""
    grid = site.grid(level_id).copy()
    # Phase 3: 가설물 오버레이를 위험 오버레이보다 **먼저** 적용한다.
    # 데크가 보행면을 만든 뒤 그 위에 개구부·단부가 얹혀야 순서가 맞다.
    apply_temp_structures(grid, level_id, day, temp_structures)
    collapse_cells, drop_cells = set(), set()
    cell_mult = {ch: {} for ch in CHANNELS}
    scaled_openings = []                          # (mult, [opening cells]) — fall 이웃 배율용

    def _setmin(ch, cell, m):
        cell_mult[ch][cell] = min(cell_mult[ch].get(cell, 1.0), m)

    for h in hazards:
        if h.level != level_id:
            continue
        eff = effects_by_instance.get(h.instance_id)
        active = eff is not None and day >= eff.effective_day
        kind = eff.kind if active else "base"
        if kind == "remove":
            continue                              # 위험 제거
        if kind == "block":
            for (r, c) in h.cells:
                if grid[r, c] != C.WALL:
                    grid[r, c] = C.WALL           # 진입 차단(→ 노출·이동 불가)
            continue
        chan = HAZARD_CHANNEL_4D.get(h.hazard_type)
        mult = eff.channel_mult.get(chan, 1.0) if (kind == "scale" and eff) else 1.0
        if h.hazard_type == _HAZ_OPENING:
            for (r, c) in h.cells:
                grid[r, c] = C.FLOOR_OPENING
            if mult != 1.0:
                scaled_openings.append((mult, [(int(r), int(c)) for r, c in h.cells]))
        elif h.hazard_type == _HAZ_EDGE:
            for (r, c) in h.cells:
                if grid[r, c] != C.WALL:
                    grid[r, c] = C.EDGE
                    if mult != 1.0:
                        _setmin("edge", (int(r), int(c)), mult)
        elif h.hazard_type == _HAZ_MATERIAL:
            for (r, c) in h.cells:
                grid[r, c] = C.MATERIAL
                if mult != 1.0:
                    _setmin("material", (int(r), int(c)), mult)
        elif h.hazard_type in (_HAZ_NARROW, _HAZ_CORRIDOR):     # B-2
            for (r, c) in h.cells:
                if grid[r, c] in (C.WALL, C.FLOOR_OPENING):
                    continue
                grid[r, c] = C.NARROW
                if mult != 1.0:
                    _setmin("narrow", (int(r), int(c)), mult)
        elif h.hazard_type == _HAZ_COLLAPSE:
            for (r, c) in h.cells:
                collapse_cells.add((int(r), int(c)))
                if mult != 1.0:
                    _setmin("collapse_zone", (int(r), int(c)), mult)
        elif h.hazard_type == _HAZ_DROP:
            for (r, c) in h.cells:
                drop_cells.add((int(r), int(c)))
                if mult != 1.0:
                    _setmin("drop_zone", (int(r), int(c)), mult)

    ch = channel_cells(grid, collapse_cells, drop_cells)
    # H001 scale: fall 노출은 개구부 인접 셀이므로 그 이웃에 배율 부여
    for mult, openset in scaled_openings:
        oset = set(openset)
        for (r, c) in ch["fall"]:
            if any((r + dr, c + dc) in oset for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))):
                _setmin("fall", (r, c), mult)
    return grid, ch, cell_mult


# ══════════════════════════════════════════════
# 크루 생성 (trade별 crewSize, rho는 crews.json 분포 표집)
# ══════════════════════════════════════════════
def sample_rho(trade: str, crews_cfg: dict, rng: random.Random) -> float:
    """crews.json 분포에서 rho 표집. mean/sd=null(전역 기본)이면 uniform(min,max)
    — 2D social.init_rho 와 동일 표집 (Phase 5 2D 동등성 유지)."""
    dist = crews_cfg.get(trade, {})
    lo = dist.get("min", C.RHO_MIN)
    hi = dist.get("max", C.RHO_MAX)
    mean, sd = dist.get("mean"), dist.get("sd")
    if mean is None or sd is None:
        return rng.uniform(lo, hi)
    return min(hi, max(lo, rng.gauss(mean, sd)))


def make_level_crews(comp: List[Cell], crew_specs, crews_cfg,
                     rng: random.Random) -> List[_Crew4D]:
    """crew_specs: [(trade, crewSize), ...]. comp: 스폰 가능한 메인 컴포넌트 셀."""
    crews = []
    for trade, size in crew_specs:
        for _ in range(int(size)):
            rho = sample_rho(trade, crews_cfg, rng)
            pos = comp[rng.randrange(len(comp))]
            crews.append(_Crew4D(trade=trade, rho=rho, pos=pos, route=[], dwell=0))
    return crews


# ══════════════════════════════════════════════
# 하루 커널 (1개 층, 1회 MC)
# ══════════════════════════════════════════════
def run_level_day(grid: np.ndarray, ch_cells: Dict[str, frozenset],
                  crews: List[_Crew4D], comp: List[Cell], horizon: int,
                  rng: random.Random, dwell_steps: int,
                  nbrs=None) -> Dict[str, Dict[Cell, int]]:
    """한 층의 하루(horizon 스텝). 반환: {channel: {cell: 노출스텝}}.
    노출은 매 스텝 워커 위치를 채널 셀 집합과 대조해 누적(§1-5 기대위험 방식)."""
    if nbrs is None:
        nbrs = _get_context(grid, None)["nbrs"]
    exp: Dict[str, Dict[Cell, int]] = {ch: defaultdict(int) for ch in CHANNELS}
    ncomp = len(comp)
    for _f in range(horizon):
        for w in crews:
            pos = w.pos
            for ch, cells in ch_cells.items():
                if pos in cells:
                    exp[ch][pos] += 1
            # ── 이동/체류 ──
            if w.dwell > 0:
                w.dwell -= 1
                continue
            if not w.route:
                target = comp[rng.randrange(ncomp)]
                w.route = soft_route(grid, w.pos, target, w.rho, rng, None, nbrs=nbrs)
                if not w.route:
                    w.dwell = 1                # 도달 불가 → 한 스텝 대기 후 재표집
                    continue
            w.pos = w.route.pop(0)
            if not w.route:
                w.dwell = dwell_steps          # 작업 지점 도착 → 체류
    return exp


# ══════════════════════════════════════════════
# 일 루프 run_project
# ══════════════════════════════════════════════
def _crew_specs_by_level(schedule: Schedule, day: int):
    """그날 in_progress 액티비티를 층별 (trade, crewSize) 목록으로."""
    by_level: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for aid in schedule.activeSet(day):
        a = schedule.activities[aid]
        by_level[a.level].append((a.trade, a.crew_size))
    return by_level


def run_project(schedule: Schedule, site: SiteModel, lifecycle: LifecycleEngine,
                crews_cfg: Optional[dict] = None,
                days: Optional[int] = None, mc_runs: int = 1, seed: int = 0,
                max_steps: Optional[int] = None, controls=None,
                extra_crews=None, library=None, day_start: int = 0) -> LambdaResult:
    """4D 일 루프. days=None이면 schedule.duration까지.
    crews_cfg: {trade: rho분포dict} (crews.json).
    controls: [ControlApplication] — 위험 인스턴스 단위 PtD 대책(Phase 3). effective_day
      이후에만 적용(그 전 무방호). TemporalRule 대책은 스케줄에 선적용(P3-5) 후 넘길 것.
    extra_crews: {(day,level):[(trade,size)]} — 직렬 공정 보완용 강제 크루 투입."""
    cfg = crews_cfg if crews_cfg is not None else _CREWS_CFG_HOLDER["cfg"]
    effects = {}
    if controls:
        if library is None:
            import ptd_ttl
            library = ptd_ttl.LIBRARY
        effects = resolve_all(library, controls, schedule, lifecycle)
        for e in effects.values():
            if e.kind == "temporal":
                raise ValueError("TemporalRule 대책은 controls.apply_temporal_shift로 "
                                 "스케줄에 선적용 후 run_project 하세요 (P3-5)")
    n_days = schedule.duration if days is None else days
    horizon = C.WORKDAY_STEPS if max_steps is None else int(max_steps)
    dwell_steps = max(1, horizon // 8)
    result = LambdaResult(days=n_days, mc_runs=mc_runs, seed=seed)
    lvl_index = {lv: i for i, lv in enumerate(site.level_order)}

    for d in range(day_start, n_days):
        hz = lifecycle.hazards(d)
        specs_by_level = _crew_specs_by_level(schedule, d)
        if extra_crews:
            for (dd, lv), specs in extra_crews.items():
                if dd == d:
                    specs_by_level[lv].extend(specs)

        # exposure_by_trade: 그날 공종 투입(crew 곡선) 기록 — schedule과 정합해야 함
        trade_steps: Dict[str, float] = defaultdict(float)

        for level_id, crew_specs in specs_by_level.items():
            if level_id not in site.levels or not crew_specs:
                continue
            grid, ch_cells, cell_mult = build_level_day(site, level_id, hz, effects, d)
            # 스폰·목적지는 '그날' 격자 기준 walkable 셀만(개구부 오버레이·block 반영)
            comp = [cell for cell in site.level(level_id).main_component()
                    if grid[cell[0], cell[1]] not in (C.WALL, C.FLOOR_OPENING)]
            if not comp:
                continue
            nbrs = _get_context(grid, None)["nbrs"]

            for run in range(mc_runs):
                rng = random.Random(f"{seed}|{d}|{level_id}|{run}")   # str 시드(재현성)
                crews = make_level_crews(comp, crew_specs, cfg, rng)
                exp = run_level_day(grid, ch_cells, crews, comp, horizon, rng,
                                    dwell_steps, nbrs=nbrs)
                for ch, cellmap in exp.items():
                    p = C.CHANNEL_PER_STEP[ch]
                    cm = cell_mult[ch]
                    for (r, c), steps in cellmap.items():
                        key = (level_id, r, c, d, ch)
                        result.lam[key] = (result.lam.get(key, 0.0)
                                           + steps * p * cm.get((r, c), 1.0) / mc_runs)
                        # 공종별 노출 집계(평균) — 해당 셀에 있던 워커의 trade 구분은
                        # 셀 단위론 불가하므로, 층 전체 노출을 층의 주 공종에 귀속
                # 층 전체 노출스텝(모든 채널) 합 → 그 층 크루 trade들에 비례 배분
                total_exp = sum(sum(m.values()) for m in exp.values())
                tsize = sum(sz for _t, sz in crew_specs)
                for tr, sz in crew_specs:
                    trade_steps[tr] += total_exp * (sz / tsize) / mc_runs if tsize else 0.0

            # movement 컨텍스트 캐시가 (day,level)마다 쌓이지 않게 정리
            movement._CTX.pop(id(grid), None)

        # 공종 투입 곡선 기록 (crew = schedule.crewsOnSite 정합)
        crews_on = schedule.crewsOnSite(d)
        for tr, crew in crews_on.items():
            result.exposure_by_trade[(d, tr)] = {
                "crew": crew, "exposure_steps": trade_steps.get(tr, 0.0)}
        # extra_crews로 투입된 공종도 기록
        if extra_crews:
            for (dd, lv), specs in extra_crews.items():
                if dd != d:
                    continue
                for tr, sz in specs:
                    row = result.exposure_by_trade.setdefault((d, tr), {"crew": 0, "exposure_steps": 0.0})
                    row["crew"] += sz
                    row["exposure_steps"] += trade_steps.get(tr, 0.0)

    return result


# ══════════════════════════════════════════════
# P3-6 폐루프 — λ 상위 인스턴스 추출 → 대안 질의 → 적용 → 재실행 비교
# ══════════════════════════════════════════════
def instance_exposure_cells(h):
    """인스턴스 λ 귀속 셀. H001(fall)은 개구부 인접, 그 외는 인스턴스 셀."""
    if h.hazard_type == _HAZ_OPENING:
        nb = set()
        for (r, c) in h.cells:
            r, c = int(r), int(c)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nb.add((r + dr, c + dc))
        return nb
    return {(int(r), int(c)) for (r, c) in h.cells}


def rank_instances_by_lambda(result: LambdaResult, lifecycle):
    """위험 인스턴스를 총 λ 기여도 내림차순으로. 반환: [(instance, lambda_sum), ...]."""
    # (level, channel) 인덱스로 조회 가속
    idx: Dict[Tuple[str, str], List[Tuple[int, int, int, float]]] = defaultdict(list)
    for (lv, r, c, d, ch), v in result.lam.items():
        idx[(lv, ch)].append((r, c, d, v))
    out = []
    for h in lifecycle.instances:
        chan = HAZARD_CHANNEL_4D.get(h.hazard_type)     # B-2: H002/H011 포함
        cells = instance_exposure_cells(h)
        tot = sum(v for (r, c, d, v) in idx.get((h.level, chan), ())
                  if (r, c) in cells and h.spawn_day <= d < h.despawn_day)
        out.append((h, tot))
    return sorted(out, key=lambda x: x[1], reverse=True)


def closed_loop_demo(schedule, site, lifecycle, crews_cfg, library, days=None,
                     mc_runs=1, seed=0, max_steps=None, extra_crews=None,
                     unconditional_only=True) -> dict:
    """base 실행 → λ 상위 인스턴스 → 적용가능 대안(HoC순) → 최상위 적용 → 재실행 → 비교."""
    common = dict(days=days, mc_runs=mc_runs, seed=seed, max_steps=max_steps,
                  extra_crews=extra_crews, library=library)
    base = run_project(schedule, site, lifecycle, crews_cfg, **common)
    ranked = [(h, v) for h, v in rank_instances_by_lambda(base, lifecycle) if v > 0]
    base_total = sum(base.lam.values())
    if not ranked:
        return {"base_total": base_total, "note": "노출된 인스턴스 없음(직렬 공정)"}
    top_h, top_lam = ranked[0]
    alts = applicable_alternatives(library, top_h.hazard_type,
                                   unconditional_only=unconditional_only)
    if not alts:
        return {"base_total": base_total, "top_instance": top_h.instance_id,
                "note": "적용가능 대안 없음"}
    best = alts[0]                          # HoC 최상위
    ctrl = ControlApplication(best.alternative_id, top_h.instance_id)
    after = run_project(schedule, site, lifecycle, crews_cfg, controls=[ctrl], **common)
    after_total = sum(after.lam.values())
    return {
        "top_instance": top_h.instance_id, "top_hazard": top_h.hazard_type,
        "top_lambda_base": top_lam,
        "applicable_alternatives": [(a.alternative_id, a.hoc_level) for a in alts],
        "chosen_alternative": best.alternative_id, "chosen_hoc": best.hoc_level,
        "base_total": base_total, "after_total": after_total,
        "delta": base_total - after_total,
        "reduction_pct": (100.0 * (base_total - after_total) / base_total) if base_total else 0.0,
    }


# crews.json 설정을 run_project에 전달하기 위한 경량 홀더(전역 상태 없이 주입)
_CREWS_CFG_HOLDER = {"cfg": {}}


def load_project(project_dir: str = "project", library=None):
    """schedule/site/lifecycle/crews 를 한 번에 로드."""
    import json
    import ptd_ttl
    schedule = Schedule.load(os.path.join(project_dir, "schedule.json"))
    site = SiteModel.load(os.path.join(project_dir, "site.json"))
    lib = library if library is not None else ptd_ttl.LIBRARY
    if lib is None:
        raise RuntimeError("TTL 라이브러리 필요 (rdflib/ptd_library.ttl)")
    lifecycle = LifecycleEngine(lib.lifecycle_templates,
                                os.path.join(project_dir, "lifecycle_bindings.json"),
                                schedule)
    with open(os.path.join(project_dir, "crews.json"), encoding="utf-8") as fp:
        crews_raw = json.load(fp)
    crews_cfg = {t["trade"]: t.get("rho", {}) for t in crews_raw.get("trades", [])}
    _CREWS_CFG_HOLDER["cfg"] = crews_cfg
    return schedule, site, lifecycle, crews_cfg


# ══════════════════════════════════════════════
# 산출 (P2-5)
# ══════════════════════════════════════════════
def write_outputs(result: LambdaResult, out_dir: Optional[str] = None):
    out_dir = out_dir or C.OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    lam_path = os.path.join(out_dir, "lambda_daily.csv")
    exp_path = os.path.join(out_dir, "exposure_by_trade.csv")

    with open(lam_path, "w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["level", "row", "col", "day", "channel", "lambda"])
        for (lv, r, c, d, ch), v in sorted(result.lam.items()):
            if v > 0.0:
                w.writerow([lv, r, c, d, ch, f"{v:.10e}"])

    with open(exp_path, "w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["day", "trade", "crew", "exposure_steps"])
        for (d, tr), row in sorted(result.exposure_by_trade.items()):
            w.writerow([d, tr, row["crew"], f"{row['exposure_steps']:.1f}"])

    return lam_path, exp_path
