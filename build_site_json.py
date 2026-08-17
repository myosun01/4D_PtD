"""build_site_json.py — IFC4 → project/site.json (P1-2 전체 추출)

ifc_to_site.py의 검증된 래스터라이저를 8개 시공층 전체에 적용하고,
계단(VerticalLink)·zone·단부(edge)를 붙여 ROADMAP §3 스키마의 site.json을 생성한다.

셀 타입(§2): 0 통로 / 1 벽(외부 포함) / 2 개구부(영구 샤프트) / 6 단부(신설)
"""
import json
import pathlib
import sys
from collections import defaultdict

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape as U
import ifcopenshell.util.placement as P
import ifcopenshell.util.unit as UU

import ifc_to_site as M

# 검증 단계에서 확정한 전역 격자 프레임 (재계산 71s 회피)
ORIGIN = (-11.0, 19.0)
DIMS = (69, 93)
RES = 1.0

# site.json에 기록되는 격자↔월드 변환 정본 (ROADMAP §2: 좌표 정본 = IFC 월드좌표 m, Z-up)
GRID_FRAME = {
    "origin_xy_m": [ORIGIN[0], ORIGIN[1]],   # 셀 (0,0)의 최소 코너, IFC 월드좌표(m)
    "resolution_m": RES,
    "axisMapping": {"row": "+Y", "col": "+X"},   # r=floor((y-oy)/res), c=floor((x-ox)/res)
    "worldCRS": "IFC world coordinates, meters, Z-up",
    "cellCenter": "world_xy = origin + (index + 0.5) * resolution",
}

# 시공 8개 층만 (Sea Level·Foundation 제외), IFC명 → levelID·순서
CONSTRUCTION_LEVELS = [
    "Basement", "Level_01", "Level_02a_Parking", "Level_02",
    "Level_03", "Level_04", "Level_05", "Roof",
]

WALKABLE, WALL, OPENING, EDGE = 0, 1, 2, 6


def cell_of(x, y):
    ox, oy = ORIGIN
    return int(np.floor((y - oy) / RES)), int(np.floor((x - ox) / RES))


def mark_edges(grid):
    """통로 셀 중 외부(벽)·개구부에 인접한 것을 단부(6)로 승격 (구조적 사실)."""
    R, C = grid.shape
    out = grid.copy()
    for r in range(R):
        for c in range(C):
            if grid[r, c] != WALKABLE:
                continue
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < R and 0 <= nc < C):
                    out[r, c] = EDGE; break
                if grid[nr, nc] in (WALL, OPENING):
                    out[r, c] = EDGE; break
    return out


def storey_elevations(f):
    """storey Name → 표고(m). Elevation은 프로젝트 길이 단위 → 단위 스케일로 m 환산."""
    scale = UU.calculate_unit_scale(f)   # 프로젝트 길이단위 → m (이 파일은 mm → 0.001)
    return {st.Name: (st.Elevation or 0.0) * scale
            for st in f.by_type('IfcBuildingStorey')}


def storey_guids(f):
    """storey Name → IfcBuildingStorey GlobalId. 이름은 중복 가능 — GUID가 정본 키."""
    return {st.Name: st.GlobalId for st in f.by_type('IfcBuildingStorey')}


def report_duplicate_guids(f):
    """IfcProduct 전체 GlobalId 중복 검사 — 경고·목록 출력만 하고 중단하지 않는다."""
    by_guid = defaultdict(list)
    for p in f.by_type('IfcProduct'):
        by_guid[p.GlobalId].append(p)
    dups = {g: ps for g, ps in by_guid.items() if len(ps) > 1}
    if dups:
        print(f"경고: GlobalId 중복 {len(dups)}건 "
              f"(IfcProduct {sum(len(ps) for ps in dups.values())}개) — GUID는 정본 키")
        for g, ps in sorted(dups.items()):
            print(f"  {g}: " + ", ".join(f"#{p.id()} {p.is_a()}({p.Name})" for p in ps))
    return dups


_GS = ifcopenshell.geom.settings(); _GS.set('use-world-coords', True)


def _stair_parts(f, st):
    out = []
    for rel in f.by_type('IfcRelAggregates'):
        if rel.RelatingObject.id() == st.id():
            out += list(rel.RelatedObjects)
    return out


