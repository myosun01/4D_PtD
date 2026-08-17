"""P1-1 — ptd_ttl.py v2 로더 검증 (ROADMAP §4 계약).

검증 항목: EA 25 / 규칙유형별 8·12·5 / 템플릿 4, TemporalRule.scheduleShift
원문 보존, isHigherThan 체인 기반 hoc_rank, rdflib·파일 부재 폴백(None 반환).
"""
import builtins

import ptd_ttl
from ptd_ttl import (SpatialChangeRule, AgentParameterRule, TemporalRule,
                     LifecycleRuleTemplate, ExecutableAlternative)


def test_ttl_loads():
    assert ptd_ttl.TTL_OK is True
    assert ptd_ttl.LIBRARY is not None


def test_layer_counts(library):
    # v2.4 (build/ptd_library_v2.4.ttl). ROADMAP §4 에 적힌 25/8/12/5/4 는 v2.3 수치이며,
    # 정본이 v2.4 로 바뀌면서 35/14/14/7/7 이 되었다. 로더가 읽은 값이 진실이다.
    assert len(library.alternatives) == 35
    assert len(library.spatial_rules) == 14
    assert len(library.agent_rules) == 14
    assert len(library.temporal_rules) == 7
    assert len(library.lifecycle_templates) == 7


def test_dataclass_types(library):
    assert all(isinstance(r, SpatialChangeRule) for r in library.spatial_rules.values())
    assert all(isinstance(r, AgentParameterRule) for r in library.agent_rules.values())
    assert all(isinstance(r, TemporalRule) for r in library.temporal_rules.values())
    assert all(isinstance(t, LifecycleRuleTemplate) for t in library.lifecycle_templates.values())
    assert all(isinstance(a, ExecutableAlternative) for a in library.alternatives.values())


def test_lifecycle_template_ids(library):
    # v2.4 에서 lifecycle_templates.csv 로 3종(DROP_ZONE / NARROW_PASSAGE /
    # EQUIPMENT_CORRIDOR)이 추가되어 7종이다.
    assert set(library.lifecycle_templates) == {
        "LCR_SLAB_OPENING", "LCR_SLAB_EDGE",
        "LCR_SHORING_COLLAPSE", "LCR_MATERIAL_STORAGE",
        "LCR_DROP_ZONE", "LCR_NARROW_PASSAGE", "LCR_EQUIPMENT_CORRIDOR"}


def test_template_hazard_types(library):
    haz = {t.template_id: t.hazard_type for t in library.lifecycle_templates.values()}
    assert haz["LCR_SLAB_OPENING"] == "H001"
    assert haz["LCR_SLAB_EDGE"] == "H007"
    assert haz["LCR_SHORING_COLLAPSE"] == "H008"
    assert haz["LCR_MATERIAL_STORAGE"] == "H004"


def test_schedule_shift_preserved(library):
    # ROADMAP §4 요구 ③: scheduleShift 원문 보존 (파싱은 Phase 3).
    for r in library.temporal_rules.values():
        assert isinstance(r.schedule_shift, str) and r.schedule_shift.strip()
    assert (library.temporal_rules["RULE_H001_TEMPORAL"].schedule_shift
            == "set FS_lag(slab_pour -> opening_closure) = 0 days")


def test_hoc_rank_from_ttl_chain(library):
    # isHigherThan 체인에서 도출 (하드코딩 없음): RiskAvoidance=1 … PPE=7.
    assert library.hoc_rank["RiskAvoidance"] == 1
    assert library.hoc_rank["PPE"] == 7
    assert library.hoc_rank["RiskAvoidance"] < library.hoc_rank["PPE"]
    for a in library.alternatives.values():
        assert a.hoc_rank == library.hoc_rank.get(a.hoc_level, 99)


def test_every_alternative_links_a_rule(library):
    # EA.hasSimulationRule → 규칙 3유형(spatial/agent/temporal) 중 하나로 해석 가능.
    for a in library.alternatives.values():
        assert library.rule_of(a.alternative_id) is not None, a.alternative_id


def test_sensitivity_targets(library):
    # 로더가 TTL 에서 추출한 값이 진실. v2.4 에서 KALIS 파생 5건(RULE_K_*)이
    # sensitivityTarget=true 로 추가되고 RULE_CP_DESIGNCHECK 가 사라져 10건이다.
    ids = library.sensitivity_targets()
    assert set(ids) == {
        "RULE_CP_LIFT_LIMIT", "RULE_FE_PLATFORM", "RULE_HS_INTFORM",
        "RULE_TRIP_LIGHT", "RULE_TRIP_STORAGE",
        "RULE_K_CA_02", "RULE_K_CA_03", "RULE_K_FE_11",
        "RULE_K_RB_03", "RULE_K_TR_08"}


def test_fallback_when_file_absent():
    # 파일 부재 → None (→ TTL_OK False → Base 폴백).
    assert ptd_ttl.load_library("____no_such_file____.ttl") is None


def test_fallback_when_rdflib_absent(monkeypatch):
    # ROADMAP §4 요구 ④: rdflib 부재 시 None 반환(v1과 동일한 Base 폴백).
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rdflib" or name.startswith("rdflib."):
            raise ImportError("simulated: rdflib 없음")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert ptd_ttl.load_library() is None


def test_identity_effects_base_neutral():
    # Base(무대책): 모든 위험 셀 배율 1.0.
    for cell, mult in ptd_ttl.identity_effects().items():
        assert mult == {"prob_mult": 1.0, "fatal_mult": 1.0, "weight_mult": 1.0}
