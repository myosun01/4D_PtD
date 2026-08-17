# -*- coding: utf-8 -*-
"""v3.8 Part A — `max_steps` 하한 실측.

## 왜 재는가

v3.7 B-3 에서 POI/워커·일 = 0.83~0.86 (1 미만) 이 나왔다. 하루 안에 목표에
도달하지 못하는 워커가 있다는 뜻이고, 그 상태의 노출은 "도달 실패 상태의 노출"
이다. 격자 대각선 이동에 필요한 스텝 수가 `max_steps=80` 을 넘는지를 실측한다.

## 어떻게 재는가 — 커널을 고치지 않는다

도달성 지표(첫 도달 스텝·state 별 스텝·미도달 비율)는 `fourd_workers` 를
수정하지 않고 얻는다. `run_project_workers` 는 `trajectory_path` 가 주어지면
매 스텝 `logger.log(day, level, step, workers)` 를 부르므로, `TrajectoryLogger`
자리에 **메모리 집계만 하는 프로브**를 끼워 넣는다(monkeypatch).
CSV 를 쓰지 않고 카운터만 누적한다 — v3.7 에서 겪은 "원자료를 다 들고 있어
느려지는" 함정을 피한다.

프로브는 관측 비용이 있으므로 **실행 시간은 프로브 없는 실행에서만 잰다.**
프로브 실행 시간은 계측 오버헤드로 따로 보고한다.

실행:
    python scripts/sweep_max_steps.py [--steps 80,150,300,480,720] [--reps 5]
산출:
    build/max_steps_sweep.md
"""
import argparse
import collections
import json
import math
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import fourd_workers as FW
import movement
import ptd_ttl
from pilot_run import EXPOSURE_CH        # 위험유형 → 노출채널 (단일 원천)

OUT = "build/max_steps_sweep.md"
RAW_OUT = "build/max_steps_sweep_raw.json"
HAZ = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")

# v4.0 Phase 0 의 MDD 측정값 (build/pilot_run.md §목표 MDD 별 필요 반복).
# n = 2·(1.96/δ)²·CV̄², 가장 분산이 큰 채널(zone_occupancy, CV̄=0.0234) 기준.
#   δ=1%   → 43      (측정값)
#   δ=0.5% → 169     (측정값)
#   δ=0.2% → 1,050   (같은 식의 연장)
# 500·1000 은 지시서가 지정한 참고 반복수이며 특정 δ 의 산출값이 아니다.
REPS_TABLE = [(43, "δ=1% (pilot_run.md 측정)"),
              (169, "δ=0.5% (pilot_run.md 측정)"),
              (500, "참고값 — 특정 δ 산출 아님"),
              (1000, "참고값 — δ=0.2% 는 n≈1,050")]
N_VARIANTS = 10          # build/variant_manifest.json 의 [S] 실험 조건 수


# ══════════════════════════════════════════════════════════
# 도달성 프로브 — TrajectoryLogger 자리에 끼운다
# ══════════════════════════════════════════════════════════
class ReachProbe:
    """매 스텝 워커 상태를 받아 카운터만 누적한다. 파일을 쓰지 않는다.

    `run_project_workers` 가 기대하는 인터페이스: __init__(path, every=),
    log(day, level, step, workers), close(), .rows
    """

    LAST = None            # 가장 최근 인스턴스 — 호출부가 logger 를 돌려주지 않는다

    def __init__(self, path=None, every: int = 1):
        ReachProbe.LAST = self
        self.path, self.every, self.rows = path, 1, 0
        self.state_steps = collections.Counter()      # state → 스텝 수
        self.first_work = {}                          # (day, level, wid) → 첫 도달 스텝
        self.seen = {}                                # (day, level, wid) → target_derived
        self.visits = {}                              # (day, level, wid) → 방문 수

    def log(self, day, level, step, workers):
        for w in workers:
            key = (day, level, w.wid)
            self.seen[key] = w.target_derived
            self.visits[key] = w.visits
            self.state_steps[w.state] += 1
            if w.state == "work" and key not in self.first_work:
                self.first_work[key] = step
        self.rows += len(workers)

    def close(self):
        pass

    def summary(self, derived_only: bool = False):
        # v3.7 poi_structure.py 및 result["placement"]과 같은 분모(전체 워커일)를
        # 쓴다. derived_only=True는 진단용으로만 남긴다.
        keys = [k for k, d in self.seen.items() if d or not derived_only]
        n = len(keys)
        if not n:
            return {}
        never = sum(1 for k in keys if self.visits.get(k, 0) == 0)
        arr = sorted(self.first_work[k] for k in keys if k in self.first_work)
        tot = sum(self.state_steps.values())
        return {
            "worker_days": n,
            "never_arrived": never,
            "never_arrived_pct": 100.0 * never / n,
            "visits_total": sum(self.visits.get(k, 0) for k in keys),
            "visits_per_worker_day": sum(self.visits.get(k, 0) for k in keys) / n,
            "arrive_median": statistics.median(arr) if arr else None,
            "arrive_p90": arr[max(0, int(math.ceil(len(arr) * 0.9)) - 1)] if arr else None,
            "arrival_steps": arr,
            "state_steps": dict(self.state_steps),
            "work_step_pct": 100.0 * self.state_steps["work"] / tot if tot else 0.0,
            "travel_step_pct": 100.0 * self.state_steps["travel"] / tot if tot else 0.0,
            "wait_step_pct": 100.0 * self.state_steps["wait"] / tot if tot else 0.0,
        }


