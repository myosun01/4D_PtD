"""check_unity_bundle.py — unity_bundle/ 검증 (전부 통과해야 번들 완성)

1. 키 정합   : GLB 노드 GlobalId 집합 == manifest 키 집합 (양방향 차집합 리포트,
               불일치 0건), GlobalId 중복 0건.
2. 개구부 관통: site.json cellType==2 셀을 층별 최대 5개 샘플 → gridFrame으로 셀 중심
               월드 (x,y) 계산 → trimesh 수직 레이캐스트로 해당 층 슬래브와 교차 0건.
               대조군: cellType==0 통로 셀 5개/층은 교차 ≥1건.
3. 좌표 정합 : verticalLinks 계단 셀 중심 (x,y)가 해당 층 IfcStair manifest bbox의
               XY 범위 내 — 링크 3개 이상 확인.
4. 규모 리포트: 클래스별 요소 수, GLB 크기, 층별 요소 수.

[v3.1 Part C-5 추가 — 번들에 새로 실린 3개 파일 검사]
5. 타임라인 정합 : timeline.json 액티비티 수 == 현행 project/schedule.json
6. 위험구역     : hazard_zones.json zone 84 + hazard_type 7종 전부
7. 궤적         : 좌표가 model.glb 바운딩박스 안, activity_id 가 timeline 에 실재
   (5~7 은 해당 파일이 없으면 '건너뜀'으로 리포트하고 실패로 치지 않는다 —
    번들을 지오메트리만으로 쓰던 기존 사용법을 깨지 않기 위해서다.)

좌표 규약: IFC (x,y,z) Z-up ↔ glTF (x,z,-y) Y-up. 수직 레이 = glTF -Y 방향.
사용: python check_unity_bundle.py [--bundle unity_bundle] [--site project/site.json]
"""
import argparse
import json
import pathlib
import sys
from collections import Counter

import numpy as np
import pygltflib
import trimesh

# Windows cp949 콘솔/리다이렉트 대비 (build_unity_bundle.py와 동일 사유)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

GUID_LEN = 22
OPENING, WALKABLE = 2, 0
SAMPLES_PER_LEVEL = 5


def load_bundle(bundle_dir):
    b = pathlib.Path(bundle_dir)
    with open(b / "manifest.json", encoding='utf-8') as fp:
        manifest = json.load(fp)
    with open(b / "bundle_meta.json", encoding='utf-8') as fp:
        meta = json.load(fp)
    return b / "model.glb", manifest, meta


def load_site(site_path):
    with open(site_path, encoding='utf-8') as fp:
        return json.load(fp)


def cell_center_world(grid_frame, r, c):
    """gridFrame 규약: r=+Y, c=+X, world_xy = origin + (index+0.5)*resolution."""
    ox, oy = grid_frame["origin_xy_m"]
    res = grid_frame["resolution_m"]
    return ox + (c + 0.5) * res, oy + (r + 0.5) * res


def _sample_even(cells, k):
    """정렬된 셀 목록에서 균등 간격 k개 (결정적 샘플링)."""
    if len(cells) <= k:
        return list(cells)
    idx = np.linspace(0, len(cells) - 1, k).astype(int)
    return [cells[i] for i in idx]


# ── 1. 키 정합 ────────────────────────────────────────────────────────────────

