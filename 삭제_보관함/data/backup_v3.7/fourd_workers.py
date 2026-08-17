"""fourd_workers.py — 2D 이동 알고리즘의 4D 최소 이식 (v3.1 Part B)

## 무엇을 옮겼고 무엇을 안 옮겼나

이식함 (2D movement.py 에서 import — 원본 미수정):
  · `soft_route()`      소프트 위험가중 A* (8방향, octile, 대각선 코너컷 금지)
  · 위험 회피 가중      config.HAZARD_WEIGHT × RISK_K × (1−ρ), 개구부 인접 OPEN_EDGE_PEN
  · 경로 노이즈         config.PATH_NOISE
  · 이동 속도 제한      WORKER_SPEED_MPS × STEP_SECONDS / CELL_SIZE_M (누적 1칸마다 전진)
  · 한 셀 = 한 명       점유 충돌 회피와 교착 해소(옆걸음)

미이식 — 후속:
  · social.apply_witness_shock  (사고 목격 시 ρ 하락)
  · social.apply_imitation      (주변 평균 ρ 모방)
  · 사고 표집(P_FALL_PER_STEP 등) — 4D 는 λ(기대건수) 방식이라 표집하지 않는다
  ρ 는 크루 생성 시 한 번 정해지고 하루 동안 고정이다. 4D 1회 실행이 2D 보다
  훨씬 무거워, 파라미터가 많은 채로 옮기면 조정 사이클이 감당되지 않는다.
  최소 구성이 도는 것을 확인한 뒤 근거를 갖고 추가한다.

## 2D 와 다른 점 (4D 이기 때문에 필요한 것)

  · 격자가 층별로 다르고 날마다 다르다 (fourd.build_level_day)
  · 작업 위치가 임의 셀이 아니라 **액티비티가 대상으로 하는 IFC 요소의 셀**이다
  · 크루 인원이 공정표의 crewSize 에서 온다
  · 궤적에 day·level·activity_id 축이 붙는다

## 경계

  movement.py / social.py / lifecycle.py / site_model.py / controls.py 를 수정하지
  않는다. fourd.py 는 격자 구성(build_level_day)만 재사용한다.
"""
from __future__ import annotations

import csv
import json
import os
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import config as C
import fourd
import movement
from movement import soft_route, _get_context

Cell = Tuple[int, int]

# 액티비티 → IFC 요소 GUID (기존 산출물, 이 모듈이 만들지 않는다)
ELEMENT_TASK_MAPPING = "element_task_mapping.json"
# 요소 GUID → bbox(IFC 월드 m). unity_bundle 번들의 manifest 를 그대로 쓴다.
MANIFEST = os.path.join("unity_bundle", "manifest.json")
# 파생 위치표 (scripts/build_task_locations.py 산출). 없으면 위 GUID 경로만 쓴다.
TASK_LOCATIONS = os.path.join("build", "task_locations.json")
# zone 셀 원천 (zone:material 등 GUID 가 아닌 위치 원천용)
HAZARD_ZONES = os.path.join("build", "hazard_zones.json")


