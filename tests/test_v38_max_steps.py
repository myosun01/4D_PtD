"""v3.8 Part A — max_steps 조사 러너의 집계·읽기 전용 해상도 진단."""
from types import SimpleNamespace

import fourd

from scripts import sweep_max_steps as S


def test_time_bands_use_strict_boundaries():
    assert S.time_band(8 * 3600) == "8시간 이내"
    assert S.time_band(8 * 3600 + 1) == "8~24시간"
    assert S.time_band(24 * 3600 + 1) == "24~72시간"
    assert S.time_band(72 * 3600 + 1) == "72시간 초과"


def test_linearity_and_channel_direction_are_data_driven():
    assert S.linearity_label(6.0, 6.0) == "선형"
    assert S.linearity_label(1.5, 6.0) == "sublinear"
    assert S.linearity_label(7.0, 6.0) == "superlinear"
    assert "통과형→체류형" in S.channel_shift_label(20, 30, 70, 60)
    assert "체류형→통과형" in S.channel_shift_label(30, 20, 60, 70)
    assert "혼합" in S.channel_shift_label(20, 30, 60, 70)


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


def test_reach_probe_accepts_commute_logger_interface():
    probe = S.ReachProbe()
    assert probe.log_commute(0, object(), object()) is None


def test_hazard_exposure_filters_active_days_and_deduplicates_same_type(monkeypatch):
    # 같은 H004 셀의 두 인스턴스가 [1,3), [2,4)에 겹친다. 합집합 [1,4)만
    # 한 번 세어야 하므로 day 0·4는 제외되고 day 2도 중복되지 않는다.
    h1 = SimpleNamespace(hazard_type="H004", level="L1", cells=((1, 1),),
                         spawn_day=1, despawn_day=3)
    h2 = SimpleNamespace(hazard_type="H004", level="L1", cells=((1, 1),),
                         spawn_day=2, despawn_day=4)
    monkeypatch.setattr(fourd, "instance_exposure_cells", lambda h: h.cells)
    result = {"exposure_steps": {
        ("L1", 1, 1, day, "material"): 10.0 for day in range(5)
    }}
    got = S.haz_exposure(result, SimpleNamespace(instances=[h1, h2]))
    assert got == {"H004": 30.0}


def test_exposure_channel_totals_preserve_engine_total():
    result = {"exposure_steps": {
        ("L1", 0, 0, 0, "fall"): 1.0,
        ("L1", 0, 1, 0, "edge"): 2.0,
        ("L1", 0, 2, 0, "material"): 3.0,
        ("L1", 0, 3, 0, "narrow"): 4.0,
        ("L1", 0, 4, 0, "drop_zone"): 5.0,
        ("L1", 0, 5, 0, "collapse_zone"): 6.0,
    }}
    got = S.exposure_channel_totals(result)
    assert got == {"dwell_time": 3.0,
                   "passage_count": 12.0,
                   "zone_occupancy": 6.0}
    assert sum(got.values()) == sum(result["exposure_steps"].values())
