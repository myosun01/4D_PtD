"""
movement.py — 시뮬레이션 엔진 + 작업자 이동 알고리즘
====================================================
- 격자 생성 / 작업자 클래스 / 하루 진행 루프 / 사고 판정(공유 엔진)
- 이동: 소프트 위험가중 A*(거시경로) + 작업구역 순회 + 작업 중 미세이동
"""
from __future__ import annotations
import csv
import datetime
import heapq
import math
import os
import random

import numpy as np

import config as C
import social

DIAG = 1.41421356


# ══════════════════════════════════════════════
# 격자
# ══════════════════════════════════════════════
def build_grid():
    rows, cols = C.GRID_ROWS, C.GRID_COLS
    g = np.zeros((rows, cols), dtype=int)
    g[0, :] = C.WALL; g[rows - 1, :] = C.WALL
    g[:, 0] = C.WALL; g[:, cols - 1] = C.WALL
    g[1:rows - 1, 15] = C.WALL; g[8:13, 15] = C.WALKABLE
    g[1:rows - 1, 30] = C.WALL; g[17:22, 30] = C.WALKABLE
    g[15, 1:15] = C.WALL; g[15, 5:9] = C.WALKABLE
    g[19:25, 4:11] = C.FLOOR_OPENING
    g[3:7, 3:9]    = C.MATERIAL
    g[4:9, 33:40]  = C.MATERIAL
    g[20:27, 18:20] = C.NARROW
    g[6:13, 22:24]  = C.NARROW
    return g


def fall_edge_cells(grid):
    R, Co = grid.shape
    out = set()
    for r in range(R):
        for c in range(Co):
            if grid[r, c] in (C.WALL, C.FLOOR_OPENING):
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                if 0 <= r + dr < R and 0 <= c + dc < Co and grid[r + dr, c + dc] == C.FLOOR_OPENING:
                    out.add((r, c)); break
    return out


def _walk(g, r, c):
    R, Co = g.shape
    return 0 <= r < R and 0 <= c < Co and g[r, c] not in (C.WALL, C.FLOOR_OPENING)


def _octile(a, b):
    dr, dc = abs(a[0] - b[0]), abs(a[1] - b[1])
    return (dr + dc) + (DIAG - 2) * min(dr, dc)


# ══════════════════════════════════════════════
# 정적 컨텍스트(격자·effects가 고정인 동안 1회만 계산 → 매 스텝 조회)
# ══════════════════════════════════════════════
# [성능] step_world/soft_route가 매 스텝·매 이웃마다 재계산하던 값들
# (walkable 판정, 위험가중, 개구부 인접, 대각선 코너컷, 작업구역/점유용 집합)은
# 격자와 effects가 바뀌지 않는 한 항상 같다. 격자당 1회만 만들어 재사용한다.
# 캐시 키는 grid 객체 식별자이며, grid/effects 동일성(is)까지 검증해 재활용한다.
# rng를 소비하지 않는 순수 정적 계산이므로 시뮬 결과는 비트 단위로 동일하다.
_CTX = {}


def _resolve_eff(effects):
    return effects or {ct: {"prob_mult": 1.0, "fatal_mult": 1.0, "weight_mult": 1.0}
                       for ct in (C.FLOOR_OPENING, C.MATERIAL, C.NARROW)}


