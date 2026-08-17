"""P3-5 — TemporalRule 실행기: scheduleShift 파싱 규약 + 스케줄 재계산(선후행/양생 lag)."""
import pathlib

from schedule import Schedule, Activity, Predecessor, Calendar
from controls import parse_schedule_shift, apply_temporal_shift

PROJECT = pathlib.Path(__file__).resolve().parent.parent / "project"


def _act(aid, dur, preds=(), trade="rebar", zone="L1:Z-A", wt=""):
    return Activity(aid, aid, trade, zone, dur, [Predecessor(*p) for p in preds], 4, {}, wt)


def test_parse_patterns():
    assert parse_schedule_shift("set FS_lag(slab_pour -> opening_closure) = 0 days") == {
        "kind": "set_fs_lag", "from_work": "slab_pour", "to_work": "opening_closure", "lag_days": 0}
    assert parse_schedule_shift(
        "add precedence condition: formwork_stripping(Z) requires strength_verified(Z) "
        "[min curing lag enforced]")["kind"] == "min_curing_lag"
    assert parse_schedule_shift(
        "set precedence: opening_closure(Z) FS-before formwork_stripping(Z)")["kind"] == "fs_before"
    assert parse_schedule_shift("무관한 텍스트")["kind"] == "unsupported"


def test_min_curing_lag_enforced():
    # 타설(2d) → 해체, FS lag 1일 → 최소 6일 강제 시 해체 시작이 밀림
    pour = _act("P", 2, trade="concrete_pour", wt="slab")
    strip = _act("S", 2, [("P", "FS", 1)], trade="formwork_stripping", wt="strip")
    sch = Schedule("t", Calendar({}), [pour, strip])
    assert strip.es == pour.ef + 1
    n = apply_temporal_shift(sch, "min curing lag enforced", min_curing_days=6)
    assert n == 1
    assert strip.es == pour.ef + 6                 # 재-CPM 반영


def test_set_fs_lag_synthetic():
    pour = _act("P", 2, trade="concrete_pour", wt="slab")
    clo = _act("C", 3, [("P", "FS", 5)], trade="material_handling", wt="opening_closure")
    sch = Schedule("t", Calendar({}), [pour, clo])
    assert clo.es == pour.ef + 5
    n = apply_temporal_shift(sch, "set FS_lag(slab_pour -> opening_closure) = 0 days")
    assert n == 1 and clo.es == pour.ef           # lag 0


def test_min_curing_on_real_schedule_only_lengthens():
    # 실제 공정표에 양생 최소 lag 강제 → 총 공기가 줄지 않음(같거나 늘어남)
    sch = Schedule.load(str(PROJECT / "schedule.json"))
    before = sch.duration
    apply_temporal_shift(sch, "min curing lag enforced", min_curing_days=6)
    assert sch.duration >= before
