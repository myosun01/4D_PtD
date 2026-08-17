# -*- coding: utf-8 -*-
"""v3.4 — H001 개구부 채널 노출 신호 진단 (진단 전용, 아무것도 수정하지 않는다).

H001_FloorOpening 은 zone 39개로 가장 많은데 노출스텝은 1,030 (전체의 1%) 이다.
같은 dwell_time 채널인 H007_SlabEdge 는 zone 8개로 19,257 이다.
떨어짐 사다리가 축 1 실험의 주력인데 그 채널의 신호가 노이즈 수준이면
대안을 적용해도 저감량이 나오지 않는다.

이 스크립트는 A(zone 단위 분포) / B(작업위치 겹침·walkable) / C(회피 강도)를
측정만 한다. 파일을 쓰지 않는다 (리포트는 별도 인자로 명시할 때만).

실행: python scripts/diagnose_h001.py
"""
import argparse
import collections
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import fourd_workers as FW
from movement import fall_edge_cells

OUT = "build/h001_signal_diagnosis.md"
HAZ_ALL = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")


def run(days=None, max_steps=80, seed="v3.1-workers", ts=True):
    sch, site, life, cfg, wl = FW.load_project_v2()
    tstruct = fourd.load_temp_structures() if ts else None
    res = FW.run_project_workers(sch, site, life, cfg, wl, days=days, mc_runs=1,
                                 seed=seed, max_steps=max_steps,
                                 temp_structures=tstruct)
    return sch, site, life, cfg, wl, res


def exposure_index(res, key="exposure_steps"):
    """(level, channel, r, c) → 노출스텝 합 (일자 무관)."""
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res.get(key, {}).items():
        idx[(lv, ch, int(r), int(c))] += v
    return idx


