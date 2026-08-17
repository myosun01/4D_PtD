# -*- coding: utf-8 -*-
"""Phase 2 — 가설물 파생 계층 (v3.3).

## 왜 필요한가

현재 walkable 격자는 IFC 슬래브에서 나온다. 그런데 거푸집 설치·배근 단계에는
슬래브가 아직 존재하지 않는다. **작업자가 존재하지 않는 바닥 위를 걷고 있다.**

또 KE_T_HS_04(작업발판 일체형 거푸집)·KE_K_FE_10(시스템비계·동바리)는 대체급
대안인데 가설물 형상이 없어 AgentParameterRule + 휴리스틱 계수로 들어가 있다.
"상위 등급은 계수가 아니라 창발로 산출된다"는 이 연구의 주장과 충돌한다.

## 범위 — 발자국·보행면·시각 표현만

가설물을 영구 부재와 공정에서 규칙 기반으로 자동 생성하는 것은 이 분야의 표준
접근이다 (Lee/Ham/Lee 2009 거푸집 레이아웃, Kim & Teizer 2014 BIM 비계 자동설계,
Kim/Cho/Zhang 2016 AiC 비계 배치·안전, Jin & Gambatese 2019 거푸집 Revit API,
Jongeling et al. 2008 AiC 작업순서-가설물 통합).

**단 여기서 가설물은 목적이 아니라 기반이다. 구조 설계(동바리 간격 계산, 거푸집
응력 검토)는 범위가 아니며 하지 않는다.**

## 파생 규칙 4종 — 전부 기존 IFC 부재와 이미 계산된 zone 에서 나온다

  TS1 formwork_deck  슬래브 풋프린트를 슬래브 두께만큼 하향 오프셋한 면.
                     타설 전 단계의 walkable 면.
  TS2 shoring        H008_ShoringCollapse zone 셀에 격자 간격으로 배치한 수직 부재.
                     하부층 보행 장애물.
  TS3 scaffold       슬래브 외곽선을 바깥으로 오프셋한 밴드. 외부 작업 동선.
  TS4 platform       H007_SlabEdge 단부를 따른 밴드. **대안 적용 대상이라 BASE 에는 없다.**

실행: python scripts/temp_structures.py
산출: build/temp_structures.json, build/temp_structures_log.md
"""
import collections
import csv
import io
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

SITE = "project/site.json"
SCHEDULE = "project/schedule.json"
CSV_SCHED = "build/construction_schedule_v2.csv"
ZONES = "build/hazard_zones.json"
MANIFEST = "unity_bundle/manifest.json"
OUT = "build/temp_structures.json"
LOG = "build/temp_structures_log.md"

# ══════════════════════════════════════════════════════════
# 파라미터 — 전부 근거 없음. 문헌값이 아니다. 민감도 대상.
# ══════════════════════════════════════════════════════════
PARAMS = {
    "shoring_spacing_m": 2.0,
    "scaffold_band_m": 1.5,
    "deck_offset_source": "슬래브 bbox z 범위의 층별 중앙값 (IFC 파생)",
}
PARAMS_NOTE = (
    "shoring_spacing_m 과 scaffold_band_m 은 **근거 없는 임의값**이며 문헌값이 "
    "아니다. 통행·시각 목적의 배치 파라미터일 뿐 구조 계산의 산물이 아니다. "
    "전부 민감도 분석 대상이다. deck_offset 만 IFC 슬래브 두께에서 유도된 값이다."
)

WALKABLE, WALL, FLOOR_OPENING = 0, 1, 2


def cell_of(gf, x, y):
    ox, oy = gf["origin_xy_m"]
    res = float(gf["resolution_m"])
    return int(math.floor((y - oy) / res)), int(math.floor((x - ox) / res))


def bbox_cells(gf, bb):
    r0, c0 = cell_of(gf, bb["min"][0], bb["min"][1])
    r1, c1 = cell_of(gf, bb["max"][0], bb["max"][1])
    return {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}


