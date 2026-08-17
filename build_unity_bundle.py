"""build_unity_bundle.py — IFC4 → unity_bundle/ (Unity 프런트엔드 3D 표시·요소 조회용)

시뮬레이션 엔진(fourd.py)이 정본이고, 이 번들은 시각화 전용이다.
산출물 3종 (ROADMAP §6 U-트랙):
  model.glb      — 요소별 노드 분리 glTF 바이너리. 노드/메쉬 이름 = IfcRoot.GlobalId.
  manifest.json  — 요소별 element_key·클래스·층·bbox(IFC 월드좌표 m, Z-up)·psets·재료.
                   GLB 요소 + 집계 호스트(IfcStair 등, bbox=하위 부재 합집합) 수록.
                   aggregate_host_guid로 직접 포함/집계 부재를 구분.
  bundle_meta.json — 스키마 버전, 좌표계 선언, site.json gridFrame 사본, 파이프라인 기록.

[고정 계약 — ROADMAP §2]
  element_key = { "ifc_guid": IfcRoot.GlobalId, "revit_uid": null }  (revit_uid는 예약)
  좌표 정본 = IFC 월드좌표(m, Z-up). manifest의 모든 좌표는 이 프레임.
  모델 원점 이동/센터링 금지 — site.json gridFrame과의 정합이 깨진다.
  격자 파생은 build_site_json.py 소관 — 이 스크립트는 격자를 만들지 않는다.

지오메트리 파이프라인:
  1차: IfcConvert 서브프로세스 (--use-element-guids, 센터링 옵션 금지). 생성 후
       pygltflib로 노드명 GlobalId 커버리지 검사.
  폴백: ifcopenshell.geom iterator(use-world-coords) + pygltflib 자체 GLB 작성.
       (x,y,z)_ifc → (x,z,-y)_gltf (Z-up→Y-up 우수계). 채택 여부는 bundle_meta에 기록.
IfcSpace·IfcOpeningElement 지오메트리는 제외하되, 개구부 보이드는 슬래브·벽 메쉬에
실제 구멍으로 반영된다(두 파이프라인 모두 IfcRelVoidsElement 불리언 기본 적용).

사용: python build_unity_bundle.py <ifc> [--out unity_bundle] [--site project/site.json] [--slim]
"""
import argparse
import json
import multiprocessing
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as EL
import ifcopenshell.util.unit as UU
import pygltflib

# Windows cp949 콘솔/리다이렉트에서 한글·특수문자 print가 UnicodeEncodeError로
# 죽지 않도록 — 산출물 직전 로그 한 줄 때문에 빌드 전체가 무효화되는 것 방지
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from build_site_json import CONSTRUCTION_LEVELS

SCHEMA_VERSION = "1.0"
GUID_RE = re.compile(r'^[0-9A-Za-z_$]{22}$')      # IFC GlobalId (base64, 22자)
EXCLUDE_CLASSES = ("IfcSpace", "IfcOpeningElement")
# --slim 시 유지할 pset — 이름·수량 관련 핵심만
SLIM_PSET_RE = re.compile(r'(Common|Quantit|BaseQuant|Dimension)', re.I)


# ── 지오메트리 수집 (manifest bbox용 — 두 파이프라인 공통) ─────────────────────

def collect_geometry(f):
    """iterator(use-world-coords)로 {guid: (verts_m Nx3, faces Mx3)} 수집.
    verts는 IFC 월드좌표 m (ifcopenshell이 프로젝트 단위→SI 변환·배치 적용)."""
    s = ifcopenshell.geom.settings()
    s.set('use-world-coords', True)
    excl = [e for cls in EXCLUDE_CLASSES for e in f.by_type(cls)]
    it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(),
                                    exclude=excl if excl else None)
    out = {}
    if not it.initialize():
        return out
    while True:
        sh = it.get()
        v = np.array(sh.geometry.verts, dtype=np.float64).reshape(-1, 3)
        fc = np.array(sh.geometry.faces, dtype=np.uint32).reshape(-1, 3)
        if len(v) and len(fc):
            out[sh.guid] = (v, fc)
        if not it.next():
            break
    return out


# ── 1차: IfcConvert ───────────────────────────────────────────────────────────

def try_ifcconvert(ifc_path, glb_path):
    """IfcConvert로 GLB 생성 시도. 성공 + 노드명 GlobalId 커버리지 ≥99%면 채택.
    센터링 옵션(--center-model 등)은 절대 전달하지 않는다."""
    exe = shutil.which('IfcConvert')
    if not exe:
        return False, "IfcConvert 미설치 (PATH에 없음)"
    cmd = [exe, str(ifc_path), str(glb_path), '-y', '--use-element-guids',
           '--exclude', 'entities'] + list(EXCLUDE_CLASSES)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except Exception as e:
        return False, f"IfcConvert 실행 실패: {e}"
    if r.returncode != 0 or not pathlib.Path(glb_path).exists():
        return False, f"IfcConvert 종료코드 {r.returncode}: {r.stderr[:300]}"
    names = [n.name or "" for n in pygltflib.GLTF2().load(str(glb_path)).nodes
             if n.mesh is not None]
    if not names:
        return False, "IfcConvert GLB에 메쉬 노드 없음"
    cov = sum(1 for n in names if GUID_RE.match(n)) / len(names)
    if cov < 0.99:
        return False, f"노드명 GlobalId 커버리지 {cov:.1%} < 99% — 폴백 전환"
    return True, f"IfcConvert 채택 (노드 {len(names)}, GlobalId 커버리지 {cov:.1%})"


