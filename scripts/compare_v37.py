# -*- coding: utf-8 -*-
"""v3.7 D-1 — 이식 보강 4단계 대조 + Part A 검증.

  stage6   v3.6 종료 (dwell 12.5%, 경로 effects 없음, 확률적 변동 없음)
  stage7a  + 경로 effects 전달 (Part A)
  stage7b  + 체류 비율 0.75 (Part B)
  stage7c  + 확률적 변동 (Part C)

추가로 Part A-2/A-3 을 검증한다:
  A-2  ALT_H001_05 적용 시 **노출량**과 **λ** 가 각각 어느 방향으로 변하는가
  A-3  variant 적용 시 궤적이 BASE 와 실제로 달라지는가

실행: python scripts/compare_v37.py [--days N] [--reps N]
산출: build/stage7_comparison.md
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

import config as C
import fourd
import fourd_workers as FW
import movement
import ptd_ttl
from controls import ControlApplication, resolve_all

OUT = "build/stage7_comparison.md"
HAZ = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")
STAGES = [("stage6", "v36", "v3.6 종료 (기준)"),
          ("stage7a", "a", "+ 경로 effects (Part A)"),
          ("stage7b", "ab", "+ 체류 비율 0.75 (Part B)"),
          ("stage7c", "v37", "+ 확률적 변동 (Part C)")]


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
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, sd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--reps", type=int, default=5)
    a = ap.parse_args()

    lib = ptd_ttl.require_library()
    sch, site, life, cfg, wl = FW.load_project_v2()
    ts = fourd.load_temp_structures()

    def run(stage, seed, effects=None):
        movement._CTX.clear()
        return FW.run_project_workers(sch, site, life, cfg, wl, days=a.days,
                                      mc_runs=1, seed=seed, max_steps=a.max_steps,
                                      temp_structures=ts, stage=stage,
                                      controls_effects=effects, library=lib)

    # ── 단계별 (reps 회 반복해 회차 간 표준편차도 낸다) ──
    rows = []
    for name, stage, desc in STAGES:
        # [주의] 반복 결과를 리스트로 들고 있으면 안 된다. 1회 결과가
        # exposure_steps+lam+fallback 약 9만 항목이라 20회를 보관하면 180만 항목이
        # 되고, GC·메모리 압력으로 **실행 시간 측정이 오염된다**(실측: 11초 → 2,348초).
        # 각 회차를 즉시 집계하고 버린다.
        tot, ch, hz = [], collections.Counter(), collections.Counter()
        p = None
        t0 = time.time()
        for i in range(a.reps):
            r = run(stage, "v37|%s|%d" % (stage, i))
            tot.append(sum(r["exposure_steps"].values()))
            for k, v in FW.channel_totals(r).items():
                ch[k] += v / a.reps
            for k, v in haz_exposure(r, life).items():
                hz[k] += v / a.reps
            if p is None:
                p = dict(r["placement"])
                first = {"dwell_steps": r["dwell_steps"],
                         "stagger_steps": r["stagger_steps"],
                         "fb": sum(r["exposure_steps_fallback"].values())}
            del r
        secs = (time.time() - t0) / a.reps
        m, sd = stats(tot)
        rows.append(dict(name=name, desc=desc, stage=stage, mean=m, sd=sd,
                         secs=secs, chan=dict(ch), haz=dict(hz),
                         dwell=first["dwell_steps"], stagger=first["stagger_steps"],
                         poi=p["visits"] / max(1, p["worker_days"]),
                         fb=first["fb"]))
        print("  %-8s %-30s %.1fs  총=%9.0f ±%-7.0f dwell=%-3d POI/워커일=%.2f"
              % (name, desc, secs, m, sd, first["dwell_steps"], rows[-1]["poi"]))

    # ── A-2/A-3: 변형이 실제로 무엇을 바꾸는가 ──
    print("\nPart A 검증 중…")
    inst_by_haz = collections.defaultdict(list)
    for h in life.instances:
        inst_by_haz[h.hazard_type].append(h)
    probes = []
    for aid, haz in (("ALT_H001_05", "H001"), ("ALT_S_CP_04", "H008"),
                     ("ALT_T_CP_03", "H008"), ("ALT_H001_01", "H001")):
        tg = inst_by_haz.get(haz) or []
        if not tg or aid not in lib.alternatives:
            continue
        try:
            eff = resolve_all(lib, [ControlApplication(aid, h.instance_id)
                                    for h in tg], sch, life)
        except Exception as ex:
            probes.append((aid, None, None, None, None, str(ex)[:60]))
            continue
        base = run("v37", "probe|base")
        e0 = sum(base["exposure_steps"].values())
        l0 = sum(base["lam"].values())
        base_exp = base["exposure_steps"]
        del base
        var = run("v37", "probe|base", effects=eff)
        e1 = sum(var["exposure_steps"].values())
        l1 = sum(var["lam"].values())
        same_traj = base_exp == var["exposure_steps"]
        n_eff_days = var["path_effect_days"]["with_effects"]
        del var, base_exp
        probes.append((aid, e0, e1, l0, l1, same_traj, n_eff_days))
        print("  %-14s 노출 %+.2f%%  λ %+.2f%%  궤적동일=%s  경로effects적용일=%d"
              % (aid, 100 * (e1 - e0) / e0, 100 * (l1 - l0) / l0,
                 same_traj, n_eff_days))

    # ── 리포트 ──
    w = io.StringIO()
    w.write("# 4D 작업자 알고리즘 이식 보강 — 4단계 대조 (v3.7 D-1)\n\n")
    w.write("하루 %d 스텝, 각 단계 %d회 반복(시드 다름), 전체 공기 %d일. "
            "**수치를 조정하지 않았다.**\n\n"
            % (a.max_steps, a.reps, a.days or sch.duration))

    w.write("## 총 노출 · 실행 시간\n\n")
    w.write("| 단계 | 내용 | 체류스텝 | POI/워커일 | 총 노출(평균) | 회차간 sd | 초/회 |\n")
    w.write("|---|---|---|---|---|---|---|\n")
    for r in rows:
        w.write("| **%s** | %s | %d | %.2f | %s | %s | %.1f |\n"
                % (r["name"], r["desc"], r["dwell"], r["poi"],
                   "{:,.0f}".format(r["mean"]), "{:,.0f}".format(r["sd"]), r["secs"]))
    w.write("\n")
    b = rows[0]
    w.write("stage6 대비 총 노출: " + " · ".join(
        "%s %+.1f%%" % (r["name"], 100 * (r["mean"] - b["mean"]) / b["mean"])
        for r in rows[1:]) + "\n\n")

    w.write("## 채널별 노출 — 통과형 → 체류형 이동\n\n")
    keys = sorted(set().union(*[set(r["chan"]) for r in rows]))
    w.write("| 채널 | " + " | ".join(r["name"] for r in rows) + " | s6→s7c |\n")
    w.write("|---|" + "---|" * (len(rows) + 1) + "\n")
    for k in keys:
        v = [r["chan"].get(k, 0.0) for r in rows]
        w.write("| %s | %s | %s |\n"
                % (k, " | ".join("{:,.0f}".format(x) for x in v),
                   "%+.1f%%" % (100 * (v[-1] - v[0]) / v[0]) if v[0] else "—"))
    w.write("\n")

    w.write("## 위험유형별 노출\n\n")
    w.write("| 위험유형 | " + " | ".join(r["name"] for r in rows) + " | s6→s7c |\n")
    w.write("|---|" + "---|" * (len(rows) + 1) + "\n")
    for k in HAZ:
        v = [r["haz"].get(k, 0.0) for r in rows]
        w.write("| %s | %s | %s |\n"
                % (k, " | ".join("{:,.0f}".format(x) for x in v),
                   "%+.1f%%" % (100 * (v[-1] - v[0]) / v[0]) if v[0] else "—"))
    w.write("\n")

    w.write("## Part A 검증 — 대책이 경로를 바꾸는가\n\n")
    w.write("| 대안 | 노출 변화 | λ 변화 | 궤적이 BASE 와 동일? | 경로effects 적용일 |\n")
    w.write("|---|---|---|---|---|\n")
    for p in probes:
        if len(p) == 6 and isinstance(p[5], str):
            w.write("| `%s` | — | — | — | 실패: %s |\n" % (p[0], p[5]))
            continue
        aid, e0, e1, l0, l1, same, nd = p
        w.write("| `%s` | %+.2f%% | %+.2f%% | %s | %d |\n"
                % (aid, 100 * (e1 - e0) / e0, 100 * (l1 - l0) / l0,
                   "**예 (변화 없음)**" if same else "아니오", nd))
    w.write("\n")
    w.write("> **경로effects 적용일이 0 이면 그 대안은 경로를 바꾸지 않는다.** "
            "`movement._build_context` 가 경로 비용에 쓰는 값은 "
            "`hazardWeightMultiplier` 뿐인데, 라이브러리 전체에서 그 값을 가진 규칙은 "
            "`RULE_HS_DEBRISNET` 1건이고 그것마저 `drop_zone` 이라 2D 셀타입 대응이 없다. "
            "`fallProbMultiplier`(λ 배율)를 경로 비용으로 쓰는 것은 값의 의미를 "
            "지어내는 것이므로 하지 않았다.\n\n")

    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())
    print("\n저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