# ══════════════════════════════════════════════════════════
# 작업 위치 유도 — 액티비티가 대상으로 하는 요소의 셀
# ══════════════════════════════════════════════════════════
class WorkLocations:
    """activityID → 그 액티비티가 손대는 자리의 격자 셀 목록.

    두 원천을 받는다 (v3.3 확장, 기존 GUID 경로는 그대로):

      GUID 경로  element_task_mapping.json / build/task_locations.json 의
                 element_ids → manifest.json(GUID→bbox, IFC 월드 m)
                 → site.json gridFrame(월드→셀)
      zone 경로  build/task_locations.json 의 zone_ids → hazard_zones.json 셀
                 (자재 반입·소진처럼 특정 부재에 귀속되지 않는 작업용)

    좌표 규약은 기존 계약 그대로다
    (gridFrame: row=+Y, col=+X, world_xy = origin + (index+0.5)*resolution).

    `build/task_locations.json` 이 없으면 예전과 똑같이 element_task_mapping.json
    만 본다 — 후방호환.

    어느 원천으로도 위치가 나오지 않는 액티비티는 **비운다**. 임의 위치를
    지어내지 않고, 호출부가 '층 메인 컴포넌트 배회'로 폴백하며 그 사실을 집계에
    남긴다.
    """

    def __init__(self, grid_frame: dict, mapping_path: str = ELEMENT_TASK_MAPPING,
                 manifest_path: str = MANIFEST,
                 locations_path: str = TASK_LOCATIONS,
                 zones_path: str = HAZARD_ZONES):
        self.grid_frame = grid_frame
        self.res = float(grid_frame["resolution_m"])
        self.ox, self.oy = grid_frame["origin_xy_m"]
        self._cells: Dict[str, List[Cell]] = {}
        self.stats = {"activities_with_elements": 0, "guids_referenced": 0,
                      "guids_resolved": 0, "manifest_missing": 0,
                      "from_zone": 0, "locations_file": 0}

        self._mapping = {}
        if os.path.exists(mapping_path):
            with open(mapping_path, encoding="utf-8") as fp:
                self._mapping = json.load(fp)

        # 파생 위치표 (있으면 우선)
        self._loc = {}
        if os.path.exists(locations_path):
            with open(locations_path, encoding="utf-8") as fp:
                self._loc = json.load(fp).get("tasks", {})
            self.stats["locations_file"] = 1

        self._zone_cells: Dict[str, List[Cell]] = {}
        if self._loc and os.path.exists(zones_path):
            with open(zones_path, encoding="utf-8") as fp:
                for z in json.load(fp)["zones"]:
                    self._zone_cells[z["zone_id"]] = [
                        (int(r), int(c)) for r, c in z.get("cells", [])]

        self._bbox = {}
        if os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as fp:
                for m in json.load(fp):
                    bb = m.get("bbox_ifc_m")
                    if bb:
                        self._bbox[m["element_key"]["ifc_guid"]] = bb
        else:
            self.stats["manifest_missing"] = 1

    # ── 원천 조회 ──────────────────────────────────────────
    def _rec(self, activity_id: str) -> dict:
        return self._loc.get(activity_id.replace("T-", "", 1)) or {}

    def source_of(self, activity_id: str) -> Optional[str]:
        """이 액티비티의 위치 원천 (original / inherited:* / zone:* / None)."""
        rec = self._rec(activity_id)
        if rec:
            return rec.get("source")
        task = activity_id.replace("T-", "", 1)
        return "original" if (self._mapping.get(task) or {}).get("element_ids") else None

    def level_of(self, activity_id: str, default: str) -> str:
        """작업이 실제로 이루어지는 층. 해체처럼 직하부인 경우 override 가 있다."""
        return self._rec(activity_id).get("level_override") or default

    def _bbox_cells(self, bb: dict) -> List[Cell]:
        """bbox XY 발자국이 덮는 셀. gridFrame 규약의 역함수."""
        c0 = int(np.floor((bb["min"][0] - self.ox) / self.res))
        c1 = int(np.floor((bb["max"][0] - self.ox) / self.res))
        r0 = int(np.floor((bb["min"][1] - self.oy) / self.res))
        r1 = int(np.floor((bb["max"][1] - self.oy) / self.res))
        return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]

    def cells_for(self, activity_id: str) -> List[Cell]:
        if activity_id in self._cells:
            return self._cells[activity_id]
        task = activity_id.replace("T-", "", 1)
        rec = self._rec(activity_id)
        if rec:
            guids = rec.get("element_ids") or []
            zone_ids = rec.get("zone_ids") or []
        else:                                    # 후방호환: 위치표 없을 때
            guids = (self._mapping.get(task) or {}).get("element_ids") or []
            zone_ids = []

        if guids or zone_ids:
            self.stats["activities_with_elements"] += 1
        self.stats["guids_referenced"] += len(guids)

        out: List[Cell] = []
        seen = set()
        for g in guids:
            bb = self._bbox.get(g)
            if bb is None:
                continue
            self.stats["guids_resolved"] += 1
            for cell in self._bbox_cells(bb):
                if cell not in seen:
                    seen.add(cell)
                    out.append(cell)
        for zid in zone_ids:
            cells = self._zone_cells.get(zid) or []
            if cells:
                self.stats["from_zone"] += 1
            for cell in cells:
                if cell not in seen:
                    seen.add(cell)
                    out.append(cell)
        self._cells[activity_id] = out
        return out

    def targets_on_grid(self, activity_id: str, grid: np.ndarray) -> List[Cell]:
        """그날 격자에서 실제로 서 있을 수 있는 작업 셀만 남긴다."""
        R, Co = grid.shape
        return [(r, c) for (r, c) in self.cells_for(activity_id)
                if 0 <= r < R and 0 <= c < Co
                and grid[r, c] not in (C.WALL, C.FLOOR_OPENING)]