# ── 폴백: pygltflib 자체 GLB 작성 ─────────────────────────────────────────────

def write_glb(geom, glb_path):
    """{guid: (verts_ifc, faces)} → 요소별 노드 GLB. 노드/메쉬 이름 = GlobalId.
    좌표 (x,y,z)_ifc → (x,z,-y)_gltf (Z-up→Y-up 우수계 회전, det=+1), 단위 m."""
    g = pygltflib.GLTF2(asset=pygltflib.Asset(version="2.0",
                        generator="build_unity_bundle.py fallback (ifcopenshell+pygltflib)"))
    blob = bytearray()
    node_ids = []
    for guid in sorted(geom):
        v_ifc, faces = geom[guid]
        v = np.column_stack([v_ifc[:, 0], v_ifc[:, 2], -v_ifc[:, 1]]).astype(np.float32)
        idx = faces.astype(np.uint32).ravel()

        bv_i = len(g.bufferViews)
        off = len(blob); blob += idx.tobytes()
        g.bufferViews.append(pygltflib.BufferView(
            buffer=0, byteOffset=off, byteLength=idx.nbytes,
            target=pygltflib.ELEMENT_ARRAY_BUFFER))
        off = len(blob); blob += v.tobytes()
        g.bufferViews.append(pygltflib.BufferView(
            buffer=0, byteOffset=off, byteLength=v.nbytes,
            target=pygltflib.ARRAY_BUFFER))

        acc_i = len(g.accessors)
        g.accessors.append(pygltflib.Accessor(
            bufferView=bv_i, componentType=pygltflib.UNSIGNED_INT,
            count=len(idx), type=pygltflib.SCALAR))
        g.accessors.append(pygltflib.Accessor(
            bufferView=bv_i + 1, componentType=pygltflib.FLOAT,
            count=len(v), type=pygltflib.VEC3,
            min=v.min(axis=0).tolist(), max=v.max(axis=0).tolist()))

        g.meshes.append(pygltflib.Mesh(name=guid, primitives=[pygltflib.Primitive(
            attributes=pygltflib.Attributes(POSITION=acc_i + 1), indices=acc_i)]))
        g.nodes.append(pygltflib.Node(name=guid, mesh=len(g.meshes) - 1))
        node_ids.append(len(g.nodes) - 1)

    g.scenes.append(pygltflib.Scene(nodes=node_ids))
    g.scene = 0
    g.buffers.append(pygltflib.Buffer(byteLength=len(blob)))
    g.set_binary_blob(bytes(blob))
    g.save_binary(str(glb_path))


def glb_guids(glb_path):
    """GLB 메쉬 노드명 목록 (중복 포함 — 검증용)."""
    return [n.name or "" for n in pygltflib.GLTF2().load(str(glb_path)).nodes
            if n.mesh is not None]


# ── manifest ─────────────────────────────────────────────────────────────────