def _build_context(grid, effects):
    R, Co = grid.shape
    eff = _resolve_eff(effects)

    def wm(cell):
        return eff.get(cell, {}).get("weight_mult", 1.0)

    edge_base = C.OPEN_EDGE_PEN * wm(C.FLOOR_OPENING)

    # 셀이 개구부(4방)에 인접한지 마스크 — 원래 soft_route의 edge 루프를 대체
    is_open = (grid == C.FLOOR_OPENING)
    near_open = np.zeros((R, Co), dtype=bool)
    near_open[1:, :]  |= is_open[:-1, :]
    near_open[:-1, :] |= is_open[1:, :]
    near_open[:, 1:]  |= is_open[:, :-1]
    near_open[:, :-1] |= is_open[:, 1:]

    # walkable 파이썬 2D 테이블 — numpy 스칼라 인덱싱 제거용
    walk = [[bool(grid[r, c] not in (C.WALL, C.FLOOR_OPENING)) for c in range(Co)]
            for r in range(R)]

    # 셀별 정적 위험비용. Theta*의 line-of-sight 구간 비용에도 동일한 값을 쓴다.
    risk_extra = {}
    for r in range(R):
        for c in range(Co):
            if not walk[r][c]:
                continue
            ncell = int(grid[r, c])
            extra = C.HAZARD_WEIGHT.get(ncell, 0.0) * C.RISK_K * wm(ncell)
            if near_open[r, c]:
                extra += edge_base
            risk_extra[(r, c)] = extra

    # 이웃 인접표: 각 walkable 셀에서 이동 가능한 이웃과 그 '정적 비용'을 선계산.
    # 순서는 원본 DIRS 순서 그대로 유지(=rng.uniform 호출 순서 동일).
    # cost = base + extra*aversion + rng.uniform(0, PATH_NOISE)  (aversion만 런타임)
    DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    nbrs = {}
    for r in range(R):
        for c in range(Co):
            if not walk[r][c]:
                continue
            lst = []
            for dr, dc in DIRS:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < R and 0 <= nc < Co and walk[nr][nc]):
                    continue
                diag = dr != 0 and dc != 0
                if diag and not (walk[r][nc] and walk[nr][c]):   # 대각선 코너컷 금지
                    continue
                base = DIAG if diag else 1.0
                extra = risk_extra[(nr, nc)]
                lst.append((nr, nc, base, extra))
            nbrs[(r, c)] = lst

    material = frozenset(map(tuple, np.argwhere(grid == C.MATERIAL).tolist()))
    narrow   = frozenset(map(tuple, np.argwhere(grid == C.NARROW).tolist()))
    anchors  = {z: C.WORK_ZONES[z]["cell"] for z in C.WORK_ZONES}
    zone_cells = {z: _zone_cells(grid, anchors[z]) for z in C.WORK_ZONES}

    return {"grid": grid, "effects": effects, "eff": eff, "nbrs": nbrs,
            "walk": walk, "risk_extra": risk_extra,
            "material": material, "narrow": narrow,
            "anchors": anchors, "zone_cells": zone_cells}


def _get_context(grid, effects):
    key = id(grid)
    ctx = _CTX.get(key)
    if ctx is not None and ctx["grid"] is grid and ctx["effects"] is effects:
        return ctx
    ctx = _build_context(grid, effects)
    _CTX[key] = ctx
    return ctx


# ══════════════════════════════════════════════
# 이동: 소프트 위험가중 A*
# ══════════════════════════════════════════════
def soft_route(g, start, goal, rho, rng, effects=None, max_expand=4000, nbrs=None):
    if start == goal:
        return []
    if nbrs is None:                     # 단독 호출 시(테스트 등) 컨텍스트 자동 구성
        nbrs = _get_context(g, effects)["nbrs"]
    aversion = 1.0 - max(0.05, min(0.95, rho))
    noise = C.PATH_NOISE
    uniform = rng.uniform
    push = heapq.heappush; pop = heapq.heappop
    gr, gc = goal
    openh = [(0.0, 0, start)]; came = {start: None}; gsc = {start: 0.0}; cnt = 1
    closed = set(); found = False; expanded = 0
    while openh:
        _, _, cur = pop(openh)
        if cur in closed:
            continue
        closed.add(cur)
        expanded += 1
        if expanded > max_expand:        # 안전 상한(최악의 경우 폭주 방지)
            break
        if cur == goal:
            found = True; break
        gcur = gsc[cur]
        for nr, nc, base, extra in nbrs[cur]:
            nxt = (nr, nc)
            if nxt in closed:
                continue
            # rng.uniform 호출 위치/순서/인자는 원본과 동일 → 결과 비트 동일
            t = gcur + base + extra * aversion + uniform(0, noise)
            if nxt not in gsc or t < gsc[nxt]:
                gsc[nxt] = t; came[nxt] = cur
                dr = nr - gr; dc = nc - gc      # _octile 인라인
                if dr < 0: dr = -dr
                if dc < 0: dc = -dc
                h = (dr + dc) + (DIAG - 2) * (dr if dr < dc else dc)
                push(openh, (t + h, cnt, nxt)); cnt += 1
    if not found:
        return []
    path = []; cur = goal
    while cur and cur != start:
        path.append(cur); cur = came[cur]
    path.reverse()
    return path