# ══════════════════════════════════════════════════════════
# 4D 워커
# ══════════════════════════════════════════════════════════
@dataclass
class Worker4D:
    """4D 격자 위의 개별 작업자. 2D Worker 의 이동 관련 상태만 옮긴 최소 구성."""
    __slots__ = ("wid", "trade", "activity_id", "rho", "pos", "targets",
                 "target", "route", "state", "timer", "move_accum", "stuck",
                 "target_derived")
    wid: int
    trade: str
    activity_id: str
    rho: float
    pos: Cell
    targets: List[Cell]
    target: Optional[Cell]
    route: List[Cell]
    state: str                 # travel / work
    timer: int
    move_accum: float
    stuck: int
    target_derived: bool       # True=요소에서 유도, False=폴백(층 배회)


TRAJECTORY_HEADER = ["day", "level", "worker_id", "step", "row", "col",
                     "state", "activity_id", "trade"]


class TrajectoryLogger:
    """워커 궤적 CSV. 몬테카를로 반복 중에는 붙이지 않는다(호출부가 mc_runs==1 확인).

    every: N 스텝마다 1줄. 스텝 전량 기록은 파일이 과대해진다 —
    기본값 근거는 scripts/run_4d_workers.py 가 실측해 로그에 남긴다.
    """

    def __init__(self, path: str, every: int = 1):
        self.path = path
        self.every = max(1, int(every))
        self.rows = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._fh = open(path, "w", newline="", encoding="utf-8")
        self._wr = csv.writer(self._fh)
        self._wr.writerow(TRAJECTORY_HEADER)

    def log(self, day: int, level: str, step: int, workers: Sequence[Worker4D]):
        if step % self.every:
            return
        self._wr.writerows(
            [day, level, w.wid, step, w.pos[0], w.pos[1], w.state,
             w.activity_id, w.trade] for w in workers)
        self.rows += len(workers)

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def make_workers(crew_specs, work_locs: WorkLocations, grid: np.ndarray,
                 comp: List[Cell], crews_cfg: dict, rng: random.Random,
                 wid0: int = 0) -> Tuple[List[Worker4D], Dict[str, int]]:
    """crew_specs: [(activity_id, trade, crew_size)]. 인원은 공정표 값 그대로.

    작업 위치는 액티비티 요소 셀에서 유도하고, 유도 불가면 층 메인 컴포넌트로
    폴백한다(그 사실을 stats 에 센다 — 임의 위치를 지어낸 것이 아님을 남기려고)."""
    workers: List[Worker4D] = []
    stats = {"derived": 0, "fallback": 0}
    wid = wid0
    for activity_id, trade, size in crew_specs:
        targets = work_locs.targets_on_grid(activity_id, grid)
        derived = bool(targets)
        if not derived:
            targets = comp
        for _ in range(int(size)):
            # ρ 는 crews.json 분포에서 1회 표집하고 하루 동안 고정 (사회효과 미이식)
            rho = fourd.sample_rho(trade, crews_cfg, rng)
            start = comp[rng.randrange(len(comp))]
            workers.append(Worker4D(
                wid=wid, trade=trade, activity_id=activity_id, rho=rho,
                pos=start, targets=targets, target=None, route=[],
                state="travel", timer=0, move_accum=0.0, stuck=0,
                target_derived=derived))
            wid += 1
            stats["derived" if derived else "fallback"] += 1
    return workers, stats


