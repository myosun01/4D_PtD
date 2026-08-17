"""P1-4 — lifecycle.py 생멸 엔진 검증 (템플릿×바인딩 조인, 일 경계 의미론).

실제 TTL 템플릿 4종을 사용하되, 합성 미니 공정표 + 임시 바인딩으로 날짜 경계를
정밀 검증한다: 타설완료 익일 개구부 spawn, 마감완료 익일 despawn,
동바리(started)는 타설일부터 해체완료까지, collapse_zone은 직하부 층 생성.
"""
import json
from collections import Counter

import pytest

from schedule import Schedule, Activity, Predecessor, Calendar
from lifecycle import LifecycleEngine, parse_trigger


def _act(aid, dur, preds=(), trade="rebar", zone="L1:Z-A", wt=""):
    return Activity(activity_id=aid, name=aid, trade=trade, zone=zone,
                    duration_days=dur,
                    predecessors=[Predecessor(*p) for p in preds],
                    crew_size=4, daily_pattern={}, work_type=wt)


def _bindings_file(tmp_path, bindings):
    p = tmp_path / "bindings.json"
    p.write_text(json.dumps({"bindings": bindings}, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_opening_spawn_and_despawn_day(library, tmp_path):
    # dummy(0..10) → pour[L2 slab](10..12) → closure[opening_closure](12..17)
    dummy = _act("D0", 10)
    pour = _act("P", 2, [("D0", "FS", 0)], trade="concrete_pour", zone="L2:Z-A", wt="slab")
    closure = _act("C", 5, [("P", "FS", 0)], trade="material_handling",
                   zone="L2:Z-A", wt="opening_closure")
    sch = Schedule("s", Calendar({}), [dummy, pour, closure])
    assert (pour.es, pour.ef) == (10, 12)
    assert (closure.es, closure.ef) == (12, 17)

    binds = [{"template": "LCR_SLAB_OPENING", "boundActivity": "P",
              "spawnLocation": {"level": "L2", "cells": [[19, 4]]},
              "despawnActivity": "C"}]
    eng = LifecycleEngine(library.lifecycle_templates, _bindings_file(tmp_path, binds), sch)
    h = eng.instances[0]

    assert h.hazard_type == "H001" and h.level == "L2"
    # 타설 완료 익일(=ef)에 spawn
    assert h.spawn_day == pour.ef == 12
    assert not h.active(11) and h.active(12)
    # 마감 완료 익일(=ef)에 despawn
    assert h.despawn_day == closure.ef == 17
    assert h.active(16) and not h.active(17)
    # hazards(d) 질의는 활성 인스턴스만 반환
    assert h in eng.hazards(12) and h not in eng.hazards(11)


def test_collapse_zone_directly_below(library, tmp_path):
    # L2 타설(started 트리거) → 직하부 L1 collapse_zone, 해체 완료까지 활성.
    dummy = _act("D0", 5)
    pour = _act("P2", 2, [("D0", "FS", 0)], trade="concrete_pour", zone="L2:Z-A", wt="slab")
    strip = _act("S2", 3, [("P2", "FS", 3)], trade="formwork_stripping", zone="L2:Z-A", wt="strip")
    sch = Schedule("s", Calendar({}), [dummy, pour, strip])
    assert (pour.es, pour.ef) == (5, 7)
    assert (strip.es, strip.ef) == (10, 13)

    binds = [{"template": "LCR_SHORING_COLLAPSE", "boundActivity": "P2",
              "spawnLocation": {"level": "L1", "cells": [[3, 4]]},
              "despawnActivity": "S2"}]
    eng = LifecycleEngine(library.lifecycle_templates, _bindings_file(tmp_path, binds), sch)
    h = eng.instances[0]

    assert h.hazard_type == "H008"
    assert h.level == "L1"                    # 직하부 (L2 - 1)
    assert h.spawn_day == pour.es == 5        # started 트리거 → 시작일
    assert h.despawn_day == strip.ef == 13    # 해체 완료 익일
    assert h.active(5) and h.active(12) and not h.active(13)


def test_below_level_helper(library, tmp_path):
    eng = LifecycleEngine(library.lifecycle_templates, _bindings_file(tmp_path, []),
                          Schedule("s", Calendar({}), [_act("X", 1)]))
    assert eng._below_level("L3") == "L2"
    assert eng._below_level("L2") == "L1"
    assert eng._below_level("L1") is None


def test_lowest_level_collapse_rejected(library, tmp_path):
    # L1 타설에 collapse 바인딩 → 직하부 없음 → 오류.
    pour = _act("P1", 2, trade="concrete_pour", zone="L1:Z-A", wt="slab")
    strip = _act("S1", 2, [("P1", "FS", 0)], trade="formwork_stripping", zone="L1:Z-A")
    sch = Schedule("s", Calendar({}), [pour, strip])
    binds = [{"template": "LCR_SHORING_COLLAPSE", "boundActivity": "P1",
              "spawnLocation": {"level": "L1", "cells": [[1, 1]]}, "despawnActivity": "S1"}]
    with pytest.raises(ValueError):
        LifecycleEngine(library.lifecycle_templates, _bindings_file(tmp_path, binds), sch)


def test_spawn_filter_mismatch_rejected(library, tmp_path):
    # 개구부 템플릿(spawn 필터 trade=concrete_pour)에 rebar 액티비티 바인딩 → 오류.
    reb = _act("R", 2, trade="rebar", zone="L2:Z-A", wt="slab")
    sch = Schedule("s", Calendar({}), [reb])
    binds = [{"template": "LCR_SLAB_OPENING", "boundActivity": "R",
              "spawnLocation": {"level": "L2", "cells": [[1, 1]]}, "despawnActivity": None}]
    with pytest.raises(ValueError):
        LifecycleEngine(library.lifecycle_templates, _bindings_file(tmp_path, binds), sch)


def test_parse_trigger():
    t = parse_trigger("activity[trade=concrete_pour, workType=slab].completed")
    assert t.state == "completed"
    assert t.filters["trade"] == "concrete_pour"
    assert t.filters["workType"] == "slab"


# ── 실제 프로젝트 데이터 ──
def test_real_instances_load_intact(real_lifecycle):
    # 무결 로드 자체가 boundActivity/despawnActivity/필터/층 정합의 통합 검증.
    assert len(real_lifecycle.instances) == 21


def test_real_hazard_type_breakdown(real_lifecycle):
    assert Counter(h.hazard_type for h in real_lifecycle.instances) == \
        Counter({"H007": 8, "H001": 6, "H008": 7})


def test_real_collapse_zone_below(real_lifecycle, real_schedule):
    h008 = [h for h in real_lifecycle.instances if h.hazard_type == "H008"]
    assert h008
    for h in h008:
        n = int(real_schedule.activities[h.bound_activity].level.lstrip("L"))
        assert h.level == f"L{n - 1}"


def test_real_h008_first_three_levels(real_lifecycle):
    # 지침 명시 스펙: collapse_zone이 직하부 층에 순서대로 생성됨
    levels = [h.level for h in real_lifecycle.instances if h.hazard_type == "H008"]
    assert levels[:3] == ["L1", "L2", "L3"]


def test_real_hazards_query_matches_active(real_lifecycle):
    # 임의 인스턴스가 spawn_day에는 hazards()에 있고, 직전일에는 없음.
    h = next(h for h in real_lifecycle.instances if h.spawn_day > 0)
    assert h in real_lifecycle.hazards(h.spawn_day)
    assert h not in real_lifecycle.hazards(h.spawn_day - 1)