def _stair_xy(f, st):
    """하위 부재 지오메트리에서 XY 중앙값(깨진 정점 범위필터)."""
    for p in _stair_parts(f, st) + [st]:
        if not getattr(p, 'Representation', None):
            continue
        try:
            # shape를 변수에 바인딩 — 임시 객체면 .geometry 버퍼가 GC로 해제되어
            # verts가 빈 배열이 됨 (ifcopenshell 0.8.x)
            sh = ifcopenshell.geom.create_shape(_GS, p)
            v = U.get_vertices(sh.geometry)
        except Exception:
            continue
        ox, oy = ORIGIN
        mask = (np.abs(v[:, 0] - ox) < 500) & (np.abs(v[:, 1] - oy) < 500)
        if mask.sum() == 0:
            continue
        vv = v[mask]
        return float(np.median(vv[:, 0])), float(np.median(vv[:, 1]))
    return None


def stair_links(f, smap, levelid_of):
    """IfcStair 하위부재 XY로 위치 잡아 연속 시공층 간 VerticalLink 생성 (셀·층쌍 중복 제거)."""
    order = {nm: i for i, nm in enumerate(CONSTRUCTION_LEVELS)}
    seen = {}
    for st in f.by_type('IfcStair'):
        host = smap.get(st.id())
        if host not in order or order[host] + 1 >= len(CONSTRUCTION_LEVELS):
            continue
        xy = _stair_xy(f, st)
        if xy is None:
            continue
        r, c = cell_of(*xy)
        if not (0 <= r < DIMS[0] and 0 <= c < DIMS[1]):
            continue
        upper = CONSTRUCTION_LEVELS[order[host] + 1]
        key = (host, r, c)
        if key in seen:
            continue
        seen[key] = {
            "linkType": "stair",
            "connects": [
                {"level": levelid_of[host], "cell": [r, c]},
                {"level": levelid_of[upper], "cell": [r, c]},
            ],
            "capacity": 2, "traversalSteps": 40, "availableFromActivity": None,
        }
    links = []
    for i, v in enumerate(seen.values(), 1):
        v = {"linkID": f"ST{i}", **v}
        links.append(v)
    return links


def build(ifc_path, out_path):
    f = ifcopenshell.open(ifc_path)
    report_duplicate_guids(f)
    smap = M._storey_map(f)
    sops = M.slab_openings(f)
    elev = storey_elevations(f)
    guids = storey_guids(f)
    levelid_of = {nm: f"L{i+1}" for i, nm in enumerate(CONSTRUCTION_LEVELS)}

    levels = []
    for i, nm in enumerate(CONSTRUCTION_LEVELS):
        grid, st = M.extract_storey(f, nm, ORIGIN, DIMS, smap, sops)
        grid[grid == -1] = WALL              # 외부 = 통행불가
        grid = mark_edges(grid)
        u, c = np.unique(grid, return_counts=True)
        dist = dict(zip(u.tolist(), c.tolist()))
        print(f"  {levelid_of[nm]}={nm:18s} 통로{dist.get(0,0)} 벽{dist.get(1,0)} "
              f"개구부{dist.get(2,0)} 단부{dist.get(6,0)}  (요소 {st})")
        # zone: 통로+단부를 단일 work 존으로 (세분화는 후처리)
        work_cells = [[int(r), int(cc)] for r in range(DIMS[0]) for cc in range(DIMS[1])
                      if grid[r, cc] in (WALKABLE, EDGE)]
        levels.append({
            "levelID": levelid_of[nm], "elevation_m": round(elev.get(nm, 0.0), 3),
            "sourceIfcStorey": nm,
            "sourceIfcStoreyGuid": guids.get(nm),
            "grid": {"rows": DIMS[0], "cols": DIMS[1], "cells": grid.tolist()},
            "zones": [{"zoneID": "Z-A", "zoneType": "work", "cells": work_cells}],
        })

    vlinks = stair_links(f, smap, levelid_of)
    print(f"  VerticalLink(계단): {len(vlinks)}개")

    site = {"siteID": "PRJ001", "schemaVersion": "1.1", "gridResolution_m": RES,
            "gridFrame": GRID_FRAME,
            "sourceIFC": pathlib.Path(ifc_path).name,   # 백슬래시 경로에서도 파일명만
            "levels": levels, "verticalLinks": vlinks}
    with open(out_path, 'w', encoding='utf-8') as fp:
        json.dump(site, fp, ensure_ascii=False)
    print(f"저장: {out_path}  (레벨 {len(levels)}, 링크 {len(vlinks)})")


if __name__ == '__main__':
    ifc = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else 'site.json'
    build(ifc, out)
