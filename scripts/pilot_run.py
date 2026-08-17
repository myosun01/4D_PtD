# -*- coding: utf-8 -*-
"""v4.0 Phase 0-2/0-3 — 사전 실험: 분산 측정과 본실험 규모 산정.

BASE 와 variant 1개(무너짐 사다리 제거급)를 **20회씩** 돌려 측정한다.
  · 채널별 노출량의 평균·표준편차·변동계수
  · 반복 n 에 따른 95% 신뢰구간 반폭 수렴 곡선
  · 반폭이 평균의 5% 이하가 되는 데 필요한 반복 횟수 추정
  · 확률적 요소가 실제로 작동하는지 (분산이 0이면 결정론)

실행: python scripts/pilot_run.py [--n 20] [--max-steps 80]
산출: build/pilot_run.md
"""
import argparse
import collections
import concurrent.futures
import io
import json
import math
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import ptd_ttl
import fourd
import fourd_workers as FW
import movement
from controls import ControlApplication, resolve_all
from lifecycle import LifecycleEngine
from schedule import Schedule
from site_model import SiteModel

MANIFEST = "build/variant_manifest.json"
OUT = "build/pilot_run.md"
CHANNELS = ("fall", "edge", "material", "narrow", "collapse_zone", "drop_zone")
# 지시서 §1-2 의 3채널 (hazard_zones.json 의 exposure_channel 어휘)
EXPOSURE_CH = {"H001": "dwell_time", "H007": "dwell_time",
               "H002": "passage_count", "H004": "passage_count",
               "H009": "passage_count", "H011": "passage_count",
               "H008": "zone_occupancy"}


def load_variant(v):
    """variant 하나를 실행 가능한 상태로 적재. 반환 (sch, site, life, cfg, wl, effects)."""
    lib = ptd_ttl.require_library()
    d = v["dir"]
    sch = Schedule.load(os.path.join(d, "schedule.json"))
    site = SiteModel.load("project/site.json")
    life = LifecycleEngine(lib.lifecycle_templates,
                           os.path.join(d, "lifecycle_bindings_v2.json"), sch)
    with open("project/crews.json", encoding="utf-8") as fp:
        cfg = {t["trade"]: t.get("rho", {})
               for t in json.load(fp).get("trades", [])}
    gf = json.load(open("project/site.json", encoding="utf-8"))["gridFrame"]
    wl = FW.WorkLocations(gf, zones_path=os.path.join(d, "hazard_zones.json"))
    effects = {}
    if v.get("mechanism") == "controls_effect":
        targets = [h for h in life.instances
                   if h.hazard_type == v["target_hazard_type"]]
        effects = resolve_all(lib, [ControlApplication(v["alternative_id"],
                                                       h.instance_id)
                                    for h in targets], sch, life)
    return sch, site, life, cfg, wl, effects


def run_once(v, seed, max_steps):
    sch, site, life, cfg, wl, effects = load_variant(v)
    movement._CTX.clear()
    res = FW.run_project_workers(sch, site, life, cfg, wl, mc_runs=1, seed=seed,
                                 max_steps=max_steps,
                                 temp_structures=fourd.load_temp_structures(),
                                 controls_effects=effects)
    # 위험유형별 → 노출채널별 집계
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), val in res["exposure_steps"].items():
        idx[(lv, ch, int(r), int(c))] += val
    haz = collections.Counter()
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        haz[h.hazard_type] += sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                                  for (r, c) in fourd.instance_exposure_cells(h))
    exch = collections.Counter()
    for hz, val in haz.items():
        exch[EXPOSURE_CH.get(hz, "?")] += val
    return {"haz": dict(haz), "exposure_channel": dict(exch),
            "channel": FW.channel_totals(res),
            "total": sum(res["exposure_steps"].values()),
            "fallback": sum(res["exposure_steps_fallback"].values())}


def _run_job(job):
    """ProcessPool용 최상위 함수(Windows spawn 호환)."""
    v, seed, max_steps = job
    return run_once(v, seed, max_steps)


