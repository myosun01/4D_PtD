# -*- coding: utf-8 -*-
"""Phase 4-1 — 노출 변화를 3단계로 대조한다 (v3.3).

  stage1  매핑 보강 전   (element_task_mapping.json 만, TS 없음)
  stage2  매핑 보강 후   (build/task_locations.json, TS 없음)
  stage3  walkable 재조정 후 (+ build/temp_structures.json)

같은 시드·같은 스텝수로 세 번 돌려 총 노출·채널별·위험유형별·층별·폴백 비율을
그대로 대조한다. **수치를 조정하지 않는다.** 변화의 방향과 크기를 그대로 낸다.

실행: python scripts/compare_stages.py [--max-steps 80]
산출: build/stage_comparison.md
"""
import argparse
import collections
import io
import json
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import fourd
import fourd_workers as FW

OUT = "build/stage_comparison.md"
HAZ = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")


def haz_exposure(res, life, key="exposure_steps"):
    # 귀속은 fourd.instance_exposure_cells() 로 통일 (v3.5 A-1)
    cells_by = collections.defaultdict(set)
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        for (r, c) in fourd.instance_exposure_cells(h):
            cells_by[h.hazard_type].add((h.level, ch, int(r), int(c)))
    out = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res.get(key, {}).items():
        for haz, cells in cells_by.items():
            if (lv, ch, r, c) in cells:
                out[haz] += v
    return dict(out)


def level_exposure(res):
    out = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res["exposure_steps"].items():
        out[lv] += v
    return dict(out)