# ══════════════════════════════════════════════
# 이동: 위험가중 any-angle Theta*
# ══════════════════════════════════════════════
def _grid_line(a, b):
    """두 셀 중심 사이를 잇는 8-connected DDA 선분(양 끝 포함)."""
    r0, c0 = a; r1, c1 = b
    n = max(abs(r1 - r0), abs(c1 - c0))
    if n == 0:
        return [a]
    out = []
    for i in range(n + 1):
        r = int(round(r0 + (r1 - r0) * i / n))
        c = int(round(c0 + (c1 - c0) * i / n))
        if not out or out[-1] != (r, c):
            out.append((r, c))
    return out


def _line_of_sight(a, b, walk):
    """벽/개구부 관통과 대각선 코너컷을 모두 금지한 셀 중심 LOS."""
    cells = _grid_line(a, b)
    for r, c in cells:
        if not (0 <= r < len(walk) and 0 <= c < len(walk[0]) and walk[r][c]):
            return False
    for (r0, c0), (r1, c1) in zip(cells, cells[1:]):
        if r0 != r1 and c0 != c1:
            if not (walk[r0][c1] and walk[r1][c0]):
                return False
    return True


def theta_route(g, start, goal, rho, rng, effects=None, max_expand=4000,
                nbrs=None, ctx=None):
    """위험가중 확률적 Theta* 경로.

    A*의 8방향 이웃 확장은 유지하되, ``parent(current)`` 에서 이웃까지 LOS가
    있으면 현재 노드를 건너뛰어 any-angle 부모로 연결한다. 반환값은 작업자 이동·
    점유 집계에 쓸 수 있도록 LOS 세그먼트를 다시 연속 셀 경로로 펼친다.
    """
    if start == goal:
        return []
    if ctx is None:
        ctx = _get_context(g, effects)
    if nbrs is None:
        nbrs = ctx["nbrs"]
    walk = ctx["walk"]
    if (start not in nbrs or goal not in nbrs
            or not _line_of_sight(start, start, walk)
            or not _line_of_sight(goal, goal, walk)):
        return []

    aversion = 1.0 - max(0.05, min(0.95, rho))
    noise_by_cell = {}

    def cell_noise(cell):
        if cell not in noise_by_cell:
            noise_by_cell[cell] = rng.uniform(0.0, C.PATH_NOISE)
        return noise_by_cell[cell]

    def segment_cost(a, b):
        line = _grid_line(a, b)
        total = 0.0
        pr, pc = line[0]
        for cell in line[1:]:
            r, c = cell
            total += math.hypot(r - pr, c - pc)
            total += ctx["risk_extra"].get(cell, 0.0) * aversion
            total += cell_noise(cell)
            pr, pc = r, c
        return total

    gr, gc = goal
    parent = {start: start}
    gsc = {start: 0.0}
    openh = [(math.hypot(start[0] - gr, start[1] - gc), 0, start)]
    closed = set(); count = 1; expanded = 0; found = False

    while openh:
        _f, _tie, cur = heapq.heappop(openh)
        if cur in closed:
            continue
        closed.add(cur)
        expanded += 1
        if expanded > max_expand:
            break
        if cur == goal:
            found = True
            break
        pcur = parent[cur]
        for nr, nc, _base, _extra in nbrs[cur]:
            nxt = (nr, nc)
            if nxt in closed:
                continue
            if _line_of_sight(pcur, nxt, walk):
                candidate_parent = pcur
                tentative = gsc[pcur] + segment_cost(pcur, nxt)
            else:
                candidate_parent = cur
                tentative = gsc[cur] + segment_cost(cur, nxt)
            if tentative < gsc.get(nxt, float("inf")):
                gsc[nxt] = tentative
                parent[nxt] = candidate_parent
                h = math.hypot(nr - gr, nc - gc)  # any-angle에 admissible한 Euclidean h
                heapq.heappush(openh, (tentative + h, count, nxt))
                count += 1

    if not found:
        return []
    waypoints = [goal]
    cur = goal
    while cur != start:
        cur = parent[cur]
        waypoints.append(cur)
    waypoints.reverse()
    path = []
    for a, b in zip(waypoints, waypoints[1:]):
        segment = _grid_line(a, b)
        path.extend(segment[1:])
    return path


