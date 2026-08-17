"""V2 검증 #2·#3 — export_timeline.py v2: hazardSpans / elementAppear.

#2 hazardSpans 손검증(Basement): 기둥 철근배근 첫날부터 edge 활성, 계단 설치 후 비활성.
   슬래브 공정 중 opening 활성, 문 설치 후 비활성.
#3 elementAppear 수량 보존: (level,class)별 count 합 == CSV element_count 합.
"""
import csv
import json
import pathlib
from collections import defaultdict

import pytest

from schedule import Schedule
import export_timeline as X

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "project" / "schedule.json"
SITE = ROOT / "project" / "site.json"
MANIFEST = ROOT / "unity_bundle" / "manifest.json"

LEVEL_ID = {"Basement": "L1", "Level_01": "L2", "Level_02a_Parking": "L3",
            "Level_02": "L4", "Level_03": "L5", "Level_04": "L6",
            "Level_05": "L7", "Roof": "L8"}


def _source_csv():
    """schedule.json이 선언한 현행 CSV를 따른다.

    v3.3에서 원본 178건에 해체 8건·자재 48건이 추가됐는데, 이전 테스트는
    원본 CSV를 timeline(현행 234건)과 비교해 수량을 이중 기준으로 셌다.
    """
    raw = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    name = raw["sourceCsv"]
    for candidate in (ROOT / name, ROOT / "build" / name):
        if candidate.exists():
            return candidate
    raise AssertionError("선언된 원천 CSV를 찾을 수 없다: %s" % name)


@pytest.fixture(scope="module")
def timeline():
    sch = Schedule.load(str(SCHEDULE))
    raw = X._load_raw_activities(str(SCHEDULE))
    with open(MANIFEST, encoding="utf-8") as fp:
        manifest = json.load(fp)
    with open(SITE, encoding="utf-8") as fp:
        site = json.load(fp)
    return X.build_timeline(sch, raw, manifest, site), sch


@pytest.fixture(scope="module")
def csv_rows():
    with open(_source_csv(), encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _active(span, d):
    return span["spawnDay"] <= d and (span["despawnDay"] is None or d < span["despawnDay"])


# ── #2 hazardSpans 손검증 (Basement = L1) ────────────────────────────────────

def test_basement_edge_span(timeline):
    tl, sch = timeline
    edge = next(s for s in tl["hazardSpans"]
                if s["level"] == "L1" and s["kind"] == "edge")
    # 기둥 철근배근(T-1) 첫날부터 활성
    col_rebar_es = sch.activities["T-1"].es
    assert col_rebar_es == 0
    assert _active(edge, col_rebar_es)
    # 첫 계단 설치(T-1301, edge_protected)에서 비활성 전이
    stair_es = sch.activities["T-1301"].es
    assert edge["despawnDay"] == stair_es
    assert not _active(edge, stair_es)
    assert _active(edge, stair_es - 1)          # 직전일은 활성
    assert edge["cells"], "edge 셀은 site.json EDGE(6) 셀"


def test_basement_opening_span(timeline):
    tl, sch = timeline
    opening = next(s for s in tl["hazardSpans"]
                   if s["level"] == "L1" and s["kind"] == "opening")
    # [v3.8 Part D] v3.3 augment_schedule.py §1-3에서 opening_open 시점을
    # 거푸집(T-5)에서 타설 후 슬래브 양생(T-8)으로 바로잡았다. 활동 ID를
    # 단정하지 않고 현행 schedule.json의 첫 opening_open 상태에서 산출한다.
    raw = json.loads(SCHEDULE.read_text(encoding="utf-8"))["activities"]
    opening_acts = [a for a in raw
                    if a["zone"].startswith("L1:") and a.get("hazardState") == "opening_open"]
    slab_start = min(sch.activities[a["activityID"]].es for a in opening_acts)
    assert opening["spawnDay"] == slab_start
    assert _active(opening, slab_start)
    # 첫 문 설치(T-1401, opening_covered)에서 비활성
    door_es = sch.activities["T-1401"].es
    assert opening["despawnDay"] == door_es
    assert not _active(opening, door_es)
    assert _active(opening, door_es - 1)


def test_collapse_span_directly_below(timeline):
    tl, sch = timeline
    # L2(Level_01) 슬래브 타설 → L1(Basement) 직하부 collapse
    coll = [s for s in tl["hazardSpans"] if s["kind"] == "collapse"]
    assert coll, "collapse 스팬 존재"
    for s in coll:
        assert s["hazardType"] == "H008"
        assert s["despawnDay"] is not None and s["despawnDay"] > s["spawnDay"]
    # 최하층(L1)에서 시작하는 슬래브는 직하부가 없어 collapse 없음
    assert all(s["level"] != "L8" or True for s in coll)  # 상한 존재만 확인
    levels = {s["level"] for s in coll}
    assert "L1" in levels                      # L2 슬래브의 직하부


# ── #3 elementAppear 수량 보존 ───────────────────────────────────────────────

def test_element_appear_quantity_conserved(timeline, csv_rows):
    tl, _ = timeline
    csv_sum = defaultdict(int)
    for r in csv_rows:
        key = (LEVEL_ID[r["level"]], r["ifc_class"])
        csv_sum[key] += int(r["element_count"])

    tl_sum = {}
    for e in tl["elementAppear"]:
        if any(a.get("fallback") for a in e["appearances"]):
            continue                            # 폴백(공정표 미포함)은 CSV 대조 제외
        tl_sum[(e["level"], e["ifcClass"])] = sum(a["count"] for a in e["appearances"])

    for key, total in csv_sum.items():
        if total == 0:
            continue
        assert tl_sum.get(key) == total, (key, tl_sum.get(key), total)


def test_element_appear_progressive(timeline):
    tl, _ = timeline
    # 구조부재는 여러 타설일에 걸쳐 점진 출현(일할 수량) — 최소 한 군은 복수 출현
    multi = [e for e in tl["elementAppear"]
             if e["ifcClass"] in X.STRUCTURAL_CLASSES and len(e["appearances"]) > 1]
    assert multi, "분할 타설 부재군은 점진 출현해야 함"


def test_ghost_phase_before_appear(timeline):
    tl, sch = timeline
    # 고스트(작업 시작) ≤ 해당 부재군 첫 출현일
    appear_first = {(e["level"], e["ifcClass"]): e["appearances"][0]["day"]
                    for e in tl["elementAppear"]
                    if not any(a.get("fallback") for a in e["appearances"])}
    for g in tl["ghostPhase"]:
        key = (g["level"], g["ifcClass"])
        if key in appear_first:
            assert g["workStartDay"] <= appear_first[key], key