def zone_rows(life, zones_by_id, idx, hazard_code):
    """위험유형별 zone 단위 노출 표."""
    rows = []
    for h in life.instances:
        if h.hazard_type != hazard_code:
            continue
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        zid = None
        # instance_id 는 HZ-<i>-<template>-<activity> 형식이라 zone_id 가 없다.
        # 바인딩 순서 == instances 순서이므로 호출부가 zid 를 붙여 넘긴다.
        rows.append((h, ch))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--write", action="store_true", help="리포트 파일 생성")
    a = ap.parse_args()

    w = io.StringIO()
    P = (lambda *x: (print(*x), w.write(" ".join(str(i) for i in x) + "\n")))

    zdoc = json.load(open("build/hazard_zones.json", encoding="utf-8"))
    zones = zdoc["zones"]
    binds = json.load(open("build/lifecycle_bindings_v2.json",
                           encoding="utf-8"))["bindings"]
    site_raw = json.load(open("project/site.json", encoding="utf-8"))
    grids_static = {l["levelID"]: np.array(l["grid"]["cells"])
                    for l in site_raw["levels"]}

    sch, site, life, cfg, wl, res = run(days=a.days, max_steps=a.max_steps)
    idx = exposure_index(res)
    idx_fb = exposure_index(res, "exposure_steps_fallback")

    # 바인딩 순서 == LifecycleEngine.instances 순서
    zid_of = {}
    for b, inst in zip(binds, life.instances):
        zid_of[inst.instance_id] = b.get("_zone_id")
    zmeta = {z["zone_id"]: z for z in zones}

    # ══════════════════════════════════════════════════════
    P("# H001 개구부 채널 노출 신호 진단 (v3.4)\n")
    P("진단 전용. 어떤 파일도 수정하지 않았다. "
      "실행: 전체 공기 %d일, 하루 %d 스텝, mc_runs=1.\n" % (sch.duration, a.max_steps))

    # ── A. zone 단위 노출 분포 ────────────────────────────
    for code in ("H001", "H007"):
        P("\n## A. zone 단위 노출 — %s\n" % code)
        P("| zone_id | storey | cells | raw_area_m2 | 활성일 | 노출스텝 | /활성일 | /cells |")
        P("|---|---|---|---|---|---|---|---|")
        tot = 0.0
        nzero = 0
        rows = []
        for h in life.instances:
            if h.hazard_type != code:
                continue
            ch = fourd.HAZARD_CHANNEL_4D.get(code)
            zid = zid_of.get(h.instance_id)
            z = zmeta.get(zid, {})
            cells = {(int(r), int(c)) for r, c in h.cells}
            e = sum(idx.get((h.level, ch, r, c), 0.0) for (r, c) in cells)
            dp = h.despawn_day if h.despawn_day != float("inf") else sch.duration
            act = max(0, int(min(dp, sch.duration)) - int(h.spawn_day))
            rows.append((zid, z.get("storey"), len(cells), z.get("raw_area_m2"),
                         act, e))
            tot += e
            if e == 0:
                nzero += 1
        rows.sort(key=lambda r: -r[5])
        for zid, st, nc, area, act, e in rows:
            P("| `%s` | %s | %d | %s | %d | %.0f | %s | %s |"
              % (zid, st, nc, area, act, e,
                 ("%.1f" % (e / act)) if act else "—",
                 ("%.2f" % (e / nc)) if nc else "—"))
        P("")
        P("**%s: zone %d개 / 노출 합 %.0f / 노출 0인 zone %d개 (%.0f%%)**\n"
          % (code, len(rows), tot, nzero, 100.0 * nzero / max(1, len(rows))))
        bylv = collections.Counter()
        for h in life.instances:
            if h.hazard_type == code:
                ch = fourd.HAZARD_CHANNEL_4D.get(code)
                bylv[h.level] += sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                                     for r, c in h.cells)
        P("층별 합계: %s\n" % ", ".join("%s=%.0f" % kv for kv in sorted(bylv.items())))

    # ── B-1. 작업 위치 겹침 ───────────────────────────────
    P("\n## B-1. 작업 위치와 위험 zone 의 겹침\n")
    loc = json.load(open("build/task_locations.json", encoding="utf-8"))["tasks"]
    acts = {x["activityID"]: x for x in
            json.load(open("project/schedule.json", encoding="utf-8"))["activities"]}
    # 액티비티별 작업 셀 (level 은 override 반영)
    work_cells = {}
    for t, rec in loc.items():
        aid = rec["activityID"]
        a_ = acts.get(aid)
        if a_ is None:
            continue
        lv = rec.get("level_override") or a_["zone"].split(":")[0]
        cells = {(int(r), int(c)) for (r, c) in wl.cells_for(aid)}
        if cells:
            work_cells[aid] = (lv, cells)

    haz_cells = collections.defaultdict(set)     # code → {(level,r,c)}
    for h in life.instances:
        for (r, c) in h.cells:
            haz_cells[h.hazard_type].add((h.level, int(r), int(c)))

    all_work = set()
    for aid, (lv, cells) in work_cells.items():
        all_work |= {(lv, r, c) for (r, c) in cells}

    P("전체 작업 위치 셀 %s개 (액티비티 %d건).\n"
      % ("{:,}".format(len(all_work)), len(work_cells)))
    P("| 위험유형 | zone 셀 | 작업셀∩zone | 작업셀 중 비율 | 겹치는 액티비티 |")
    P("|---|---|---|---|---|")
    overlap_acts = {}
    for code in HAZ_ALL:
        hz = haz_cells[code]
        inter = all_work & hz
        n_act = 0
        lst = []
        for aid, (lv, cells) in work_cells.items():
            if any((lv, r, c) in hz for (r, c) in cells):
                n_act += 1
                lst.append(aid)
        overlap_acts[code] = lst
        P("| %s | %s | %s | %.2f%% | %d |"
          % (code, "{:,}".format(len(hz)), "{:,}".format(len(inter)),
             100.0 * len(inter) / max(1, len(all_work)), n_act))
    P("")
    P("H001 과 겹치는 액티비티 %d건: %s\n"
      % (len(overlap_acts["H001"]),
         ", ".join("`%s`" % x for x in sorted(overlap_acts["H001"])[:40]) or "없음"))

    # ── B-2. 개구부 셀이 walkable 인가 ────────────────────
    P("\n## B-2. H001 zone 셀은 격자에서 무엇이 되는가\n")
    P("`fourd.build_level_day` 의 위험유형별 오버레이:\n")
    P("| 위험유형 | 격자 셀타입 | walkable | 노출 셀 정의 (`channel_cells`) |")
    P("|---|---|---|---|")
    P("| H001 | `C.FLOOR_OPENING`(2) | **아니오 — 구멍** | `fall_edge_cells(grid)` = 개구부에 인접한 walkable 셀만 |")
    P("| H007 | `C.EDGE`(6) | **예** | `grid == C.EDGE` = **zone 셀 전체** |")
    P("| H004 | `C.MATERIAL`(4) | 예 | `grid == C.MATERIAL` = zone 셀 전체 |")
    P("| H002·H011 | `C.NARROW`(5) | 예 | `grid == C.NARROW` = zone 셀 전체 |")
    P("| H008·H009 | (오버레이 없음) | 예 | zone 셀 중 walkable = zone 셀 전체 |")
    P("")

    # 실측: 어느 날 H001 이 활성인 층에서 zone 셀 수 vs fall 셀 수
    P("실측 — H001 이 활성인 (일자, 층) 표본에서 zone 셀 수 대 실제 노출 대상(fall) 셀 수:\n")
    P("| 일자 | 층 | H001 zone 셀 | fall 노출셀 | 비율 |")
    P("|---|---|---|---|---|")
    seen = 0
    ratios = []
    for d in range(0, sch.duration, 7):
        hz = life.hazards(d)
        h1 = [h for h in hz if h.hazard_type == "H001"]
        if not h1:
            continue
        lv = h1[0].level
        grid, ch_cells, _cm = fourd.build_level_day(
            site, lv, hz, {}, d, temp_structures=fourd.load_temp_structures())
        zc = {(int(r), int(c)) for h in h1 if h.level == lv for r, c in h.cells}
        fc = ch_cells["fall"]
        if zc:
            ratios.append(len(fc) / len(zc))
            if seen < 8:
                P("| %d | %s | %d | %d | %.2f |" % (d, lv, len(zc), len(fc),
                                                     len(fc) / len(zc)))
                seen += 1
    if ratios:
        P("")
        P("표본 %d개 — fall 노출셀 / zone 셀 중앙값 **%.2f** "
          "(즉 zone 셀의 약 %.0f%% 만 노출 대상이 된다).\n"
          % (len(ratios), sorted(ratios)[len(ratios) // 2],
             100.0 * sorted(ratios)[len(ratios) // 2]))

    # ── B-3. 개구부 관련 작업이 공정표에 있는가 ───────────
    P("\n## B-3. 개구부 관련 작업이 공정표에 있는가\n")
    import csv as _csv
    rows_csv = list(_csv.DictReader(open("build/construction_schedule_v2.csv",
                                         encoding="utf-8-sig")))
    ets = collections.Counter(r["element_type"] for r in rows_csv)
    P("공정표 `element_type` 분포: %s\n"
      % ", ".join("%s=%d" % kv for kv in sorted(ets.items(), key=lambda x: -x[1])))
    kw = ("개구", "관통", "슬리브", "덮개", "설비", "배관", "전기", "닥트", "샤프트")
    hits = [r for r in rows_csv if any(k in r["task_name"] for k in kw)]
    P("개구부·관통부·설비 관련 태스크: **%d건**%s\n"
      % (len(hits), (" — " + ", ".join("T-%s %s" % (r["task_id"], r["task_name"])
                                        for r in hits[:10])) if hits else ""))

    P("H001 zone 39개의 despawnActivity:\n")
    dsp = collections.Counter()
    by_task = {r["task_id"]: r for r in rows_csv}
    for b, inst in zip(binds, life.instances):
        if inst.hazard_type != "H001":
            continue
        da = b.get("despawnActivity")
        nm = by_task.get((da or "").replace("T-", ""), {}).get("task_name", "?")
        dsp[(da, nm)] += 1
    P("| despawnActivity | 태스크명 | zone 수 |")
    P("|---|---|---|")
    for (da, nm), n in dsp.most_common():
        P("| `%s` | %s | %d |" % (da, nm, n))
    P("")
    act_days = []
    for h in life.instances:
        if h.hazard_type == "H001":
            dp = h.despawn_day if h.despawn_day != float("inf") else sch.duration
            act_days.append(int(min(dp, sch.duration)) - int(h.spawn_day))
    if act_days:
        P("H001 활성 기간(일): 최소 %d / 중앙값 %d / 최대 %d\n"
          % (min(act_days), sorted(act_days)[len(act_days) // 2], max(act_days)))

    # ── C-1. 회피 배율 ────────────────────────────────────
    P("\n## C-1. 기대값 대비 실측 (회피 배율)\n")
    P("무작위 보행이라면 어떤 유형의 노출 비율 = 그 유형의 노출대상 셀이 "
      "walkable 셀에서 차지하는 비율이다. 실측이 그보다 낮으면 회피, 높으면 유인이다.\n")
    # (일자, 층) 표본에서 채널별 노출대상 셀 비율과 실측 노출 비율
    exp_cells = collections.Counter()     # code → Σ(노출대상 셀 수)
    walk_cells = collections.Counter()    # (일자,층) 표본의 walkable 셀 수 합
    samp = 0
    tsx = fourd.load_temp_structures()
    for d in range(0, sch.duration, 7):
        hz = life.hazards(d)
        if not hz:
            continue
        for lv in sorted({h.level for h in hz}):
            if lv not in site.levels:
                continue
            grid, ch_cells, _ = fourd.build_level_day(site, lv, hz, {}, d,
                                                      temp_structures=tsx)
            nwalk = int((~np.isin(grid, [C.WALL, C.FLOOR_OPENING])).sum())
            if not nwalk:
                continue
            walk_cells["_"] += nwalk
            samp += 1
            for code in HAZ_ALL:
                ch = fourd.HAZARD_CHANNEL_4D.get(code)
                zc = {(int(r), int(c)) for h in hz
                      if h.hazard_type == code and h.level == lv for r, c in h.cells}
                if not zc:
                    continue
                exp_cells[code] += len(zc & ch_cells.get(ch, frozenset()))

    tot_exposure = sum(res["exposure_steps"].values())
    haz_exp = collections.Counter()
    for code in HAZ_ALL:
        ch = fourd.HAZARD_CHANNEL_4D.get(code)
        haz_exp[code] = sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                            for h in life.instances if h.hazard_type == code
                            for r, c in h.cells)
    denom = float(walk_cells["_"]) or 1.0
    P("| 유형 | 노출대상셀 비중(기대) | 실측 노출 비중 | 회피 배율(기대/실측) |")
    P("|---|---|---|---|")
    for code in HAZ_ALL:
        expect = exp_cells[code] / denom
        actual = haz_exp[code] / (tot_exposure or 1.0)
        ratio = (expect / actual) if actual else float("inf")
        P("| %s | %.4f%% | %.4f%% | %s |"
          % (code, 100 * expect, 100 * actual,
             ("%.2f×" % ratio) if ratio != float("inf") else "∞"))
    P("")
    P("(표본: 7일 간격 %d개 (일자,층) 조합, walkable 셀 누계 %s)\n"
      % (samp, "{:,}".format(int(denom))))

    # ── C-2. 경로 비용 기여도 ─────────────────────────────
    P("\n## C-2. soft_route 비용 항 비교\n")
    P("`movement._build_context` 의 이웃 비용: "
      "`cost = base + extra×aversion + uniform(0, PATH_NOISE)`\n")
    P("```")
    P("base            = 1.0 (직교) / 1.414 (대각)")
    P("extra(cell)     = HAZARD_WEIGHT[cell] × RISK_K × weight_mult")
    P("extra += OPEN_EDGE_PEN × weight_mult(FLOOR_OPENING)   # 개구부에 4방 인접한 셀")
    P("aversion        = 1 - clamp(rho, 0.05, 0.95)")
    P("```")
    P("")
    P("| 셀 타입 | HAZARD_WEIGHT | RISK_K | 개구부 인접 가산 | extra 합 | base(1.0) 대비 |")
    P("|---|---|---|---|---|---|")
    hw = C.HAZARD_WEIGHT
    for name, cell, near_open in (("개구부 인접 walkable (H001 노출셀)", None, True),
                                  ("EDGE (H007 노출셀)", C.EDGE, False),
                                  ("MATERIAL (H004)", C.MATERIAL, False),
                                  ("NARROW (H002·H011)", C.NARROW, False),
                                  ("일반 통로", C.WALKABLE, False)):
        e = hw.get(cell, 0.0) * C.RISK_K
        if near_open:
            e += C.OPEN_EDGE_PEN
        P("| %s | %s | %.1f | %s | %.2f | %.2f× |"
          % (name, hw.get(cell, 0.0), C.RISK_K,
             ("+%.1f" % C.OPEN_EDGE_PEN) if near_open else "—", e, e / 1.0))
    P("")
    P("**HAZARD_WEIGHT 에 EDGE(6) 항목이 %s.** config.HAZARD_WEIGHT = %s\n"
      % ("없다" if C.EDGE not in hw else "있다", dict(hw)))

    if a.write:
        with io.open(OUT, "w", encoding="utf-8") as fp:
            fp.write(w.getvalue())
        print("\n저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