def _json_safe(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    return str(v)


def element_psets(elem, slim):
    try:
        psets = EL.get_psets(elem)
    except Exception:
        return {}
    if slim:
        psets = {k: v for k, v in psets.items() if SLIM_PSET_RE.search(k)}
    return _json_safe(psets)


def element_materials(elem):
    try:
        return [m.Name for m in EL.get_materials(elem) if getattr(m, 'Name', None)]
    except Exception:
        return []


def _bbox_of(vlist):
    v = np.vstack(vlist)                          # IFC 월드좌표 m, Z-up
    return {"min": [round(float(x), 4) for x in v.min(axis=0)],
            "max": [round(float(x), 4) for x in v.max(axis=0)]}


def build_manifest(f, geom, guids, slim):
    """manifest 배열 = GLB에 실린 요소 + 그 집계 호스트(IfcStair 등, 지오메트리 없이
    부재로 분해되는 요소 — bbox는 하위 부재 합집합). 호스트는 GLB에 노드가 없으며
    check 1에서 정보성으로 리포트된다. aggregate_host_guid: 집계 부모 GUID(직접
    포함이면 null) — 래스터 소관(build_site_json)과 동일 기준의 슬래브 선별에 사용."""
    levelid_of = {nm: f"L{i+1}" for i, nm in enumerate(CONSTRUCTION_LEVELS)}
    glb_set = set(guids)

    host_parts = {}                               # host guid → 하위 부재 guid 집합
    host_elem = {}
    for guid in glb_set:
        try:
            elem = f.by_guid(guid)
        except Exception:
            continue
        h, child = EL.get_aggregate(elem), guid
        while h is not None and h.is_a('IfcElement'):
            host_parts.setdefault(h.GlobalId, set()).add(guid)
            host_elem[h.GlobalId] = h
            h = EL.get_aggregate(h)

    def row_of(guid, elem, bbox):
        etype = ifcopenshell.util.element.get_type(elem)
        storey = None
        cont = EL.get_container(elem)             # 집계 부재는 호스트의 층으로 귀속
        if cont is not None and cont.is_a('IfcBuildingStorey'):
            storey = {"name": cont.Name, "guid": cont.GlobalId,
                      "levelID": levelid_of.get(cont.Name)}   # 시공층 밖이면 null
        agg = EL.get_aggregate(elem)
        return {
            "element_key": {"ifc_guid": guid, "revit_uid": None},
            "ifc_class": elem.is_a(),
            "name": elem.Name,
            "type_name": etype.Name if etype is not None else None,
            "storey": storey,
            "bbox_ifc_m": bbox,
            "aggregate_host_guid": agg.GlobalId
                if agg is not None and agg.is_a('IfcElement') else None,
            "psets": element_psets(elem, slim),
            "material": element_materials(elem),
        }

    rows = []
    for guid in sorted(glb_set):
        try:
            elem = f.by_guid(guid)
        except Exception:
            continue
        bbox = _bbox_of([geom[guid][0]]) if guid in geom else None
        rows.append(row_of(guid, elem, bbox))
    for guid in sorted(set(host_parts) - glb_set):
        parts = [geom[g][0] for g in host_parts[guid] if g in geom]
        rows.append(row_of(guid, host_elem[guid],
                           _bbox_of(parts) if parts else None))
    return rows


# ── main ─────────────────────────────────────────────────────────────────────

def build(ifc_path, out_dir, site_path, slim=False):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    site_path = pathlib.Path(site_path)
    if not site_path.exists():
        sys.exit(f"오류: {site_path} 없음 — 먼저 build_site_json.py로 생성 (gridFrame 정본).")
    with open(site_path, encoding='utf-8') as fp:
        site = json.load(fp)
    grid_frame = site.get("gridFrame")
    if grid_frame is None:
        sys.exit("오류: site.json에 gridFrame 없음 — build_site_json.py 최신본으로 재생성.")

    f = ifcopenshell.open(str(ifc_path))
    unit_scale = UU.calculate_unit_scale(f)       # 프로젝트 길이단위 → m (하드코딩 금지)
    print(f"IFC 열림: {ifc_path} (길이 단위 스케일 {unit_scale} → m)")

    print("지오메트리 수집(iterator, world coords)...")
    geom = collect_geometry(f)
    print(f"  메쉬 요소 {len(geom)}개")

    glb_path = out / "model.glb"
    ok, note = try_ifcconvert(ifc_path, glb_path)
    pipeline = "IfcConvert"
    if not ok:
        print(f"1차(IfcConvert) 불가: {note}")
        print("폴백: pygltflib 자체 GLB 작성...")
        write_glb(geom, glb_path)
        pipeline = "ifcopenshell+pygltflib (fallback)"
        note = f"폴백 채택 — 사유: {note}"
    print(f"  {note}")

    guids = [n for n in glb_guids(glb_path) if GUID_RE.match(n)]
    manifest = build_manifest(f, geom, guids, slim)
    with open(out / "manifest.json", 'w', encoding='utf-8') as fp:
        json.dump(manifest, fp, ensure_ascii=False)

    meta = {
        "schemaVersion": SCHEMA_VERSION,
        "sourceIFC": pathlib.Path(ifc_path).name,
        "units": "m",
        "worldCRS": "IFC world coordinates, meters, Z-up",
        "gltf_up": "+Y",
        "gltfAxisTransform": "(x,y,z)_ifc -> (x,z,-y)_gltf",
        "gridFrame": grid_frame,                  # site.json에서 복사 (정본은 site.json)
        "generatedAt": datetime.now().isoformat(timespec='seconds'),
        "elementCount": len(manifest),
        "geometryPipeline": pipeline,
        "fallbackUsed": pipeline != "IfcConvert",
        "pipelineNote": note,
        "slimPsets": slim,
        "unitScaleToMeter": unit_scale,
    }
    with open(out / "bundle_meta.json", 'w', encoding='utf-8') as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)

    print(f"저장: {glb_path} ({glb_path.stat().st_size/1e6:.1f} MB), "
          f"manifest {len(manifest)}개 요소, bundle_meta.json")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc")
    ap.add_argument("--out", default="unity_bundle")
    ap.add_argument("--site", default="project/site.json")
    ap.add_argument("--slim", action="store_true", help="psets를 이름·수량 핵심만 수록")
    a = ap.parse_args()
    build(a.ifc, a.out, a.site, a.slim)