def run_level_day_workers(grid: np.ndarray, ch_cells: Dict[str, frozenset],
                          workers: List[Worker4D], horizon: int,
                          rng: random.Random, dwell_steps: int,
                          nbrs=None, logger: Optional[TrajectoryLogger] = None,
                          day: int = 0, level: str = ""):
    """한 층의 하루. 반환: (derived_exp, fallback_exp) — 각각 {channel: {cell: 노출스텝}}.

    2D step_world 의 이동 규율을 그대로 따른다 — 한 셀 한 명, 속도 제한 누적,
    막히면 옆걸음. 사고 판정과 사회효과는 없다(4D 는 λ 방식·최소 이식)."""
    if nbrs is None:
        nbrs = _get_context(grid, None)["nbrs"]
    # 노출을 두 벌로 센다: 위치가 기하에서 유도된 워커(derived)와 폴백 워커.
    # 폴백은 층 전체를 배회하므로 위험구역과의 관계가 면적 비례일 뿐이다 —
    # 주 집계에서 빼되 값 자체는 버리지 않고 병기한다 (§Phase 1-5).
    exp: Dict[str, Dict[Cell, int]] = {ch: defaultdict(int) for ch in fourd.CHANNELS}
    exp_fb: Dict[str, Dict[Cell, int]] = {ch: defaultdict(int) for ch in fourd.CHANNELS}
    cells_per_step = C.WORKER_SPEED_MPS * C.STEP_SECONDS / C.CELL_SIZE_M
    occupied = {w.pos for w in workers}

    for step in range(horizon):
        for w in workers:
            # ── 노출 집계: 위치를 채널 셀집합과 대조 ──
            pos = w.pos
            bucket = exp if w.target_derived else exp_fb
            for ch, cells in ch_cells.items():
                if pos in cells:
                    bucket[ch][pos] += 1

            # ── 작업(체류) ──
            if w.state == "work":
                w.timer -= 1
                if w.timer <= 0:
                    w.state = "travel"
                    w.target = None
                    w.route = []
                continue

            # ── 목표 선정 ──
            if w.target is None:
                w.target = w.targets[rng.randrange(len(w.targets))]
                w.route = []
            if abs(w.pos[0] - w.target[0]) <= 1 and abs(w.pos[1] - w.target[1]) <= 1:
                w.state = "work"
                w.timer = max(1, dwell_steps)
                continue
            if not w.route:
                w.route = soft_route(grid, w.pos, w.target, w.rho, rng, None,
                                     nbrs=nbrs)
                if not w.route:                      # 도달 불가 → 다른 목표 재표집
                    w.target = None
                    continue

            nxt = w.route[0]
            if nxt != w.pos and nxt in occupied:      # 한 셀 = 한 명
                w.stuck += 1
                if w.stuck > 8:                       # 교착 → 옆걸음으로 대칭을 깬다
                    side = [(nr, nc) for (nr, nc, _b, _e) in nbrs.get(w.pos, ())
                            if (nr, nc) not in occupied]
                    if side:
                        occupied.discard(w.pos)
                        w.pos = rng.choice(side)
                        occupied.add(w.pos)
                    w.route = []
                    w.stuck = 0
                continue
            w.stuck = 0
            w.move_accum += cells_per_step
            if w.move_accum < 1.0:                    # 속도 제한: 2스텝당 1칸
                continue
            w.move_accum -= 1.0
            w.route.pop(0)
            if nxt != w.pos:
                occupied.discard(w.pos)
                occupied.add(nxt)
            w.pos = nxt

        if logger is not None:
            logger.log(day, level, step, workers)
    return exp, exp_fb


# ══════════════════════════════════════════════════════════
# 일 루프
# ══════════════════════════════════════════════════════════
def _crew_specs_by_level(schedule, day: int, work_locs: "WorkLocations" = None):
    """그날 in_progress 액티비티 → 층별 [(activityID, trade, crewSize)].

    층은 `work_locs.level_of()` 가 정한다. 동바리 해체처럼 작업이 슬래브 하부에서
    이루어지는 경우 액티비티의 zone 층이 아니라 직하부 층에 워커를 놓는다
    (H008 zone 이 이미 직하부로 계산되어 있고 그 zone 의 despawnActivity 가
    바로 그 해체 태스크다 — 추정이 아니다)."""
    by_level: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
    for aid in sorted(schedule.activeSet(day)):
        a = schedule.activities[aid]
        if not a.crew_size:
            continue
        lv = work_locs.level_of(a.activity_id, a.level) if work_locs else a.level
        by_level[lv].append((a.activity_id, a.trade, a.crew_size))
    return by_level


