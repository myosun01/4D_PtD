# -*- coding: utf-8 -*-
"""Part C — Unity 로 넘길 데이터를 완성한다 (씬 작업은 이 머신에서 불가).

  C-1 타임라인 재생성   현행 공정표(project/schedule.json) 기준
  C-2 위험구역 익스포트 build/hazard_zones.json 84 zone, 7유형 전부
  C-3 워커 궤적 익스포트 output/worker_trajectory.csv → 프레임 단위 조회 구조
  C-4 라이브러리 메타   variant 별 적용 대안 (현재 BASE 만, 확장 가능한 구조)

## 좌표 계약 (기존 계약 그대로 — tests/test_unity_bundle.py 가 강제한다)

  IFC 원본 mm → m (bundle_meta.unitScaleToMeter = 0.001, ifcopenshell 이 적용)
  격자 → 월드 : world_xy = gridFrame.origin + (index + 0.5) * resolution
                row=+Y, col=+X, z = level.elevation_m
  월드 → glTF : (x, y, z)_ifc → (x, z, -y)_gltf, up = +Y
  센터링 금지 : 원점을 옮기지 않는다 (site.json gridFrame 정합이 깨진다)

실행: python scripts/export_unity_bundle.py [--bundle unity_bundle]
"""
import argparse
import io
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import ptd_ttl
from controls import CELLTYPE_TO_HAZARD
from lifecycle import LifecycleEngine
from schedule import Schedule
from ptd_ttl import TemporalRule

SCHEMA_VERSION = "1.0"
SITE = "project/site.json"
SCHEDULE = "project/schedule.json"
ZONES = "build/hazard_zones.json"
BINDINGS = "build/lifecycle_bindings_v2.json"
TRAJECTORY = "output/worker_trajectory.csv"
TEMP_STRUCTURES = "build/temp_structures.json"
LOG = "build/export_unity_bundle_log.md"

COORD_CONTRACT = {
    "sourceUnits": "IFC mm → m (unitScaleToMeter 0.001, ifcopenshell 적용)",
    "worldCRS": "IFC world coordinates, meters, Z-up",
    "gltfAxisTransform": "(x,y,z)_ifc -> (x,z,-y)_gltf",
    "gltf_up": "+Y",
    "cellCenter": "world_xy = gridFrame.origin + (index + 0.5) * resolution",
    "axisMapping": {"row": "+Y", "col": "+X"},
    "centering": "none — 모델 원점 이동 금지",
}


def to_gltf(x, y, z):
    """IFC 월드(m, Z-up) → glTF(+Y-up). 기존 build_unity_bundle.py 와 같은 변환."""
    return [round(x, 4), round(z, 4), round(-y, 4)]


class Frame:
    def __init__(self, grid_frame):
        self.ox, self.oy = grid_frame["origin_xy_m"]
        self.res = float(grid_frame["resolution_m"])

    def cell_world(self, r, c):
        return self.ox + (c + 0.5) * self.res, self.oy + (r + 0.5) * self.res

    def cell_gltf(self, r, c, z):
        x, y = self.cell_world(r, c)
        return to_gltf(x, y, z)