# ══════════════════════════════════════════════
# 작업자
# ══════════════════════════════════════════════
class Worker:
    __slots__ = ("id", "is_foreman", "pos", "home", "queue", "cur", "state",
                 "route", "timer", "rho", "base_rho", "ppe", "injured",
                 "accident_type", "depart", "_stuck", "_move_accum")

    def __init__(self, wid, start, home, queue, rho, is_foreman, depart):
        self.id = wid; self.is_foreman = is_foreman
        self.pos = start; self.home = home
        self.queue = list(queue); self.cur = self.queue.pop(0) if self.queue else None
        self.state = "wait"            # wait→travel→work→travel→...
        self.route = []; self.timer = 0
        self.rho = rho; self.base_rho = rho; self.ppe = False
        self.injured = False; self.accident_type = "none"
        self.depart = depart; self._stuck = 0
        self._move_accum = 0.0         # 이동 속도 누적(칸). 1.0 이상일 때 한 칸 전진


def _assign_task_queue(rng):
    """PoI(작업구역) 큐 배정 — [4D 격리점] 나중에 공정 스케줄에서 채우도록 교체."""
    zone_ids = list(C.WORK_ZONES)
    return rng.sample(zone_ids, min(C.TASKS_PER_WORKER, len(zone_ids)))


def make_workers(grid, rng):
    """고유 스폰 + foreman + PoI 큐 + 출발시각 분산."""
    R, Co = grid.shape
    hr, hc = C.HOME_CELL
    spawn = [(r, c) for r in range(hr - 4, hr + 1) for c in range(2, 14)
             if 0 <= r < R and grid[r, c] == C.WALKABLE]
    rng.shuffle(spawn)
    workers = []
    for i in range(C.N_WORKERS):
        is_fore = i < C.N_FOREMEN
        rho = social.init_rho(i, is_fore, rng)
        q = _assign_task_queue(rng)
        st = spawn.pop() if spawn else C.HOME_CELL
        depart = rng.randint(0, C.START_STAGGER_S)
        workers.append(Worker(i, st, C.HOME_CELL, q, rho, is_fore, depart))
    return workers


def _zone_cells(grid, anchor):
    ar, ac = anchor
    return [(ar + dr, ac + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)
            if _walk(grid, ar + dr, ac + dc)]


