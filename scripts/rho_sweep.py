# -*- coding: utf-8 -*-
"""v3.7 D-2 — 회피 강도(ρ) 스윕. 이번 작업의 통과 기준 판정.

ρ 는 A* 비용의 `aversion = 1 − clamp(ρ, 0.05, 0.95)` 로 들어간다.
ρ 가 크면 회피가 약해(최단경로에 가까워) 위험구역을 더 지나고,
ρ 가 작으면 회피가 강해 돌아간다.

측정:
  · 회피 강도에 따라 BASE 노출이 단조롭게 변하는가
  · **대안 효과(BASE 대비 저감량)가 회피 강도에 따라 변하는가**
  · 공학적(계수형)과 제거·대체(형상·시점형)의 반응이 다른가

통과 기준: 대안 효과가 stage6 의 −0.33% 수준을 벗어나 유의해지고,
회피 강도에 따라 변화가 관측될 것.
**통과하지 못하면 그대로 보고한다. 파라미터를 조정해 신호를 만들지 않는다.**

실행: python scripts/rho_sweep.py [--reps 20]
산출: build/rho_sweep.md
"""
import argparse
import collections
import io
import json
import math
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import fourd
import fourd_workers as FW
import movement
import ptd_ttl
from lifecycle import LifecycleEngine
from schedule import Schedule
from site_model import SiteModel
from controls import ControlApplication, resolve_all

OUT = "build/rho_sweep.md"
MANIFEST = "build/variant_manifest.json"

# 회피 강도 3수준. ρ 는 회피의 **역수** 방향이다 (ρ↑ = 회피↓).
RHO_LEVELS = [("낮음(회피 약)", 0.90), ("중간(현행 분포)", None), ("높음(회피 강)", 0.10)]

# 비교할 variant — 등급 성격이 다른 것을 고른다
PROBE = [("ALT_H001_01", "제거", "형상(zone 제거)"),
         ("ALT_T_CP_01", "대체", "형상(zone 제거)"),
         ("ALT_H001_05", "공학적", "계수(λ 배율)"),
         ("ALT_S_CP_04", "공학적", "계수(λ 배율)")]


def stats(xs):
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd


def load_variant(v, lib):
    d = v["dir"]
    sch = Schedule.load(os.path.join(d, "schedule.json"))
    site = SiteModel.load("project/site.json")
    life = LifecycleEngine(lib.lifecycle_templates,
                           os.path.join(d, "lifecycle_bindings_v2.json"), sch)
    with open("project/crews.json", encoding="utf-8") as fp:
        cfg = {t["trade"]: t.get("rho", {}) for t in json.load(fp).get("trades", [])}
    gf = json.load(open("project/site.json", encoding="utf-8"))["gridFrame"]
    wl = FW.WorkLocations(gf, zones_path=os.path.join(d, "hazard_zones.json"))
    return sch, site, life, cfg, wl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--days", type=int, default=None)
    a = ap.parse_args()

    lib = ptd_ttl.require_library()
    man = json.load(open(MANIFEST, encoding="utf-8"))
    vs = {v["variant_id"]: v for v in man["variants"]}
    ts = fourd.load_temp_structures()

    def run(vid, rho, seed):
        v = vs[vid]
        sch, site, life, cfg, wl = load_variant(v, lib)
        eff = None
        if v.get("mechanism") == "controls_effect":
            tg = [h for h in life.instances
                  if h.hazard_type == v.get("target_hazard_type")]
            eff = resolve_all(lib, [ControlApplication(v["alternative_id"],
                                                       h.instance_id) for h in tg],
                              sch, life)
        movement._CTX.clear()
        r = FW.run_project_workers(sch, site, life, cfg, wl, days=a.days,
                                   mc_runs=1, seed=seed, max_steps=a.max_steps,
                                   temp_structures=ts, stage="v37",
                                   controls_effects=eff, library=lib,
                                   rho_override=rho)
        return sum(r["exposure_steps"].values()), sum(r["lam"].values())

    # [중요] BASE 와 variant 를 **같은 시드로 짝지어** 돌린다.
    # 시드가 다르면 회차 간 잡음(sd≈1,000)이 처치 효과를 덮는다. 특히 계수형은
    # 궤적을 전혀 바꾸지 않으므로 짝지으면 차이가 정확히 0 으로 나와야 한다 —
    # 그것이 참값이고, 시드를 달리하면 ±0.4% 의 가짜 변동이 생긴다.
    results = {}
    for lname, rho in RHO_LEVELS:
        for vid in ["BASE"] + [p[0] for p in PROBE]:
            if vid not in vs:
                continue
            t0 = time.time()
            xs = [run(vid, rho, "rho|%s|%d" % (lname, i))   # vid 를 시드에서 뺀다
                  for i in range(a.reps)]
            results[(lname, vid)] = xs
            m, sd = stats([x[0] for x in xs])
            print("  %-16s %-14s 노출 %9.0f ±%-6.0f  (%.1fs/회)"
                  % (lname, vid, m, sd, (time.time() - t0) / a.reps),
                  flush=True)
            # 중단되어도 재분석할 수 있도록 조건이 끝날 때마다 원자료를 남긴다
            with io.open("build/rho_sweep_raw.json", "w", encoding="utf-8") as fp:
                json.dump({"reps": a.reps, "max_steps": a.max_steps,
                           "results": {"%s|%s" % k: v for k, v in results.items()}},
                          fp, ensure_ascii=False)

    w = io.StringIO()
    w.write("# 회피 강도(ρ) 스윕 (v3.7 D-2)\n\n")
    w.write("각 조건 %d회, 하루 %d 스텝, stage=v37. "
            "ρ 는 A* 의 `aversion = 1 − ρ` 로 들어간다 — **ρ 가 크면 회피가 약하다.**\n\n"
            % (a.reps, a.max_steps))

    w.write("## BASE 노출의 ρ 반응 (단조성)\n\n")
    w.write("| 회피 강도 | ρ | BASE 노출 평균 | sd |\n|---|---|---|---|\n")
    base_m = {}
    for lname, rho in RHO_LEVELS:
        xs = results.get((lname, "BASE"))
        if not xs:
            continue
        m, sd = stats([x[0] for x in xs])
        base_m[lname] = (m, sd)
        w.write("| %s | %s | %s | %s |\n"
                % (lname, rho if rho is not None else "분포",
                   "{:,.0f}".format(m), "{:,.0f}".format(sd)))
    w.write("\n")
    seq = [base_m[l][0] for l, _ in RHO_LEVELS if l in base_m]
    mono = (all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1))
            or all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1)))
    w.write("단조 변화: **%s** (%s)\n\n"
            % ("예" if mono else "아니오",
               " → ".join("{:,.0f}".format(x) for x in seq)))

    w.write("## 대안 효과가 회피 강도에 따라 변하는가\n\n")
    w.write("**짝지은 비교**: 같은 시드의 BASE 와 variant 를 회차별로 빼서 저감량 "
            "분포를 만든다. 95%CI = 1.96·sd(차이)/√n. 짝짓지 않으면 회차 간 잡음"
            "(sd≈1,000)이 처치 효과를 덮는다.\n\n")
    w.write("| variant | 등급 | 성격 | " +
            " | ".join(l for l, _ in RHO_LEVELS) + " |\n")
    w.write("|---|---|---|" + "---|" * len(RHO_LEVELS) + "\n")
    sig_by_kind = {"형상": False, "계수": False}
    varies = []
    for vid, grade, kind in PROBE:
        if ("중간(현행 분포)", vid) not in results:
            continue
        cells = []
        eff_by_level = []
        for lname, _ in RHO_LEVELS:
            xb = results.get((lname, "BASE"))
            xv = results.get((lname, vid))
            if not xb or not xv:
                cells.append("—"); continue
            n = min(len(xb), len(xv))
            diffs = [xb[i][0] - xv[i][0] for i in range(n)]       # 짝지은 차이
            mb, _ = stats([x[0] for x in xb])
            md, sdd = stats(diffs)
            pct = 100.0 * md / mb if mb else 0.0
            ci = 1.96 * sdd / math.sqrt(n) if n > 1 else 0.0
            sig = abs(md) > ci
            k = "형상" if "형상" in kind else "계수"
            sig_by_kind[k] = sig_by_kind[k] or sig
            eff_by_level.append((pct, 100.0 * ci / mb if mb else 0.0))
            cells.append("%+.2f%% ±%.2f %s"
                         % (pct, 100.0 * ci / mb if mb else 0.0,
                            "**유의**" if sig else "(비유의)"))
        if len(eff_by_level) >= 2:
            ps = [e[0] for e in eff_by_level]
            # 수준 간 차이가 각 수준의 CI 를 넘는가 (변동이 잡음인지 판정)
            maxci = max(e[1] for e in eff_by_level)
            spread = max(ps) - min(ps)
            varies.append((vid, spread, maxci, spread > 2 * maxci))
        w.write("| `%s` | %s | %s | %s |\n" % (vid, grade, kind, " | ".join(cells)))
    w.write("\n")

    w.write("### 회피 강도에 따른 효과 변동이 잡음을 넘는가\n\n")
    w.write("| variant | 최대−최소 (%p) | 최대 CI 반폭 (%p) | 변동이 잡음 밖? |\n")
    w.write("|---|---|---|---|\n")
    for vid, sp, mc, ok in varies:
        w.write("| `%s` | %.2f | %.2f | %s |\n"
                % (vid, sp, mc, "**예**" if ok else "아니오"))
    w.write("\n")

    w.write("## 통과 판정 — 성격별로 갈린다\n\n")
    w.write("| 기준 | 형상·시점형 | 계수형 |\n|---|---|---|\n")
    w.write("| 대안 효과가 stage6 의 −0.33%% 수준을 벗어나 유의해졌는가 | %s | %s |\n"
            % ("**예**" if sig_by_kind["형상"] else "**아니오**",
               "**예**" if sig_by_kind["계수"] else "**아니오**"))
    varies_shape = [v for v in varies if v[0] in
                    [p[0] for p in PROBE if "형상" in p[2]]]
    varies_coef = [v for v in varies if v[0] in
                   [p[0] for p in PROBE if "계수" in p[2]]]
    w.write("| 회피 강도에 따라 효과가 변하는가 (잡음 밖) | %s | %s |\n"
            % ("**예**" if any(v[3] for v in varies_shape) else "**아니오**",
               "**예**" if any(v[3] for v in varies_coef) else "**아니오**"))
    w.write("\nBASE 가 ρ 에 단조 반응하는가: **%s**\n\n" % ("예" if mono else "아니오"))

    if not sig_by_kind["계수"]:
        w.write("> **계수형은 통과하지 못했다. 이는 잡음이 아니라 구조다.**\n>\n"
                "> 계수형(AgentParameterRule)은 λ 배율만 부여하고 격자를 바꾸지 않는다. "
                "짝지은 비교에서 노출 저감이 **정확히 0** 으로 나오는 것이 참값이며, "
                "`build/stage7_comparison.md` 의 Part A 검증(같은 시드)에서도 "
                "`+0.00%`, `궤적동일=True` 로 확인된다.\n>\n"
                "> 경로를 바꾸려면 `hazardWeightMultiplier` 가 필요한데 라이브러리 전체에 "
                "1건뿐이고 그마저 `drop_zone` 이라 2D 셀타입 대응이 없다. "
                "`fallProbMultiplier`(λ 배율)를 경로 비용으로 전용하는 것은 값의 의미를 "
                "지어내는 것이라 하지 않았다. **파라미터를 조정해 신호를 만들지 않았다.**\n>\n"
                "> 필요한 것은 `build/worker_algorithm_port.md` §A-2 에 적었다.\n")
    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())
    print("저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