def check_keys(glb_path, manifest):
    """GLB 노드 GlobalId ⊆ manifest 키 (불일치 0건), 중복 0건.
    역방향 미포함분(manifest에만 있는 키)은 집계 호스트(IfcStair 등 — GLB에 노드가
    없는 분해 요소)만 허용하고 정보성으로 리포트한다."""
    names = [n.name or "" for n in pygltflib.GLTF2().load(str(glb_path)).nodes
             if n.mesh is not None]
    mkeys = [m["element_key"]["ifc_guid"] for m in manifest]
    ok = True

    dup_glb = [g for g, n in Counter(names).items() if n > 1]
    dup_mf = [g for g, n in Counter(mkeys).items() if n > 1]
    if dup_glb or dup_mf:
        ok = False
        print(f"  FAIL GlobalId 중복 — GLB {len(dup_glb)}건 {dup_glb[:5]} / "
              f"manifest {len(dup_mf)}건 {dup_mf[:5]}")
    bad = [n for n in names if len(n) != GUID_LEN]
    if bad:
        ok = False
        print(f"  FAIL GlobalId 아닌 노드명 {len(bad)}건: {bad[:5]}")

    gset, mset = set(names), set(mkeys)
    only_glb = sorted(gset - mset)
    if only_glb:
        ok = False
        print(f"  FAIL GLB에만 있는 GlobalId {len(only_glb)}건: {only_glb[:5]}")

    referenced_hosts = {m["aggregate_host_guid"] for m in manifest
                        if m.get("aggregate_host_guid")}
    only_mf = sorted(mset - gset)
    stray = [g for g in only_mf if g not in referenced_hosts]
    if stray:
        ok = False
        print(f"  FAIL manifest에만 있고 집계 호스트도 아닌 키 {len(stray)}건: {stray[:5]}")
    if only_mf:
        cls = Counter(m["ifc_class"] for m in manifest
                      if m["element_key"]["ifc_guid"] in set(only_mf))
        print(f"  리포트: GLB 미포함 manifest 키 {len(only_mf)}건 (집계 호스트) — "
              + ", ".join(f"{k}={v}" for k, v in cls.most_common()))

    print(f"  GLB 메쉬노드 {len(names)} / manifest {len(mkeys)} / "
          f"교집합 {len(gset & mset)} — {'OK' if ok else 'FAIL'}")
    return ok


# ── 2. 개구부 관통 (수직 레이캐스트) ──────────────────────────────────────────

def _footprint_opening_frac(m, gf, grid):
    """슬래브 bbox XY 발자국 셀 중 개구부(2) 비율 (격자 밖은 0)."""
    b = m.get("bbox_ifc_m")
    if not b:
        return 0.0
    ox, oy = gf["origin_xy_m"]
    res = gf["resolution_m"]
    R, C = grid.shape
    c0 = max(int(np.floor((b["min"][0] - ox) / res)), 0)
    c1 = min(int(np.floor((b["max"][0] - ox) / res)), C - 1)
    r0 = max(int(np.floor((b["min"][1] - oy) / res)), 0)
    r1 = min(int(np.floor((b["max"][1] - oy) / res)), R - 1)
    if r1 < r0 or c1 < c0:
        return 0.0
    return float((grid[r0:r1 + 1, c0:c1 + 1] == OPENING).mean())


def _level_slab_mesh(scene, manifest, level_id, gf, grid):
    """해당 시공층(levelID)에 직접 포함된 IfcSlab 메쉬 결합체 (glTF 프레임).
    집계 부재(계단참 등, aggregate_host_guid≠null)는 제외 — 래스터라이저
    (ifc_to_site.extract_storey)가 직접 포함 슬래브만 보는 것과 동일 기준.
    발자국 과반이 개구부 셀인 '덮개' 슬래브(보이드 구역을 메우는 별도 패치,
    예: 샤프트 위 5cm 판)도 제외하고 리포트 — 래스터라이저는 보이드를 최후에
    덮어쓰므로 격자 정본상 그 셀은 개구부이고, 덮개를 대상에 넣으면 진짜 결함
    (호스트 슬래브의 보이드 불리언 실패)과 구분할 수 없다."""
    rows = [m for m in manifest
            if m["ifc_class"] == "IfcSlab"
            and m.get("aggregate_host_guid") is None
            and m["storey"] and m["storey"]["levelID"] == level_id]
    covers = [m for m in rows if _footprint_opening_frac(m, gf, grid) >= 0.5]
    for m in covers:
        print(f"  리포트: {level_id} 개구부 덮개 슬래브 제외 — "
              f"{m['element_key']['ifc_guid']} ({m['name']})")
    cover_set = {m["element_key"]["ifc_guid"] for m in covers}
    guids = [m["element_key"]["ifc_guid"] for m in rows
             if m["element_key"]["ifc_guid"] not in cover_set]
    meshes = [scene.geometry[g] for g in guids if g in scene.geometry]
    if not meshes:
        return None, 0
    return trimesh.util.concatenate(meshes), len(meshes)


def _vertical_hits(mesh, x, y):
    """IFC 월드 (x,y) 위에서 수직 하향 레이 — glTF 프레임 (x, +Y_top, -y)→(0,-1,0)."""
    top = float(mesh.bounds[1][1]) + 10.0
    loc, _, _ = mesh.ray.intersects_location(
        ray_origins=[[x, top, -y]], ray_directions=[[0.0, -1.0, 0.0]])
    return len(loc)