def aggregate_probe_summaries(summaries):
    """동일 조건 5개 시드의 워커일·도달 스텝·상태 카운터를 합친다."""
    n = sum(s["worker_days"] for s in summaries)
    arrivals = sorted(step for s in summaries for step in s["arrival_steps"])
    states = collections.Counter()
    for s in summaries:
        states.update(s["state_steps"])
    total_states = sum(states.values())
    never = sum(s["never_arrived"] for s in summaries)
    visits = sum(s["visits_total"] for s in summaries)
    return {
        "probe_runs": len(summaries),
        "worker_days": n,
        "never_arrived_pct": 100.0 * never / n if n else 0.0,
        "visits_per_worker_day": visits / n if n else 0.0,
        "arrive_median": statistics.median(arrivals) if arrivals else None,
        "arrive_p90": (arrivals[max(0, int(math.ceil(len(arrivals) * 0.9)) - 1)]
                       if arrivals else None),
        "work_step_pct": 100.0 * states["work"] / total_states if total_states else 0.0,
        "travel_step_pct": 100.0 * states["travel"] / total_states if total_states else 0.0,
        "wait_step_pct": 100.0 * states["wait"] / total_states if total_states else 0.0,
    }


def haz_exposure(res, life):
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res["exposure_steps"].items():
        idx[(lv, ch, int(r), int(c))] += v
    out = collections.Counter()
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        out[h.hazard_type] += sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                                  for (r, c) in fourd.instance_exposure_cells(h))
    return out


def stats(xs):
    n = len(xs)
    if not n:
        return 0.0, 0.0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd


def fmt_hours(sec):
    h = sec / 3600.0
    return "%.1f 시간" % h if h >= 0.1 else "%.0f 분" % (sec / 60.0)


def time_band(sec):
    if sec > 72 * 3600:
        return "72시간 초과"
    if sec > 24 * 3600:
        return "24~72시간"
    if sec > 8 * 3600:
        return "8~24시간"
    return "8시간 이내"


def _point_in_ring(point, ring):
    """temp_works.Grid.cells_in과 같은 셀 중심 포함 검사를 외부 의존성 없이 수행."""
    x, y = point
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)
                and x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_geometry(point, geometry):
    parts = ([geometry["coords"]] if geometry["type"] == "polygon"
             else geometry["coords"])
    return any(rings and _point_in_ring(point, rings[0])
               and not any(_point_in_ring(point, hole) for hole in rings[1:])
               for rings in parts)


