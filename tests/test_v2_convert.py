"""V2 검증 #1 — convert_schedule_csv.py: CSV → schedule.json v2.

핵심: 날짜 입력 금지(§3)를 지키되 엔진 CPM ES/EF가 CSV 날짜를 전건 재현하는지 확인.
day 0 = 2024-01-01, calendar MON-SUN(전 요일 작업일).
"""
import csv
import datetime as dt
import json
import pathlib

import pytest

from schedule import Schedule, TRADES
import convert_schedule_csv as CV

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "project" / "schedule.json"
BASE = dt.date(2024, 1, 1)

# [v3.8 Part D] CSV 경로를 고정하지 않는다.
# v3.3 `scripts/augment_schedule.py` 가 `construction_schedule.csv`(178행)를
# **원본 그대로 두고** `build/construction_schedule_v2.csv`(234행)를 새로 만들었고,
# `project/schedule.json` 은 그 뒤로 v2 를 원천으로 삼는다(`sourceCsv` 필드).
# 여기서 v1 을 고정 참조하면 원천이 바뀔 때마다 테스트가 낡는다 —
# schedule.json 이 스스로 선언한 원천을 따라간다.
def _source_csv() -> pathlib.Path:
    src = json.loads(SCHEDULE.read_text(encoding="utf-8")).get("sourceCsv")
    assert src, "schedule.json 에 sourceCsv 선언이 없다"
    for cand in (ROOT / src, ROOT / "build" / src):
        if cand.exists():
            return cand
    raise AssertionError("선언된 원천 CSV 를 찾을 수 없다: %s" % src)


CSV = _source_csv()


@pytest.fixture(scope="module")
def csv_rows():
    with open(CSV, encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


@pytest.fixture(scope="module")
def schedule():
    return Schedule.load(str(SCHEDULE))


# ── #1 CPM 재현: 엔진 ES/EF ↔ CSV 날짜 178건 전건 일치 ────────────────────────

def test_cpm_reproduces_csv_dates(schedule, csv_rows):
    # 건수를 박지 않는다 — 원천 CSV 행수와 일치하는지만 본다 (v3.8 Part D).
    assert len(schedule.activities) == len(csv_rows)
    for r in csv_rows:
        a = schedule.activities[f"T-{r['task_id']}"]
        es_expect = (dt.date.fromisoformat(r["start_date"]) - BASE).days
        ef_expect = (dt.date.fromisoformat(r["end_date"]) - BASE).days + 1  # ef 배타적
        assert a.es == es_expect, (r["task_id"], a.es, es_expect)
        assert a.ef == ef_expect, (r["task_id"], a.ef, ef_expect)


def test_calendar_mon_sun(schedule):
    # 일요일 시작 태스크 존재 → 전 요일 작업일이어야 CPM이 날짜를 재현
    assert schedule.calendar.workdays == {0, 1, 2, 3, 4, 5, 6}


# ── 스키마 v2: trade 어휘·양생 플래그·elementBinding 하위호환 ─────────────────

def test_trades_in_vocabulary(schedule):
    for a in schedule.activities.values():
        assert a.trade in TRADES


def test_curing_tasks_zero_crew(schedule):
    raw = _raw()
    curing = [a for a in raw if a.get("isCuring")]
    assert len(curing) == 22
    for a in curing:
        assert a["crewSize"] == 0
        assert a["trade"] == "concrete_pour"      # 트리거 매칭용 보존


def test_curing_hazard_state_follows_pour_order(schedule):
    """[v3.8 Part D] 이 테스트는 원래 `hazardState == ""` 를 단정했다.

    v3.3 `scripts/augment_schedule.py` §1-3 이 상태 부여 시점을 고쳤다 —
    슬래브 개구부는 **타설 이후**에 존재하므로, 거푸집면이 곧 작업면인 단계
    (거푸집·철근·타설)에서 `opening_open` 을 떼어 `edge_open` 으로 바꾸고
    **슬래브 양생**에 `opening_open` 을 붙였다.
    따라서 "양생은 위험상태 없음" 은 더 이상 참이 아니다. 건수를 박는 대신
    그 규칙 자체를 검증한다 (`build/schedule_augment_log.md` §1-3).
    """
    raw = _raw()
    for a in raw:
        if not a.get("isCuring"):
            continue
        is_slab = "슬래브" in a["name"]
        assert a["hazardState"] == ("opening_open" if is_slab else ""), a["activityID"]
    # 같은 규칙의 뒷면: 슬래브 타설·거푸집 단계는 개구부가 아니라 단부다
    for a in raw:
        if "슬래브" in a["name"] and a["workType"] in ("formwork", "rebar", "pour"):
            assert a["hazardState"] in ("edge_open", ""), a["activityID"]


def test_element_binding_present(schedule):
    raw = _raw()
    for a in raw:
        eb = a["elementBinding"]
        assert set(eb) >= {"ifcClass", "elementType", "elementCount"}
        assert eb["ifcClass"].startswith("Ifc")


def test_backward_compat_schedule_load(schedule, csv_rows):
    # 신규 필드가 있어도 기존 Schedule.load/CPM이 정상 동작 (예외 없이 로드됨)
    # [v3.8 Part D] 공기는 409 였다. v3.3 augment_schedule.py §1-4 에서 350 이 됐다 —
    # 해체 8건이 늘었는데도 줄어든 이유는 층간 중첩(층 N 마감이 층 N+1 골조와 겹침)
    # 이다. 값을 박지 않고 원천 CSV 의 최종 종료일에서 유도해 대조한다.
    last = max(dt.date.fromisoformat(r["end_date"]) for r in csv_rows)
    assert schedule.duration == (last - BASE).days + 1
    # v3.3 자재 반입 태스크가 day 0에도 생겼다. 특정 딕셔너리를 박지 않고
    # activeSet과 각 activity의 crew_size에서 현장 인원을 독립 산출한다.
    expected = {}
    for aid in schedule.activeSet(0):
        a = schedule.activities[aid]
        expected[a.trade] = expected.get(a.trade, 0) + a.crew_size
    assert schedule.crewsOnSite(0) == expected
    assert expected["rebar"] == 6
    assert expected["material_handling"] == 8


def _raw():
    import json
    with open(SCHEDULE, encoding="utf-8") as fp:
        return json.load(fp)["activities"]
