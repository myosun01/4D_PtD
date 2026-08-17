# -*- coding: utf-8 -*-
"""v3.4 D절 — H001 신호에 대한 민감도 스윕 (진단 전용).

**파일을 일절 수정하지 않는다.** config 값은 프로세스 메모리에서만 바꾸고
각 조건이 끝나면 즉시 되돌린다. `opening_buffer_m` 은 zone 재생성이 필요해
파일을 건드리게 되므로, 대신 **버퍼 의미론 반사실 실험**을 메모리에서 수행한다
(H001 zone 을 구멍이 아니라 통행 가능한 위험대로 취급했을 때 무엇이 되는가).

이 스윕의 목적은 "어떤 값이 옳은가"를 정하는 것이 아니다. 민감도의 방향과
크기를 보는 것뿐이다. **이 결과로 값을 정하지 말 것.**

실행: python scripts/sweep_h001.py [--days N] [--max-steps N]
"""
import argparse
import collections
import copy
import io
import json
import sys

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import fourd_workers as FW
import movement

HAZ = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")


def haz_exposure(res, life):
    """위험유형별 노출. H001 은 zone 셀이 구멍이라 노출이 '인접 링'에 생기므로
    fourd.instance_exposure_cells 의 정의(H001=4방 이웃)를 그대로 쓴다."""
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res["exposure_steps"].items():
        idx[(lv, ch, int(r), int(c))] += v
    out = collections.Counter()
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        cells = fourd.instance_exposure_cells(h)
        out[h.hazard_type] += sum(idx.get((h.level, ch, r, c), 0.0)
                                  for (r, c) in cells)
    return out


def zone_cell_exposure(res, life):
    """비교용 — zone 셀에 직접 귀속한 값 (지금까지 보고에 쓰던 방식)."""
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res["exposure_steps"].items():
        idx[(lv, ch, int(r), int(c))] += v
    out = collections.Counter()
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        out[h.hazard_type] += sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                                  for (r, c) in h.cells)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--seed", default="v3.1-workers")
    a = ap.parse_args()

    sch, site, life, cfg, wl = FW.load_project_v2()
    ts = fourd.load_temp_structures()

    def go(label):
        movement._CTX.clear()          # 격자 컨텍스트 캐시는 비용식을 굽는다 — 초기화
        fourd._TS_CACHE["path"] = None
        r = FW.run_project_workers(sch, site, life, cfg, wl, days=a.days,
                                   mc_runs=1, seed=a.seed, max_steps=a.max_steps,
                                   temp_structures=fourd.load_temp_structures())
        h = haz_exposure(r, life)
        z = zone_cell_exposure(r, life)
        print("  %-34s H001(링)=%7.0f  H001(zone셀)=%6.0f  총=%9.0f"
              % (label, h["H001"], z["H001"], sum(r["exposure_steps"].values())))
        return label, h, z, sum(r["exposure_steps"].values())

    results = []

    # ── 기준 ──
    results.append(go("baseline (현재값)"))

    # ── D-1. OPEN_EDGE_PEN ──
    orig_pen = C.OPEN_EDGE_PEN
    for f in (0.5, 0.25, 0.0):
        C.OPEN_EDGE_PEN = orig_pen * f
        results.append(go("OPEN_EDGE_PEN ×%.2f (=%.2f)" % (f, C.OPEN_EDGE_PEN)))
    C.OPEN_EDGE_PEN = orig_pen
    assert C.OPEN_EDGE_PEN == orig_pen

    # ── D-2. HAZARD_WEIGHT ──
    orig_hw = copy.deepcopy(C.HAZARD_WEIGHT)
    for f in (0.5, 0.0):
        C.HAZARD_WEIGHT = {k: v * f for k, v in orig_hw.items()}
        results.append(go("HAZARD_WEIGHT ×%.1f" % f))
    C.HAZARD_WEIGHT = orig_hw
    assert C.HAZARD_WEIGHT == orig_hw

    # ── D-3. 버퍼 의미론 반사실 ──
    # H001 zone 을 '구멍'이 아니라 '통행 가능한 위험대'(H007 과 같은 취급)로 두면?
    # opening_buffer_m 을 바꿔 zone 을 재생성하는 것과 방향이 같은 실험이며,
    # 파일을 건드리지 않는다. **수정안이 아니라 가설 검정이다.**
    orig_build = fourd.build_level_day

    def build_edge_like(site_, level_id, hazards, effects, day, temp_structures=None):
        # H001 인스턴스를 H007 로 위장해 EDGE 오버레이를 타게 한다.
        class _Fake:
            __slots__ = ("instance_id", "hazard_type", "template_id", "level",
                         "cells", "spawn_day", "despawn_day", "bound_activity",
                         "despawn_activity")
        patched = []
        for h in hazards:
            if h.hazard_type == "H001":
                f = _Fake()
                f.instance_id = h.instance_id
                f.hazard_type = "H007"
                f.template_id = h.template_id
                f.level = h.level
                f.cells = h.cells
                f.spawn_day = h.spawn_day
                f.despawn_day = h.despawn_day
                f.bound_activity = h.bound_activity
                f.despawn_activity = h.despawn_activity
                patched.append(f)
            else:
                patched.append(h)
        return orig_build(site_, level_id, patched, effects, day,
                          temp_structures=temp_structures)

    fourd.build_level_day = build_edge_like
    lbl, h_cf, z_cf, tot_cf = go("[반사실] H001 zone 을 통행가능 위험대로")
    results.append((lbl, h_cf, z_cf, tot_cf))
    fourd.build_level_day = orig_build
    assert fourd.build_level_day is orig_build

    # ── 표 ──
    print("")
    print("| 조건 | H001(링) | vs base | H001(zone셀) | H002 | H004 | H007 | 총 노출 |")
    print("|---|---|---|---|---|---|---|---|")
    base = results[0][1]["H001"]
    for lbl, h, z, tot in results:
        print("| %s | %.0f | %s | %.0f | %.0f | %.0f | %.0f | %.0f |"
              % (lbl, h["H001"],
                 ("%+.1f%%" % (100.0 * (h["H001"] - base) / base)) if base else "—",
                 z["H001"], h["H002"], h["H004"], h["H007"], tot))
    print("")
    print("복원 확인: OPEN_EDGE_PEN=%.2f (원래 %.2f), HAZARD_WEIGHT=%s (원래 %s), "
          "build_level_day 원복=%s"
          % (C.OPEN_EDGE_PEN, orig_pen, C.HAZARD_WEIGHT, orig_hw,
             fourd.build_level_day is orig_build))
    return 0


if __name__ == "__main__":
    sys.exit(main())