def run_project_workers(schedule, site, lifecycle, crews_cfg, work_locs: WorkLocations,
                        days: Optional[int] = None, day_start: int = 0,
                        mc_runs: int = 1, seed=0, max_steps: Optional[int] = None,
                        trajectory_path: Optional[str] = None,
                        trajectory_every: int = 1,
                        controls_effects: Optional[dict] = None,
                        temp_structures=None) -> dict:
    """워커 기반 4D 일 루프. fourd.run_project 와 같은 λ 정의를 쓰되 개별 워커가 돈다.

    trajectory_path 는 mc_runs == 1 일 때만 유효하다 — 반복 중 기록은 성능을 떨어뜨리고
    2D MovementLogger 도 같은 이유로 몬테카를로에 붙이지 않는다."""
    n_days = schedule.duration if days is None else days
    horizon = C.WORKDAY_STEPS if max_steps is None else int(max_steps)
    dwell_steps = max(1, horizon // 8)
    effects = controls_effects or {}

    lam: Dict[Tuple[str, int, int, int, str], float] = {}
    exposure_steps: Dict[Tuple[str, int, int, int, str], float] = {}       # 주 집계(유도만)
    exposure_steps_fb: Dict[Tuple[str, int, int, int, str], float] = {}    # 폴백(병기용)
    place = {"derived": 0, "fallback": 0}

    logger = None
    if trajectory_path:
        if mc_runs != 1:
            raise ValueError("궤적 기록은 mc_runs==1 에서만 허용된다 "
                             "(반복 중 기록은 성능을 떨어뜨린다)")
        logger = TrajectoryLogger(trajectory_path, every=trajectory_every)

    try:
        for d in range(day_start, n_days):
            hz = lifecycle.hazards(d)
            for level_id, specs in _crew_specs_by_level(schedule, d, work_locs).items():
                if level_id not in site.levels or not specs:
                    continue
                grid, ch_cells, cell_mult = fourd.build_level_day(
                    site, level_id, hz, effects, d, temp_structures=temp_structures)
                comp = [cell for cell in site.level(level_id).main_component()
                        if grid[cell[0], cell[1]] not in (C.WALL, C.FLOOR_OPENING)]
                if not comp:
                    continue
                nbrs = _get_context(grid, None)["nbrs"]
                for run in range(mc_runs):
                    rng = random.Random(f"{seed}|{d}|{level_id}|{run}")
                    workers, st = make_workers(specs, work_locs, grid, comp,
                                               crews_cfg, rng)
                    place["derived"] += st["derived"]
                    place["fallback"] += st["fallback"]
                    exp, exp_fb = run_level_day_workers(
                        grid, ch_cells, workers, horizon, rng, dwell_steps,
                        nbrs=nbrs, logger=logger, day=d, level=level_id)
                    # 주 집계: 위치가 기하에서 유도된 워커만 (λ 도 여기서 나온다)
                    for ch, cellmap in exp.items():
                        p = C.CHANNEL_PER_STEP[ch]
                        cm = cell_mult[ch]
                        for (r, c), steps in cellmap.items():
                            key = (level_id, r, c, d, ch)
                            exposure_steps[key] = (exposure_steps.get(key, 0.0)
                                                   + steps / mc_runs)
                            lam[key] = (lam.get(key, 0.0)
                                        + steps * p * cm.get((r, c), 1.0) / mc_runs)
                    # 폴백: 병기용으로만 보관 (주 집계·λ 에 넣지 않는다)
                    for ch, cellmap in exp_fb.items():
                        for (r, c), steps in cellmap.items():
                            key = (level_id, r, c, d, ch)
                            exposure_steps_fb[key] = (exposure_steps_fb.get(key, 0.0)
                                                      + steps / mc_runs)
                movement._CTX.pop(id(grid), None)
    finally:
        if logger is not None:
            logger.close()

    return {"lam": lam,
            "exposure_steps": exposure_steps,          # 주 집계 — 유도 워커만
            "exposure_steps_fallback": exposure_steps_fb,   # 병기용 — 폴백 워커
            "days": n_days, "day_start": day_start, "mc_runs": mc_runs,
            "seed": seed, "horizon": horizon,
            "placement": place,
            "trajectory_path": trajectory_path,
            "trajectory_rows": logger.rows if logger else 0,
            "temp_structures": bool(temp_structures),
            "work_location_stats": dict(work_locs.stats)}


def channel_totals(result: dict, key: str = "exposure_steps") -> Dict[str, float]:
    out: Dict[str, float] = defaultdict(float)
    for (lv, r, c, d, ch), v in result.get(key, {}).items():
        out[ch] += v
    return dict(out)


def load_project_v2(project_dir: str = "project",
                    bindings: str = "build/lifecycle_bindings_v2.json",
                    library=None):
    """B-4: 84건 현행 바인딩을 **명시 주입**해 로드한다.

    project/lifecycle_bindings.json 은 21건으로 낡았고 갱신하지 않는다
    (그 파일 자체에 deprecated 표시를 남겨 두었다)."""
    import ptd_ttl
    from lifecycle import LifecycleEngine
    from schedule import Schedule
    from site_model import SiteModel

    lib = library if library is not None else ptd_ttl.require_library()
    schedule = Schedule.load(os.path.join(project_dir, "schedule.json"))
    site = SiteModel.load(os.path.join(project_dir, "site.json"))
    life = LifecycleEngine(lib.lifecycle_templates, bindings, schedule)
    with open(os.path.join(project_dir, "crews.json"), encoding="utf-8") as fp:
        crews_raw = json.load(fp)
    crews_cfg = {t["trade"]: t.get("rho", {}) for t in crews_raw.get("trades", [])}
    with open(os.path.join(project_dir, "site.json"), encoding="utf-8") as fp:
        grid_frame = json.load(fp)["gridFrame"]
    return schedule, site, life, crews_cfg, WorkLocations(grid_frame)
