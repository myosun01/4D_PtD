# -*- coding: utf-8 -*-
"""Part 2. 가설물·위험구역 파생기.

IFC 는 완성된 건물만 기술한다. 거푸집·동바리·작업발판과 그것들이 만드는 위험
공간은 IFC 에 없다. 영구 부재(IFC) + 보강 공정표에서 이를 파생한다.

## lifecycle.py 와의 인터페이스 (읽고 확인한 사실)

lifecycle.py 의 LifecycleEngine 은 **폴리곤을 받지 않는다.** 다음을 받는다:

    {"bindings": [{"template": "LCR_...", "boundActivity": "T-702",
                   "despawnActivity": "T-9003",
                   "spawnLocation": {"level": "L1", "cells": [[r,c], ...]}}]}

  · cells      = 그리드 (row, col) 정수쌍. project/site.json 의 69x93, 1.0m 격자.
  · level      = "L1".."L8" (int(level.lstrip("L")) 로 파싱하므로 이 형식 고정)
  · hazard_type / spawn·despawn 트리거는 TTL LifecycleRuleTemplate 에서 오고,
    바인딩은 '어느 액티비티·어느 셀'만 지정한다.
  · activity_id 는 "T-<task_id>" 형식 (project/schedule.json 실측).

따라서 지시서의 hazard_zones.json 스키마(polygon coords / z / height)는
lifecycle 이 소비할 수 없다. 두 표현을 **함께** 낸다:
  · zones[].geometry  — 폴리곤 (Unity·면적검증·추적성)
  · zones[].cells     — 그리드 셀 (lifecycle 소비용)
  · build/lifecycle_bindings_v2.json — lifecycle.py 가 그대로 읽는 형식

## 파라미터

opening_buffer_m / edge_band_m / drop_angle_deg / wall_proximity_m 는
**근거가 없는 값이다.** 문헌값이 아니며 전부 민감도 분석 대상이다.
하드코딩하지 않고 meta.params 로 노출한다.
"""
import argparse
import csv
import io
import json
import os
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import date, datetime

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

IFC_PATH = "ARK_NordicLCA_Office_Concrete_BuildingPermit_Revit.ifc"
SCHEDULE_V2 = "build/construction_schedule_v2.csv"
SITE_JSON = "project/site.json"
PRODUCTIVITY = "productivity_rates.json"
OUT_JSON = "build/hazard_zones.json"
OUT_BINDINGS = "build/lifecycle_bindings_v2.json"
OUT_LOG = "build/temp_works_log.md"

# IFC storey ↔ site.json level ↔ 공정표 level
STOREY_ORDER = ["Basement", "Level_01", "Level_02a_Parking", "Level_02",
                "Level_03", "Level_04", "Level_05", "Roof"]
STOREY_TO_SITE = {s: "L%d" % (i + 1) for i, s in enumerate(STOREY_ORDER)}

# 지시서에 주어진 층별 바닥면적 (자기검증용, m²)
FLOOR_AREA_REF = {"Level_01": 1015, "Level_02": 1201, "Level_03": 1185,
                  "Level_04": 1185, "Level_05": 597}
# 지시서에 주어진 개구부 층별 분포 (자기검증용)
OPENING_REF = {"Level_01": 6, "Level_02": 8, "Level_03": 9,
               "Level_04": 9, "Level_05": 3, "Roof": 4}


# ──────────────────────────────────────────────── 그리드
class Grid(object):
    """site.json gridFrame — world_xy = origin + (index + 0.5) * resolution."""

    def __init__(self, site_path):
        with io.open(site_path, encoding="utf-8") as f:
            site = json.load(f)
        gf = site["gridFrame"]
        self.ox, self.oy = gf["origin_xy_m"]
        self.res = float(gf["resolution_m"])
        lv0 = site["levels"][0]["grid"]
        self.rows, self.cols = int(lv0["rows"]), int(lv0["cols"])
        self.levels = [l["levelID"] for l in site["levels"]]

    def cell_center(self, r, c):
        return (self.ox + (c + 0.5) * self.res, self.oy + (r + 0.5) * self.res)

    def cells_in(self, geom):
        """폴리곤 내부에 셀 중심이 들어가는 (row, col) 목록."""
        if geom.is_empty:
            return []
        minx, miny, maxx, maxy = geom.bounds
        c0 = max(0, int((minx - self.ox) / self.res) - 1)
        c1 = min(self.cols - 1, int((maxx - self.ox) / self.res) + 1)
        r0 = max(0, int((miny - self.oy) / self.res) - 1)
        r1 = min(self.rows - 1, int((maxy - self.oy) / self.res) + 1)
        if c1 < c0 or r1 < r0:
            return []
        pg = prep(geom)
        from shapely.geometry import Point
        out = []
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                x, y = self.cell_center(r, c)
                if pg.contains(Point(x, y)):
                    out.append([r, c])
        return out


# ──────────────────────────────────────────── IFC 지오메트리
def footprint(shape_verts, faces=None):
    """메시 → XY 평면 실제 풋프린트 폴리곤.

    ## v2.5 수정: convex hull → 삼각형 투영 합집합

    v2.4 는 정점의 convex hull 을 풋프린트로 썼다. 그러나 이 건물의 슬래브에는
    고리형·L형·중정형이 있어 hull 이 빈 부분을 메워 버렸다. 실측:

        Level_01 z=59.0 ROOF   hull 1141.8 m² vs 실제 261.3 m²  (4.37배 팽창)
        Level_01 main          hull 1088.1 m² vs 실제 1014.7 m²
        Level_02 FLOOR         hull 1247.3 m² vs 실제 1200.9 m²

    팽창은 면적만 틀리게 하는 것이 아니라 **없는 교집합을 만들어 냈다.**
    z=59.0 ROOF 와 Level_02 FLOOR 는 hull 기준 853.5 m² 겹치지만 실제로는
    0.0 m² 로 전혀 겹치지 않는다. 이 가짜 교집합이 직하부 판정을 오염시켰다.

    실제 투영값은 지시서가 준 층별 바닥면적과 일치한다
    (Level_01 1014.7 ≈ 1015, Level_02 1200.9 ≈ 1201).

    faces 가 없으면 hull 로 물러난다(정점만 있는 경우).
    """
    if shape_verts is None or len(shape_verts) < 3:
        return None
    if faces is not None and len(faces) >= 3:
        tris = []
        for i in range(0, len(faces) - 2, 3):
            a = shape_verts[faces[i]]
            b = shape_verts[faces[i + 1]]
            c = shape_verts[faces[i + 2]]
            p = Polygon([a[:2], b[:2], c[:2]])
            if p.area > 1e-9:
                tris.append(p if p.is_valid else p.buffer(0))
        if tris:
            poly = unary_union(tris)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.area > 1e-9:
                return poly
    xy = np.unique(np.round(shape_verts[:, :2], 4), axis=0)
    if len(xy) < 3:
        return None
    poly = Polygon(xy).convex_hull
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if (poly.area > 1e-9) else None