# ══════════════════════════════════════════════
# 하루 진행 (1스텝)
# ══════════════════════════════════════════════
def step_world(workers, grid, effects, rng, frame, fall_edges, record_accident=None,
               logger=None, scale=None):
    """모든 작업자 1스텝. 한 셀=한 명, 사고 판정(effects 반영), 사회효과(social 위임).
    scale=None이면 C.ACCIDENT_PROB_SCALE(관전 배율)를 사용하고, 연구/보정 경로는
    scale=1.0(또는 0.0=사고 OFF)을 명시적으로 넘긴다. logger가 있으면 스텝별 동선 기록."""
    scale = C.ACCIDENT_PROB_SCALE if scale is None else scale
    ctx = _get_context(grid, effects)        # 격자당 1회 구성 → 이후 조회만
    eff = ctx["eff"]
    p_fall   = C.P_FALL_PER_STEP   * eff[C.FLOOR_OPENING]["prob_mult"] * scale
    p_mat    = C.P_STRUCK_MATERIAL * eff[C.MATERIAL]["prob_mult"]      * scale
    p_narrow = C.P_STRUCK_NARROW   * eff[C.NARROW]["prob_mult"]        * scale
    fatal_p  = C.FATAL_FRACTION    * eff[C.FLOOR_OPENING]["fatal_mult"]
    anchors = ctx["anchors"]; zone_cells = ctx["zone_cells"]
    material = ctx["material"]; narrow = ctx["narrow"]; nbrs = ctx["nbrs"]
    # 이동 속도: 스텝당 전진 칸수 = 속도(m/s)×스텝(s)÷셀(m). 0.5m/s → 0.5칸/스텝(2스텝당 1칸)
    cells_per_step = C.WORKER_SPEED_MPS * C.STEP_SECONDS / C.CELL_SIZE_M

    occupied = {w.pos for w in workers if not w.injured and w.state != "done"}

    for w in workers:
        if w.injured or w.state == "done":
            continue
        # 출발 분산: 아직 출발 전이면 집에서 대기
        if w.state == "wait":
            if frame >= w.depart:
                w.state = "travel"
            else:
                continue

        pos = w.pos; r, c = pos

        # ── 사고 판정 (grid[r,c] numpy 인덱싱 → 선계산 집합 조회) ──
        hit = None
        if pos in material and rng.random() < p_mat:
            hit = "struck"
        elif pos in narrow and rng.random() < p_narrow:
            hit = "struck"
        elif pos in fall_edges and rng.random() < p_fall:
            hit = "fatal" if rng.random() < fatal_p else "fall"
        if hit:
            w.injured = True; w.accident_type = hit; w.state = "injured"
            if record_accident:
                record_accident(r, c, hit)
            social.apply_witness_shock(workers, r, c)
            continue

        # ── 작업(체류) 중: 구역 내 미세이동(차분하게) ──
        if w.state == "work":
            w.timer -= 1
            if rng.random() < C.MILL_MOVE_PROB:
                cand = [p for p in zone_cells[w.cur] if p not in occupied]
                if cand:
                    occupied.discard(w.pos); w.pos = rng.choice(cand); occupied.add(w.pos)
            if w.timer <= 0:
                if not w.queue:
                    w.queue = _assign_task_queue(rng)
                w.cur = w.queue.pop(0); w.state = "travel"; w.route = []
            continue

        # ── 이동 ──
        target = anchors[w.cur]
        if abs(w.pos[0] - target[0]) <= 1 and abs(w.pos[1] - target[1]) <= 1:
            # 체류시간에 개인별 ±편차(평균은 DWELL_STEPS 유지) → 작업 진입/종료가
            # 한꺼번에 몰려 '전원 작업'으로 멈춘 듯 보이는 현상 완화. FRAC=0이면 기존과 동일.
            dwell = C.DWELL_STEPS
            if C.DWELL_JITTER_FRAC:
                dwell += int(round(rng.uniform(-1.0, 1.0) * C.DWELL_JITTER_FRAC * C.DWELL_STEPS))
            w.state = "work"; w.timer = max(1, dwell)
            continue
        if not w.route:
            w.route = soft_route(grid, w.pos, target, w.rho, rng, eff, nbrs=nbrs)
            if not w.route:
                continue
        nxt = w.route[0]
        if nxt != w.pos and nxt in occupied:        # 한 셀 = 한 명: 대기
            w._stuck += 1
            if w._stuck > 8:                         # 오래 막히면 교착 → 옆걸음으로 대칭을 깬다
                # 비어있는 인접 칸으로 한 칸 비켜서 정체를 풀고 경로 재탐색.
                # (이 장치가 없으면 좁은 통로에서 전원이 서로를 막아 영구 정지함)
                side = [(nr, nc) for (nr, nc, _b, _e) in nbrs.get(w.pos, ())
                        if (nr, nc) not in occupied]
                if side:
                    occupied.discard(w.pos); w.pos = rng.choice(side); occupied.add(w.pos)
                w.route = []; w._stuck = 0
            continue
        w._stuck = 0
        # ── 이동 속도 제한: 누적이 한 칸(1.0) 찰 때만 전진(0.5m/s → 2스텝당 1칸) ──
        w._move_accum += cells_per_step
        if w._move_accum < 1.0:
            continue
        w._move_accum -= 1.0
        if w.route:
            w.route.pop(0)
        if nxt != w.pos:
            occupied.discard(w.pos); occupied.add(nxt)
        w.pos = nxt

    social.apply_imitation(workers, frame)
    if logger is not None:                   # 스텝별 작업자 위치/상태 CSV 기록
        logger.log_frame(frame, workers)


