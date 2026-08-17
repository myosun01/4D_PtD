"""
viewer.py — 화면(관전) + Monte Carlo 반복(히트맵)
=================================================
- 관전: 하루(10:00~18:00)를 실시간 재생. 위치만 갱신해 부드럽게(깜빡임 없음).
- 반복: 사용자가 횟수를 입력 → N회 반복 → 사고 핫스팟 히트맵.
  · 화면: "반복 횟수" 입력칸 + [히트맵 생성] 버튼
  · 명령행: python viewer.py --mc --scenario base --runs 200

[Unity 이식] 이 파일(화면/실행)은 Unity가 대체 → 폐기 대상.
의존: config, movement, ptd_ttl (social은 movement 통해 사용).
"""
import argparse
import multiprocessing as mp
import os
import queue as _queue
import random
import time

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap
from matplotlib.widgets import Button, Slider, TextBox
from matplotlib import font_manager

import config as C
import movement as M
import ptd_ttl


# ── 한글 폰트 ──
def set_korean_font():
    for name in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
            plt.rcParams["font.family"] = name
            break
        except Exception:
            continue
    plt.rcParams["axes.unicode_minus"] = False


set_korean_font()

STATE_COLOR = {"wait": "#94a3b8", "travel": "#16a34a", "work": "#7c3aed", "done": "#2563eb"}
BTN_FACE, BTN_EDGE = "#ffffff", "#1e3a8a"