def pct(new, old):
    if not old:
        return "—" if not new else "+∞"
    return "%+.1f%%" % (100.0 * (new - old) / old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--seed", default="v3.1-workers")
    a = ap.parse_args()

    sch, site, life, cfg, _wl = FW.load_project_v2()
    gf = json.load(open("project/site.json", encoding="utf-8"))["gridFrame"]
    ts = fourd.load_temp_structures()

    # stage1: 위치표 없이 (원본 매핑만) — 후방호환 경로를 그대로 탄다
    wl1 = FW.WorkLocations(gf, locations_path="__none__")
    # stage2/3: 파생 위치표
    wl2 = FW.WorkLocations(gf)
    wl3 = FW.WorkLocations(gf)

    stages = []
    for name, wl, use_ts in (("stage1 매핑 보강 전", wl1, None),
                             ("stage2 매핑 보강 후", wl2, None),
                             ("stage3 walkable 재조정 후", wl3, ts)):
        t0 = time.time()
        r = FW.run_project_workers(sch, site, life, cfg, wl, mc_runs=1,
                                   seed=a.seed, max_steps=a.max_steps,
                                   temp_structures=use_ts)
        r["_name"] = name
        r["_secs"] = time.time() - t0
        stages.append(r)
        print("  %-26s %.1fs  주집계 %s  폴백 %s"
              % (name, r["_secs"],
                 "{:,.0f}".format(sum(r["exposure_steps"].values())),
                 "{:,.0f}".format(sum(r["exposure_steps_fallback"].values()))))

    w = io.StringIO()
    w.write("# 노출 변화 3단계 대조 (v3.3 Phase 4-1)\n\n")
    w.write("같은 시드 `%s`, 하루 %d 스텝, mc_runs=1, 전체 공기 %d일. "
            "**수치를 조정하지 않았다.**\n\n" % (a.seed, a.max_steps, sch.duration))

    w.write("| 단계 | 위치 원천 | 가설물 |\n|---|---|---|\n")
    w.write("| stage1 | `element_task_mapping.json` (112/234) | 없음 |\n")
    w.write("| stage2 | `build/task_locations.json` (234/234) | 없음 |\n")
    w.write("| stage3 | `build/task_locations.json` | `build/temp_structures.json` |\n\n")

    # ── 총계 ──
    w.write("## 총 노출스텝\n\n")
    w.write("| 집계 | stage1 | stage2 | vs s1 | stage3 | vs s2 |\n"
            "|---|---|---|---|---|---|\n")
    d = [sum(s["exposure_steps"].values()) for s in stages]
    f = [sum(s["exposure_steps_fallback"].values()) for s in stages]
    tt = [d[i] + f[i] for i in range(3)]
    for label, v in (("주 집계 (유도 워커)", d), ("폴백 (부가)", f),
                     ("포함 합계 (참고)", tt)):
        w.write("| %s | %s | %s | %s | %s | %s |\n"
                % (label, "{:,.0f}".format(v[0]), "{:,.0f}".format(v[1]),
                   pct(v[1], v[0]), "{:,.0f}".format(v[2]), pct(v[2], v[1])))
    w.write("\n")

    # ── 폴백 비율 ──
    w.write("## 폴백 비율\n\n| 기준 | stage1 | stage2 | stage3 |\n|---|---|---|---|\n")
    row = []
    for s in stages:
        p = s["placement"]
        tot = p["derived"] + p["fallback"]
        row.append(100.0 * p["fallback"] / tot if tot else 0.0)
    w.write("| 워커-일 | %.1f%% | %.1f%% | %.1f%% |\n" % tuple(row))
    row2 = [100.0 * f[i] / tt[i] if tt[i] else 0.0 for i in range(3)]
    w.write("| 노출스텝 | %.1f%% | %.1f%% | %.1f%% |\n\n" % tuple(row2))
    if row[2] > 30.0:
        w.write("> **경고 — stage3 폴백 비율 %.1f%% 가 30%% 를 넘는다.** "
                "이 상태로는 variant 실험을 돌릴 수 없다.\n\n" % row[2])
    else:
        w.write("stage3 폴백 비율 %.1f%% — 30%% 기준 이하.\n\n" % row[2])

    # ── 채널별 ──
    w.write("## 채널별 노출스텝 (주 집계)\n\n")
    ch = [FW.channel_totals(s) for s in stages]
    keys = sorted(set().union(*[set(x) for x in ch]))
    w.write("| 채널 | stage1 | stage2 | vs s1 | stage3 | vs s2 |\n|---|---|---|---|---|---|\n")
    for k in keys:
        v = [x.get(k, 0.0) for x in ch]
        w.write("| %s | %s | %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(v[0]), "{:,.0f}".format(v[1]), pct(v[1], v[0]),
                   "{:,.0f}".format(v[2]), pct(v[2], v[1])))
    w.write("\n")

    # ── 위험유형별 ──
    w.write("## 위험유형별 노출스텝 (주 집계)\n\n")
    hz = [haz_exposure(s, life) for s in stages]
    w.write("| 위험유형 | stage1 | stage2 | vs s1 | stage3 | vs s2 |\n|---|---|---|---|---|---|\n")
    for k in HAZ:
        v = [x.get(k, 0.0) for x in hz]
        w.write("| %s | %s | %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(v[0]), "{:,.0f}".format(v[1]), pct(v[1], v[0]),
                   "{:,.0f}".format(v[2]), pct(v[2], v[1])))
    w.write("\n**H008** 은 해체 태스크를 직하부 층에 배정한 효과가 직접 나타나는 항목이다.\n\n")

    # ── 층별 ──
    w.write("## 층별 노출스텝 (주 집계)\n\n")
    lv = [level_exposure(s) for s in stages]
    keys = sorted(set().union(*[set(x) for x in lv]))
    w.write("| 층 | stage1 | stage2 | stage3 |\n|---|---|---|---|\n")
    for k in keys:
        w.write("| %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(lv[0].get(k, 0.0)),
                   "{:,.0f}".format(lv[1].get(k, 0.0)),
                   "{:,.0f}".format(lv[2].get(k, 0.0))))
    w.write("\n")

    # ── 실행 시간 ──
    w.write("## 실행 시간 · 규모\n\n| 단계 | 실행 | λ 항목 |\n|---|---|---|\n")
    for s in stages:
        w.write("| %s | %.1fs | %s |\n"
                % (s["_name"], s["_secs"], "{:,}".format(len(s["lam"]))))
    w.write("\n")

    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())
    print("저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