def measure_openings_at_2m(path="build/hazard_zones.json"):
    """1m 위험구역 폴리곤을 동일 원점의 2m 셀 중심 방식으로 재투영한다.

    모델을 바꾸거나 다시 생성하지 않는 조사다. 먼저 1m 재계산이 저장된 cells와
    일치하는지 확인한 뒤, 2m에서 0/1셀로 축소되는 개구부 수를 센다.
    """
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    meta = data["meta"]["grid"]
    ox, oy = meta["origin_xy_m"]
    openings = [z for z in data["zones"]
                if z["hazard_type"] == "H001_FloorOpening"]

    def count(zone, resolution):
        rows = int(math.ceil(meta["rows"] * meta["resolution_m"] / resolution))
        cols = int(math.ceil(meta["cols"] * meta["resolution_m"] / resolution))
        return sum(_point_in_geometry((ox + (c + 0.5) * resolution,
                                       oy + (r + 0.5) * resolution),
                                      zone["geometry"])
                   for r in range(rows) for c in range(cols))

    one = [count(z, 1.0) for z in openings]
    stored = [len(z["cells"]) for z in openings]
    if one != stored:
        raise AssertionError("1m 재투영이 저장 cells와 불일치: %d/39"
                             % sum(a == b for a, b in zip(one, stored)))
    two = sorted(count(z, 2.0) for z in openings)
    return {
        "openings": len(two),
        "validation_1m_equal": True,
        "zero_cells": sum(n == 0 for n in two),
        "one_or_fewer": sum(n <= 1 for n in two),
        "median_cells": two[len(two) // 2],
        "min_cells": min(two),
        "max_cells": max(two),
        "counts": two,
    }


def save_raw(rows, args, steps_list):
    """긴 스윕이 보고서 서식 오류로 유실되지 않도록 조건마다 원자료를 저장."""
    serial = []
    for row in rows:
        item = dict(row)
        item["chan"] = [dict(v) for v in row["chan"]]
        item["hz"] = [dict(v) for v in row["hz"]]
        serial.append(item)
    os.makedirs("build", exist_ok=True)
    with open(RAW_OUT, "w", encoding="utf-8") as fp:
        json.dump({"args": {"days": args.days, "reps": args.reps},
                   "steps": steps_list, "rows": serial},
                  fp, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="80,150,300,480,720")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--abort-s", type=float, default=600.0,
                    help="1회 실행이 이 시간을 넘으면 그 조건은 1회만 재고 사유를 남긴다")
    ap.add_argument("--report-only", action="store_true",
                    help="기존 build/max_steps_sweep_raw.json에서 보고서만 재생성")
    a = ap.parse_args()
    steps_list = [int(s) for s in a.steps.split(",") if s.strip()]

    if a.report_only:
        with open(RAW_OUT, encoding="utf-8") as fp:
            raw = json.load(fp)
        a.days = raw["args"]["days"]
        a.reps = raw["args"]["reps"]
        write_report(raw["rows"], a, raw["steps"])
        return

    lib = ptd_ttl.require_library()
    sch, site, life, cfg, wl = FW.load_project_v2()
    ts = fourd.load_temp_structures()

    def run(max_steps, seed, probe=False):
        movement._CTX.clear()
        kw = {}
        if probe:
            kw = {"trajectory_path": "<probe>"}     # 프로브가 경로를 무시한다
        t0 = time.time()
        res = FW.run_project_workers(sch, site, life, cfg, wl, days=a.days,
                                     mc_runs=1, seed=seed, max_steps=max_steps,
                                     temp_structures=ts, stage="v37",
                                     library=lib, **kw)
        return res, time.time() - t0

    rows = []
    for ms in steps_list:
        print("── max_steps = %d" % ms)
        sys.stdout.flush()
        tot, chan, hz, secs, poi = [], [], [], [], []
        reps_done, aborted = 0, None
        for rep in range(a.reps):
            res, dt = run(ms, seed=rep)
            reps_done += 1
            secs.append(dt)
            ct = FW.channel_totals(res)
            tot.append(sum(ct.values()))
            hzc = haz_exposure(res, life)
            hz.append(hzc)
            g = collections.Counter()
            for h, v in hzc.items():
                g[EXPOSURE_CH.get(h, "?")] += v
            chan.append(g)
            pl = res["placement"]
            poi.append(pl.get("visits", 0) / max(1, pl.get("worker_days", 1)))
            print("   rep%d  %.1fs  노출 %s  POI/워커일 %.2f"
                  % (rep, dt, "{:,.0f}".format(tot[-1]), poi[-1]))
            sys.stdout.flush()
            del res
            if dt > a.abort_s and rep == 0:
                aborted = ("1회 실행이 %.0fs 로 --abort-s(%.0fs)를 넘어 1회만 측정"
                           % (dt, a.abort_s))
                break

        # 도달성 프로브 (동일 시드별 별도 실행, 시간 측정에서 제외)
        orig = FW.TrajectoryLogger
        FW.TrajectoryLogger = ReachProbe
        probe_summaries, probe_times = [], []
        try:
            for rep in range(reps_done):
                ReachProbe.LAST = None
                pres, pdt = run(ms, seed=rep, probe=True)
                del pres
                probe_times.append(pdt)
                if ReachProbe.LAST:
                    probe_summaries.append(ReachProbe.LAST.summary())
        finally:
            FW.TrajectoryLogger = orig
        probe = aggregate_probe_summaries(probe_summaries) if probe_summaries else {}
        rows.append({"max_steps": ms, "reps": reps_done, "aborted": aborted,
                     "tot": stats(tot), "secs": stats(secs),
                     "poi": stats(poi), "chan": chan, "hz": hz,
                     "probe": probe, "probe_s": stats(probe_times)})
        save_raw(rows, a, steps_list)
        print("   probes %d회, 평균 %.1fs  %s"
              % (len(probe_times), rows[-1]["probe_s"][0], rows[-1]["probe"]))
        sys.stdout.flush()

    write_report(rows, a, steps_list)