# ══════════════════════════════════════════════════════════
# C-1 타임라인
# ══════════════════════════════════════════════════════════
def regen_timeline(bundle, w):
    out = os.path.join(bundle, "timeline.json")
    before = None
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fp:
            t = json.load(fp)
        before = (t.get("projectDays"), len(t.get("activities", [])))
    rc = subprocess.call([sys.executable, "export_timeline.py",
                          "--schedule", SCHEDULE, "--site", SITE,
                          "--manifest", os.path.join(bundle, "manifest.json"),
                          "--out", out],
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    with open(out, encoding="utf-8") as fp:
        t = json.load(fp)
    after = (t.get("projectDays"), len(t.get("activities", [])))
    w("## C-1 타임라인 재생성\n\n")
    w("| | 공기(일) | 액티비티 |\n|---|---|---|\n")
    if before:
        w("| 이전(번들에 있던 것) | %s | %s |\n" % before)
    w("| 재생성 | %s | %s |\n\n" % after)
    w("`export_timeline.py` 종료코드 %d. hazardSpans %d건.\n\n"
      % (rc, len(t.get("hazardSpans", []))))
    return after, rc


# ══════════════════════════════════════════════════════════
# C-2 위험구역
# ══════════════════════════════════════════════════════════
def export_zones(bundle, site, frame, w):
    with open(ZONES, encoding="utf-8") as fp:
        src = json.load(fp)
    zones = src["zones"]
    elev = {lv["levelID"]: lv["elevation_m"] for lv in site["levels"]}

    # 생멸 '일 인덱스'는 엔진(LifecycleEngine)이 정본이다 — 날짜 문자열을 재해석하지 않는다.
    sch = Schedule.load(SCHEDULE)
    lib = ptd_ttl.require_library()
    life = LifecycleEngine(lib.lifecycle_templates, BINDINGS, sch)
    with open(BINDINGS, encoding="utf-8") as fp:
        binds = json.load(fp)["bindings"]
    # 바인딩 순서 == LifecycleEngine.instances 순서 (lifecycle._build 가 enumerate)
    day_by_zone = {}
    for b, inst in zip(binds, life.instances):
        zid = b.get("_zone_id")
        if zid:
            dd = inst.despawn_day
            day_by_zone[zid] = (int(inst.spawn_day),
                                None if dd == float("inf") else int(dd))

    def rings(geom):
        """polygon → [ring], multipolygon → 모든 ring. 좌표는 [x,y] IFC 월드 m."""
        t = geom.get("type")
        if t == "polygon":
            return geom.get("coords") or []
        if t == "multipolygon":
            out = []
            for poly in geom.get("coords") or []:
                out.extend(poly)
            return out
        return []

    def split_rings(geom):
        """[v3.5 D-3] H001 폴리곤은 도넛이다 — 바깥 링 = 버퍼 경계, 안쪽 링 = 개구부 본체.
        (검증: 안쪽 링 면적 합 / raw_area_m2 중앙값 = 1.000)
        Unity 가 본체(구멍)와 버퍼(위험대)를 다르게 렌더링할 수 있도록 나눠 싣는다."""
        t = geom.get("type")
        polys = ([geom.get("coords") or []] if t == "polygon"
                 else [p for p in (geom.get("coords") or []) if p])
        outer = [p[0] for p in polys if p]
        inner = [r for p in polys for r in p[1:]]
        return outer, inner

    out_zones = []
    missing_day = []
    n_body = 0
    for z in zones:
        lv = z["level"]
        e = elev.get(lv, 0.0)
        zid = z["zone_id"]
        sp, dp = day_by_zone.get(zid, (None, None))
        if sp is None:
            missing_day.append(zid)
        is_open = z["hazard_type"].startswith("H001")
        outer_rings, inner_rings = (split_rings(z.get("geometry") or {})
                                    if is_open else ([], []))
        if inner_rings:
            n_body += 1
        out_zones.append({
            "zone_id": zid,
            "hazard_type": z["hazard_type"],
            "hazard_code": z["hazard_type"].split("_")[0],
            "exposure_channel": z["channel"],
            "lambda_channel": fourd.HAZARD_CHANNEL_4D.get(
                z["hazard_type"].split("_")[0]),
            "level": lv,
            "storey": z.get("storey"),
            "elevation_m": e,
            "spawnDay": sp,
            "despawnDay": dp,
            "spawnActivity": (z.get("spawn") or {}).get("activity_id"),
            "despawnActivity": (z.get("despawn") or {}).get("activity_id"),
            "variant": z.get("variant", "BASE"),
            "raw_area_m2": z.get("raw_area_m2"),
            "cells": [[int(r), int(c)] for r, c in z.get("cells", [])],
            "cellCenters_gltf": [frame.cell_gltf(int(r), int(c), e)
                                 for r, c in z.get("cells", [])],
            "outline_gltf": [[to_gltf(pt[0], pt[1], e) for pt in ring]
                             for ring in rings(z.get("geometry") or {})],
            # v3.5 D-3: 개구부는 본체(구멍)와 버퍼(통행 가능 위험대)를 나눠 싣는다
            "geometry_role": ("opening_buffer_band" if is_open else "zone"),
            "walkable": (True if is_open else None),
            "buffer_outline_gltf": [[to_gltf(p[0], p[1], e) for p in r]
                                    for r in outer_rings],
            "opening_body_outline_gltf": [[to_gltf(p[0], p[1], e) for p in r]
                                          for r in inner_rings],
        })

    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "source": ZONES,
        "coordinateContract": COORD_CONTRACT,
        "gridFrame": site["gridFrame"],
        "counts": dict(Counter(z["hazard_type"] for z in out_zones)),
        "zones": out_zones,
    }
    path = os.path.join(bundle, "hazard_zones.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False)

    w("## C-2 위험구역 익스포트\n\n")
    w("`%s` — zone %d, 유형 %d종, %.1f MB\n\n"
      % (path.replace("\\", "/"), len(out_zones), len(doc["counts"]),
         os.path.getsize(path) / 1e6))
    w("| 위험유형 | zone | 노출채널 | λ채널 |\n|---|---|---|---|\n")
    ch_by = {}
    for z in out_zones:
        ch_by[z["hazard_type"]] = (z["exposure_channel"], z["lambda_channel"])
    for haz, n in sorted(doc["counts"].items()):
        w("| %s | %d | %s | %s |\n" % (haz, n, ch_by[haz][0], ch_by[haz][1] or "—"))
    w("\n생멸 일 인덱스는 `LifecycleEngine` 산출을 그대로 실었다 "
      "(날짜 문자열을 재해석하지 않는다). 일 인덱스를 얻지 못한 zone: %d건%s\n\n"
      % (len(missing_day), (" — " + ", ".join(missing_day)) if missing_day else ""))
    w("**개구부 본체/버퍼 구분 (v3.5 D-3)**: H001 zone 의 `cells`·`geometry` 는 "
      "개구부 **주변 버퍼**(통행 가능한 위험대)이고, 개구부 본체는 폴리곤의 안쪽 "
      "링이다. Unity 가 다르게 렌더링할 수 있도록 `buffer_outline_gltf`(위험대)와 "
      "`opening_body_outline_gltf`(구멍)를 나눠 실었다. 본체 링을 가진 zone %d / %d "
      "— 나머지는 개구부가 1셀 미만이거나 슬래브 경계에서 잘려 본체 링이 없다.\n\n"
      % (n_body, sum(1 for z in out_zones if z["hazard_code"] == "H001")))
    return doc


# ══════════════════════════════════════════════════════════
# C-3 워커 궤적
# ══════════════════════════════════════════════════════════
def export_trajectory(bundle, site, frame, w):
    w("## C-3 워커 궤적 익스포트\n\n")
    if not os.path.exists(TRAJECTORY):
        w("`%s` 없음 — `python scripts/run_4d_workers.py` 를 먼저 실행해야 한다. "
          "**궤적 미포함.**\n\n" % TRAJECTORY)
        return None
    import csv
    elev = {lv["levelID"]: lv["elevation_m"] for lv in site["levels"]}
    frames = defaultdict(lambda: defaultdict(list))     # day → step → [worker]
    states = Counter()
    n = 0
    with open(TRAJECTORY, encoding="utf-8") as fp:
        for row in csv.DictReader(fp):
            d, st = int(row["day"]), int(row["step"])
            lv = row["level"]
            e = elev.get(lv, 0.0)
            pos = frame.cell_gltf(int(row["row"]), int(row["col"]), e)
            frames[d][st].append({
                "worker_id": int(row["worker_id"]),
                "level": lv,
                "cell": [int(row["row"]), int(row["col"])],
                "pos_gltf": pos,
                "state": row["state"],            # Unity 애니메이션 상태 매핑용
                "activity_id": row["activity_id"],
                "trade": row["trade"],
            })
            states[row["state"]] += 1
            n += 1

    days = sorted(frames)
    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "source": TRAJECTORY,
        "coordinateContract": COORD_CONTRACT,
        "note": ("프레임 단위 조회: frames[day][step] → 워커 목록. "
                 "step 은 시뮬 스텝 인덱스이며 1스텝 = config.STEP_SECONDS 초. "
                 "샘플링 간격이 1보다 크면 step 이 듬성하다 — Unity 는 사이를 보간한다."),
        "stepSeconds": C.STEP_SECONDS,
        "rows": n,
        "days": days,
        "states": dict(states),
        "frames": {str(d): {str(s): frames[d][s] for s in sorted(frames[d])}
                   for d in days},
    }
    path = os.path.join(bundle, "worker_trajectory.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False)
    steps = sorted({s for d in days for s in frames[d]})
    w("`%s` — %s행, 일자 %d개, 스텝 %d종, %.1f MB\n\n"
      % (path.replace("\\", "/"), "{:,}".format(n), len(days), len(steps),
         os.path.getsize(path) / 1e6))
    w("state 분포: %s\n\n"
      % ", ".join("%s=%s" % (k, "{:,}".format(v)) for k, v in states.most_common()))
    return doc


# ══════════════════════════════════════════════════════════
# C-4 라이브러리 메타
# ══════════════════════════════════════════════════════════
def export_library(bundle, zones_doc, w):
    lib = ptd_ttl.require_library()
    zones_by_haz = defaultdict(list)
    for z in zones_doc["zones"]:
        zones_by_haz[z["hazard_code"]].append(z["zone_id"])

    alts = []
    for aid in sorted(lib.alternatives):
        a = lib.alternatives[aid]
        rule = lib.rule_of(aid)
        temporal = isinstance(rule, TemporalRule)
        ct = "" if temporal else getattr(rule, "applies_to_cell_type", "")
        haz = CELLTYPE_TO_HAZARD.get(ct)
        alts.append({
            "alternative_id": aid,
            "from_entry": a.from_entry,
            "hoc_level": a.hoc_level,
            "hoc_rank": a.hoc_rank,
            "rule_id": a.rule_id,
            "rule_type": type(rule).__name__ if rule else None,
            "install_cost_level": a.install_cost_level,
            "install_duration_days": a.install_duration_days,
            "applies_to_cell_type": ct or None,
            "hazard_code": haz,
            "applicable_zones": zones_by_haz.get(haz, []) if haz else [],
            "multipliers": (rule.multipliers()
                            if hasattr(rule, "multipliers") else {}),
            "schedule_shift": (rule.schedule_shift if temporal else None),
        })

    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "source": C.TTL_PATH.replace(os.getcwd() + os.sep, "").replace("\\", "/"),
        "hocOrder": [k for k, _ in sorted(lib.hoc_rank.items(),
                                          key=lambda kv: kv[1])],
        "alternatives": alts,
        # variant 확장 지점 — 지금은 BASE 뿐이고, 대안 적용 세계가 생기면
        # 같은 스키마로 항목만 늘리면 된다.
        "variants": [{
            "variant_id": "BASE",
            "label": "기준안 (대안 미적용)",
            "appliedAlternatives": [],
            "zoneCount": len(zones_doc["zones"]),
            "hazardZonesFile": "hazard_zones.json",
        }],
    }
    path = os.path.join(bundle, "ptd_library.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1)

    reach = [a for a in alts if a["applicable_zones"]]
    w("## C-4 라이브러리 메타 익스포트\n\n")
    w("`%s` — 대안 %d, variant %d (BASE), %.1f MB\n\n"
      % (path.replace("\\", "/"), len(alts), len(doc["variants"]),
         os.path.getsize(path) / 1e6))
    w("이 프로젝트의 zone 에 실제로 걸리는 대안 %d / %d.\n\n" % (len(reach), len(alts)))
    w("| HoC | 대안 수 |\n|---|---|\n")
    for hoc, n in sorted(Counter(a["hoc_level"] for a in alts).items(),
                         key=lambda kv: lib.hoc_rank.get(kv[0], 99)):
        w("| %s | %d |\n" % (hoc, n))
    w("\n")
    return doc


# ══════════════════════════════════════════════════════════
# C-6 가설물 (v3.3 Phase 4-3)
# ══════════════════════════════════════════════════════════
def export_temp_structures(bundle, site, frame, w):
    w("## C-6 가설물 익스포트\n\n")
    if not os.path.exists(TEMP_STRUCTURES):
        w("`%s` 없음 — `python scripts/temp_structures.py` 를 먼저 실행해야 한다. "
          "**가설물 미포함.**\n\n" % TEMP_STRUCTURES)
        return None
    with open(TEMP_STRUCTURES, encoding="utf-8") as fp:
        src = json.load(fp)
    elev = {lv["levelID"]: lv["elevation_m"] for lv in site["levels"]}

    out = []
    for t in src.get("temp_structures", []):
        lv = t["level"]
        # z 오프셋은 층 표고에 mm 단위로 더한다 (데크는 슬래브 두께만큼 아래)
        z = elev.get(lv, 0.0) + t.get("z_offset_mm", 0) / 1000.0
        out.append({
            "ts_id": t["ts_id"],
            "ts_type": t["ts_type"],
            "derived_from": t.get("derived_from", []),
            "level": lv,
            "elevation_m": round(z, 4),
            "walkable": t.get("walkable", False),
            "z_offset_mm": t.get("z_offset_mm", 0),
            "spawnDay": (t.get("spawn") or {}).get("day"),
            "despawnDay": (t.get("despawn") or {}).get("day"),
            "spawnActivity": (t.get("spawn") or {}).get("activity_id"),
            "despawnActivity": (t.get("despawn") or {}).get("activity_id"),
            "variant": t.get("variant", "BASE"),
            "cells": [[int(r), int(c)] for r, c in t.get("cells", [])],
            "cellCenters_gltf": [frame.cell_gltf(int(r), int(c), z)
                                 for r, c in t.get("cells", [])],
            "note": t.get("note", ""),
        })

    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "source": TEMP_STRUCTURES,
        "coordinateContract": COORD_CONTRACT,
        "purpose": src.get("meta", {}).get("purpose"),
        "params": src.get("meta", {}).get("params"),
        "params_note": src.get("meta", {}).get("params_note"),
        "counts": dict(Counter(t["ts_type"] for t in out)),
        "temp_structures": out,
    }
    path = os.path.join(bundle, "temp_structures.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False)

    w("`%s` — %d개, %.1f MB\n\n"
      % (path.replace("\\", "/"), len(out), os.path.getsize(path) / 1e6))
    w("| 유형 | 개수 | walkable | 셀 합 |\n|---|---|---|---|\n")
    for tt in sorted(doc["counts"]):
        sel = [t for t in out if t["ts_type"] == tt]
        w("| `%s` | %d | %s | %s |\n"
          % (tt, len(sel), "예" if sel[0]["walkable"] else "아니오",
             "{:,}".format(sum(len(t["cells"]) for t in sel))))
    w("\n> %s\n\n" % doc.get("params_note", ""))
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="unity_bundle")
    a = ap.parse_args()

    buf = io.StringIO()
    w = buf.write
    w("# Part C 로그 — Unity 번들 익스포터 확장\n\n")

    with open(SITE, encoding="utf-8") as fp:
        site = json.load(fp)
    frame = Frame(site["gridFrame"])

    tl, rc = regen_timeline(a.bundle, w)
    zones_doc = export_zones(a.bundle, site, frame, w)
    traj = export_trajectory(a.bundle, site, frame, w)
    export_library(a.bundle, zones_doc, w)
    tsd = export_temp_structures(a.bundle, site, frame, w)

    w("## 번들 파일 목록\n\n| 파일 | 크기 |\n|---|---|\n")
    for f in sorted(os.listdir(a.bundle)):
        p = os.path.join(a.bundle, f)
        if os.path.isfile(p):
            w("| `%s` | %.1f MB |\n" % (f, os.path.getsize(p) / 1e6))
    w("\n")

    with io.open(LOG, "w", encoding="utf-8") as fp:
        fp.write(buf.getvalue())

    print("저장: %s" % LOG)
    print("  timeline  : 공기 %s일 / 액티비티 %s" % tl)
    print("  hazard    : zone %d, 유형 %d종"
          % (len(zones_doc["zones"]), len(zones_doc["counts"])))
    print("  trajectory: %s"
          % ("%s행" % "{:,}".format(traj["rows"]) if traj else "없음"))
    print("  temp_str  : %s"
          % ("%d개 %s" % (len(tsd["temp_structures"]), tsd["counts"]) if tsd else "없음"))
    return 0 if (rc == 0 and traj is not None and tsd is not None) else 1


if __name__ == "__main__":
    sys.exit(main())
