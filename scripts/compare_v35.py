# -*- coding: utf-8 -*-
"""v3.5 D-1 — 개구부 노출 모델 수정의 3단계 대조.

  stage3  v3.3 종료 상태   (zone 셀 귀속 + 버퍼를 구멍으로)
  stage4  A-1 귀속 통일     (instance_exposure_cells + 버퍼를 구멍으로)
  stage5  A-2 버퍼 분리     (instance_exposure_cells + 버퍼는 walkable 위험대)

stage3·stage4 는 **현재 코드에 이전 동작을 되살려** 재현한다(몽키패치, 진단 전용).
파일은 수정하지 않는다.

실행: python scripts/compare_v35.py
산출: build/stage_comparison_v35.md
"""
import argparse
import collections
import io
import sys
import time

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import fourd_workers as FW
import movement

OUT = "build/stage_comparison_v35.md"
HAZ = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")


def attribution(res, life, mode, key="exposure_steps"):
    """mode='zone' = v3.3 방식(zone 셀), 'instance' = v3.5 방식."""
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res.get(key, {}).items():
        idx[(lv, ch, int(r), int(c))] += v
    out = collections.Counter()
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        cells = (h.cells if mode == "zone" else fourd.instance_exposure_cells(h))
        out[h.hazard_type] += sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                                  for (r, c) in cells)
    return out