def run_one_day(grid, effects, fall_edges, seed, max_steps=None, logger=None):
    """헤드리스 하루 1회 (Monte Carlo용). 반환: (사고리스트, 노출맵, 기대위험맵 λ).
    연구 경로이므로 scale=1.0 고정 — 관전용 ACCIDENT_PROB_SCALE은 절대 곱하지 않는다.

    [기대위험 λ] 확률이 1e-8 수준이라 사고를 '표집'하면 거의 0건이 나온다. 대신
    위험셀 체류 스텝수 × 그 셀 채널의 per-step 사고확률을 누적하면, 사고가 실제로
    나지 않아도 '하루 사고 기대건수' 지도가 매끄럽게 나온다.
    λ(cell) = (그 셀 체류 worker-step 수) × p_channel  =  노출스텝 × p_channel 과 동일."""
    rng = random.Random(seed)
    workers = make_workers(grid, rng)
    R, Co = grid.shape
    accidents = []
    ctx = _get_context(grid, effects)
    material = ctx["material"]; narrow = ctx["narrow"]; fe = set(fall_edges)
    hazard = material | narrow | fe                             # 노출 대상 셀
    exp_counts = {}                                             # (r,c) → 스텝 누적
    horizon = max_steps or C.WORKDAY_STEPS
    for f in range(horizon):
        for w in workers:
            if w.injured or w.state in ("done", "wait"):
                continue
            pos = w.pos
            if pos in hazard:
                exp_counts[pos] = exp_counts.get(pos, 0) + 1
        step_world(workers, grid, effects, rng, f, fall_edges,
                   record_accident=lambda r, c, t: accidents.append((r, c, t)),
                   logger=logger, scale=1.0)
    # 채널별 실효 per-step 확률(자기보정 시 보정값이 C.P_*에 반영됨, effects 배율 포함, scale=1.0)
    eff = ctx["eff"]
    p_fall   = C.P_FALL_PER_STEP   * eff[C.FLOOR_OPENING]["prob_mult"]
    p_mat    = C.P_STRUCK_MATERIAL * eff[C.MATERIAL]["prob_mult"]
    p_narrow = C.P_STRUCK_NARROW   * eff[C.NARROW]["prob_mult"]
    exposure = np.zeros((R, Co)); risk = np.zeros((R, Co))      # 마지막에 1회 배열화
    for (rr, cc), v in exp_counts.items():
        exposure[rr, cc] = v
        cell = (rr, cc)
        # 사고 판정 우선순위(적재물>협소>추락)와 동일 채널 확률로 λ 산출
        if cell in material:
            p = p_mat
        elif cell in narrow:
            p = p_narrow
        else:                                                  # fall_edges
            p = p_fall
        risk[rr, cc] = v * p
    return accidents, exposure, risk


# ── 시간 유틸 ──
def sim_clock(frame):
    total = C.WORK_START_HOUR * 3600 + frame * C.STEP_SECONDS
    return f"{(total // 3600) % 24:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def within_work_hours(frame):
    return 0 <= frame < C.WORKDAY_STEPS


# ══════════════════════════════════════════════
# 동선 로그 (각 작업자 스텝별 위치/상태 → CSV)
# ══════════════════════════════════════════════
class MovementLogger:
    """작업자 스텝별 위치/상태를 CSV로 기록(관전/헤드리스 동선 추적용).
    every로 기록 주기를 조절한다. 몬테카를로(대량 반복)에는 성능상 붙이지 않는다."""
    HEADER = ["frame", "clock", "worker_id", "row", "col", "state",
              "is_foreman", "injured", "accident_type"]

    def __init__(self, path=None, every=None):
        if path is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(os.path.dirname(__file__), f"movement_log_{ts}.csv")
        self.path = path
        self.every = max(1, every or getattr(C, "MOVEMENT_LOG_EVERY", 1))
        self._fh = open(path, "w", newline="", encoding="utf-8-sig")
        self._wr = csv.writer(self._fh)
        self._wr.writerow(self.HEADER)

    def log_frame(self, frame, workers):
        if frame % self.every:
            return
        clk = sim_clock(frame)
        self._wr.writerows(
            [frame, clk, w.id, w.pos[0], w.pos[1], w.state,
             int(w.is_foreman), int(w.injured), w.accident_type] for w in workers)

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def run_logged_day(path=None, seed=1000, scenario="base", every=None, max_steps=None):
    """헤드리스 하루 1회를 돌리며 작업자 동선을 CSV 로그로 남긴다.
    반환: (사고리스트, 로그파일경로). 로그는 프로젝트 폴더에 movement_log_*.csv 로 생성."""
    import ptd_ttl
    grid0 = build_grid()
    grid, effects = ptd_ttl.apply(grid0, scenario)
    fall_edges = fall_edge_cells(grid)
    ensure_calibrated(grid, effects, fall_edges)          # SELF_CALIBRATE=True면 1회 보정
    with MovementLogger(path=path, every=every) as logger:
        accidents, _exp, _risk = run_one_day(grid, effects, fall_edges, seed=seed,
                                             max_steps=max_steps, logger=logger)
        return accidents, logger.path