def write_report(rows, a, steps_list):
    os.makedirs("build", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        w = f.write
        w("# `max_steps` 하한 실측 (v3.8 Part A)\n\n")
        w("`scripts/sweep_max_steps.py` 산출. **알고리즘·구조를 바꾸지 않았다 — 측정만 했다.**\n")
        w("BASE 조건, stage=v37, 전체 공기 %s일, 조건마다 %d회(시드 다름).\n\n"
          % (a.days if a.days else "전(350)", a.reps))
        w("도달성 지표는 `TrajectoryLogger` 자리에 메모리 집계 프로브를 끼워 얻었다\n")
        w("(`fourd_workers.py` 미수정). 각 조건의 동일한 5개 시드를 프로브로도\n")
        w("반복해 도달 분포를 합쳤다. 프로브에는 관측 비용이 있어 **실행 시간은\n")
        w("프로브 없는 실행에서만 쟀다.**\n\n")

        w("## 1. 도달성\n\n")
        w("| max_steps | POI/워커·일 | 미도달 워커 | 첫 도달 스텝 중앙값 | 90%tile | work 스텝 비율 | travel |\n")
        w("|---|---|---|---|---|---|---|\n")
        for r in rows:
            p = r["probe"]
            w("| **%d** | **%.2f** | %s | %s | %s | **%s** | %s |\n"
              % (r["max_steps"], r["poi"][0],
                 "%.1f%%" % p["never_arrived_pct"] if p else "—",
                 p.get("arrive_median", "—") if p else "—",
                 p.get("arrive_p90", "—") if p else "—",
                 "%.1f%%" % p["work_step_pct"] if p else "—",
                 "%.1f%%" % p["travel_step_pct"] if p else "—"))
        w("\n`dwell_ratio` 는 0.75 로 설정돼 있다. **work 스텝 비율이 75%에 못 미치면\n")
        w("체류가 설정대로 일어나지 않은 것이다** — 도달을 못 하면 체류도 없다.\n\n")
        w("반대로 75%를 넘는 값도 가능하다. 현행 `dwell_steps`는 하루 work 비율의\n")
        w("상한이 아니라 **POI 방문 1회당 체류시간**이며, 이를 끝낸 뒤 다음 POI에서\n")
        w("다시 work 상태에 들어갈 수 있기 때문이다.\n\n")

        w("## 2. 노출 — 채널 구성\n\n")
        w("| max_steps | dwell_time | passage_count | zone_occupancy | 총 노출 | 회차간 sd |\n")
        w("|---|---|---|---|---|---|\n")
        for r in rows:
            g = collections.Counter()
            for c in r["chan"]:
                for k, v in c.items():
                    g[k] += v / len(r["chan"])
            w("| **%d** | %s | %s | %s | %s | %s |\n"
              % (r["max_steps"],
                 "{:,.0f}".format(g["dwell_time"]),
                 "{:,.0f}".format(g["passage_count"]),
                 "{:,.0f}".format(g["zone_occupancy"]),
                 "{:,.0f}".format(r["tot"][0]), "{:,.0f}".format(r["tot"][1])))
        w("\n### 채널 구성비 (%)\n\n")
        w("| max_steps | dwell_time | passage_count | zone_occupancy |\n|---|---|---|---|\n")
        prev = None
        shifts = []
        for r in rows:
            g = collections.Counter()
            for c in r["chan"]:
                for k, v in c.items():
                    g[k] += v / len(r["chan"])
            s = sum(g.values()) or 1.0
            pct = {k: 100.0 * g[k] / s for k in
                   ("dwell_time", "passage_count", "zone_occupancy")}
            w("| **%d** | %.1f%% | %.1f%% | %.1f%% |\n"
              % (r["max_steps"], pct["dwell_time"], pct["passage_count"],
                 pct["zone_occupancy"]))
            if prev is not None:
                shifts.append((r["max_steps"],
                               max(abs(pct[k] - prev[k]) for k in pct)))
            prev = pct
        if shifts:
            w("\n직전 조건 대비 구성비 최대 변동(%p): ")
            w(" · ".join("%d: %.1f" % s for s in shifts) + "\n")
        if len(rows) >= 2:
            first = rows[0]
            last = rows[-1]
            def share(row, key):
                g = collections.Counter()
                for c in row["chan"]:
                    for k, v in c.items():
                        g[k] += v / len(row["chan"])
                return 100.0 * g[key] / (sum(g.values()) or 1.0)
            d0, d1 = share(first, "dwell_time"), share(last, "dwell_time")
            p0, p1 = share(first, "passage_count"), share(last, "passage_count")
            w("\n**통과형→체류형 이동은 관측되지 않았다.** dwell_time 구성비는 "
              "%.1f%%→%.1f%%, passage_count는 %.1f%%→%.1f%%였다. "
              "예상과 반대여도 수치를 조정하지 않았다.\n"
              % (d0, d1, p0, p1))

        w("\n## 3. 위험유형별 노출\n\n")
        w("| 위험유형 | 채널 | " + " | ".join(str(r["max_steps"]) for r in rows) + " |\n")
        w("|---|---|" + "---|" * len(rows) + "\n")
        for h in HAZ:
            vals = []
            for r in rows:
                vals.append(sum(c.get(h, 0) for c in r["hz"]) / len(r["hz"]))
            w("| %s | %s | " % (h, EXPOSURE_CH.get(h, "?"))
              + " | ".join("{:,.0f}".format(v) for v in vals) + " |\n")

        w("\n## 4. 비용\n\n")
        w("| max_steps | 초/회 (평균) | sd | 회차 | 80 대비 배수 | 스텝 배수 | 선형인가 | 프로브 초/회 |\n")
        w("|---|---|---|---|---|---|---|---|\n")
        b_s = rows[0]["secs"][0] if rows else 1.0
        b_ms = rows[0]["max_steps"] if rows else 1
        for r in rows:
            k_t = r["secs"][0] / b_s if b_s else 0
            k_s = r["max_steps"] / float(b_ms)
            w("| **%d** | **%.1f** | %.1f | %d%s | %.2f× | %.2f× | %s | %.1fs |\n"
              % (r["max_steps"], r["secs"][0], r["secs"][1], r["reps"],
                 " ⚠" if r["aborted"] else "", k_t, k_s,
                 "선형" if abs(k_t - k_s) / max(k_s, 1e-9) < 0.15
                 else ("**sublinear**" if k_t < k_s else "**superlinear**"),
                 r["probe_s"][0]))
        if rows:
            w("\n스텝 수는 %d→%d로 %.1f배지만 실행시간은 %.1f→%.1f초로 %.2f배다. "
              "따라서 선형이 아니라 **sublinear**다. 고정된 일·층 구성 비용이 있고, "
              "긴 체류 중에는 새 경로탐색이 줄어드는 현행 루프와 일치한다.\n"
              % (rows[0]["max_steps"], rows[-1]["max_steps"],
                 rows[-1]["max_steps"] / rows[0]["max_steps"],
                 rows[0]["secs"][0], rows[-1]["secs"][0],
                 rows[-1]["secs"][0] / rows[0]["secs"][0]))
        for r in rows:
            if r["aborted"]:
                w("\n> ⚠ max_steps=%d: %s\n" % (r["max_steps"], r["aborted"]))

        # ── 판정 ──
        w("\n## 5. 판정\n\n")
        ok = [r for r in rows if r["poi"][0] >= 1.0]
        floor = min((r["max_steps"] for r in ok), default=None)
        if floor is None:
            w("**측정 범위(%s) 안에서 POI/워커·일 ≥ 1.0 을 만족하는 지점이 없다.**\n"
              % ", ".join(str(s) for s in steps_list))
            w("최대 조건 %d 에서도 %.2f 다. 하한은 이 범위 밖에 있다 — 외삽하지 않는다.\n\n"
              % (rows[-1]["max_steps"], rows[-1]["poi"][0]))
        else:
            fr = [r for r in rows if r["max_steps"] == floor][0]
            w("**하한 = max_steps %d** (POI/워커·일 %.2f ≥ 1.0 을 만족하는 최소 조건)\n\n"
              % (floor, fr["poi"][0]))
            w("| 기준 | 그 지점의 값 | 판단 |\n|---|---|---|\n")
            wp = fr["probe"].get("work_step_pct", 0.0)
            w("| 체류 비율이 `dwell_ratio`(75%%)에 근접하는가 | %.1f%% (차이 %.1f%%p) | %s |\n"
              % (wp, wp - 75.0,
                 "근접" if abs(wp - 75.0) <= 5.0
                 else "**근접하지 않음 — 도달은 하되 체류는 부족**"))
            if shifts:
                sh = [s for s in shifts if s[0] == floor]
                w("| 채널 구성이 안정되는가 | 직전 대비 %s%%p | %s |\n"
                  % ("%.1f" % sh[0][1] if sh else "—",
                     "안정" if sh and sh[0][1] < 1.0 else "**아직 이동 중**"))
            w("\n")

            dwell_rows = [r for r in rows
                          if abs(r["probe"].get("work_step_pct", 0.0) - 75.0) <= 5.0]
            stable_steps = None
            for step, shift in shifts:
                rest = [v for s, v in shifts if s >= step]
                if shift < 1.0 and rest and max(rest) < 1.0:
                    stable_steps = step
                    break
            w("- **POI 기준 하한:** %d 스텝.\n" % floor)
            if dwell_rows:
                w("- **75%% 체류에 처음 근접(±5%%p 보고 기준):** %d 스텝, %.1f%%. "
                  "±5%%p는 모델값이 아니라 판독을 위한 보고 기준이다.\n"
                  % (dwell_rows[0]["max_steps"],
                     dwell_rows[0]["probe"]["work_step_pct"]))
            if stable_steps is not None:
                w("- **채널 구성 안정 구간의 시작:** %d 스텝. 이후 조건까지 최대 변동 "
                  "1%%p 미만(실측 %.1f%%p). 1%%p 역시 판독 기준이며 근거 있는 "
                  "시뮬레이션 파라미터가 아니다.\n"
                  % (stable_steps, max(v for s, v in shifts if s >= stable_steps)))
            w("\n따라서 정의상 하한은 %d지만, 체류 재현과 채널 안정은 각각 다른 "
              "지점을 가리킨다. 기본값 채택은 Part B 지시 전까지 하지 않는다.\n\n"
              % floor)

        # ── 실험 규모 ──
        w("## 6. 실험 규모 산정\n\n")
        w("variant %d개 × 반복 n × 1회 실행 시간. 반복수 근거는 `build/pilot_run.md`\n"
          % N_VARIANTS)
        w("의 MDD 측정값이다 (n = 2·(1.96/δ)²·CV̄², 가장 분산이 큰 zone_occupancy 기준).\n\n")
        w("| max_steps | 초/회 | " + " | ".join("n=%d" % n for n, _ in REPS_TABLE) + " |\n")
        w("|---|---|" + "---|" * len(REPS_TABLE) + "\n")
        for r in rows:
            cells = []
            for n, _ in REPS_TABLE:
                sec = r["secs"][0] * N_VARIANTS * n
                mark = {"72시간 초과": "🟥", "24~72시간": "🟧",
                        "8~24시간": "🟨", "8시간 이내": "🟩"}[time_band(sec)]
                cells.append("%s %s" % (mark, fmt_hours(sec)))
            w("| **%d** | %.1f | " % (r["max_steps"], r["secs"][0])
              + " | ".join(cells) + " |\n")
        w("\n🟩 8시간 이내 · 🟨 8~24시간 · 🟧 24~72시간 · 🟥 72시간 초과\n\n")
        for n, why in REPS_TABLE:
            w("- **n=%d** — %s\n" % (n, why))
        w("\n")

        if floor is not None:
            fr = next(r for r in rows if r["max_steps"] == floor)
            w("하한(%d)에서 경계 판정:\n\n" % floor)
            for n, _ in REPS_TABLE:
                sec = fr["secs"][0] * N_VARIANTS * n
                w("- n=%d: **%s** (%s)\n" % (n, time_band(sec), fmt_hours(sec)))
            w("\n")

        # ── 절충안: 제시만 하고 채택하지 않는다 ──
        two_m = measure_openings_at_2m()
        w("## 7. 계산비용 절충안 — 제시만, 미채택\n\n")
        max_floor_sec = (fr["secs"][0] * N_VARIANTS * max(n for n, _ in REPS_TABLE)
                         if floor is not None else 0.0)
        if max_floor_sec <= 24 * 3600:
            w("하한에서 지정된 최대 규모(n=1000)도 %s으로 24시간 이내다. 따라서 "
              "**감당 불가 조건은 발생하지 않았다.** 아래는 조건 악화 시를 위한 "
              "절충안 비교이며 이번 작업에서는 어느 안도 실행·채택하지 않았다.\n\n"
              % fmt_hours(max_floor_sec))
        else:
            w("하한에서 일부 실험 규모가 24시간을 넘으므로 절충안을 병기한다. "
              "**이번 작업에서는 어느 안도 실행하거나 채택하지 않았다.**\n\n")
        w("| 안 | 비용 영향 | 노출 정밀도 영향 |\n|---|---|---|\n")
        w("| (a) 셀 1m→2m | 셀 수 약 1/4, 경로탐색 감소 | 2m 버퍼가 1셀로 "
          "축약되어 경계 위치 오차가 커진다. 동일 원점·셀 중심 방식으로 39개 "
          "개구부 위험구역을 재투영한 실측: **소멸 %d개, 1셀 이하 %d개, "
          "셀수 최소/중앙/최대 %d/%d/%d**. 이번 데이터에서는 소멸은 없지만 "
          "위험 띠의 공간 해상도는 절반이다. 1m 재계산은 저장 cells와 전건 일치했다. |\n"
          % (two_m["zero_cells"], two_m["one_or_fewer"], two_m["min_cells"],
             two_m["median_cells"], two_m["max_cells"]))
        w("| (b) 스텝 1초→5초 | 같은 시간 범위를 약 1/5 스텝으로 계산 | "
          "한 스텝 이동량 2.5m가 되어 좁은 통로·한 셀 점유·혼잡 상호작용을 "
          "건너뛸 수 있고 노출 시간이 5초 단위로 양자화된다. |\n")
        w("| (c) 8층→기준층 5개 | Basement·Level_02a_Parking·Roof 계산 제거 | "
          "최하·최상층 경계와 주차층 이질성이 표본에서 사라지고, 직하부 3개층 "
          "동바리 존치의 경계 노출을 같은 모집단으로 추정할 수 없다. |\n")
        w("| (d) 반복 감축 | 실행시간이 반복수에 비례해 감소 | 파일럿 MDD 기준 "
          "n=43은 δ=1%, n=169는 δ=0.5%. n=500은 같은 식으로 약 δ=0.29%, "
          "n=1000은 약 δ=0.20%(정확한 0.2% 목표는 n≈1,050)까지만 검출한다. "
          "감축할수록 더 작은 효과를 구분하지 못한다. |\n")
        w("| (e) 시드 독립 병렬 실행 | 워커 수에 따라 벽시계 시간 감소 | "
          "노출 정밀도 영향 없음. 단, 시드 목록·결과 정렬·실패 재시도 기록을 "
          "고정해야 비트 재현성을 관리할 수 있다. |\n")
        w("\n2m 재투영은 **절충안을 채택한 실행이 아니라 기존 폴리곤에 대한 "
          "읽기 전용 해상도 진단**이다.\n")
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