def extract_ifc(log):
    import ifcopenshell
    import ifcopenshell.geom as G

    f = ifcopenshell.open(IFC_PATH)
    st = G.settings()
    st.set("use-world-coords", True)

    def storey_of(el):
        for rel in (getattr(el, "ContainedInStructure", None) or []):
            return rel.RelatingStructure.Name
        return None

    def shape_of(el):
        """→ (verts Nx3, faces list). 실제 풋프린트 산출에 faces 가 필요하다."""
        try:
            sh = G.create_shape(st, el)
            return (np.array(sh.geometry.verts).reshape(-1, 3),
                    list(sh.geometry.faces))
        except Exception:
            return None, None

    data = {"openings": [], "slabs": defaultdict(list),
            "walls": defaultdict(list), "columns": defaultdict(list),
            "storey_elev": {}}

    for s in f.by_type("IfcBuildingStorey"):
        if s.Name in STOREY_TO_SITE:
            data["storey_elev"][s.Name] = float(s.Elevation) / 1000.0

    # R1 원천: IfcSlab 을 voiding 하는 미충전 IfcOpeningElement
    filled = set(r.RelatingOpeningElement.id()
                 for r in f.by_type("IfcRelFillsElement"))
    n_raw = 0
    for rel in f.by_type("IfcRelVoidsElement"):
        host = rel.RelatingBuildingElement
        if not host.is_a("IfcSlab"):
            continue
        op = rel.RelatedOpeningElement
        n_raw += 1
        if op.id() in filled:
            continue
        v, fc = shape_of(op)
        if v is None or len(v) == 0:
            log.append("  - 개구부 %s: 지오메트리 생성 실패" % op.GlobalId)
            continue
        poly = footprint(v, fc)
        if poly is None:
            log.append("  - 개구부 %s: 풋프린트 없음" % op.GlobalId)
            continue
        data["openings"].append({
            "guid": op.GlobalId, "host_guid": host.GlobalId,
            "storey": storey_of(host), "poly": poly,
            "z": float(v[:, 2].min()), "top": float(v[:, 2].max()),
        })
    data["n_raw_slab_openings"] = n_raw

    for cls, key in (("IfcSlab", "slabs"), ("IfcWall", "walls"),
                     ("IfcColumn", "columns")):
        for el in f.by_type(cls):
            sy = storey_of(el)
            if sy not in STOREY_TO_SITE:
                continue
            v, fc = shape_of(el)
            if v is None or len(v) == 0:
                continue
            poly = footprint(v, fc)
            if poly is None:
                continue
            data[key][sy].append({"guid": el.GlobalId, "poly": poly,
                                  "zmin": float(v[:, 2].min()),
                                  "zmax": float(v[:, 2].max())})
    return data


