"""U-트랙 — export_timeline.py v2 하위호환 섹션 검증 (levelAppear/activities/crewByDay).

[V2 갱신 이력] 데이터 원천이 construction_schedule.csv로 전환되고 build_timeline
시그니처가 (schedule, raw_acts, manifest, site)로 바뀌었다. v1의 'hazards'(lifecycle
인스턴스 압축) 배열은 hazardSpans로 대체되었으므로, 그를 검증하던
test_hazard_* / test_real_hazards_match_instances 는 제거하고 hazardSpans/elementAppear
검증은 test_v2_timeline.py로 이관했다. 아래는 v2에서도 유효한 하위호환 섹션만 유지한다.
"""
import json
import pathlib

import pytest

from schedule import Schedule
import export_timeline as X

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "project" / "schedule.json"
SITE = ROOT / "project" / "site.json"
MANIFEST = ROOT / "unity_bundle" / "manifest.json"


@pytest.fixture(scope="module")
def timeline():
    sch = Schedule.load(str(SCHEDULE))
    raw = X._load_raw_activities(str(SCHEDULE))
    with open(MANIFEST, encoding="utf-8") as fp:
        manifest = json.load(fp)
    with open(SITE, encoding="utf-8") as fp:
        site = json.load(fp)
    return X.build_timeline(sch, raw, manifest, site), sch


def test_level_appear_monotonic(timeline):
    tl, _ = timeline
    appear = tl["levelAppear"]
    order = sorted(appear, key=lambda lv: int(lv.lstrip("L")))
    assert order == [f"L{i}" for i in range(1, len(order) + 1)]
    values = [appear[lv] for lv in order]
    assert all(a < b for a, b in zip(values, values[1:])), values


def test_activities_es_ef_identical(timeline):
    tl, sch = timeline
    assert len(tl["activities"]) == len(sch.activities)
    for row in tl["activities"]:
        a = sch.activities[row["activityID"]]
        assert (row["es"], row["ef"]) == (a.es, a.ef)
        assert row["trade"] == a.trade and row["zone"] == a.zone
        assert row["crewSize"] == a.crew_size


def test_manifest_levels_covered(timeline):
    tl, _ = timeline
    covered = set(tl["levelAppear"]) | set(tl["alwaysVisibleLevels"])
    assert X.manifest_level_ids(str(MANIFEST)) <= covered


def test_crew_by_day_matches_crews_on_site(timeline):
    tl, sch = timeline
    got = {}
    for row in tl["crewByDay"]:
        key = (row["day"], row["trade"])
        got[key] = got.get(key, 0) + row["count"]
    want = {(d, t): n
            for d in range(sch.duration)
            for t, n in sch.crewsOnSite(d).items()}
    assert got == want