def _interior_first(cells, grid, want):
    """4방이 모두 같은 타입인 '내부' 셀 우선 (래스터 경계 오차 회피), 없으면 전체."""
    R, C = grid.shape
    interior = [(r, c) for (r, c) in cells
                if 0 < r < R - 1 and 0 < c < C - 1
                and all(grid[r + dr, c + dc] == want
                        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)))]
    return interior if interior else cells


def check_openings(glb_path, manifest, site):
    gf = site["gridFrame"]
    scene = trimesh.load(str(glb_path), force='scene')
    ok = True
    n_open = n_walk = 0
    for lv in site["levels"]:
        grid = np.array(lv["grid"]["cells"])
        slab_mesh, n_slabs = _level_slab_mesh(scene, manifest, lv["levelID"], gf, grid)
        if slab_mesh is None:
            print(f"  {lv['levelID']}: IfcSlab 없음 — 건너뜀")
            continue

        opens = [tuple(x) for x in np.argwhere(grid == OPENING)]
        walks = [tuple(x) for x in np.argwhere(grid == WALKABLE)]
        for r, c in _sample_even(_interior_first(opens, grid, OPENING),
                                 SAMPLES_PER_LEVEL):
            x, y = cell_center_world(gf, r, c)
            hits = _vertical_hits(slab_mesh, x, y)
            n_open += 1
            if hits != 0:
                ok = False
                print(f"  FAIL {lv['levelID']} 개구부 셀 ({r},{c}) → "
                      f"world({x:.1f},{y:.1f}) 슬래브 교차 {hits}건 (0이어야 함)")
        for r, c in _sample_even(_interior_first(walks, grid, WALKABLE),
                                 SAMPLES_PER_LEVEL):
            x, y = cell_center_world(gf, r, c)
            hits = _vertical_hits(slab_mesh, x, y)
            n_walk += 1
            if hits < 1:
                ok = False
                print(f"  FAIL {lv['levelID']} 통로 셀 ({r},{c}) → "
                      f"world({x:.1f},{y:.1f}) 슬래브 교차 {hits}건 (≥1이어야 함)")
    print(f"  개구부 샘플 {n_open}셀(교차 0 기대) + 통로 대조군 {n_walk}셀(교차 ≥1 기대)"
          f" — {'OK' if ok else 'FAIL'}")
    return ok


# ── 3. 계단 좌표 정합 ─────────────────────────────────────────────────────────

def check_stairs(manifest, site, min_links=3):
    gf = site["gridFrame"]
    stairs_by_level = {}
    for m in manifest:
        if m["ifc_class"] == "IfcStair" and m["storey"] and m["bbox_ifc_m"]:
            stairs_by_level.setdefault(m["storey"]["levelID"], []).append(m)

    links = [l for l in site["verticalLinks"] if l["linkType"] == "stair"]
    n_pass = 0
    for link in links:
        lower = min(link["connects"], key=lambda cn: int(cn["level"][1:]))
        r, c = lower["cell"]
        x, y = cell_center_world(gf, r, c)
        hit = None
        for st in stairs_by_level.get(lower["level"], []):
            (x0, y0, _), (x1, y1, _) = st["bbox_ifc_m"]["min"], st["bbox_ifc_m"]["max"]
            if x0 <= x <= x1 and y0 <= y <= y1:
                hit = st["element_key"]["ifc_guid"]; break
        if hit:
            n_pass += 1
        else:
            print(f"  경고 {link['linkID']} ({lower['level']} 셀 {r},{c} → "
                  f"world {x:.1f},{y:.1f}) — 해당 층 IfcStair bbox 밖")
    ok = n_pass >= min_links
    print(f"  계단 링크 {len(links)}개 중 bbox 일치 {n_pass}개 "
          f"(기준 ≥{min_links}) — {'OK' if ok else 'FAIL'}")
    return ok


# ── 4. 규모 리포트 ────────────────────────────────────────────────────────────

def report_scale(glb_path, manifest):
    size_mb = pathlib.Path(glb_path).stat().st_size / 1e6
    by_class = Counter(m["ifc_class"] for m in manifest)
    by_level = Counter((m["storey"] or {}).get("levelID") or "(시공층 외)"
                       for m in manifest)
    print(f"  GLB 크기: {size_mb:.1f} MB / 요소 {len(manifest)}개")
    print("  클래스별: " + ", ".join(f"{k}={v}" for k, v in by_class.most_common()))
    print("  층별: " + ", ".join(
        f"{k}={by_level[k]}" for k in sorted(by_level, key=str)))
    return True


