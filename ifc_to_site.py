"""ifc_to_site.py — IFC4 → 층별 1m 셀 격자 래스터라이저 (P1-2, 검증용 v0)

방법: 요소 삼각형 메시를 XY로 투영, 각 삼각형의 셀 bbox 안에서 셀 중심 점-삼각형
포함검사(barycentric)로 커버 셀을 채운다. (벽이 대각/경로형이라 bbox 불가 — 메시투영 필수)

셀 타입: 0 통로 / 1 벽 / 2 개구부(슬래브 보이드). 협소·적재는 동적/후처리라 여기선 미생성.
격자 원점은 건물 전체 min XY(정수 m)로 고정 → 전 층 정수격자 정렬(collapse_zone 직하부용).
"""
import sys
import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape as U

RES = 1.0  # 셀 크기 m

_S = ifcopenshell.geom.settings()
_S.set('use-world-coords', True)


def _mesh(elem):
    sh = ifcopenshell.geom.create_shape(_S, elem)
    v = U.get_vertices(sh.geometry)            # Nx3 m, world
    fidx = U.get_faces(sh.geometry)            # Mx3
    return v, fidx


def _storey_map(f):
    """elem.id -> storey Name (contained + 보이드 host 상속)."""
    m = {}
    for rel in f.by_type('IfcRelContainedInSpatialStructure'):
        nm = rel.RelatingStructure.Name
        for e in rel.RelatedElements:
            m[e.id()] = nm
    return m


def building_bbox(f):
    """전 슬래브+벽 XY 범위(m)로 격자 원점·크기 산출."""
    xmin = ymin = 1e18
    xmax = ymax = -1e18
    for cls in ('IfcSlab', 'IfcWall'):
        for e in f.by_type(cls):
            try:
                v, _ = _mesh(e)
            except Exception:
                continue
            xmin = min(xmin, v[:, 0].min()); xmax = max(xmax, v[:, 0].max())
            ymin = min(ymin, v[:, 1].min()); ymax = max(ymax, v[:, 1].max())
    ox, oy = np.floor(xmin), np.floor(ymin)
    cols = int(np.ceil(xmax - ox)) + 1
    rows = int(np.ceil(ymax - oy)) + 1
    return (ox, oy), (rows, cols)


def _rasterize(v, faces, grid, val, origin, only_horizontal=False):
    """삼각형 메시를 XY 투영해 grid[r,c]=val. only_horizontal: 수평면(바닥판)만."""
    ox, oy = origin
    R, Cc = grid.shape
    for tri in faces:
        p = v[tri]
        if only_horizontal:
            # 법선 z성분이 큰(수평) 삼각형만 — 슬래브 상/하면 = 바닥 footprint
            n = np.cross(p[1] - p[0], p[2] - p[0])
            nn = np.linalg.norm(n)
            if nn == 0 or abs(n[2] / nn) < 0.7:
                continue
        xy = p[:, :2]
        cx0 = int(np.floor((xy[:, 0].min() - ox) / RES))
        cx1 = int(np.floor((xy[:, 0].max() - ox) / RES))
        cy0 = int(np.floor((xy[:, 1].min() - oy) / RES))
        cy1 = int(np.floor((xy[:, 1].max() - oy) / RES))
        if cx1 < 0 or cy1 < 0 or cx0 >= Cc or cy0 >= R:
            continue
        cx0 = max(cx0, 0); cy0 = max(cy0, 0)
        cx1 = min(cx1, Cc - 1); cy1 = min(cy1, R - 1)
        # 셀 중심 점-삼각형 검사(barycentric)
        ax, ay = xy[0]; bx, by = xy[1]; cxx, cyy = xy[2]
        d = (by - cyy) * (ax - cxx) + (cxx - bx) * (ay - cyy)
        if abs(d) < 1e-12:
            continue
        for cc in range(cx0, cx1 + 1):
            px = ox + (cc + 0.5) * RES
            for rr in range(cy0, cy1 + 1):
                py = oy + (rr + 0.5) * RES
                a = ((by - cyy) * (px - cxx) + (cxx - bx) * (py - cyy)) / d
                b = ((cyy - ay) * (px - cxx) + (ax - cxx) * (py - cyy)) / d
                cg = 1 - a - b
                if a >= -0.02 and b >= -0.02 and cg >= -0.02:
                    grid[rr, cc] = val


def slab_openings(f):
    """슬래브에 보이드로 뚫린 개구부만(=바닥 개구부). {opening: host_slab}."""
    out = {}
    for rel in f.by_type('IfcRelVoidsElement'):
        host = rel.RelatingBuildingElement
        if host and host.is_a('IfcSlab'):
            out[rel.RelatedOpeningElement] = host
    return out


def extract_storey(f, storey_name, origin, dims, smap, slab_ops):
    R, Cc = dims
    WALKABLE, WALL, OPENING = 0, 1, 2
    grid = np.full((R, Cc), -1, dtype=int)   # -1 = 건물 외부(미할당)

    slabs = [e for e in f.by_type('IfcSlab') if smap.get(e.id()) == storey_name]
    walls = [e for e in f.by_type('IfcWall') if smap.get(e.id()) == storey_name]
    cols = [e for e in f.by_type('IfcColumn') if smap.get(e.id()) == storey_name]

    # 1) 바닥판 = 통로 (슬래브 수평면 투영)
    for sl in slabs:
        try:
            v, fc = _mesh(sl)
        except Exception:
            continue
        _rasterize(v, fc, grid, WALKABLE, origin, only_horizontal=True)
    grid[grid == -1] = -1  # 외부 유지

    # 2) 벽·기둥 = 장애물
    for e in walls + cols:
        try:
            v, fc = _mesh(e)
        except Exception:
            continue
        _rasterize(v, fc, grid, WALL, origin)

    # 3) 바닥 개구부 (슬래브 보이드)
    ncov = 0
    for op, host in slab_ops.items():
        if smap.get(host.id()) != storey_name:
            continue
        try:
            v, fc = _mesh(op)
        except Exception:
            continue
        _rasterize(v, fc, grid, OPENING, origin)
        ncov += 1
    return grid, dict(slabs=len(slabs), walls=len(walls), cols=len(cols), slab_openings=ncov)


def ascii_map(grid, step=2):
    ch = {-1: ' ', 0: '.', 1: '#', 2: 'O'}
    lines = []
    R, Cc = grid.shape
    for r in range(0, R, step):
        lines.append(''.join(ch.get(grid[r, c], '?') for c in range(0, Cc, step)))
    return '\n'.join(lines)


if __name__ == '__main__':
    path = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else 'Level_03'
    f = ifcopenshell.open(path)
    print('bbox 계산 중...')
    origin, dims = building_bbox(f)
    print(f'origin(m)={origin}  격자(RxC)={dims}')
    smap = _storey_map(f)
    sops = slab_openings(f)
    print(f'슬래브 개구부 총 {len(sops)}개')
    print(f'[{target}] 추출 중...')
    grid, stats = extract_storey(f, target, origin, dims, smap, sops)
    print('요소:', stats)
    uniq, cnt = np.unique(grid, return_counts=True)
    print('셀 분포:', dict(zip(uniq.tolist(), cnt.tolist())))
    print('--- ASCII (. 통로 / # 벽 / O 개구부, 2셀=1문자) ---')
    print(ascii_map(grid))