# ══════════════════════════════════════════════
# Monte Carlo (화면 버튼 / 명령행 공용)
# ══════════════════════════════════════════════
def run_monte_carlo(scenario, runs, progress=True, progress_cb=None, max_steps=None,
                    save_csv=None):
    """N회 반복 → 노출·기대위험(λ) 누적. 반환 dict의 핵심은 risk(런당 평균 λ맵).
    사고 사건 표집(acc_count)은 확률이 극소라 거의 0 — 보조 지표로만 유지.
    save_csv 지정 시 좌표 로그 CSV 저장(<prefix>_risk.csv, <prefix>_accidents.csv)."""
    grid0 = M.build_grid()
    grid, effects = ptd_ttl.apply(grid0, scenario)
    fall_edges = M.fall_edge_cells(grid)
    R, Co = grid.shape
    acc_count = np.zeros((R, Co)); exposure = np.zeros((R, Co)); risk_sum = np.zeros((R, Co))
    per_run = []; by = {"struck": 0, "fall": 0, "fatal": 0}
    for k in range(runs):
        acc, exp, risk = M.run_one_day(grid, effects, fall_edges, seed=1000 + k, max_steps=max_steps)
        per_run.append(len(acc)); exposure += exp; risk_sum += risk
        for (r, c, ty) in acc:
            acc_count[r, c] += 1; by[ty] += 1
        if progress and (k + 1) % max(1, runs // 10) == 0:
            print(f"  {k+1}/{runs} 런 ... λ합 {risk_sum.sum()/(k+1):.4e} (표집사고 {sum(per_run)}건)")
        if progress_cb:
            progress_cb(k + 1, runs)
    risk_avg = risk_sum / runs                              # 런당 평균 기대위험 λ(cell)
    res = dict(grid=grid, acc=acc_count, exp=exposure, risk=risk_avg,
               per=per_run, by=by, runs=runs, scenario=scenario)
    if save_csv:
        _save_mc_csv(save_csv, res, fall_edges)
    return res


def _save_mc_csv(prefix, res, fall_edges):
    """MC 좌표 로그 저장(기대위험 산출과 일관).
    · <prefix>_risk.csv     : 위험셀별 row,col,channel,exposure_steps_per_run,lambda_per_run,cell_daily_prob_pct
    · <prefix>_accidents.csv: 표집된 실제 사고 row,col,type,count (극소; 보조)
    lambda_per_run = 노출스텝(런당) × 채널 per-step 확률 = 그 셀 하루 사고 기대건수.
    cell_daily_prob = 1 − exp(−λ)."""
    import csv
    grid = res["grid"]; risk = res["risk"]; exp = res["exp"]; runs = res["runs"]
    fe = set(fall_edges)
    with open(f"{prefix}_risk.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "col", "channel", "exposure_steps_per_run",
                    "lambda_per_run", "cell_daily_prob_pct"])
        for (r, c) in sorted(zip(*np.where(risk > 0)), key=lambda rc: -risk[rc[0], rc[1]]):
            cell = int(grid[r, c])
            ch = ("material" if cell == C.MATERIAL else
                  "narrow" if cell == C.NARROW else "fall_edge" if (r, c) in fe else "other")
            lam = risk[r, c]
            w.writerow([r, c, ch, f"{exp[r, c]/runs:.3f}", f"{lam:.6e}",
                        f"{(1-np.exp(-lam))*100:.5f}"])
    with open(f"{prefix}_accidents.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "col", "count_over_all_runs"])
        for (r, c) in zip(*np.where(res["acc"] > 0)):
            w.writerow([r, c, int(res["acc"][r, c])])


# ══════════════════════════════════════════════
# 병렬 배치 실행 (multiprocessing) — N회 하루를 코어 수만큼 분산
# ══════════════════════════════════════════════
# [spawn 안전] 워커는 최상위 함수 + Pool initializer로 프로세스당 격자를 1회 구성.
# 각 런은 seed=base+k 로 결정적이므로, 병렬 합산 결과 = 단일 프로세스 합산 결과(동일 시드).
_W = {}   # 워커 프로세스별 캐시(격자/effects/fall_edges/max_steps)


def _batch_init(scenario, max_steps):
    """Pool 워커 초기화: 프로세스당 격자·effects를 1회 구성해 재사용."""
    grid0 = M.build_grid()
    grid, effects = ptd_ttl.apply(grid0, scenario)
    _W["grid"] = grid
    _W["effects"] = effects
    _W["fall_edges"] = M.fall_edge_cells(grid)
    _W["max_steps"] = max_steps
    M.ensure_calibrated(grid, effects, _W["fall_edges"])   # SELF_CALIBRATE 시 프로세스별 1회


def _batch_run_seed(seed):
    """하루 1회 실행 → (seed, 기대위험맵, 노출맵, 사고리스트) 반환(합산용 부분결과)."""
    acc, exp, risk = M.run_one_day(_W["grid"], _W["effects"], _W["fall_edges"],
                                   seed=seed, max_steps=_W["max_steps"])
    return seed, risk, exp, acc


def run_monte_carlo_parallel(scenario, runs, n_procs=None, max_steps=None,
                             save_csv=None, progress=True, base_seed=1000):
    """N회 하루를 병렬(spawn Pool)로 실행 → 기대위험(λ)/노출/사고 합산. 반환 dict은
    run_monte_carlo 와 동일 스키마(grid, acc, exp, risk, per, by, runs, scenario)."""
    n_procs = n_procs or min(runs, mp.cpu_count() or 1)
    grid0 = M.build_grid()
    grid, effects = ptd_ttl.apply(grid0, scenario)
    fall_edges = M.fall_edge_cells(grid)
    R, Co = grid.shape
    acc_count = np.zeros((R, Co)); exposure = np.zeros((R, Co)); risk_sum = np.zeros((R, Co))
    per_run = []; by = {"struck": 0, "fall": 0, "fatal": 0}
    seeds = [base_seed + k for k in range(runs)]
    ctx = mp.get_context("spawn")               # Windows 안전 명시
    done = 0
    with ctx.Pool(n_procs, initializer=_batch_init, initargs=(scenario, max_steps)) as pool:
        for seed, risk, exp, acc in pool.imap_unordered(_batch_run_seed, seeds, chunksize=1):
            risk_sum += risk; exposure += exp
            per_run.append(len(acc))
            for (r, c, ty) in acc:
                acc_count[r, c] += 1; by[ty] += 1
            done += 1
            if progress and (done % max(1, runs // 10) == 0 or done == runs):
                print(f"  {done}/{runs} 런 완료", flush=True)
    risk_avg = risk_sum / runs                  # 런당 평균 기대위험 λ(cell)
    res = dict(grid=grid, acc=acc_count, exp=exposure, risk=risk_avg,
               per=per_run, by=by, runs=runs, scenario=scenario)
    if save_csv:
        _save_mc_csv(save_csv, res, fall_edges)
    return res


# ── 자식 프로세스 진입점 (multiprocessing.spawn 안전: 최상위 함수) ──
# [멈춤 해결] 스레드는 GIL 때문에 CPU-bound MC가 GUI를 굶긴다. 별도 '프로세스'로
# 돌리면 진짜 병렬이라 GUI가 전혀 안 멈춘다. 진행률/결과는 Queue로만 주고받는다.
# 결과 dict는 numpy 배열/리스트/기본형뿐이라 pickle 가능(Queue 전송 OK).
def _mc_worker(scenario, runs, out_queue, max_steps=None):
    try:
        res = run_monte_carlo(
            scenario, runs, progress=False, max_steps=max_steps,
            progress_cb=lambda k, total: out_queue.put(("progress", k, total)))
        out_queue.put(("result", res))
    except Exception as exc:                       # 자식이 죽어도 부모가 안 멈추게
        import traceback
        out_queue.put(("error", f"{exc}\n{traceback.format_exc()}"))


def zone_daily_probs(res):
    """구역(WORK_ZONES)별 하루 사고확률 = 1 − exp(−Σλ). 위험 높은 순 정렬해 반환."""
    grid = res["grid"]; risk = res["risk"]
    out = []
    for z, info in C.WORK_ZONES.items():
        cells = M._zone_cells(grid, info["cell"])
        lam = float(sum(risk[r, c] for (r, c) in cells))
        out.append((z, info["cell"], info.get("note", ""), lam, 1 - np.exp(-lam)))
    out.sort(key=lambda x: x[4], reverse=True)
    return out


def make_heatmap_figure(res):
    """패널1 = 기대위험 λ(셀당 하루 사고 기대건수), 패널2 = 구역별 하루 사고확률(%).
    표집된 실제 사고(극소)는 패널1에 보조 마커로만 표시."""
    grid = res["grid"]; runs = res["runs"]; risk = res["risk"]
    fall_edges = M.fall_edge_cells(grid)
    struct = np.where(np.isin(grid, [C.WALL, C.FLOOR_OPENING]), grid, np.nan)
    scmap = ListedColormap(["#cbd5e1", C.CELL_COLOR[C.WALL], C.CELL_COLOR[C.FLOOR_OPENING]])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(18, 7.5))

    def overlay(ax):
        ax.imshow(np.ma.masked_invalid(struct), cmap=scmap, vmin=0, vmax=5,
                  alpha=.4, interpolation="nearest", zorder=1)
        for cell in (C.MATERIAL, C.NARROW):
            ax.imshow(np.where(grid == cell, 1, np.nan),
                      cmap=ListedColormap([C.CELL_COLOR[cell]]), alpha=.22,
                      interpolation="nearest", zorder=1)

    # ── 패널1: 기대위험 λ ──
    m1 = np.ma.masked_where(risk <= 0, risk)
    im1 = a1.imshow(m1, cmap="hot", interpolation="nearest", alpha=.95, zorder=2)
    overlay(a1); fig.colorbar(im1, ax=a1, shrink=.7, label="셀당 하루 사고 기대건수 λ")
    total_lambda = float(risk.sum())
    site_prob = 1 - np.exp(-total_lambda)
    a1.set_title(f"① 기대위험 λ — {ptd_ttl.scenario_label(res['scenario'])} / {runs}런\n"
                 f"현장 전체 하루 사고확률 ~ {site_prob*100:.4f}% (Σλ={total_lambda:.3e})",
                 fontweight="bold")
    # 보조: 표집된 실제 사고(거의 0). 있으면 X로만 표시.
    ar, ac = np.where(res["acc"] > 0)
    if len(ar):
        a1.scatter(ac, ar, marker="x", c="#00e5ff", s=45, linewidths=1.5, zorder=5,
                   label=f"표집사고 {int(res['acc'].sum())}건")
        a1.legend(loc="upper right", fontsize=8, framealpha=.8)

    # ── 패널2: 구역별 하루 사고확률(%) ──
    zp = zone_daily_probs(res)
    overlay(a2)
    a2.imshow(m1, cmap="hot", interpolation="nearest", alpha=.35, zorder=2)  # 옅은 λ 배경
    pmax = max((p for *_, p in zp), default=1e-9) or 1e-9
    for (z, (r, c), note, lam, p) in zp:
        a2.scatter(c, r, s=90 + 900 * (p / pmax), marker="*",
                   c="#f59e0b", edgecolors="#1e293b", linewidths=.8, zorder=6)
        a2.text(c + 0.7, r, f"{p*100:.4f}%", fontsize=8, va="center",
                color="#111827", fontweight="bold", zorder=7)
    top = "  ·  ".join(f"{z} {p*100:.4f}%" for (z, _, _, _, p) in zp[:3])
    a2.set_title(f"② 구역별 하루 사고확률 (1-exp(-Σλ))\n상위: {top}", fontweight="bold")

    for ax in (a1, a2):
        ax.set_xlabel("열 (m)"); ax.set_ylabel("행 (m)")
    fig.tight_layout()
    return fig


# ══════════════════════════════════════════════
# 관전 상태
# ══════════════════════════════════════════════
class Sim:
    def __init__(self):
        self.base_grid = M.build_grid()
        self.scenario = "base"
        self.paused = True
        self.speed = C.PLAYBACK_DEFAULT
        # 히트맵 백그라운드 작업 상태 (별도 프로세스 + Queue)
        self.mc_running = False
        self.mc_progress = (0, 0)
        self.mc_result = None
        self.mc_queue = None
        self.mc_process = None
        self.reset()

    def reset(self):
        self.grid, self.effects = ptd_ttl.apply(self.base_grid, self.scenario)
        self.fall_edges = M.fall_edge_cells(self.grid)
        self.rng = random.Random(random.randint(0, 10**6))
        self.workers = M.make_workers(self.grid, self.rng)
        self.frame = 0; self.accidents = []; self.done = False

    def switch(self, scenario):
        self.scenario = scenario; self.reset()

    def step(self):
        if self.done or not M.within_work_hours(self.frame):
            self.done = True; return
        M.step_world(self.workers, self.grid, self.effects, self.rng,
                     self.frame, self.fall_edges,
                     record_accident=lambda r, c, t: self.accidents.append((r, c, t)))
        self.frame += 1


# ══════════════════════════════════════════════
# 화면
# ══════════════════════════════════════════════
def launch_gui():
    sim = Sim()
    fig = plt.figure(figsize=(15, 9))
    try:
        fig.canvas.manager.set_window_title("건설현장 작업자 시뮬레이션")
    except Exception:
        pass
    fig.subplots_adjust(left=0.04, right=0.66, top=0.93, bottom=0.06)
    ax = fig.add_axes([0.045, 0.06, 0.60, 0.87])
    ROWS, COLS = sim.base_grid.shape

    cell_cmap = ListedColormap(["#ffffff00", C.CELL_COLOR[C.WALL], C.CELL_COLOR[C.FLOOR_OPENING],
                                "#ffffff00", C.CELL_COLOR[C.MATERIAL], C.CELL_COLOR[C.NARROW]])
    bg_im = ax.imshow(np.ma.masked_where(sim.grid == C.WALKABLE, sim.grid),
                      cmap=cell_cmap, vmin=0, vmax=5, interpolation="nearest", zorder=1)
    poi_sc = ax.scatter([C.WORK_ZONES[z]["cell"][1] for z in C.WORK_ZONES],
                        [C.WORK_ZONES[z]["cell"][0] for z in C.WORK_ZONES],
                        s=110, marker="*", c="#f59e0b", edgecolors="#1e293b",
                        linewidths=.7, zorder=3)
    worker_sc = ax.scatter([], [], s=80, zorder=5)
    # 사고로 빠진 작업자: 완전히 지우지 않고 마지막 위치에 흐린 회색 점으로 잔류
    ghost_sc = ax.scatter([], [], s=55, marker="o", c="#9ca3af", alpha=0.45,
                          edgecolors="#6b7280", linewidths=0.6, zorder=4)
    acc_sc = ax.scatter([], [], s=150, marker="X", c="#dc2626",
                        edgecolors="black", linewidths=1.0, zorder=6)
    ax.set_xlim(-0.5, COLS - 0.5); ax.set_ylim(ROWS - 0.5, -0.5)
    ax.set_xlabel("열 (m)"); ax.set_ylabel("행 (m)")
    title = ax.set_title("", fontsize=13, fontweight="bold")

    def rebuild_background():
        bg_im.set_data(np.ma.masked_where(sim.grid == C.WALKABLE, sim.grid))

    _txt_cache = {"title": None, "stats": None}

    def render():
        # 활동 중 작업자: 위치/색만 갱신(set_offsets). 부상자는 회색 점으로 잔류.
        xs, ys, fcs, ecs = [], [], [], []
        gx, gy = [], []
        for w in sim.workers:
            if w.injured:
                gx.append(w.pos[1]); gy.append(w.pos[0])
                continue
            xs.append(w.pos[1]); ys.append(w.pos[0])
            fcs.append(STATE_COLOR.get(w.state, "#16a34a"))
            ecs.append("#facc15" if w.is_foreman else "#0f172a")
        if xs:
            worker_sc.set_offsets(np.c_[xs, ys]); worker_sc.set_facecolors(fcs)
            worker_sc.set_edgecolors(ecs); worker_sc.set_linewidths(1.4)
        else:
            worker_sc.set_offsets(np.empty((0, 2)))
        ghost_sc.set_offsets(np.c_[gx, gy] if gx else np.empty((0, 2)))
        if sim.accidents:
            ar = [a[1] for a in sim.accidents]; ac = [a[0] for a in sim.accidents]
            acol = ["#7f1d1d" if a[2] == "fatal" else "#dc2626" for a in sim.accidents]
            acc_sc.set_offsets(np.c_[ar, ac]); acc_sc.set_facecolors(acol)
        # 제목/통계는 내용이 바뀔 때만 set_text(문자열 조립·stale 최소화)
        tstr = (f"건설현장 작업자 시뮬레이션   |   {M.sim_clock(sim.frame)} "
                f"(10:00~18:00)  ×{sim.speed}배속   [{ptd_ttl.scenario_label(sim.scenario)}]")
        if tstr != _txt_cache["title"]:
            title.set_text(tstr); _txt_cache["title"] = tstr
        update_stats()

    # ── 우측 패널 ──
    fig.text(0.83, 0.955, "HoC 대안 선택", ha="center", fontsize=12, fontweight="bold",
             color="#1e293b")
    bx, bw, bh, gap, y0 = 0.69, 0.28, 0.050, 0.010, 0.90
    btns = []
    for i, (key, info) in enumerate(C.HOC_SCENARIOS.items()):
        bax = fig.add_axes([bx, y0 - i * (bh + gap), bw, bh])
        b = Button(bax, info["label"], color=BTN_FACE, hovercolor="#eef2ff")
        b.label.set_fontsize(9); b.label.set_color(BTN_EDGE); b.label.set_fontweight("bold")
        for sp in bax.spines.values():
            sp.set_visible(False)
        bax.add_patch(mpatches.FancyBboxPatch((0.015, 0.10), 0.97, 0.80,
                      transform=bax.transAxes, boxstyle="round,pad=0,rounding_size=0.2",
                      mutation_aspect=0.35, facecolor="none", edgecolor=BTN_EDGE,
                      linewidth=1.6, zorder=3))
        b.on_clicked(lambda e, k=key: (sim.switch(k), rebuild_background(), render(),
                                       fig.canvas.draw_idle()))
        btns.append(b)

    yc = y0 - len(C.HOC_SCENARIOS) * (bh + gap) - 0.015
    a_run = fig.add_axes([bx, yc, bw*0.32, bh]); b_run = Button(a_run, "▶ RUN", color="#166534")
    a_pause = fig.add_axes([bx + bw*0.34, yc, bw*0.32, bh]); b_pause = Button(a_pause, "⏸ PAUSE", color="#7c3aed")
    a_reset = fig.add_axes([bx + bw*0.68, yc, bw*0.32, bh]); b_reset = Button(a_reset, "↻ RESET", color="#64748b")
    for b in (b_run, b_pause, b_reset):
        b.label.set_color("white"); b.label.set_fontsize(9); b.label.set_fontweight("bold")
    b_run.on_clicked(lambda e: setattr(sim, "paused", False))
    b_pause.on_clicked(lambda e: setattr(sim, "paused", True))
    b_reset.on_clicked(lambda e: (sim.reset(), rebuild_background(), render(), fig.canvas.draw_idle()))

    a_sp = fig.add_axes([bx, yc - 0.05, bw, 0.022])
    s_speed = Slider(a_sp, "배속", 1, C.PLAYBACK_MAX, valinit=sim.speed, valstep=1, color="#3b82f6")
    s_speed.on_changed(lambda v: setattr(sim, "speed", int(v)))

    # 반복 횟수 입력 + 히트맵 버튼
    fig.text(bx, yc - 0.085, "반복 횟수 (히트맵)", fontsize=10, color="#1e293b", fontweight="bold")
    a_tb = fig.add_axes([bx, yc - 0.135, bw*0.42, bh])
    tb_runs = TextBox(a_tb, "", initial=str(C.MC_RUNS_DEFAULT))
    a_hm = fig.add_axes([bx + bw*0.46, yc - 0.135, bw*0.54, bh])
    b_hm = Button(a_hm, "히트맵 생성", color="#0f766e")
    b_hm.label.set_color("white"); b_hm.label.set_fontsize(9); b_hm.label.set_fontweight("bold")

    def on_heatmap(_):
        if sim.mc_running:
            print("[히트맵] 이미 계산 중입니다.")
            return
        try:
            n = max(1, int(tb_runs.text))
        except ValueError:
            n = C.MC_RUNS_DEFAULT
        if n > C.GUI_MC_RUNS_CAP:
            print(f"[히트맵] 화면에서는 최대 {C.GUI_MC_RUNS_CAP}회로 제한합니다. "
                  f"대량 반복은 명령행: python viewer.py --mc --scenario {sim.scenario} --runs {n}")
            n = C.GUI_MC_RUNS_CAP
        sim.paused = True                 # 계산 동안 관전 일시정지
        sim.mc_running = True
        sim.mc_progress = (0, n)
        sim.mc_result = None
        scn = sim.scenario

        # 별도 프로세스로 계산 → GIL 무관, GUI 완전 무정지. 통신은 Queue만.
        sim.mc_queue = mp.Queue()
        sim.mc_process = mp.Process(target=_mc_worker, args=(scn, n, sim.mc_queue),
                                    daemon=True)
        sim.mc_process.start()
        print(f"[히트맵] {scn} {n}회 별도 프로세스 계산 시작 (창은 멈추지 않습니다)")
    b_hm.on_clicked(on_heatmap)

    # 통계 텍스트를 '전용 투명 축'의 아티스트로 배치 → blit가 이 영역만 다시 그림
    sax = fig.add_axes([bx, 0.045, bw, yc - 0.235]); sax.set_axis_off()
    stats = sax.text(0.0, 1.0, "", transform=sax.transAxes,
                     fontsize=10, va="top", ha="left", color="#1e293b")

    def update_stats():
        moving = sum(1 for w in sim.workers if not w.injured and w.state == "travel")
        working = sum(1 for w in sim.workers if not w.injured and w.state == "work")
        waiting = sum(1 for w in sim.workers if not w.injured and w.state == "wait")
        injured = sum(1 for w in sim.workers if w.injured and w.accident_type != "fatal")
        fatal = sum(1 for w in sim.workers if w.accident_type == "fatal")
        pct = min(100, 100 * sim.frame // C.WORKDAY_STEPS)
        mc_line = ""
        if sim.mc_running:
            k, tot = sim.mc_progress
            mc_line = f"\n[히트맵 계산 중] {k}/{tot} 런..."
        sstr = (
            f"[{'⏸ 일시정지' if sim.paused else '▶ 실행 중'}]  {M.sim_clock(sim.frame)}  ({pct}%)\n"
            f"대기 {waiting} · 이동 {moving} · 작업 {working}\n"
            f"부상 {injured} · 사망 {fatal} · 누적사고 {len(sim.accidents)}\n"
            f"작업자 {C.N_WORKERS}명(foreman {C.N_FOREMEN}) · 작업 {C.DWELL_MINUTES}분\n"
            f"1셀=1m · 보행 1.0 m/s · TTL={'O' if ptd_ttl.TTL_OK else 'X'}"
            f"{mc_line}"
        )
        if sstr != _txt_cache["stats"]:
            stats.set_text(sstr); _txt_cache["stats"] = sstr

    # 범례
    leg = [mpatches.Patch(color=C.CELL_COLOR[C.WALL], label="벽"),
           mpatches.Patch(color=C.CELL_COLOR[C.FLOOR_OPENING], label="개구부"),
           mpatches.Patch(color=C.CELL_COLOR[C.MATERIAL], label="적재물"),
           mpatches.Patch(color=C.CELL_COLOR[C.NARROW], label="협소공간"),
           mpatches.Patch(color=STATE_COLOR["travel"], label="이동"),
           mpatches.Patch(color=STATE_COLOR["work"], label="작업"),
           mpatches.Patch(color="#dc2626", label="사고")]
    ax.legend(handles=leg, loc="upper center", bbox_to_anchor=(0.5, -0.06),
              ncol=7, fontsize=8, frameon=True, facecolor="white", edgecolor="#cbd5e1")

    from matplotlib.animation import FuncAnimation

    def poll_mc_queue():
        # 자식 프로세스가 보낸 진행률/결과를 논블로킹으로 수거(get_nowait)
        if sim.mc_queue is None:
            return
        try:
            while True:
                msg = sim.mc_queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    sim.mc_progress = (msg[1], msg[2])
                elif kind == "result":
                    sim.mc_result = msg[1]
                    sim.mc_running = False
                elif kind == "error":
                    print(f"[히트맵] 계산 오류:\n{msg[1]}")
                    sim.mc_running = False
        except _queue.Empty:
            pass
        # 계산이 끝났으면 프로세스/큐 정리(좀비 방지)
        if not sim.mc_running and sim.mc_process is not None:
            sim.mc_process.join(timeout=0.1)
            if not sim.mc_process.is_alive():
                sim.mc_process = None
                sim.mc_queue = None

    def update(_):
        poll_mc_queue()
        # 백그라운드 히트맵 완료 시 메인스레드에서 그림 생성
        if sim.mc_result is not None:
            res = sim.mc_result; sim.mc_result = None
            site_p = 1 - np.exp(-float(res["risk"].sum()))
            print(f"[히트맵] 완료: 현장 하루 사고확률 ~ {site_p*100:.4f}% "
                  f"(기대위험 기반, 표집사고 {int(res['acc'].sum())}건)")
            make_heatmap_figure(res); plt.show(block=False)
        if not sim.paused and not sim.done and not sim.mc_running:
            n = min(int(sim.speed), C.MAX_STEPS_PER_FRAME)   # 프레임당 스텝 하드 상한
            for _ in range(max(1, n)):
                if sim.done or not M.within_work_hours(sim.frame):
                    sim.done = True; break
                sim.step()
        render()
        # blit=True: 변경된 아티스트만 반환 → 정적 배경(격자·버튼·범례)은 다시 안 그림
        return [worker_sc, ghost_sc, acc_sc, title, stats]

    def init_anim():
        return [worker_sc, ghost_sc, acc_sc, title, stats]

    render()
    # blit=True 로 매 프레임 전체 캔버스 대신 움직이는 아티스트만 갱신(버벅임↓).
    # 시나리오 전환/리셋은 draw_idle()을 호출하므로 배경이 재캡처된다.
    anim = FuncAnimation(fig, update, init_func=init_anim,
                         interval=C.ANIM_INTERVAL_MS, blit=True, cache_frame_data=False)
    fig._anim = anim
    # 헤드리스 검증용 훅(실제 실행에는 영향 없음)
    fig._test_hooks = dict(update=update, render=render, sim=sim,
                           switch=lambda k: (sim.switch(k), rebuild_background(),
                                             render(), fig.canvas.draw_idle()))
    plt.show()


# ══════════════════════════════════════════════
# 배치 러너 (기본 모드): 횟수 입력 → 병렬 headless N회 → 자동 히트맵 + 로그
# ══════════════════════════════════════════════
def run_batch(scenario, runs=None, n_procs=None, show=True, save_prefix=None):
    """N회 하루를 병렬 headless 실행 → 기대위험 히트맵 자동 생성/저장 + 좌표 로그.
    runs=None이면 콘솔에서 입력받는다. 좌표 로그는 <prefix>_risk.csv/_accidents.csv."""
    if runs is None:
        try:
            runs = int((input("몇 회 시행하시겠습니까? (기본 100): ").strip() or "100"))
        except (ValueError, EOFError):
            runs = 100
    runs = max(1, runs)
    save_prefix = save_prefix or f"mc_{scenario}"
    nproc = n_procs or mp.cpu_count()
    print(f"[배치] {scenario} · {runs}회 · headless 풀데이(28,800스텝) · {nproc} 프로세스 병렬")
    t0 = time.perf_counter()
    res = run_monte_carlo_parallel(scenario, runs, n_procs=n_procs, save_csv=save_prefix)
    dt = time.perf_counter() - t0
    print(f"[배치] 완료: {runs}런 {dt:.1f}s  ({dt/runs:.3f}s/런, {nproc} procs)")
    site_p = 1 - np.exp(-float(res["risk"].sum()))
    top = zone_daily_probs(res)[0]
    print(f"현장 하루 사고확률 ~ {site_p*100:.4f}%  |  최고위험 구역 {top[0]} {top[4]*100:.4f}%")
    fig = make_heatmap_figure(res)
    out = f"hotspot_{scenario}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    print(f"저장: {out} · {save_prefix}_risk.csv · {save_prefix}_accidents.csv")
    if show:
        plt.show()
    return res


# ══════════════════════════════════════════════
def main():
    mp.freeze_support()          # Windows spawn 안전(패키징/재실행 대비)
    ap = argparse.ArgumentParser(
        description="건설현장 시뮬레이션: 기본은 N회 일괄 실행→자동 히트맵. --watch로 실시간 관전.")
    ap.add_argument("--watch", action="store_true", help="실시간 관전 GUI 모드(구 기본)")
    ap.add_argument("--mc", action="store_true", help="(별칭) 배치 모드와 동일")
    ap.add_argument("--scenario", default="base", choices=list(C.HOC_SCENARIOS))
    ap.add_argument("--runs", type=int, default=None, help="반복 횟수(미지정 시 콘솔 입력)")
    ap.add_argument("--procs", type=int, default=None, help="병렬 프로세스 수(기본 CPU 코어수)")
    ap.add_argument("--no-show", action="store_true", help="히트맵 창 표시 없이 저장만(headless)")
    args = ap.parse_args()
    if args.watch:
        launch_gui()                                    # 실시간 관전(옵션으로 보존)
    else:
        if args.no_show:
            matplotlib.use("Agg")
        run_batch(args.scenario, runs=args.runs, n_procs=args.procs, show=not args.no_show)


if __name__ == "__main__":
    main()
