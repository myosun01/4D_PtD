"""v3.8 Part A — max_steps 조사 러너의 집계·읽기 전용 해상도 진단."""
from scripts import sweep_max_steps as S


def test_time_bands_use_strict_boundaries():
    assert S.time_band(8 * 3600) == "8시간 이내"
    assert S.time_band(8 * 3600 + 1) == "8~24시간"
    assert S.time_band(24 * 3600 + 1) == "24~72시간"
    assert S.time_band(72 * 3600 + 1) == "72시간 초과"


def test_2m_opening_probe_reproduces_1m_source():
    measured = S.measure_openings_at_2m()
    assert measured["openings"] == 39
    assert measured["validation_1m_equal"] is True
    assert measured["zero_cells"] == 0
    assert measured["one_or_fewer"] == 0
    assert (measured["min_cells"], measured["median_cells"], measured["max_cells"]) == (4, 6, 11)


def test_probe_summaries_are_weighted_by_worker_days():
    a = {"worker_days": 2, "never_arrived": 1, "visits_total": 1,
         "arrival_steps": [10], "state_steps": {"work": 4, "travel": 6}}
    b = {"worker_days": 3, "never_arrived": 0, "visits_total": 6,
         "arrival_steps": [20, 30, 40], "state_steps": {"work": 9, "travel": 3}}
    got = S.aggregate_probe_summaries([a, b])
    assert got["worker_days"] == 5
    assert got["never_arrived_pct"] == 20.0
    assert got["visits_per_worker_day"] == 1.4
    assert got["arrive_median"] == 25.0
    assert got["arrive_p90"] == 40
    assert got["work_step_pct"] == 100.0 * 13 / 22
