"""U-트랙 — unity_bundle/ 산출물 검증 (check_unity_bundle 4항목의 pytest 래퍼).

전제: build_site_json.py로 project/site.json, build_unity_bundle.py로 unity_bundle/
생성 후 실행. 좌표 계약(ROADMAP §2): IFC 월드좌표 m Z-up이 정본, glTF는 +Y up.
"""
import json
import pathlib

import pytest

import check_unity_bundle as C

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "unity_bundle"
SITE = ROOT / "project" / "site.json"


def test_bundle_files_present():
    for f in ("model.glb", "manifest.json", "bundle_meta.json"):
        assert (BUNDLE / f).exists(), f


@pytest.fixture(scope="module")
def bundle():
    glb, manifest, meta = C.load_bundle(BUNDLE)
    return glb, manifest, meta, C.load_site(SITE)


def test_meta_contract(bundle):
    _, manifest, meta, site = bundle
    assert meta["units"] == "m"
    assert meta["gltf_up"] == "+Y"
    assert "Z-up" in meta["worldCRS"]
    assert meta["gridFrame"] == site["gridFrame"]     # site.json 사본과 일치
    assert meta["elementCount"] == len(manifest)
    assert meta["sourceIFC"] == site["sourceIFC"]
    # element_key 계약: revit_uid는 예약 필드 — 항상 null
    assert all(m["element_key"]["revit_uid"] is None for m in manifest)


def test_key_alignment(bundle):
    glb, manifest, _, _ = bundle
    assert C.check_keys(glb, manifest)


def test_opening_raycast(bundle):
    glb, manifest, _, site = bundle
    assert C.check_openings(glb, manifest, site)


def test_stair_bbox_alignment(bundle):
    _, manifest, _, site = bundle
    assert C.check_stairs(manifest, site)