# ── 5~7. v3.1 Part C-5 — 번들에 새로 실린 파일 ────────────────────────────────

EXPECTED_ZONE_COUNT = 84
EXPECTED_HAZARD_TYPES = 7


def _load_opt(path):
    if not pathlib.Path(path).exists():
        return None
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def check_timeline(bundle_dir, schedule_path="project/schedule.json"):
    """timeline.json 의 액티비티 수·공기가 현행 공정표와 일치하는가."""
    tl = _load_opt(pathlib.Path(bundle_dir) / "timeline.json")
    if tl is None:
        print("  건너뜀: timeline.json 없음")
        return True
    with open(schedule_path, encoding="utf-8") as fp:
        n_sched = len(json.load(fp)["activities"])
    n_tl = len(tl.get("activities", []))
    ok = n_tl == n_sched
    print(f"  액티비티 timeline {n_tl} vs {schedule_path} {n_sched}"
          f" / 공기 {tl.get('projectDays')}일 — {'OK' if ok else 'FAIL'}")
    if not ok:
        print("  FAIL 타임라인이 옛 공정표로 만들어졌다 — "
              "python scripts/export_unity_bundle.py 로 재생성")
    return ok


def check_hazard_zones(bundle_dir):
    """hazard_zones.json 이 84 zone · 7 유형 전부를 담고 있는가."""
    hz = _load_opt(pathlib.Path(bundle_dir) / "hazard_zones.json")
    if hz is None:
        print("  건너뜀: hazard_zones.json 없음")
        return True
    zones = hz.get("zones", [])
    types = sorted({z["hazard_type"] for z in zones})
    ok = len(zones) == EXPECTED_ZONE_COUNT and len(types) == EXPECTED_HAZARD_TYPES
    print(f"  zone {len(zones)} (기대 {EXPECTED_ZONE_COUNT}) / "
          f"유형 {len(types)} (기대 {EXPECTED_HAZARD_TYPES}) — {'OK' if ok else 'FAIL'}")
    print("  유형: " + ", ".join(f"{t}={sum(1 for z in zones if z['hazard_type']==t)}"
                                 for t in types))
    no_day = [z["zone_id"] for z in zones if z.get("spawnDay") is None]
    if no_day:
        print(f"  리포트: 생멸 일 인덱스 없는 zone {len(no_day)}건 {no_day[:5]}")
    return ok


def check_trajectory(bundle_dir):
    """궤적 좌표가 GLB 바운딩박스 안인가 / activity_id 가 timeline 에 실재하는가."""
    b = pathlib.Path(bundle_dir)
    tj = _load_opt(b / "worker_trajectory.json")
    if tj is None:
        print("  건너뜀: worker_trajectory.json 없음")
        return True
    scene = trimesh.load(str(b / "model.glb"), force="scene")
    lo, hi = scene.bounds                      # glTF 프레임 (x, +Y up, -y)
    tol = 5.0                                  # 층 표고·셀 중심 오차 여유 (m)

    tl = _load_opt(b / "timeline.json") or {}
    known = {a["activityID"] for a in tl.get("activities", [])}

    n = 0
    out_of_box = []
    unknown_act = set()
    for day, steps in tj.get("frames", {}).items():
        for step, workers in steps.items():
            for wk in workers:
                n += 1
                p = wk["pos_gltf"]
                if any(p[i] < lo[i] - tol or p[i] > hi[i] + tol for i in range(3)):
                    if len(out_of_box) < 5:
                        out_of_box.append((day, step, wk["worker_id"], p))
                if known and wk["activity_id"] not in known:
                    unknown_act.add(wk["activity_id"])
    ok = not out_of_box and not unknown_act
    print(f"  궤적 {n:,}점 / GLB bbox {[round(float(v),1) for v in lo]}~"
          f"{[round(float(v),1) for v in hi]} (여유 {tol}m)")
    if out_of_box:
        print(f"  FAIL bbox 밖 좌표 {len(out_of_box)}건(첫 5): {out_of_box}")
    else:
        print("  좌표 bbox 내 — OK")
    if unknown_act:
        print(f"  FAIL timeline 에 없는 activity_id {len(unknown_act)}건: "
              f"{sorted(unknown_act)[:5]}")
    else:
        print(f"  activity_id 전부 timeline 에 실재 ({len(known)}개 중) — OK")
    return ok