# ──────────────────────────────────────────── 공정표
def load_schedule():
    with io.open(SCHEDULE_V2, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["_s"] = date(*map(int, r["start_date"].split("-")))
        r["_e"] = date(*map(int, r["end_date"].split("-")))
    return rows


def find_task(rows, level, pred):
    for r in rows:
        if r["level"] == level and pred(r):
            return r
    return None


def task_index(rows):
    """공정표 → 층별 주요 마일스톤 task."""
    idx = {}
    for lv in STOREY_ORDER:
        sub = [r for r in rows if r["level"] == lv]
        if not sub:
            continue
        def pick(p):
            hits = [r for r in sub if p(r)]
            return hits[-1] if hits else None
        idx[lv] = {
            # 주의: 신설 해체 작업명이 "슬래브 거푸집·동바리 해체"라 '거푸집'을
            # 포함한다. origin 으로 걸러내지 않으면 설치 작업 대신 해체가 잡힌다.
            "slab_formwork": pick(lambda r: r["element_type"] == "슬래브"
                                  and "거푸집" in r["task_name"]
                                  and "해체" not in r["task_name"]
                                  and r.get("origin") != "augment:strip"),
            "slab_pour": pick(lambda r: r["element_type"] == "슬래브"
                              and "타설" in r["task_name"]),
            "slab_curing": pick(lambda r: r["element_type"] == "양생"
                                and "슬래브" in r["task_name"]),
            "strip": pick(lambda r: r.get("origin") == "augment:strip"),
            "stair": pick(lambda r: r["element_type"] == "계단"),
            # v2.6 자재 반입·소진 — LCR_MATERIAL_STORAGE 트리거가 요구하는
            # workType=delivery / consume_or_remove 를 갖는 작업이다.
            "delivery": (lambda hits: hits[0] if hits else None)(
                [r for r in sub if r.get("origin") == "augment:material"
                 and "반입" in r["task_name"]]),
            "consume": pick(lambda r: r.get("origin") == "augment:material"
                            and "소진" in r["task_name"]),
            "window": pick(lambda r: r["element_type"] == "창문"),
            "railing": pick(lambda r: r["element_type"] == "난간"),
            "first": min(sub, key=lambda r: r["_s"]),
            "last": max(sub, key=lambda r: r["_e"]),
            "all": sub,
        }
    return idx


# ──────────────────────────────────────────── zone 생성
def ring_list(g):
    """Polygon → GeoJSON 링 목록 [외곽, 구멍...]."""
    out = [[[round(x, 3), round(y, 3)] for x, y in g.exterior.coords]]
    for r in g.interiors:
        out.append([[round(x, 3), round(y, 3)] for x, y in r.coords])
    return out


def geom_from_json(g):
    """hazard_zones.json 의 geometry → shapely (구멍 포함 복원)."""
    def poly(rings):
        return Polygon(rings[0], rings[1:] if len(rings) > 1 else None)
    try:
        if g["type"] == "polygon":
            p = poly(g["coords"])
        else:
            p = unary_union([poly(r).buffer(0) for r in g["coords"]])
        return p if p.is_valid else p.buffer(0)
    except Exception:
        return None


def polygonal(geom):
    """면 성분만 남긴다.

    실제 풋프린트(삼각형 합집합)끼리 교집합을 하면 선·점이 섞인
    GeometryCollection 이 나올 수 있다. 면이 아닌 성분은 면적이 0이므로 버린다.
    """
    if geom is None or geom.is_empty:
        return geom
    gt = geom.geom_type
    if gt in ("Polygon", "MultiPolygon"):
        return geom
    if gt == "GeometryCollection":
        parts = [g for g in geom.geoms
                 if g.geom_type in ("Polygon", "MultiPolygon")
                 and not g.is_empty]
        return unary_union(parts) if parts else Polygon()
    return Polygon()


class ZoneBuilder(object):
    def __init__(self, grid, params):
        self.grid = grid
        self.p = params
        self.zones = []
        self.seq = Counter()

    def add(self, hazard_type, storey, poly, z, height, spawn, despawn,
            channel, derived_from, tag, extra=None):
        poly = polygonal(poly)
        if poly is None or poly.is_empty or poly.area <= 1e-6:
            return None
        self.seq[(storey, tag)] += 1
        zid = "HZ_%s_%s_%03d" % (STOREY_TO_SITE.get(storey, storey), tag,
                                 self.seq[(storey, tag)])
        geoms = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
        # GeoJSON 규약: Polygon = [외곽링, 구멍링...], MultiPolygon = [Polygon...]
        # v2.4 는 exterior 만 저장해 **구멍을 버렸다.** 실제 풋프린트로 바꾸자
        # 중정·개구부가 구멍으로 나타나면서 면적이 부풀려졌다(1191 → 1247).
        coords = [ring_list(g) for g in geoms]
        z_ = {
            "zone_id": zid,
            "hazard_type": hazard_type,
            "derived_from": derived_from,
            "storey": storey,
            "level": STOREY_TO_SITE.get(storey, storey),
            "geometry": {"type": "polygon" if len(coords) == 1 else "multipolygon",
                         "coords": coords[0] if len(coords) == 1 else coords,
                         "z": round(z, 3), "height": round(height, 3),
                         "area_m2": round(poly.area, 2)},
            "cells": self.grid.cells_in(poly),
            "spawn": spawn, "despawn": despawn,
            "channel": channel,
            "variant": "BASE",
        }
        if extra:
            z_.update(extra)
        self.zones.append(z_)
        return z_


# ────────────────────────────── 직하부 슬래브 판정 (v2.5 버그 수정)
#
# v2.4 는 "하부층"을 STOREY_ORDER 표고 순서로 결정했다. 그러나 이 건물은 층이
# 수직으로 포개지지 않는 구간이 있어(서측 주차데크) 표고 순서가 물리적 직하부와
# 어긋났고, Level_02 골조의 존치·낙하구역이 6~8 m² 로 과소 산정되었다.
#
# 규칙의 원래 의미는 "물리적으로 아래에 있는 슬래브"이고 표고 순서는 그 대리
# 지표였을 뿐이므로, 이는 의미 변경이 아니라 버그 수정이다.
#
# 새 규칙: 대상 풋프린트와 XY 교집합이 최대인 하위 표고 **슬래브**를 직하부로
#          삼는다. 층 단위가 아니라 슬래브 단위. 교집합이 상부 풋프린트의
#          SUPPORT_MIN_RATIO 미만이면 직하부 없음.
SUPPORT_MIN_RATIO = 0.10
# 상·하부 슬래브 사이 순간격이 이보다 작으면 '층'이 아니라 적층 부재(구조슬래브+
# 마감, 지붕+바닥 등)로 보고 축퇴 후보로 기록한다. 후보에서 제외하지는 않는다.
DEGENERATE_CLEAR_M = 0.5


def find_support_slab(upper_poly, upper_zmin, all_slabs, exclude_guids=()):
    """대상 풋프린트의 직하부 슬래브를 찾는다.

    → (slab dict, 교집합 면적) 또는 (None, 0.0)

    후보  : zmin 이 대상보다 낮은 모든 슬래브 (층 무관)
    선택  : 교집합 최대 → 동률이면 z 가 가장 가까운 것
    기각  : 교집합 < 상부 풋프린트의 SUPPORT_MIN_RATIO
    """
    if upper_poly is None or upper_poly.is_empty or upper_poly.area <= 0:
        return None, 0.0
    thresh = upper_poly.area * SUPPORT_MIN_RATIO
    cands, best_a = [], 0.0
    for s in all_slabs:
        if s["guid"] in exclude_guids:
            continue
        if s["zmin"] >= upper_zmin - 1e-6:
            continue
        try:
            a = upper_poly.intersection(s["poly"]).area
        except Exception:
            continue
        if a <= 0:
            continue
        best_a = max(best_a, a)
        if a >= thresh:
            cands.append((s, a))
    if not cands:
        return None, best_a
    # 기준(10%)을 넘는 후보 중 **가장 가까운 아래**(zmax 최대)를 고른다.
    # '교집합 최대'만으로 고르면 아래쪽의 더 큰 슬래브가 이겨서 Roof→Basement
    # (순간격 23 m) 같은 물리적으로 불가능한 지지 관계가 나온다. 규칙의 의미는
    # '물리적 직하부'이므로 교집합은 **자격 요건**, 근접도가 **선택 기준**이다.
    cands.sort(key=lambda x: (-x[0]["zmax"], -x[1]))
    return cands[0][0], cands[0][1]


# 상·하부 슬래브가 평면상 거의 겹치지 않으면 투영 zone 이 극히 작아진다.
# 이는 클리핑 버그가 아니라 건물 형상(별동·스킵플로어·주차데크 등)일 수 있으므로,
# 특정 층을 하드코딩하지 않고 **겹침 비율이 임계 미만일 때** 사유를 붙인다.
ANOMALY_OVERLAP_RATIO = 0.10


def overlap_anomaly(upper, lower, upper_poly, lower_poly, proj,
                    z_top, z_bot):
    """투영 결과가 상부 풋프린트 대비 지나치게 작으면 설명을 만든다."""
    if upper_poly is None or upper_poly.is_empty or upper_poly.area <= 0:
        return None
    ratio = proj.area / upper_poly.area
    if ratio >= ANOMALY_OVERLAP_RATIO:
        return None
    la = lower_poly.area if (lower_poly is not None
                             and not lower_poly.is_empty) else 0.0
    return (
        "상부 %s 슬래브(%.0f m²)가 하부 %s 슬래브(%.0f m²)와 평면상 %.1f m² "
        "(상부의 %.1f%%)만 겹쳐 투영 구역이 매우 작다. 표고차 %.0f mm. "
        "클리핑 오류가 아니라 두 층이 수직으로 포개지지 않는 건물 형상"
        "(별동·스킵플로어·주차데크 등)에서 비롯된 값이다. "
        "근거는 build/level_02a_diagnosis.md 참조."
        % (upper, upper_poly.area, lower, la, proj.area, 100.0 * ratio,
           abs(z_top - z_bot) * 1000.0)
    )


def trig(task, kind="task_complete"):
    if task is None:
        return None
    return {"trigger": kind, "task_id": int(task["task_id"]),
            "activity_id": "T-%s" % task["task_id"],
            "date": task["end_date"] if kind == "task_complete"
            else task["start_date"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opening-buffer-m", type=float, default=2.0)
    ap.add_argument("--edge-band-m", type=float, default=2.0)
    ap.add_argument("--drop-angle-deg", type=float, default=15.0)
    ap.add_argument("--wall-proximity-m", type=float, default=0.5)
    ap.add_argument("--equip-corridor-width-m", type=float, default=4.0)
    ap.add_argument("--retention-days", type=int, default=0)
    ap.add_argument("--overlap-days", type=int, default=0)
    args = ap.parse_args()

    for p in (IFC_PATH, SCHEDULE_V2, SITE_JSON):
        if not os.path.exists(p):
            raise SystemExit("[중단] %s 없음. 루트에서 실행하고 Part 1 을 먼저 "
                             "실행하세요." % p)

    params = OrderedDict([
        ("opening_buffer_m", args.opening_buffer_m),
        ("edge_band_m", args.edge_band_m),
        ("drop_angle_deg", args.drop_angle_deg),
        ("wall_proximity_m", args.wall_proximity_m),
        ("equip_corridor_width_m", args.equip_corridor_width_m),
        ("retention_days", args.retention_days),
        ("overlap_days", args.overlap_days),
    ])

    log = []
    print("위험구역 파생")
    print("  파라미터: %s" % json.dumps(dict(params), ensure_ascii=False))
    print("  IFC 파싱 중 ...")
    ifc = extract_ifc(log)
    print("    개구부(슬래브 voiding, 미충전) : %d / 원천 %d"
          % (len(ifc["openings"]), ifc["n_raw_slab_openings"]))
    print("    슬래브 %d층 / 벽 %d층 / 기둥 %d층"
          % (len(ifc["slabs"]), len(ifc["walls"]), len(ifc["columns"])))

    grid = Grid(SITE_JSON)
    rows = load_schedule()
    tix = task_index(rows)
    B = ZoneBuilder(grid, params)

    slab_union = {}
    for sy, items in ifc["slabs"].items():
        slab_union[sy] = unary_union([i["poly"] for i in items])

    # ── R1. 슬래브 개구부 (추출)
    for o in ifc["openings"]:
        sy = o["storey"]
        t = tix.get(sy, {})
        poly = o["poly"].buffer(params["opening_buffer_m"])
        # 노출 버퍼는 바닥이 있는 범위로 한정한다. 슬래브 가장자리 개구부에서
        # 버퍼가 밖으로 삐져나가면 층 위험구역 면적이 바닥면적을 넘는다(Roof).
        su_o = slab_union.get(sy)
        if su_o is not None and not su_o.is_empty:
            clipped = poly.intersection(su_o)
            if not clipped.is_empty:
                poly = clipped
        despawn = trig(t.get("window")) or trig(t.get("last"))
        B.add("H001_FloorOpening", sy, poly, o["z"], 2.0,
              trig(t.get("slab_pour")), despawn, "dwell_time",
              [o["guid"]], "OPEN",
              {"host_slab": o["host_guid"],
               "raw_area_m2": round(o["poly"].area, 2)})
    n_r1 = len(B.zones)

    # ── R2. 슬래브 단부
    for sy in STOREY_ORDER:
        su = slab_union.get(sy)
        if su is None or su.is_empty:
            continue
        walls = ifc["walls"].get(sy, [])
        wall_u = unary_union([w["poly"] for w in walls]) if walls else None
        band = su.difference(su.buffer(-params["edge_band_m"]))
        if wall_u is not None and not wall_u.is_empty:
            band = band.difference(wall_u.buffer(params["wall_proximity_m"]))
        if band.is_empty:
            continue
        t = tix.get(sy, {})
        # LCR_SLAB_EDGE 의 despawn 필터는 workType=perimeter_protection 이다.
        # 계단·난간(IfcStair/IfcRailing)만 그 workType 을 받으므로 창문(=
        # opening_closure)으로 물러나면 템플릿과 어긋난다. 난간 → 계단 순.
        despawn = trig(t.get("railing")) or trig(t.get("stair"))
        B.add("H007_SlabEdge", sy, band,
              ifc["storey_elev"].get(sy, 0.0), 2.0,
              trig(t.get("slab_pour")), despawn, "dwell_time",
              [i["guid"] for i in ifc["slabs"][sy]], "EDGE")
    n_r2 = len(B.zones) - n_r1

    # ── R3. 동바리 존치구간 — 직하부를 슬래브 단위로 판정 (v2.5)
    all_slabs = []
    for _sy, _items in ifc["slabs"].items():
        for _it in _items:
            all_slabs.append(dict(_it, storey=_sy))
    support_log = []
    for sy in STOREY_ORDER:
        su = slab_union.get(sy)
        if su is None or su.is_empty:
            continue
        t = tix.get(sy, {})
        fw, strip = t.get("slab_formwork"), t.get("strip")
        if fw is None or strip is None:
            log.append("  - R3 %s: 거푸집 또는 해체 작업 없음 → 미생성" % sy)
            continue
        own = set(x["guid"] for x in ifc["slabs"][sy])
        z_top_slab = min(x["zmin"] for x in ifc["slabs"][sy])
        sup, inter_a = find_support_slab(su, z_top_slab, all_slabs, own)
        if sup is None:
            log.append("  - R3 %s: 교집합 %.1f m² 가 기준(%.0f%%) 미만 → 직하부 없음"
                       % (sy, inter_a, SUPPORT_MIN_RATIO * 100))
            support_log.append({"rule": "R3", "upper": sy, "support": None,
                                "inter": round(inter_a, 1)})
            continue
        below = sup["storey"]
        proj = su.intersection(sup["poly"])
        if proj.is_empty:
            continue
        z_top = ifc["storey_elev"].get(sy, z_top_slab)
        z_bot = ifc["storey_elev"].get(below, sup["zmax"])
        clear = z_top_slab - sup["zmax"]        # 상·하부 슬래브 순간격
        extra = {"supports_storey": sy,
                 "support_slab": sup["guid"],
                 "support_storey": below,
                 "support_intersection_m2": round(inter_a, 1),
                 "clear_gap_m": round(clear, 3),
                 "storey_height_m": round(z_top - z_bot, 3),
                 "unclipped_area_m2": round(su.area, 1),
                 "clipped_to_lower_slab": round(proj.area, 1) < round(su.area, 1),
                 "below_selection": "max_xy_intersection"}
        if clear < DEGENERATE_CLEAR_M:
            extra["degenerate_support"] = (
                "직하부로 선택된 슬래브 %s 와의 순간격이 %.2f m 로 층고라 보기 "
                "어렵다(적층 부재 가능성). 존치 높이는 층 표고차 %.2f m 를 썼다."
                % (sup["guid"], clear, z_top - z_bot))
        note = overlap_anomaly(sy, below, su, sup["poly"], proj, z_top, z_bot)
        if note:
            extra["anomaly_note"] = note
        support_log.append({"rule": "R3", "upper": sy, "support": sup["guid"],
                            "support_storey": below, "inter": round(inter_a, 1),
                            "clear": round(clear, 3),
                            "area": round(proj.area, 1)})
        # LCR_SHORING_COLLAPSE 의 spawn 필터는 trade=concrete_pour 다(v2.3 지식).
        # 거푸집 착수가 아니라 **타설 착수**를 spawn 으로 삼아야 템플릿과 맞는다.
        # 거푸집을 쓰면 trade=formwork_erection 이라 lifecycle 검증에서 탈락한다.
        spawn_shore = trig(t.get("slab_pour"), "task_start") or trig(fw, "task_start")
        B.add("H008_ShoringCollapse", below, proj, z_bot,
              max(0.1, z_top - z_bot),
              spawn_shore, trig(strip), "zone_occupancy",
              [x["guid"] for x in ifc["slabs"][sy]], "SHORE", extra)
    n_r3 = len(B.zones) - n_r1 - n_r2

    # ── R4. 낙하 영향구역 — 상하부 동시작업이 실제로 있을 때만
    tan_t = np.tan(np.deg2rad(params["drop_angle_deg"]))
    r4_notes = []
    for sy in STOREY_ORDER:
        su = slab_union.get(sy)
        t = tix.get(sy, {})
        if su is None or su.is_empty or not t:
            continue
        up_s, up_e = t["first"]["_s"], t["last"]["_e"]
        # 직하부를 슬래브 단위로 따라 내려간다 (depth 1 = 직하부, 2 = 그 아래).
        cur_poly, cur_z = su, min(x["zmin"] for x in ifc["slabs"][sy])
        seen = set(x["guid"] for x in ifc["slabs"][sy])
        for depth in (1, 2):
            sup, inter_a = find_support_slab(cur_poly, cur_z, all_slabs, seen)
            if sup is None:
                if depth == 1:
                    r4_notes.append("%s: 직하부 슬래브 없음 (교집합 %.1f m²)"
                                    % (sy, inter_a))
                break
            below = sup["storey"]
            seen.add(sup["guid"])
            tb = tix.get(below)
            if not tb:
                cur_poly, cur_z = sup["poly"], sup["zmin"]
                continue
            lo = max(up_s, tb["first"]["_s"])
            hi = min(up_e, tb["last"]["_e"])
            ov = (hi - lo).days + 1
            if ov <= 0:
                r4_notes.append("%s↔%s(depth %d) 중첩 없음" % (sy, below, depth))
                cur_poly, cur_z = sup["poly"], sup["zmin"]
                continue
            z_up = ifc["storey_elev"].get(sy, 0.0)
            z_bl = ifc["storey_elev"].get(below, z_up - 3.0)
            margin = abs(z_up - z_bl) * tan_t
            expanded = su.buffer(margin)
            poly = expanded.intersection(sup["poly"])
            extra = {"source_storey": sy, "projection_depth": depth,
                     "margin_m": round(margin, 3), "overlap_days": ov,
                     "unclipped_area_m2": round(expanded.area, 1),
                     "support_slab": sup["guid"], "support_storey": below,
                     "support_intersection_m2": round(inter_a, 1),
                     "below_selection": "max_xy_intersection"}
            note = overlap_anomaly(sy, below, expanded, sup["poly"], poly,
                                   z_up, z_bl)
            if note:
                extra["anomaly_note"] = note
            support_log.append({"rule": "R4-d%d" % depth, "upper": sy,
                                "support": sup["guid"], "support_storey": below,
                                "inter": round(inter_a, 1),
                                "clear": round(cur_z - sup["zmax"], 3),
                                "area": round(poly.area, 1)})
            B.add("H009_DropZone", below, poly, z_bl, 2.0,
                  trig(t["first"], "task_start"), trig(t["last"]),
                  "passage_count",
                  [x["guid"] for x in ifc["slabs"][sy]], "DROP", extra)
            cur_poly, cur_z = sup["poly"], sup["zmin"]
    n_r4 = len(B.zones) - n_r1 - n_r2 - n_r3

    # ── R5. 협소통로 · 적재구역
    with io.open(PRODUCTIVITY, encoding="utf-8") as f:
        prod = json.load(f)
    assume = prod.get("assumptions", {})
    r5_alloc = []
    r6_walkable = {}          # R6 가 재사용할 층별 (보행가능영역, 적재구역)
    for sy in STOREY_ORDER:
        su = slab_union.get(sy)
        if su is None or su.is_empty:
            continue
        t = tix.get(sy, {})
        obstacles = []
        for k in ("walls", "columns"):
            items = ifc[k].get(sy, [])
            if items:
                obstacles.append(unary_union([x["poly"] for x in items]))
        for o in ifc["openings"]:
            if o["storey"] == sy:
                obstacles.append(o["poly"])
        free = su
        if obstacles:
            free = su.difference(unary_union(obstacles))
        if free.is_empty:
            continue

        # 적재구역 면적 배정:
        #   층의 최대 element_count 작업 × productivity_rates.assumptions[ifc_class].area_m2
        #   × stack_factor(1/3, 3단 적치 가정) — 이 계수도 근거 없음, 민감도 대상
        best, best_area = None, 0.0
        for r in t.get("all", []):
            try:
                n = int(float(r.get("element_count") or 0))
            except ValueError:
                n = 0
            if n <= 0:
                continue
            a = assume.get(r["ifc_class"], assume.get("default", {})).get("area_m2", 5.0)
            if n * a > best_area:
                best, best_area = r, n * a
        stack_area = best_area / 3.0 if best else 0.0
        r5_alloc.append({"storey": sy, "task": best["task_id"] if best else "-",
                         "task_name": best["task_name"] if best else "-",
                         "n": int(float(best["element_count"])) if best else 0,
                         "unit_area": (assume.get(best["ifc_class"], {}).get("area_m2")
                                       if best else 0),
                         "raw_area": round(best_area, 1),
                         "alloc_area": round(stack_area, 1),
                         "free_area": round(free.area, 1)})

        # 적재구역: 자유영역 내부에서 슬래브 중심 인근에 면적만큼 배정
        mat = None
        if stack_area > 0 and free.area > stack_area:
            cx, cy = free.representative_point().x, free.representative_point().y
            side = float(np.sqrt(stack_area))
            mat = box(cx - side / 2, cy - side / 2,
                      cx + side / 2, cy + side / 2).intersection(free)
            if not mat.is_empty:
                # LCR_MATERIAL_STORAGE 트리거는 material_handling 의
                # delivery(.in_progress) → consume_or_remove(.completed) 를
                # 요구한다. v2.6 에서 공정표에 그 작업이 생겼으므로 바인딩한다.
                B.add("H004_MaterialStorage", sy, mat,
                      ifc["storey_elev"].get(sy, 0.0), 2.0,
                      trig(t.get("delivery"), "task_start")
                      or trig(t.get("first"), "task_start"),
                      trig(t.get("consume")) or trig(t.get("last")),
                      "passage_count",
                      [best["task_id"]] if best else [], "MAT",
                      {"alloc_rule": "element_count × assumptions[%s].area_m2 ÷ 3"
                                     % (best["ifc_class"] if best else "-"),
                       "alloc_area_m2": round(stack_area, 1)})

        walkable = free.difference(mat) if mat is not None and not mat.is_empty else free
        r6_walkable[sy] = (walkable, mat)
        narrow = walkable.difference(walkable.buffer(-0.75)).buffer(0)
        if not narrow.is_empty:
            B.add("H002_NarrowPassage", sy, narrow,
                  ifc["storey_elev"].get(sy, 0.0), 2.0,
                  trig(t.get("slab_curing")) or trig(t.get("first"), "task_start"),
                  trig(t.get("last")), "passage_count",
                  [x["guid"] for x in ifc["slabs"][sy]], "NARROW")
    n_r5 = len(B.zones) - n_r1 - n_r2 - n_r3 - n_r4

    # ── R6. 장비 주행 구역 (H011_EquipmentCorridor) — v2.5 신규
    #
    # 장비 에이전트는 만들지 않는다. 주행 구역을 정적 zone 으로 두고 작업자의
    # 통과 횟수를 세는 방식이며 구조는 R4(낙하 영향구역)와 같다.
    # 진출입구 ↔ 양중·타설 지점을 잇는 통로를 R5 의 보행가능영역 안에서 잡는다.
    r6_log = []
    for sy in STOREY_ORDER:
        wk = r6_walkable.get(sy)
        if wk is None:
            continue
        walkable, mat = wk
        if walkable is None or walkable.is_empty:
            continue
        t = tix.get(sy, {})
        # 주행 경로 대용: 층 진출입(외곽) → 양중·타설 지점(적재구역 또는 도심)
        # 두 점을 잇는 축을 폭 equip_corridor_width_m 밴드로 부풀린다.
        try:
            entry_pt = walkable.representative_point()
            if mat is not None and not mat.is_empty:
                target = mat.representative_point()
            else:
                target = walkable.centroid
            from shapely.geometry import LineString
            axis = LineString([(entry_pt.x, entry_pt.y), (target.x, target.y)])
            if axis.length < 1e-6:
                continue
            band = axis.buffer(params["equip_corridor_width_m"] / 2.0,
                               cap_style=2)
            corr = polygonal(band.intersection(walkable))
        except Exception as e:
            log.append("  - R6 %s: 주행 구역 산출 실패 (%s)" % (sy, type(e).__name__))
            continue
        if corr is None or corr.is_empty or corr.area < 1.0:
            r6_log.append({"storey": sy, "area": 0.0, "note": "보행가능영역 내 밴드 없음"})
            continue
        spawn = trig(t.get("first"), "task_start")
        despawn = trig(t.get("slab_curing")) or trig(t.get("last"))
        z_ = B.add("H011_EquipmentCorridor", sy, corr,
                   ifc["storey_elev"].get(sy, 0.0), 2.0,
                   spawn, despawn, "passage_count",
                   [x["guid"] for x in ifc["slabs"][sy]], "EQUIP",
                   {"corridor_width_m": params["equip_corridor_width_m"],
                    "axis_length_m": round(axis.length, 2),
                    "derivation": "R5 보행가능영역 내 진출입↔양중지점 축을 "
                                  "equip_corridor_width_m 폭으로 밴드화",
                    "width_basis": "근거 없음 — 민감도 분석 대상"})
        if z_:
            r6_log.append({"storey": sy, "area": round(corr.area, 1),
                           "cells": len(z_["cells"]),
                           "axis": round(axis.length, 2)})
    n_r6 = len(B.zones) - n_r1 - n_r2 - n_r3 - n_r4 - n_r5

    print("  생성 zone: R1 %d / R2 %d / R3 %d / R4 %d / R5 %d / R6 %d = %d"
          % (n_r1, n_r2, n_r3, n_r4, n_r5, n_r6, len(B.zones)))
    print("  R6 장비 주행 구역 (H011, 폭 %.1fm — 근거 없음/민감도 대상):"
          % params["equip_corridor_width_m"])
    for x in r6_log:
        print("    %-20s 면적%8.1f m²  셀 %-5s 축길이 %s"
              % (x["storey"], x.get("area", 0.0), x.get("cells", "-"),
                 x.get("axis", x.get("note", "-"))))
    print("  직하부 판정 (슬래브 단위, 교집합 최대):")
    for s in support_log:
        print("    %-7s %-20s → %-22s %-20s 교집합%8.1f 순간격%7.2f 면적%8.1f"
              % (s["rule"], s["upper"], s.get("support") or "(없음)",
                 s.get("support_storey", "-"), s["inter"],
                 s.get("clear", 0.0), s.get("area", 0.0)))
    with io.open("build/below_selection.json", "w", encoding="utf-8") as f:
        json.dump(support_log, f, ensure_ascii=False, indent=1)

    # ── 자기 검증
    checks = run_checks(B.zones, ifc, slab_union, rows, n_r1)
    for c in checks:
        print("  [%s] %s" % ("OK" if c["ok"] else "FAIL", c["name"]))
        if not c["ok"]:
            for d_ in c["detail"][:5]:
                print("        %s" % d_)

    # ── 출력
    meta = OrderedDict([
        ("source_ifc", IFC_PATH),
        ("source_schedule", SCHEDULE_V2),
        ("source_site", SITE_JSON),
        ("generated", datetime.now().isoformat(timespec="seconds")),
        ("grid", {"rows": grid.rows, "cols": grid.cols,
                  "resolution_m": grid.res, "origin_xy_m": [grid.ox, grid.oy]}),
        ("params", dict(params)),
        ("params_note",
         "opening_buffer_m / edge_band_m / drop_angle_deg / wall_proximity_m 는 "
         "근거 없는 임의값이며 전부 민감도 분석 대상이다. 문헌값이 아니다."),
        ("counts", {"R1_opening": n_r1, "R2_edge": n_r2, "R3_shoring": n_r3,
                    "R4_dropzone": n_r4, "R5_passage_storage": n_r5,
                    "R6_equipment_corridor": n_r6,
                    "total": len(B.zones)}),
    ])
    if not os.path.isdir("build"):
        os.makedirs("build")
    with io.open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "zones": B.zones}, f, ensure_ascii=False, indent=1)
    print("  산출: %s (%d zones)" % (OUT_JSON, len(B.zones)))

    bound, skipped = write_bindings(B.zones)
    write_log(B.zones, ifc, checks, params, r4_notes, r5_alloc, log,
              (n_r1, n_r2, n_r3, n_r4, n_r5), slab_union, bound, skipped)
    print("  산출: %s (바인딩 %d, 템플릿 없어 제외 %d)"
          % (OUT_BINDINGS, len(bound), len(skipped)))
    if skipped:
        print("        제외 유형: %s"
              % dict(Counter(s["hazard_type"] for s in skipped)))
    print("  로그: %s" % OUT_LOG)
    return 0 if all(c["ok"] for c in checks) else 1


# TTL 의 LifecycleRuleTemplate 6종에 대응한다.
# v2.4 TTL: LCR_SLAB_OPENING / LCR_SLAB_EDGE / LCR_SHORING_COLLAPSE /
#           LCR_MATERIAL_STORAGE / LCR_DROP_ZONE / LCR_NARROW_PASSAGE
#           (LCR_EXPOSED_REBAR 는 찔림 계열로 범위 제외)
#
# LCR_DROP_ZONE / LCR_NARROW_PASSAGE 는 lifecycle_templates.csv → build_ttl.py
# 경로로 추가했다. TTL 에 직접 쓰면 재생성 시 사라진다.
TEMPLATE_OF = {
    "H001_FloorOpening": "LCR_SLAB_OPENING",
    "H007_SlabEdge": "LCR_SLAB_EDGE",
    "H008_ShoringCollapse": "LCR_SHORING_COLLAPSE",
    "H004_MaterialStorage": "LCR_MATERIAL_STORAGE",
    "H009_DropZone": "LCR_DROP_ZONE",
    "H002_NarrowPassage": "LCR_NARROW_PASSAGE",
    "H011_EquipmentCorridor": "LCR_EQUIPMENT_CORRIDOR",
}
NO_TEMPLATE_REASON = (
    "TTL 에 대응 LifecycleRuleTemplate 이 없다. 템플릿은 지식이므로 코드에서 "
    "생성하지 않는다 — 필요하면 ptd_library_master xlsx 에 항목을 추가하고 "
    "TTL 을 재생성해야 한다."
)


V24_TTL = "build/ptd_library_v2.4.ttl"
PROJ_SCHEDULE = "project/schedule.json"


def ttl_templates():
    """생성된 v2.4 TTL 에 실재하는 LifecycleRuleTemplate 집합."""
    path = V24_TTL
    if not os.path.exists(path):
        return None
    try:
        import rdflib
        g = rdflib.Graph()
        g.parse(path, format="turtle")
        Pns = rdflib.Namespace(C.PTD_NS)
        return set(C.uri_frag(s) for s in
                   g.subjects(rdflib.RDF.type, Pns.LifecycleRuleTemplate))
    except Exception:
        return None


def trigger_filter_checker():
    """(template, kind, activity_id) → 위반 사유 문자열 또는 None.

    lifecycle.LifecycleEngine 은 템플릿 트리거의 trade/workType 필터가 바인딩된
    액티비티와 맞지 않으면 **로드 전체를 ValueError 로 중단**시킨다. 어긋난
    바인딩을 파일에 넣어 두면 엔진이 아예 뜨지 않으므로, 여기서 미리 걸러
    사유를 남긴다. 검사 자체는 lifecycle 의 로직을 그대로 쓴다.
    """
    if not (os.path.exists(V24_TTL) and os.path.exists(PROJ_SCHEDULE)):
        print("  [warn] TTL 또는 project/schedule.json 없음 — 트리거 필터 검사 생략")
        return None
    try:
        sys.path.insert(0, ".")
        import ptd_ttl
        import schedule as _sched
        import lifecycle as _lc
        lib = ptd_ttl.load_library(V24_TTL)
        sch = _sched.load_schedule(PROJ_SCHEDULE)
        tpls = lib.lifecycle_templates
    except Exception as e:
        print("  [warn] 트리거 필터 검사 초기화 실패 (%s: %s) — 생략"
              % (type(e).__name__, str(e)[:80]))
        return None

    def check(template, kind, activity_id):
        tpl = tpls.get(template)
        if tpl is None or not activity_id:
            return None
        act = sch.activities.get(activity_id)
        if act is None:
            return "%s 가 schedule.json 에 없음" % activity_id
        raw = tpl.spawn_trigger if kind == "spawn" else tpl.despawn_trigger
        try:
            tr = _lc.parse_trigger(raw)
        except Exception:
            return None
        if tr.matches(act):
            return None
        want = dict((k, v) for k, v in tr.filters.items()
                    if k in ("trade", "workType"))
        return ("%s %s 필터 %s 와 불일치: %s(trade=%s, workType=%s)"
                % (template, kind, want, activity_id, act.trade, act.work_type))

    def check_level(template, spawn_id, level, lower_level=None):
        """lifecycle 의 locationSelector 정합.

        zone.below 일 때 lifecycle 은 lowerLevel 이 있으면 그것을, 없으면
        L(act-1) 산술을 기대한다 (v2.6 후방호환 확장). 그 규칙을 그대로 쓴다.
        """
        tpl = tpls.get(template)
        act = sch.activities.get(spawn_id) if spawn_id else None
        if tpl is None or act is None:
            return None
        if getattr(tpl, "location_selector", "") == "zone.below":
            if lower_level:
                expect = lower_level
            else:
                n = int(act.level.lstrip("L"))
                expect = "L%d" % (n - 1) if n >= 2 else None
        else:
            expect = act.level
        if expect == level:
            return None
        return ("%s locationSelector=%s: spawnLocation.level=%s 이나 "
                "lifecycle 은 %s 를 기대(액티비티 %s 는 %s). 기하 직하부가 표고 "
                "인접층과 달라 생긴 불일치이며, lifecycle._below_level 이 "
                "L(n-1) 산술만 지원해 표현할 수 없다."
                % (template, getattr(tpl, "location_selector", "?"), level,
                   expect, spawn_id, act.level))

    check.check_level = check_level
    return check


def write_bindings(zones):
    """lifecycle.py 가 그대로 읽는 형식으로 별도 출력.

    lifecycle.LifecycleEngine 은 미정의 템플릿에 ValueError 를 던지므로,
    TTL 에 실재하는 템플릿을 가진 zone 만 바인딩으로 낸다.
    """
    live = ttl_templates()
    if live is not None:
        ghost = sorted(set(TEMPLATE_OF.values()) - live)
        if ghost:
            print("  [경고] TEMPLATE_OF 가 TTL 에 없는 템플릿을 가리킨다: %s"
                  % ghost)
            print("         lifecycle_templates.csv 에 추가하고 build_ttl.py 를 "
                  "재실행해야 한다.")
    filt = trigger_filter_checker()

    out, skipped = [], []
    for z in zones:
        tpl = TEMPLATE_OF.get(z["hazard_type"])
        if tpl is not None and live is not None and tpl not in live:
            skipped.append({"zone_id": z["zone_id"],
                            "hazard_type": z["hazard_type"],
                            "reason": "매핑된 템플릿 %s 가 TTL 에 없음" % tpl})
            continue
        if tpl is None:
            skipped.append({"zone_id": z["zone_id"],
                            "hazard_type": z["hazard_type"],
                            "reason": NO_TEMPLATE_REASON})
            continue
        if not z["cells"] or not z["spawn"]:
            skipped.append({"zone_id": z["zone_id"],
                            "hazard_type": z["hazard_type"],
                            "reason": "셀 또는 spawn 트리거 없음"})
            continue
        spawn_id = z["spawn"]["activity_id"]
        despawn_id = z["despawn"]["activity_id"] if z["despawn"] else None
        # [v2.6] 기하로 판정한 직하부를 lifecycle 에 명시 전달한다.
        # zone.below 템플릿(R3·R4)에서만 의미가 있으며, lifecycle 은 이 값이
        # 없으면 기존 L(n-1) 산술로 폴백한다 (후방호환).
        lower = z["level"] if z.get("support_storey") else None
        if filt is not None:
            why = (filt(tpl, "spawn", spawn_id)
                   or filt(tpl, "despawn", despawn_id)
                   or filt.check_level(tpl, spawn_id, z["level"], lower))
            if why:
                skipped.append({"zone_id": z["zone_id"],
                                "hazard_type": z["hazard_type"],
                                "template": tpl, "reason": why})
                continue
        b = OrderedDict([
            ("template", tpl),
            ("boundActivity", spawn_id),
            ("spawnLocation", {"level": z["level"], "cells": z["cells"]}),
        ])
        if despawn_id:
            b["despawnActivity"] = despawn_id
        if lower:
            b["lowerLevel"] = lower
        b["_zone_id"] = z["zone_id"]
        out.append(b)
    with io.open(OUT_BINDINGS, "w", encoding="utf-8") as f:
        json.dump({"bindings": out, "_skipped": skipped},
                  f, ensure_ascii=False, indent=1)
    return out, skipped


def run_checks(zones, ifc, slab_union, rows, n_r1):
    by_id = {r["task_id"]: r for r in rows}
    checks = []

    # 1. 개구부 zone 수 == 39, 층별 분포 일치
    opens = [z for z in zones if z["hazard_type"] == "H001_FloorOpening"]
    dist = Counter(z["storey"] for z in opens)
    ok = (len(opens) == 39) and all(dist.get(k, 0) == v
                                    for k, v in OPENING_REF.items())
    checks.append({"name": "개구부 zone 39개 및 층별 분포 (6/8/9/9/3/4)",
                   "ok": ok,
                   "detail": ["실측 %d개, 분포 %s" % (len(opens), dict(dist))]})

    # 2. 층별 위험구역 면적 ≤ 바닥면적
    # 겹치는 zone(개구부 버퍼·단부 밴드·협소통로)을 단순 합산하면 바닥면적을
    # 쉽게 넘는다. 물리적으로 의미 있는 값은 **합집합 면적**이다.
    det, ok2 = [], True
    for sy in STOREY_ORDER:
        zs = [z for z in zones if z["storey"] == sy]
        if not zs:
            continue
        polys = []
        for z in zs:
            p = geom_from_json(z["geometry"])
            if p is not None and not p.is_empty:
                polys.append(p.buffer(0))
        try:
            u = unary_union(polys) if polys else None
        except Exception:
            # 위상 예외 시 개별 면적 합(상한)으로 물러난다 — 검사는 보수적으로.
            u = None
            det.append("%s: unary_union 위상 예외 → 면적합 상한으로 대체" % sy)
        ua = u.area if u is not None else sum(p.area for p in polys)
        slab_a = slab_union.get(sy).area if slab_union.get(sy) else 0.0
        ref = FLOOR_AREA_REF.get(sy)
        mark = ""
        # 바닥면적 기준은 IFC 슬래브 풋프린트 합집합(실측)이다.
        if slab_a > 0 and ua > slab_a * 1.001:
            ok2 = False
            mark = "  ← 초과"
        det.append("%s: zone합집합 %.0f / IFC슬래브 %.0f%s%s"
                   % (sy, ua, slab_a, mark,
                      (" / 지시서 참조 %d" % ref) if ref else ""))
    checks.append({"name": "층별 위험구역 합집합 면적 ≤ 해당 층 바닥면적",
                   "ok": ok2, "detail": det})

    # 3. spawn 이 despawn 보다 먼저 발생
    # 트리거 종류에 따라 비교 시점이 다르다:
    #   task_complete → 그 작업 종료일,  task_start → 그 작업 시작일
    def when(t):
        r = by_id.get(str(t["task_id"]))
        if r is None:
            return None
        return r["_e"] if t["trigger"] == "task_complete" else r["_s"]

    bad = []
    for z in zones:
        s, d_ = z["spawn"], z["despawn"]
        if not s or not d_:
            continue
        ws, wd = when(s), when(d_)
        if ws is None or wd is None:
            bad.append("%s: task 미정의" % z["zone_id"])
            continue
        if ws >= wd:
            bad.append("%s: spawn(%s %s) %s >= despawn(%s %s) %s"
                       % (z["zone_id"], s["trigger"], s["task_id"], ws,
                          d_["trigger"], d_["task_id"], wd))
    checks.append({"name": "모든 zone 의 spawn 시점 < despawn 시점",
                   "ok": not bad,
                   "detail": bad or ["위반 0건"]})

    # 4. derived_from GUID 실재
    guids = set(o["guid"] for o in ifc["openings"])
    for k in ("slabs", "walls", "columns"):
        for lst in ifc[k].values():
            guids |= set(x["guid"] for x in lst)
    miss = []
    for z in zones:
        for g in z["derived_from"]:
            if isinstance(g, str) and len(g) == 22 and g not in guids:
                miss.append("%s: %s" % (z["zone_id"], g))
    checks.append({"name": "derived_from GUID 가 IFC 에 실재", "ok": not miss,
                   "detail": miss or ["미확인 0건"]})

    # 5. 채널별 집계
    ch = Counter(z["channel"] for z in zones)
    checks.append({"name": "채널별 zone 수 집계", "ok": True,
                   "detail": ["%s: %d" % (k, v) for k, v in sorted(ch.items())]})
    return checks


def write_log(zones, ifc, checks, params, r4_notes, r5_alloc, extra_log,
              counts, slab_union, bound=None, skipped=None):
    n_r1, n_r2, n_r3, n_r4, n_r5 = counts
    L = []
    a = L.append
    a("# 가설물·위험구역 파생 로그 (Part 2)\n")
    a("IFC 는 완성된 건물만 기술한다. 거푸집·동바리·작업발판과 그것들이 만드는 "
      "위험 공간은 IFC 에 없으므로 영구 부재와 공정에서 파생했다.\n")

    a("## lifecycle.py 인터페이스\n")
    a("`lifecycle.py` 의 `LifecycleEngine` 은 **폴리곤을 받지 않는다.** "
      "`spawnLocation.cells` = 그리드 `(row, col)` 정수쌍, `level` = `\"L1\"..\"L8\"`, "
      "`boundActivity` = `\"T-<task_id>\"` 형식이다. `hazard_type` 과 트리거는 "
      "TTL `LifecycleRuleTemplate` 에서 오고 바인딩은 '어느 액티비티·어느 셀'만 "
      "지정한다.\n")
    a("따라서 지시서의 `hazard_zones.json` 스키마(polygon/z/height)는 lifecycle 이 "
      "소비할 수 없다. 두 표현을 함께 냈다 — `zones[].geometry`(폴리곤, "
      "Unity·면적검증용)와 `zones[].cells`(그리드, lifecycle 소비용), 그리고 "
      "`build/lifecycle_bindings_v2.json`(lifecycle 이 그대로 읽는 형식).\n")
    a("`element_task_mapping.json` 의 `element_ids` 는 **IFC GlobalId GUID** "
      "(22자 base64)다. Name/Tag 가 아니다. 178 task 중 112개에 총 1,438 GUID.\n")

    if skipped is not None:
        a("### 템플릿이 없어 바인딩에서 제외된 zone\n")
        a("v2.4 TTL 의 `LifecycleRuleTemplate` 은 **4종뿐**이다 — "
          "`LCR_SLAB_OPENING` / `LCR_SLAB_EDGE` / `LCR_SHORING_COLLAPSE` / "
          "`LCR_MATERIAL_STORAGE` (`LCR_EXPOSED_REBAR` 는 찔림 계열로 범위 제외). "
          "낙하영향구역·협소통로에 대응하는 템플릿은 존재하지 않는다.\n")
        a("`lifecycle.LifecycleEngine` 은 미정의 템플릿에 `ValueError` 를 던지므로 "
          "해당 zone 은 바인딩에서 제외했다. **템플릿은 지식이므로 코드에서 "
          "만들어내지 않았다** — 필요하면 `ptd_library_master` xlsx 에 항목을 "
          "추가하고 TTL 을 재생성하는 것이 정규 경로다(CLAUDE.md §1·§2).\n")
        a("zone 자체는 `hazard_zones.json` 에 그대로 남아 있어 유실이 없다.\n")
        sc = Counter(s["hazard_type"] for s in skipped)
        a("| 위험유형 | 제외 zone 수 | 대응 템플릿 |")
        a("|---|---:|---|")
        for k, v in sorted(sc.items()):
            a("| %s | %d | **없음** |" % (k, v))
        a("")
        a("바인딩 산출 %d건 / 제외 %d건 (합계 %d = 전체 zone).\n"
          % (len(bound or []), len(skipped), len(bound or []) + len(skipped)))

    a("## 규칙별 생성 zone 수\n")
    a("| 규칙 | 위험유형 | 채널 | zone 수 |")
    a("|---|---|---|---:|")
    a("| R1 슬래브 개구부 | H001_FloorOpening | dwell_time | %d |" % n_r1)
    a("| R2 슬래브 단부 | H007_SlabEdge | dwell_time | %d |" % n_r2)
    a("| R3 동바리 존치 | H008_ShoringCollapse | zone_occupancy | %d |" % n_r3)
    a("| R4 낙하 영향구역 | H009_DropZone | passage_count | %d |" % n_r4)
    a("| R5 협소통로·적재 | H002/H004 | passage_count | %d |" % n_r5)
    a("| **합계** | | | **%d** |\n" % len(zones))

    a("### 층별 분포\n")
    lv = sorted(set(z["storey"] for z in zones),
                key=lambda s: STOREY_ORDER.index(s) if s in STOREY_ORDER else 99)
    types = ["H001_FloorOpening", "H007_SlabEdge", "H008_ShoringCollapse",
             "H009_DropZone", "H002_NarrowPassage", "H004_MaterialStorage"]
    a("| 층 | " + " | ".join(t.split("_")[0] for t in types) + " | 합계 |")
    a("|---" * (len(types) + 2) + "|")
    for s in lv:
        c = Counter(z["hazard_type"] for z in zones if z["storey"] == s)
        a("| %s | %s | %d |" % (s, " | ".join(str(c.get(t, 0)) for t in types),
                                sum(c.values())))
    a("")

    a("## 자기 검증\n")
    for c in checks:
        a("### %s — %s\n" % (c["name"], "OK" if c["ok"] else "FAIL"))
        for d_ in c["detail"]:
            a("- %s" % d_)
        a("")

    a("## R4 낙하 영향구역\n")
    if n_r4 == 0:
        a("**0건 생성.** 층간 중첩이 없어 상하부 동시작업이 성립하지 않는다. "
          "억지로 만들지 않았다.\n")
        for n in r4_notes[:20]:
            a("- %s" % n)
    else:
        a("Part 1 의 층간 중첩으로 상하부 동시작업이 실제로 발생해 %d건이 "
          "생성되었다. 중첩이 없었다면 0건이 정상이다.\n" % n_r4)
        a("| zone | 상부층 | 투영 대상 | 깊이 | 여유폭(m) | 중첩(일) |")
        a("|---|---|---|---:|---:|---:|")
        for z in zones:
            if z["hazard_type"] == "H009_DropZone":
                a("| %s | %s | %s | %d | %.2f | %d |"
                  % (z["zone_id"], z["source_storey"], z["storey"],
                     z["projection_depth"], z["margin_m"], z["overlap_days"]))
    a("")

    a("## R5 적재구역 면적 배정 규칙\n")
    a("층의 `element_count` 최대 작업을 골라, "
      "`productivity_rates.json` 의 `assumptions[ifc_class].area_m2` 를 곱해 "
      "소요 면적을 구하고 **3단 적치 가정으로 ÷3** 했다. "
      "적치 단수 3 은 근거 없는 값이며 민감도 대상이다.\n")
    a("| 층 | 기준 작업 | 개수 | 단위면적(m²) | 소요(m²) | 배정(m²) | 자유영역(m²) |")
    a("|---|---|---:|---:|---:|---:|---:|")
    for r in r5_alloc:
        a("| %s | %s %s | %d | %s | %.1f | %.1f | %.1f |"
          % (r["storey"], r["task"], r["task_name"][:22], r["n"],
             r["unit_area"], r["raw_area"], r["alloc_area"], r["free_area"]))
    a("")

    a("## 파라미터 — 전부 민감도 분석 대상\n")
    a("| 파라미터 | 값 | 근거 |")
    a("|---|---:|---|")
    a("| `opening_buffer_m` | %s | **없음.** 개구부 주변 노출 버퍼. 문헌값 아님 |"
      % params["opening_buffer_m"])
    a("| `edge_band_m` | %s | **없음.** 단부 노출 밴드 폭. 문헌값 아님 |"
      % params["edge_band_m"])
    a("| `drop_angle_deg` | %s | **없음.** 낙하 확산각. 문헌값 아님 |"
      % params["drop_angle_deg"])
    a("| `wall_proximity_m` | %s | **없음.** 벽 인접 판정 임계. 문헌값 아님 |"
      % params["wall_proximity_m"])
    a("| `retention_days` | %s | Part 1 파라미터. 기본 0 = 현행 유지 |"
      % params["retention_days"])
    a("| `overlap_days` | %s | Part 1 파라미터. 기본 0 = 벽체 양생 익일 착수 |"
      % params["overlap_days"])
    a("| 적치 단수 | 3 | **없음.** R5 면적 배정용 |")
    a("")
    a("> 이 값들에 문헌 근거가 있는 것처럼 쓰지 않았다. 전부 민감도 분석에서 "
      "변화시켜야 하는 임의값이다.\n")

    if extra_log:
        a("## 파생 중 경고\n")
        for x in extra_log[:30]:
            a("- %s" % x.strip())
        a("")

    with io.open(OUT_LOG, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