def main():
    site = json.load(open(SITE, encoding="utf-8"))
    gf = site["gridFrame"]
    levels = {l["levelID"]: l for l in site["levels"]}
    storey_to_level = {l["sourceIfcStorey"]: l["levelID"] for l in site["levels"]}
    grids = {l["levelID"]: np.array(l["grid"]["cells"]) for l in site["levels"]}
    R, Co = next(iter(grids.values())).shape

    acts = {a["activityID"]: a for a in
            json.load(open(SCHEDULE, encoding="utf-8"))["activities"]}
    rows = list(csv.DictReader(open(CSV_SCHED, encoding="utf-8-sig")))
    by_task = {r["task_id"]: r for r in rows}
    zdoc = json.load(open(ZONES, encoding="utf-8"))
    zones = zdoc["zones"]
    mf = json.load(open(MANIFEST, encoding="utf-8"))

    # 층별 슬래브 (직접 포함, bbox 있음)
    slabs = collections.defaultdict(list)
    guid_exists = set()
    for x in mf:
        guid_exists.add(x["element_key"]["ifc_guid"])
        if (x["ifc_class"] == "IfcSlab" and x.get("bbox_ifc_m")
                and x["storey"] and x["storey"]["levelID"]):
            slabs[x["storey"]["levelID"]].append(x)

    # 층별 슬래브 두께 중앙값 (IFC bbox z 범위 — 유도값)
    thickness = {}
    for lv, xs in slabs.items():
        t = sorted(b["bbox_ifc_m"]["max"][2] - b["bbox_ifc_m"]["min"][2] for b in xs)
        thickness[lv] = t[len(t) // 2]

    # 태스크 인덱스
    def find_task(pred):
        return [r for r in rows if pred(r)]

    deck_spawn = {}      # levelID → task_id (슬래브 거푸집+동바리)
    for r in rows:
        if r["origin"] == "original" and "슬래브 거푸집" in r["task_name"]:
            lv = storey_to_level.get(r["level"])
            if lv:
                deck_spawn[lv] = r["task_id"]
    deck_despawn = {}    # levelID → task_id (해체)
    for r in rows:
        if r["origin"] == "augment:strip":
            lv = storey_to_level.get(r["level"])
            if lv:
                deck_despawn[lv] = r["task_id"]
    frame_start = {}     # levelID → 첫 골조 태스크
    for r in rows:
        if r["origin"] != "original":
            continue
        lv = storey_to_level.get(r["level"])
        if lv and (lv not in frame_start or int(r["task_id"]) < int(frame_start[lv])):
            frame_start[lv] = r["task_id"]
    envelope_end = {}    # levelID → 마지막 외피(창문 설치) 태스크
    for r in rows:
        if "창문 설치" not in r["task_name"]:
            continue
        lv = storey_to_level.get(r["level"])
        if lv and (lv not in envelope_end or int(r["task_id"]) > int(envelope_end[lv])):
            envelope_end[lv] = r["task_id"]

    def day_of(task_id, which):
        a = acts.get("T-%s" % task_id)
        if a is None:
            return None
        from schedule import Schedule
        return None    # 아래에서 Schedule 로 일괄 계산

    from schedule import Schedule
    sch = Schedule.load(SCHEDULE)

    def es_of(t):
        a = sch.activities.get("T-%s" % t)
        return int(a.es) if a else None

    def ef_of(t):
        a = sch.activities.get("T-%s" % t)
        return int(a.ef) if a else None

    ts = []
    skipped = []

    # ── TS1. 거푸집 데크 ────────────────────────────────────
    for lv in sorted(slabs):
        sp, dp = deck_spawn.get(lv), deck_despawn.get(lv)
        if not sp or not dp:
            skipped.append(("TS1", lv, "spawn/despawn 태스크 없음 (거푸집=%s, 해체=%s)"
                            % (sp, dp)))
            continue
        grid = grids[lv]
        cells = set()
        guids = []
        for x in slabs[lv]:
            guids.append(x["element_key"]["ifc_guid"])
            for (r, c) in bbox_cells(gf, x["bbox_ifc_m"]):
                if 0 <= r < R and 0 <= c < Co and grid[r, c] != WALL:
                    cells.add((r, c))
        if not cells:
            skipped.append(("TS1", lv, "슬래브 bbox 가 격자와 겹치지 않음"))
            continue
        ts.append({
            "ts_id": "TS_%s_DECK_001" % lv,
            "ts_type": "formwork_deck",
            "derived_from": sorted(guids),
            "level": lv,
            "cells": sorted([int(r), int(c)] for r, c in cells),
            "walkable": True,
            "z_offset_mm": int(round(-thickness.get(lv, 0.0) * 1000)),
            "spawn": {"trigger": "task_start", "task_id": int(sp),
                      "activity_id": "T-%s" % sp, "day": es_of(sp)},
            "despawn": {"trigger": "task_complete", "task_id": int(dp),
                        "activity_id": "T-%s" % dp, "day": ef_of(dp)},
            "variant": "BASE",
            "note": ("슬래브 풋프린트를 슬래브 두께(%.3f m, IFC bbox z 중앙값)만큼 "
                     "하향 오프셋한 면. 타설 전 단계의 walkable 면이다."
                     % thickness.get(lv, 0.0)),
        })

    # ── TS2. 동바리 ────────────────────────────────────────
    spacing = int(round(PARAMS["shoring_spacing_m"] / float(gf["resolution_m"])))
    spacing = max(1, spacing)
    for z in zones:
        if not z["hazard_type"].startswith("H008"):
            continue
        lv = z["level"]
        zcells = {(int(r), int(c)) for r, c in z.get("cells", [])}
        if not zcells:
            skipped.append(("TS2", z["zone_id"], "zone 셀 없음"))
            continue
        # 격자 간격 배치 — zone 셀 안에서만 (구조 계산 아님).
        # 동바리는 바닥 위에 선다 — 그 층 정적 격자가 WALL·개구부인 셀은 제외한다.
        # (H008 zone 은 상부 슬래브를 하부 슬래브에 투영해 만든 것이라, 하부층
        #  격자에서 바닥이 없는 셀이 섞인다. 제외 수를 아래 로그에 남긴다.)
        g_lv = grids[lv]
        raw = [(r, c) for (r, c) in zcells if r % spacing == 0 and c % spacing == 0]
        posts_rc = [(r, c) for (r, c) in raw
                    if 0 <= r < R and 0 <= c < Co
                    and g_lv[r, c] not in (WALL, FLOOR_OPENING)]
        n_dropped = len(raw) - len(posts_rc)
        posts = sorted([r, c] for (r, c) in posts_rc)
        ts.append({
            "ts_id": "TS_%s_SHORE_%s" % (lv, z["zone_id"].split("_")[-1]),
            "ts_type": "shoring",
            "derived_from": list(z.get("derived_from", [])),
            "level": lv,
            "cells": posts,
            "walkable": False,
            "z_offset_mm": 0,
            "spawn": dict(z.get("spawn") or {}),
            "despawn": dict(z.get("despawn") or {}),
            "variant": "BASE",
            "source_zone": z["zone_id"],
            "dropped_no_floor": n_dropped,
            "note": ("H008 zone 셀에 %d 셀(=%.1f m) 간격으로 배치. **구조 계산이 "
                     "아니다** — 통행·시각 목적의 배치 파라미터이며 근거 없음. "
                     "바닥이 없는 셀(WALL·개구부) %d개는 기둥을 세울 수 없어 제외."
                     % (spacing, PARAMS["shoring_spacing_m"], n_dropped)),
        })

    # ── TS3. 비계 (외부) ───────────────────────────────────
    band = max(1, int(round(PARAMS["scaffold_band_m"] / float(gf["resolution_m"]))))
    for lv in sorted(slabs):
        sp = frame_start.get(lv)
        dp = envelope_end.get(lv)
        if not sp:
            skipped.append(("TS3", lv, "골조 착수 태스크 없음"))
            continue
        if not dp:
            skipped.append(("TS3", lv,
                            "외피(커튼월/창문 설치) 태스크가 이 층에 없어 despawn "
                            "원천이 없다 — 억지로 만들지 않고 건너뛴다"))
            continue
        grid = grids[lv]
        foot = set()
        guids = []
        for x in slabs[lv]:
            guids.append(x["element_key"]["ifc_guid"])
            foot |= bbox_cells(gf, x["bbox_ifc_m"])
        foot = {(r, c) for (r, c) in foot if 0 <= r < R and 0 <= c < Co}
        if not foot:
            skipped.append(("TS3", lv, "슬래브 발자국이 격자 밖"))
            continue
        # 발자국을 band 만큼 팽창시킨 뒤 원 발자국을 빼서 바깥 밴드만 남긴다
        grown = set()
        for (r, c) in foot:
            for dr in range(-band, band + 1):
                for dc in range(-band, band + 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < R and 0 <= cc < Co:
                        grown.add((rr, cc))
        bandcells = sorted([r, c] for (r, c) in (grown - foot))
        if not bandcells:
            skipped.append(("TS3", lv, "밴드 셀 0"))
            continue
        ts.append({
            "ts_id": "TS_%s_SCAF_001" % lv,
            "ts_type": "scaffold",
            "derived_from": sorted(guids),
            "level": lv,
            "cells": bandcells,
            "walkable": True,
            "z_offset_mm": 0,
            "spawn": {"trigger": "task_start", "task_id": int(sp),
                      "activity_id": "T-%s" % sp, "day": es_of(sp)},
            "despawn": {"trigger": "task_complete", "task_id": int(dp),
                        "activity_id": "T-%s" % dp, "day": ef_of(dp)},
            "variant": "BASE",
            "note": ("슬래브 외곽선을 %d 셀(=%.1f m) 바깥으로 오프셋한 밴드. "
                     "폭은 **근거 없는 파라미터**. despawn 은 이 층 마지막 창문 설치 "
                     "완료 — 이 IFC 에 커튼월 설치 태스크가 없어 외피 완료의 대리로 쓴다."
                     % (band, PARAMS["scaffold_band_m"])),
        })

    # ── TS4. 작업발판·안전난간 (BASE 에는 없음) ─────────────
    n_edge = sum(1 for z in zones if z["hazard_type"].startswith("H007"))
    skipped.append(("TS4", "-",
                    "BASE 에는 없다. H007 단부 zone %d 개가 파생 원천이며, "
                    "KE_H001_05(개구부 난간) 등 대안이 적용될 때 형상이 추가된다."
                    % n_edge))

    doc = {
        "meta": {
            "generatedBy": "scripts/temp_structures.py",
            "purpose": ("가설물은 목적이 아니라 기반이다 — 발자국·보행면·시각 표현만. "
                        "구조 설계(동바리 간격 계산·거푸집 응력 검토)는 범위가 아니다."),
            "gridFrame": gf,
            "params": PARAMS,
            "params_note": PARAMS_NOTE,
            "slab_thickness_m_by_level": {k: round(v, 3) for k, v in
                                          sorted(thickness.items())},
            "counts": dict(collections.Counter(t["ts_type"] for t in ts)),
            "total": len(ts),
        },
        "temp_structures": ts,
    }
    with io.open(OUT, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False)

    # ── 자기 검증 ──────────────────────────────────────────
    checks = []

    bad = [t["ts_id"] for t in ts
           if (t["spawn"].get("day") is not None and t["despawn"].get("day") is not None
               and not (t["spawn"]["day"] < t["despawn"]["day"]))]
    checks.append(("spawn < despawn", not bad, "위반 %d건 %s" % (len(bad), bad[:5])))

    missing = sorted({g for t in ts for g in t["derived_from"]} - guid_exists)
    checks.append(("derived_from GUID 가 IFC 에 실재", not missing,
                   "부재 %d건 %s" % (len(missing), missing[:5])))

    # TS1 데크 셀 수 vs 슬래브 면적 (같은 자릿수)
    order_bad = []
    for t in ts:
        if t["ts_type"] != "formwork_deck":
            continue
        area = sum((b["bbox_ifc_m"]["max"][0] - b["bbox_ifc_m"]["min"][0]) *
                   (b["bbox_ifc_m"]["max"][1] - b["bbox_ifc_m"]["min"][1])
                   for b in slabs[t["level"]])
        n = len(t["cells"])
        if area <= 0 or not (0.1 <= n / area <= 10.0):
            order_bad.append((t["ts_id"], n, round(area, 1)))
    checks.append(("TS1 데크 셀 수가 슬래브 면적과 같은 자릿수", not order_bad,
                   "이탈 %d건 %s" % (len(order_bad), order_bad[:5])))

    zone_cells = {}
    for z in zones:
        if z["hazard_type"].startswith("H008"):
            zone_cells[z["zone_id"]] = {(int(r), int(c)) for r, c in z.get("cells", [])}
    out_of_zone = []
    for t in ts:
        if t["ts_type"] != "shoring":
            continue
        zc = zone_cells.get(t.get("source_zone"), set())
        n_out = sum(1 for r, c in t["cells"] if (r, c) not in zc)
        if n_out:
            out_of_zone.append((t["ts_id"], n_out))
    checks.append(("TS2 동바리가 H008 zone 안에만 존재", not out_of_zone,
                   "이탈 %d건 %s" % (len(out_of_zone), out_of_zone[:5])))

    # 층 바닥면적 비교는 **건물 안에 있는 TS** 에만 성립한다.
    # 비계(TS3)는 정의상 슬래브 발자국 바깥에 서므로 이 검사의 대상이 아니다 —
    # 대신 아래에서 '발자국 밖에만 있는가'를 따로 검사한다.
    INSIDE_TYPES = ("formwork_deck", "shoring", "platform")
    over = []
    for lv, g in grids.items():
        floor = int((g != WALL).sum())
        used = set()
        for t in ts:
            if t["level"] == lv and t["ts_type"] in INSIDE_TYPES:
                used |= {(r, c) for r, c in t["cells"]}
        if floor and len(used) > floor:
            over.append((lv, len(used), floor))
    checks.append(("층별 실내 TS 총면적 ≤ 층 바닥면적 (비계 제외)", not over,
                   "초과 %d건 %s" % (len(over), over[:5])))

    # TS3 는 슬래브 발자국 밖에만 있어야 한다 (밴드 정의)
    inside_band = []
    for t in ts:
        if t["ts_type"] != "scaffold":
            continue
        foot = set()
        for x in slabs[t["level"]]:
            foot |= bbox_cells(gf, x["bbox_ifc_m"])
        n_in = sum(1 for r, c in t["cells"] if (r, c) in foot)
        if n_in:
            inside_band.append((t["ts_id"], n_in))
    checks.append(("TS3 비계 밴드가 슬래브 발자국 밖에만 존재", not inside_band,
                   "발자국 안 %d건 %s" % (len(inside_band), inside_band[:5])))

    ok = all(c[1] for c in checks)

    w = io.StringIO()
    w.write("# 가설물 파생 계층 (v3.3 Phase 2)\n\n")
    w.write("산출 `%s` — 총 %d개.\n\n" % (OUT, len(ts)))
    w.write("| 유형 | 개수 |\n|---|---|\n")
    for k, v in sorted(doc["meta"]["counts"].items()):
        w.write("| `%s` | %d |\n" % (k, v))
    w.write("\n")

    w.write("## 파라미터 — 근거 없음\n\n")
    w.write("| 파라미터 | 값 |\n|---|---|\n")
    for k, v in PARAMS.items():
        w.write("| `%s` | %s |\n" % (k, v))
    w.write("\n> %s\n\n" % PARAMS_NOTE)
    w.write("층별 슬래브 두께(IFC bbox z 중앙값, m): %s\n\n"
            % json.dumps(doc["meta"]["slab_thickness_m_by_level"], ensure_ascii=False))

    w.write("## 파생 결과\n\n")
    w.write("| ts_id | 유형 | 층 | 셀 | walkable | z오프셋 | spawn일 | despawn일 |\n")
    w.write("|---|---|---|---|---|---|---|---|\n")
    for t in sorted(ts, key=lambda x: (x["level"], x["ts_type"])):
        w.write("| `%s` | %s | %s | %d | %s | %d mm | %s | %s |\n"
                % (t["ts_id"], t["ts_type"], t["level"], len(t["cells"]),
                   "예" if t["walkable"] else "아니오", t["z_offset_mm"],
                   t["spawn"].get("day"), t["despawn"].get("day")))
    w.write("\n")

    drop = [(t["ts_id"], t.get("dropped_no_floor", 0)) for t in ts
            if t["ts_type"] == "shoring"]
    w.write("## TS2 동바리 — 바닥 없어 제외한 기둥\n\n")
    w.write("H008 zone 은 상부 슬래브를 하부 슬래브에 투영해 만든 것이라, 하부층 "
            "정적 격자에서 바닥이 없는(WALL·개구부) 셀이 섞인다. 기둥은 바닥 위에 "
            "서므로 그 셀은 제외했다.\n\n| ts_id | 제외 기둥 수 |\n|---|---|\n")
    for a, b in drop:
        w.write("| `%s` | %d |\n" % (a, b))
    w.write("\n")

    w.write("## 만들지 않은 것과 사유\n\n| 규칙 | 대상 | 사유 |\n|---|---|---|\n")
    for x in skipped:
        w.write("| %s | %s | %s |\n" % x)
    w.write("\n")

    w.write("## 자기 검증\n\n| 항목 | 결과 | 비고 |\n|---|---|---|\n")
    for name, good, note in checks:
        w.write("| %s | %s | %s |\n" % (name, "OK" if good else "**FAIL**", note))
    w.write("\n%s\n" % ("전항목 통과." if ok else "**실패 항목이 있다.**"))

    with io.open(LOG, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())

    print("저장: %s (%d개: %s)" % (OUT, len(ts), dict(doc["meta"]["counts"])))
    print("저장: %s" % LOG)
    for name, good, note in checks:
        print("  [%s] %s — %s" % ("OK" if good else "FAIL", name, note))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