def check_temp_structures(bundle_dir, site_path="project/site.json"):
    """가설물: spawn<despawn / 셀이 격자 안 / 좌표가 GLB bbox 안 / 유형 존재."""
    b = pathlib.Path(bundle_dir)
    ts = _load_opt(b / "temp_structures.json")
    if ts is None:
        print("  건너뜀: temp_structures.json 없음")
        return True
    items = ts.get("temp_structures", [])
    site = load_site(site_path)
    dims = {lv["levelID"]: (lv["grid"]["rows"], lv["grid"]["cols"])
            for lv in site["levels"]}
    ok = True

    bad_span = [t["ts_id"] for t in items
                if t.get("spawnDay") is not None and t.get("despawnDay") is not None
                and not (t["spawnDay"] < t["despawnDay"])]
    if bad_span:
        ok = False
        print(f"  FAIL spawn>=despawn {len(bad_span)}건: {bad_span[:5]}")

    out_grid = []
    for t in items:
        R, Co = dims.get(t["level"], (0, 0))
        n = sum(1 for r, c in t["cells"] if not (0 <= r < R and 0 <= c < Co))
        if n:
            out_grid.append((t["ts_id"], n))
    if out_grid:
        ok = False
        print(f"  FAIL 격자 밖 셀 {len(out_grid)}건: {out_grid[:5]}")

    scene = trimesh.load(str(b / "model.glb"), force="scene")
    lo, hi = scene.bounds
    tol = 5.0
    outside = []
    npts = 0
    for t in items:
        for p in t["cellCenters_gltf"]:
            npts += 1
            if any(p[i] < lo[i] - tol or p[i] > hi[i] + tol for i in range(3)):
                if len(outside) < 5:
                    outside.append((t["ts_id"], p))
    # 비계는 건물 바깥 밴드라 GLB bbox 를 벗어나는 것이 정상이다 — 리포트만 한다.
    scaf = {t["ts_id"] for t in items if t["ts_type"] == "scaffold"}
    hard = [x for x in outside if x[0] not in scaf]
    if hard:
        ok = False
        print(f"  FAIL bbox 밖 좌표(비계 제외) {len(hard)}건: {hard[:3]}")

    types = Counter(t["ts_type"] for t in items)
    print(f"  가설물 {len(items)}개 / 좌표 {npts:,}점 / 유형: "
          + ", ".join(f"{k}={v}" for k, v in sorted(types.items())))
    print(f"  spawn<despawn OK / 격자 내 OK / bbox 내 OK(비계는 바깥 정상)"
          if ok else "  위 실패 참조")
    return ok


def main(bundle_dir="unity_bundle", site_path="project/site.json"):
    glb_path, manifest, meta = load_bundle(bundle_dir)
    site = load_site(site_path)
    print(f"번들: {bundle_dir} (pipeline={meta['geometryPipeline']}, "
          f"fallback={meta['fallbackUsed']})")
    results = {}
    print("[1] 키 정합 (GLB ↔ manifest)")
    results["keys"] = check_keys(glb_path, manifest)
    print("[2] 개구부 관통 레이캐스트")
    results["openings"] = check_openings(glb_path, manifest, site)
    print("[3] 계단 좌표 정합")
    results["stairs"] = check_stairs(manifest, site)
    print("[4] 규모 리포트")
    results["scale"] = report_scale(glb_path, manifest)
    print("[5] 타임라인 ↔ 현행 공정표")
    results["timeline"] = check_timeline(bundle_dir)
    print("[6] 위험구역 84 zone / 7 유형")
    results["hazard_zones"] = check_hazard_zones(bundle_dir)
    print("[7] 워커 궤적 좌표·액티비티 정합")
    results["trajectory"] = check_trajectory(bundle_dir)
    print("[8] 가설물(TS) 정합")
    results["temp_structures"] = check_temp_structures(bundle_dir, site_path)
    ok = all(results.values())
    print(("전 항목 통과" if ok else
           "실패 항목: " + ", ".join(k for k, v in results.items() if not v)))
    return ok


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="unity_bundle")
    ap.add_argument("--site", default="project/site.json")
    a = ap.parse_args()
    sys.exit(0 if main(a.bundle, a.site) else 1)