# ══════════════════════════════════════════════
# 자기보정 (노출초 가정 없이 실제 배치에 per-step 확률을 맞춤)
# ══════════════════════════════════════════════
def measure_exposure(grid, effects, fall_edges, n_days=None, base_seed=None):
    """예비 headless 실행으로 채널별 1인당·하루 평균 노출스텝을 측정.
    사고는 끄고(scale=0.0) 순수 노출만 세며, 사고 판정의 elif 우선순위
    (적재물 > 협소 > 추락)를 그대로 반영해 '실효 노출'을 집계한다."""
    n_days    = C.CALIB_DAYS if n_days is None else n_days
    base_seed = C.CALIB_SEED if base_seed is None else base_seed
    ctx = _get_context(grid, effects)
    material = ctx["material"]; narrow = ctx["narrow"]; fe = set(fall_edges)
    tot_fall = tot_mat = tot_narrow = 0
    for d in range(n_days):
        rng = random.Random(base_seed + d)
        workers = make_workers(grid, rng)
        for f in range(C.WORKDAY_STEPS):
            for w in workers:
                if w.injured or w.state in ("done", "wait"):
                    continue
                p = w.pos
                if p in material:
                    tot_mat += 1
                elif p in narrow:
                    tot_narrow += 1
                elif p in fe:
                    tot_fall += 1
            step_world(workers, grid, effects, rng, f, fall_edges, scale=0.0)
    denom = max(1, n_days * C.N_WORKERS)
    return {"fall": tot_fall / denom, "mat": tot_mat / denom, "narrow": tot_narrow / denom}


def calibrate_probabilities(grid, effects, fall_edges, n_days=None, base_seed=None):
    """측정 노출 → per-step 확률 역산.
    per_step = (연재해율 × 유형비중 ÷ 연근무일) ÷ (1인당 하루 평균 노출스텝).
    struck(적재물+협소)는 두 채널 노출 합으로 나눠 동일 per-step을 부여."""
    exp = measure_exposure(grid, effects, fall_edges, n_days, base_seed)
    daily_fall   = C.ANNUAL_INJURY_RATE * C.SHARE_FALL   / C.WORK_DAYS_PER_YEAR
    daily_struck = C.ANNUAL_INJURY_RATE * C.SHARE_STRUCK / C.WORK_DAYS_PER_YEAR
    struck_exp = exp["mat"] + exp["narrow"]
    p_fall   = daily_fall / exp["fall"] if exp["fall"] > 0 else 0.0
    p_struck = daily_struck / struck_exp if struck_exp > 0 else 0.0
    return {"p_fall": p_fall, "p_mat": p_struck, "p_narrow": p_struck,
            "exposure": exp, "daily_fall": daily_fall, "daily_struck": daily_struck}


_CALIBRATED = False


def ensure_calibrated(grid, effects, fall_edges, force=False):
    """SELF_CALIBRATE=True면 1회만 예비실행으로 확률을 역산해 config에 런타임 반영.
    꺼져 있으면 아무것도 하지 않아 config의 고정 절대값을 그대로 쓴다."""
    global _CALIBRATED
    if not force and (_CALIBRATED or not C.SELF_CALIBRATE):
        return None
    res = calibrate_probabilities(grid, effects, fall_edges)
    C.P_FALL_PER_STEP   = res["p_fall"]
    C.P_STRUCK_MATERIAL = res["p_mat"]
    C.P_STRUCK_NARROW   = res["p_narrow"]
    _CALIBRATED = True
    return res