def stats(xs):
    n = len(xs)
    m = sum(xs) / n if n else 0.0
    if n < 2:
        return m, 0.0, 0.0, 0.0
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(var)
    half = 1.96 * sd / math.sqrt(n)          # 95% CI 반폭 (정규 근사)
    cv = sd / m if m else 0.0
    return m, sd, half, cv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--jobs", type=int, default=1,
                    help="독립 반복 병렬 프로세스 수(기본 1)")
    ap.add_argument("--target", default="5.0", help="수렴 기준 — 반폭/평균 %%")
    ap.add_argument("--from-raw", action="store_true",
                    help="build/pilot_raw.json 으로 리포트만 다시 만든다(재실행 없음)")
    a = ap.parse_args()
    target = float(a.target) / 100.0

    man = json.load(open(MANIFEST, encoding="utf-8"))
    vs = {v["variant_id"]: v for v in man["variants"]}

    if a.from_raw:
        raw = json.load(open("build/pilot_raw.json", encoding="utf-8"))
        runs = raw["runs"]
        times = raw["seconds_per_run"]
        pilot_ids = list(runs)
        a.n = raw["n"]
        a.max_steps = raw["max_steps"]
        print("원자료에서 재생성: %s (각 %d회)" % (pilot_ids, a.n))
    else:
        pilot_ids = ["BASE"]
        # 무너짐 사다리 제거급 — [S] 중 accident_type=무너짐 & hoc=제거
        elim = [v for v in man["variants"]
                if v.get("accident_type") == "무너짐" and v.get("hoc_level") == "제거"]
        if not elim:                              # 없으면 대체급으로 대체
            elim = [v for v in man["variants"]
                    if v.get("accident_type") == "무너짐" and v.get("hoc_level") == "대체"]
        pilot_ids.append(elim[0]["variant_id"])
        print("사전 실험 대상:", pilot_ids)

        runs = {}
        times = {}
        for vid in pilot_ids:
            v = vs[vid]
            t0 = time.time()
            # BASE와 대안은 같은 반복 번호에서 같은 시드를 써 CRN 대응비교가 된다.
            jobs = [(v, "pilot|replicate|%d" % i, a.max_steps)
                    for i in range(a.n)]
            if a.jobs > 1:
                with concurrent.futures.ProcessPoolExecutor(
                        max_workers=a.jobs) as pool:
                    rs = list(pool.map(_run_job, jobs))
            else:
                rs = [_run_job(job) for job in jobs]
            for i, row in enumerate(rs):
                print("  %-14s %2d/%d  총=%s" % (vid, i + 1, a.n,
                                                 "{:,.0f}".format(row["total"])))
            times[vid] = (time.time() - t0) / a.n
            runs[vid] = rs
        # 재실행 없이 분석을 다시 할 수 있도록 원자료를 남긴다
        with io.open("build/pilot_raw.json", "w", encoding="utf-8") as fp:
            json.dump({"n": a.n, "max_steps": a.max_steps, "seconds_per_run": times,
                       "runs": runs}, fp, ensure_ascii=False)

    w = io.StringIO()
    w.write("# 사전 실험 (v4.0 Phase 0-2 / 0-3)\n\n")
    w.write("대상 `%s`, 각 **%d회**, 하루 %d 스텝, 매 회 다른 시드.\n\n"
            % (" / ".join(pilot_ids), a.n, a.max_steps))

    # ── 결정론 여부 ──
    w.write("## 확률적 요소가 작동하는가\n\n")
    w.write("| variant | 총 노출 최소 | 최대 | 서로 다른 값의 수 | 판정 |\n|---|---|---|---|---|\n")
    deterministic = []
    for vid in pilot_ids:
        tot = [r["total"] for r in runs[vid]]
        uniq = len(set(round(x, 6) for x in tot))
        det = uniq == 1
        if det:
            deterministic.append(vid)
        w.write("| `%s` | %s | %s | %d / %d | %s |\n"
                % (vid, "{:,.0f}".format(min(tot)), "{:,.0f}".format(max(tot)),
                   uniq, len(tot), "**결정론 — 시드가 안 먹는다**" if det else "확률적"))
    w.write("\n")
    if deterministic:
        w.write("> **경고: %s 가 결정론적이다.** 시드 주입이 실제로 반영되는지 "
                "확인해야 한다. 반복 실행이 무의미해진다.\n\n"
                % ", ".join(deterministic))
    else:
        w.write("두 조건 모두 반복마다 값이 달라진다 — 시드 주입이 작동한다.\n\n")

    # ── 채널별 통계 ──
    for vid in pilot_ids:
        w.write("## `%s` — 채널별 통계 (%d회)\n\n" % (vid, a.n))
        w.write("| 노출채널 | 평균 | 표준편차 | 변동계수 | 95%%CI 반폭 | 반폭/평균 |\n")
        w.write("|---|---|---|---|---|---|\n")
        keys = sorted({k for r in runs[vid] for k in r["exposure_channel"]})
        for k in keys:
            xs = [r["exposure_channel"].get(k, 0.0) for r in runs[vid]]
            m, sd, half, cv = stats(xs)
            w.write("| %s | %s | %s | %.4f | %s | **%.2f%%** |\n"
                    % (k, "{:,.0f}".format(m), "{:,.1f}".format(sd), cv,
                       "{:,.1f}".format(half), 100.0 * half / m if m else 0.0))
        xs = [r["total"] for r in runs[vid]]
        m, sd, half, cv = stats(xs)
        w.write("| **총계** | %s | %s | %.4f | %s | **%.2f%%** |\n\n"
                % ("{:,.0f}".format(m), "{:,.1f}".format(sd), cv,
                   "{:,.1f}".format(half), 100.0 * half / m if m else 0.0))

    # ── 수렴 곡선 ──
    w.write("## 반복 n 에 따른 95%% 신뢰구간 반폭 (총 노출)\n\n")
    w.write("| n | " + " | ".join("`%s` 반폭/평균" % v for v in pilot_ids) + " |\n")
    w.write("|---|" + "---|" * len(pilot_ids) + "\n")
    for n in range(2, a.n + 1):
        cells = []
        for vid in pilot_ids:
            xs = [r["total"] for r in runs[vid][:n]]
            m, sd, half, cv = stats(xs)
            cells.append("%.2f%%" % (100.0 * half / m) if m else "—")
        w.write("| %d | %s |\n" % (n, " | ".join(cells)))
    w.write("\n")

    # ── 검출 가능한 최소 차이 (MDD) — 이것이 진짜 제약이다 ──
    w.write("## 검출 가능한 최소 차이 (MDD) — 반복 횟수를 정하는 진짜 기준\n\n")
    w.write("수렴 기준(반폭 ≤ 평균의 5%)은 **variant 하나의 추정 정밀도**만 본다. "
            "그러나 실험이 실제로 답해야 하는 것은 **BASE 와 variant 의 차이가 "
            "유의한가**다. 두 표본 차의 95% 신뢰구간 반폭이 MDD 이며, "
            "MDD = 1.96·√(sd₁²/n + sd₂²/n) 다.\n\n")
    a_id, b_id = pilot_ids[0], pilot_ids[1]
    w.write("| 노출채널 | `%s` 평균 | `%s` 평균 | 실측 차이 | MDD(n=%d) | 유의? |\n"
            % (a_id, b_id, a.n))
    w.write("|---|---|---|---|---|---|\n")
    mdd_rows = []
    keys = sorted({k for vid in pilot_ids for r in runs[vid]
                   for k in r["exposure_channel"]})
    for k in keys + ["__total__"]:
        def series(vid):
            if k == "__total__":
                return [r["total"] for r in runs[vid]]
            return [r["exposure_channel"].get(k, 0.0) for r in runs[vid]]
        m1, sd1, _, cv1 = stats(series(a_id))
        m2, sd2, _, cv2 = stats(series(b_id))
        diff = m2 - m1
        mdd = 1.96 * math.sqrt(sd1 ** 2 / a.n + sd2 ** 2 / a.n)
        sig = abs(diff) > mdd
        mdd_rows.append((k, m1, m2, diff, mdd, sig, cv1, cv2))
        w.write("| %s | %s | %s | %s (%+.2f%%) | ±%s | %s |\n"
                % ("**총계**" if k == "__total__" else k,
                   "{:,.0f}".format(m1), "{:,.0f}".format(m2),
                   "{:+,.0f}".format(diff),
                   100.0 * diff / m1 if m1 else 0.0, "{:,.0f}".format(mdd),
                   "**예**" if sig else "아니오"))
    w.write("\n")
    nsig = sum(1 for r in mdd_rows if r[5])
    w.write("n=%d 에서 유의한 채널 **%d / %d**.\n\n" % (a.n, nsig, len(mdd_rows)))

    # 목표 MDD 별 필요 n
    w.write("### 목표 MDD 별 필요 반복\n\n")
    w.write("차이를 평균의 δ% 까지 검출하려면 "
            "**n ≥ 2·(1.96/δ)²·CV̄²** (두 조건의 CV 를 평균값 CV̄ 로 볼 때).\n\n")
    w.write("| 노출채널 | CV̄ | δ=5%% | δ=2%% | δ=1%% | δ=0.5%% |\n|---|---|---|---|---|---|\n")
    need_by_delta = collections.defaultdict(int)
    for k, m1, m2, diff, mdd, sig, cv1, cv2 in mdd_rows:
        cvb = (cv1 + cv2) / 2.0
        cells = []
        for d_ in (0.05, 0.02, 0.01, 0.005):
            n_ = max(1, math.ceil(2 * (1.96 / d_) ** 2 * cvb ** 2))
            need_by_delta[d_] = max(need_by_delta[d_], n_)
            cells.append(str(n_))
        w.write("| %s | %.4f | %s |\n"
                % ("**총계**" if k == "__total__" else k, cvb, " | ".join(cells)))
    w.write("\n| δ (검출 목표) | 최대 필요 n | 10 variant 소요 |\n|---|---|---|\n")
    per_pre = sum(times.values()) / len(times)
    for d_ in (0.05, 0.02, 0.01, 0.005):
        n_ = need_by_delta[d_]
        w.write("| %.1f%% | **%d** | %.1f 시간 |\n"
                % (d_ * 100, n_, len(man["variants"]) * n_ * per_pre / 3600.0))
    w.write("\n")

    # ── 필요 반복 추정 ──
    w.write("## 수렴에 필요한 반복 횟수 추정 (지시서의 5%% 기준)\n\n")
    w.write("정규 근사에서 반폭 = 1.96·sd/√n 이므로, 반폭/평균 ≤ %g%% 를 만족하는 "
            "최소 n 은 **n ≥ (1.96·CV / %g)²** 다.\n\n" % (target * 100, target))
    w.write("| variant | 노출채널 | CV | 필요 n |\n|---|---|---|---|\n")
    need_max = 1
    for vid in pilot_ids:
        keys = sorted({k for r in runs[vid] for k in r["exposure_channel"]})
        for k in keys:
            xs = [r["exposure_channel"].get(k, 0.0) for r in runs[vid]]
            m, sd, half, cv = stats(xs)
            need = max(1, math.ceil((1.96 * cv / target) ** 2)) if m else 1
            need_max = max(need_max, need)
            w.write("| `%s` | %s | %.4f | **%d** |\n" % (vid, k, cv, need))
    w.write("\n**최대 필요 반복 = %d회** (가장 분산이 큰 채널 기준).\n\n" % need_max)

    # ── 본실험 규모 ──
    n_var = len([v for v in man["variants"]])
    per = sum(times.values()) / len(times)
    w.write("## 본실험 규모 제안 (Phase 0-3)\n\n")
    w.write("| 항목 | 값 |\n|---|---|\n")
    w.write("| variant 수 (BASE 포함) | %d |\n" % n_var)
    w.write("| 1회 실행 시간 (실측 평균) | **%.1f 초** |\n" % per)
    w.write("| 수렴 기준 | 95%%CI 반폭 ≤ 평균의 **%g%%** (채널별 전부 충족) |\n"
            % (target * 100))
    w.write("| 필요 반복 (추정) | **%d회** |\n" % need_max)
    w.write("| 반복 상한 | **200회** (수렴 실패 시 그 사실과 함께 중단) |\n")
    est = n_var * need_max * per
    w.write("| 예상 총 소요 (5%% 기준, n=%d) | %d × %d × %.1fs = **%.1f 시간** |\n"
            % (need_max, n_var, need_max, per, est / 3600.0))
    worst = n_var * 200 * per
    w.write("| 최악(상한 200회) | **%.1f 시간** |\n" % (worst / 3600.0))
    n_rec = need_by_delta[0.01]
    est_rec = n_var * n_rec * per
    w.write("| **권장 (δ=1%% 검출, n=%d)** | **%.1f 시간** |\n\n" % (n_rec, est_rec / 3600.0))

    w.write("> **5%% 수렴 기준은 이 시스템에서 구속력이 없다.** 반복 간 변동계수가 "
            "%.4f~%.4f 로 작아 n=1 에서도 충족된다. 그러나 그것으로는 variant 효과를 "
            "구분할 수 없다 — 위 MDD 표에서 보듯 n=%d 에서도 유의하지 않은 채널이 있다. "
            "**반복 횟수는 검출하려는 차이(δ)로 정해야 한다.**\n\n"
            % (min(r[6] for r in mdd_rows), max(r[7] for r in mdd_rows), a.n))

    if est_rec > 8 * 3600 or est > 8 * 3600:
        w.write("> **예상 소요가 8시간을 넘는다.** 대안과 각각의 정밀도 영향:\n\n")
        w.write("| 대안 | 소요 | 정밀도 영향 |\n|---|---|---|\n")
        w.write("| 반복을 %d 로 감축 | %.1f h | 반폭/평균이 %g%% → %.1f%% 로 커진다 |\n"
                % (max(2, need_max // 2), n_var * max(2, need_max // 2) * per / 3600.0,
                   target * 100, target * 100 * math.sqrt(2)))
        w.write("| 병렬 4프로세스 | %.1f h | **없음** — 시드가 런별로 독립이라 "
                "결과가 비트 동일하다 |\n" % (est / 4 / 3600.0))
        w.write("| max_steps 축소 | 비례 감소 | **절대 노출량 해석 불가.** "
                "variant 간 상대 비교만 가능해진다 |\n\n")
    else:
        w.write("예상 소요가 8시간 이내라 감축이 필요하지 않다.\n\n")

    w.write("## 1회 실행 시간 (variant 별)\n\n| variant | 초/회 |\n|---|---|\n")
    for vid, t in times.items():
        w.write("| `%s` | %.1f |\n" % (vid, t))
    lo, hi = min(times.values()), max(times.values())
    if hi > 2 * lo:
        w.write("\n> **variant 별 실행 시간이 %.1f배 차이난다(%.1fs vs %.1fs).** "
                "`%s` 는 공정표가 바뀌어 공기가 늘고 동시 진행 층이 많아지기 때문이다. "
                "총 소요 산정에 평균(%.1fs)이 아니라 **최대값을 쓰는 것이 안전하다** — "
                "10 variant × n회 기준으로 최대 %.1f 시간까지 늘 수 있다.\n"
                % (hi / lo, hi, lo,
                   max(times, key=lambda k: times[k]), per,
                   len(man["variants"]) * need_by_delta[0.01] * hi / 3600.0))
    w.write("\n")

    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())
    print("저장: %s" % OUT)
    print("  필요 반복 추정 %d회 / 1회 %.1fs / 예상 %.1f시간"
          % (need_max, per, est / 3600.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