def walkable_census(site, life, sch, ts, legacy_overlay):
    """표본 (일자,층) 에서 walkable 셀 누계 — 버퍼 분리의 직접 효과."""
    tot = 0
    n = 0
    for d in range(0, sch.duration, 7):
        hz = life.hazards(d)
        for lv in sorted({h.level for h in hz}):
            if lv not in site.levels:
                continue
            grid, _ch, _cm = fourd.build_level_day(site, lv, hz, {}, d,
                                                   temp_structures=ts)
            tot += int((~np.isin(grid, [C.WALL, C.FLOOR_OPENING])).sum())
            n += 1
    return tot, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--seed", default="v3.1-workers")
    a = ap.parse_args()

    sch, site, life, cfg, wl = FW.load_project_v2()
    ts = fourd.load_temp_structures()

    orig_build = fourd.build_level_day
    orig_chan = fourd.channel_cells
    orig_apply = fourd.apply_temp_structures

    # ── 이전 동작 재현용 몽키패치 (진단 전용) ──────────────
    def legacy_apply_ts(grid, level_id, day, temp_structures=None):
        """v3.3 동작: walkable TS 가 FLOOR_OPENING 도 메운다."""
        if not temp_structures:
            return {}
        R, Co = grid.shape
        stat = {"walkable_added": 0, "blocked": 0, "types": collections.Counter()}
        for t in temp_structures.get(level_id, ()):
            if not fourd._ts_active(t, day):
                continue
            if t.get("walkable"):
                for r, c in t["cells"]:
                    if 0 <= r < R and 0 <= c < Co and grid[r, c] in (C.WALL, C.FLOOR_OPENING):
                        grid[r, c] = C.WALKABLE
            else:
                for r, c in t["cells"]:
                    if 0 <= r < R and 0 <= c < Co and grid[r, c] != C.WALL:
                        grid[r, c] = C.WALL
        return stat

    def legacy_build(site_, level_id, hazards, effects, day, temp_structures=None):
        """v3.3 동작: H001 zone(버퍼)을 FLOOR_OPENING 으로 덮어쓴다."""
        grid = site_.grid(level_id).copy()
        legacy_apply_ts(grid, level_id, day, temp_structures)
        collapse_cells, drop_cells = set(), set()
        cell_mult = {ch: {} for ch in fourd.CHANNELS}

        def _setmin(ch, cell, m):
            cell_mult[ch][cell] = min(cell_mult[ch].get(cell, 1.0), m)

        for h in hazards:
            if h.level != level_id:
                continue
            if h.hazard_type == fourd._HAZ_OPENING:
                for (r, c) in h.cells:
                    grid[r, c] = C.FLOOR_OPENING
            elif h.hazard_type == fourd._HAZ_EDGE:
                for (r, c) in h.cells:
                    if grid[r, c] != C.WALL:
                        grid[r, c] = C.EDGE
            elif h.hazard_type == fourd._HAZ_MATERIAL:
                for (r, c) in h.cells:
                    grid[r, c] = C.MATERIAL
            elif h.hazard_type in (fourd._HAZ_NARROW, fourd._HAZ_CORRIDOR):
                for (r, c) in h.cells:
                    if grid[r, c] not in (C.WALL, C.FLOOR_OPENING):
                        grid[r, c] = C.NARROW
            elif h.hazard_type == fourd._HAZ_COLLAPSE:
                collapse_cells |= {(int(r), int(c)) for r, c in h.cells}
            elif h.hazard_type == fourd._HAZ_DROP:
                drop_cells |= {(int(r), int(c)) for r, c in h.cells}
        ch = orig_chan(grid, collapse_cells, drop_cells)      # 버퍼 미전달 = 구 동작
        return grid, ch, cell_mult

    def go(label, legacy, attr_mode):
        if legacy:
            fourd.build_level_day = legacy_build
        else:
            fourd.build_level_day = orig_build
        movement._CTX.clear()
        t0 = time.time()
        r = FW.run_project_workers(sch, site, life, cfg, wl, mc_runs=1,
                                   seed=a.seed, max_steps=a.max_steps,
                                   temp_structures=ts)
        secs = time.time() - t0
        wc, n = walkable_census(site, life, sch, ts, legacy)
        fourd.build_level_day = orig_build
        h = attribution(r, life, attr_mode)
        d_ = sum(r["exposure_steps"].values())
        f_ = sum(r["exposure_steps_fallback"].values())
        print("  %-42s %.1fs  주=%9.0f 폴백=%7.0f  H001=%7.0f  walkable=%s"
              % (label, secs, d_, f_, h["H001"], "{:,}".format(wc)))
        return dict(label=label, secs=secs, haz=h, main=d_, fb=f_,
                    walk=wc, nsamp=n, chan=FW.channel_totals(r))

    print("3단계 대조 실행 중…")
    s3 = go("stage3 v3.3 종료 (zone 귀속 + 버퍼=구멍)", True, "zone")
    s4 = go("stage4 A-1 귀속 통일 (버퍼=구멍 유지)", True, "instance")
    s5 = go("stage5 A-2 버퍼 분리 (버퍼=walkable 위험대)", False, "instance")

    assert fourd.build_level_day is orig_build
    assert fourd.channel_cells is orig_chan
    assert fourd.apply_temp_structures is orig_apply

    stages = [s3, s4, s5]

    def pct(new, old):
        if not old:
            return "—" if not new else "+∞"
        return "%+.1f%%" % (100.0 * (new - old) / old)

    w = io.StringIO()
    w.write("# 개구부 노출 모델 수정 — 3단계 대조 (v3.5 D-1)\n\n")
    w.write("같은 시드 `%s`, 하루 %d 스텝, mc_runs=1, 전체 공기 %d일. "
            "**수치를 조정하지 않았다.**\n\n" % (a.seed, a.max_steps, sch.duration))
    w.write("| 단계 | 귀속 | 개구부 버퍼 |\n|---|---|---|\n")
    w.write("| stage3 | zone 셀 | FLOOR_OPENING (구멍) |\n")
    w.write("| stage4 | `instance_exposure_cells()` | FLOOR_OPENING (구멍) |\n")
    w.write("| stage5 | `instance_exposure_cells()` | **walkable + fall 노출 대상** |\n\n")

    w.write("## 총계\n\n| 항목 | stage3 | stage4 | vs s3 | stage5 | vs s4 |\n"
            "|---|---|---|---|---|---|\n")
    for key, lbl in (("main", "주 집계"), ("fb", "폴백(부가)"), ("walk", "walkable 셀 누계")):
        v = [s[key] for s in stages]
        w.write("| %s | %s | %s | %s | %s | %s |\n"
                % (lbl, "{:,.0f}".format(v[0]), "{:,.0f}".format(v[1]), pct(v[1], v[0]),
                   "{:,.0f}".format(v[2]), pct(v[2], v[1])))
    w.write("\n(walkable 셀 누계는 7일 간격 %d개 (일자,층) 표본)\n\n" % s5["nsamp"])

    w.write("## 위험유형별 노출스텝\n\n")
    w.write("| 위험유형 | stage3 | stage4 | vs s3 | stage5 | vs s4 |\n|---|---|---|---|---|---|\n")
    for k in HAZ:
        v = [s["haz"][k] for s in stages]
        w.write("| %s | %s | %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(v[0]), "{:,.0f}".format(v[1]), pct(v[1], v[0]),
                   "{:,.0f}".format(v[2]), pct(v[2], v[1])))
    w.write("\n")

    w.write("## 채널별 노출스텝\n\n")
    keys = sorted(set().union(*[set(s["chan"]) for s in stages]))
    w.write("| 채널 | stage3 | stage4 | stage5 | vs s4 |\n|---|---|---|---|---|\n")
    for k in keys:
        v = [s["chan"].get(k, 0.0) for s in stages]
        w.write("| %s | %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(v[0]), "{:,.0f}".format(v[1]),
                   "{:,.0f}".format(v[2]), pct(v[2], v[1])))
    w.write("\n")

    w.write("## 실행 시간\n\n| 단계 | 초 |\n|---|---|\n")
    for s in stages:
        w.write("| %s | %.1f |\n" % (s["label"], s["secs"]))
    w.write("\n")

    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())
    print("저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
