"""P1-3 — schedule.py CPM 전진계산(FS/SS/FF+lag) 및 조회 API 검증.

손계산 DAG로 ES/EF/임계경로를 대조하고, 실제 공정표의
불변식(모든 액티비티 스케줄됨, activeSet/crewsOnSite 정합)을 확인한다.
"""
import csv
import json
import pathlib
from datetime import date

import pytest

from schedule import Schedule, Activity, Predecessor, Calendar, TRADES


ROOT = pathlib.Path(__file__).resolve().parent.parent


def _act(aid, dur, preds=(), trade="rebar", zone="L1:Z-A", crew=4, wt=""):
    return Activity(activity_id=aid, name=aid, trade=trade, zone=zone,
                    duration_days=dur,
                    predecessors=[Predecessor(*p) for p in preds],
                    crew_size=crew, daily_pattern={}, work_type=wt)


def _mini():
    """손계산 DAG (FS/SS/FF+lag 모두 포함).

    A(0,3) → B FS+1 (4,6) ; A → C SS+2 (2,6) ; D ← B FS, C FF+1  →  D(6,8)
    """
    A = _act("A", 3)
    B = _act("B", 2, [("A", "FS", 1)])
    C = _act("C", 4, [("A", "SS", 2)])
    D = _act("D", 2, [("B", "FS", 0), ("C", "FF", 1)])
    return Schedule("mini", Calendar({}), [A, B, C, D])


def test_forward_pass_handcalc():
    s = _mini()
    got = {k: (a.es, a.ef) for k, a in s.activities.items()}
    assert got == {"A": (0, 3), "B": (4, 6), "C": (2, 6), "D": (6, 8)}
    assert s.duration == 8


def test_critical_path_handcalc():
    assert _mini().critical_path() == ["A", "B", "D"]


def test_state_transitions():
    B = _mini().activities["B"]          # es=4, ef=6
    assert B.state(3) == "not_started"
    assert B.state(4) == "in_progress"
    assert B.state(5) == "in_progress"
    assert B.state(6) == "completed"


def test_active_set_and_crews():
    s = _mini()
    assert s.activeSet(0) == {"A"}
    assert "C" in s.activeSet(2)
    total = sum(s.activities[a].crew_size for a in s.activeSet(2))
    assert sum(s.crewsOnSite(2).values()) == total


def test_snake_case_aliases():
    s = _mini()
    assert s.active_set(2) == s.activeSet(2)
    assert s.crews_on_site(2) == s.crewsOnSite(2)


def test_cycle_detected():
    A = _act("A", 2, [("B", "FS", 0)])
    B = _act("B", 2, [("A", "FS", 0)])
    with pytest.raises(ValueError):
        Schedule("cyc", Calendar({}), [A, B])


def test_invalid_trade_rejected():
    with pytest.raises(ValueError):
        Schedule("bad", Calendar({}), [_act("X", 1, trade="welding")])


def test_undefined_predecessor_rejected():
    with pytest.raises(ValueError):
        Schedule("u", Calendar({}), [_act("A", 1, [("ZZZ", "FS", 0)])])


def test_calendar_workday_mapping():
    # 2024-01-01 = 월요일. workdays MON-SAT → 일요일(01-07) 건너뜀.
    cal = Calendar({"workdays": "MON-SAT", "startDate": "2024-01-01"})
    assert cal.to_date(0) == date(2024, 1, 1)   # Mon
    assert cal.to_date(5) == date(2024, 1, 6)   # Sat
    assert cal.to_date(6) == date(2024, 1, 8)   # 다음 Mon (일요일 스킵)


# ── 실제 프로젝트 데이터 ──
def test_real_schedule_counts(real_schedule):
    # [v3.8 Part D] v3.3 augment_schedule.py가 원본 178건에 해체 8건과
    # 자재 반입·소진 48건을 더해 234건으로 만들었다. 234를 다시 박지 않고
    # 원본 행수 + 현행 CSV의 origin별 추가 행수로 산출해 검증한다.
    raw = json.loads((ROOT / "project" / "schedule.json").read_text(encoding="utf-8"))
    source = ROOT / "build" / raw["sourceCsv"]
    with (ROOT / "construction_schedule.csv").open(encoding="utf-8-sig", newline="") as fp:
        original = list(csv.DictReader(fp))
    with source.open(encoding="utf-8-sig", newline="") as fp:
        current = list(csv.DictReader(fp))
    strip = sum(r.get("origin") == "augment:strip" for r in current)
    material = sum(r.get("origin") == "augment:material" for r in current)
    assert (len(original), strip, material) == (178, 8, 48)
    assert len(real_schedule.activities) == len(original) + strip + material
    assert real_schedule.duration == max(a.ef for a in real_schedule.activities.values())


def test_real_all_scheduled(real_schedule):
    for a in real_schedule.activities.values():
        assert a.es is not None and a.ef is not None
        assert a.ef == a.es + a.duration_days
        assert a.trade in TRADES


def test_real_active_set_invariant(real_schedule):
    s = real_schedule
    for d in (0, 100, 200, 300, s.duration - 1):
        active = s.activeSet(d)
        for aid in active:
            assert s.activities[aid].state(d) == "in_progress"
        total = sum(s.activities[a].crew_size for a in active)
        assert sum(s.crewsOnSite(d).values()) == total


def test_real_critical_path_is_chain(real_schedule):
    s = real_schedule
    cp = s.critical_path()
    assert s.activities[cp[-1]].ef == s.duration
    for prev, cur in zip(cp, cp[1:]):
        assert any(p.activity == prev for p in s.activities[cur].predecessors)
