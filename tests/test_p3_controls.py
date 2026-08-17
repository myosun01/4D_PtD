"""P3-1 — ControlApplication + 적용가능 대안 질의(HoC순, SPARQL) + 효과 해석(effective_day).
모든 효과 수치는 TTL에서 온다(하드코딩 없음).

[v2.4 대안 ID 갱신] v2.3 은 대안 ID 가 규칙명을 따랐고(ALT_H001_GUARD),
v2.4 는 `ALT_` + entry_id 에서 `KE_` 를 뗀 형태다(ALT_H001_05). 같은 대안의
같은 규칙을 가리키는 이름만 바뀐 것이라 아래 상수로 대응시킨다:
    ALT_H001_ELIM      → ALT_H001_01                (RULE_H001_ELIM)
    ALT_H001_RELOCATE  → ALT_S_H001_09              (RULE_H001_RELOCATE)
    ALT_H001_GUARD     → ALT_H001_05                (RULE_H001_GUARD)
    ALT_ADM_H001       → ALT_H001_07                (RULE_ADM_H001)
    ALT_PPE_H001       → ALT_H001_08                (RULE_PPE_H001)
    ALT_FE_GUARDRAIL   → ALT_M_Fall_FormErection_02 (RULE_FE_GUARDRAIL)
    ALT_CP_PC          → ALT_T_CP_01                (RULE_CP_PC)
    ALT_CP_NOENTRY     → ALT_T_CP_03                (RULE_CP_NOENTRY)
    ALT_CP_LIFT_LIMIT  → ALT_S_CP_04                (RULE_CP_LIFT_LIMIT)
    ALT_FE_METALDECK   → ALT_S_FE_08                (RULE_FE_METALDECK)
    ALT_CP_DESIGNCHECK → **v2.4 에 없음** (RULE_CP_DESIGNCHECK 자체가 없다)
"""
import pytest

from controls import (ControlApplication, applicable_alternatives, resolve_effect,
                      resolve_all, condition_holds, sparql_applicable)

ELIM = "ALT_H001_01"
RELOCATE = "ALT_S_H001_09"
GUARD = "ALT_H001_05"
ADM = "ALT_H001_07"
PPE = "ALT_H001_08"
EDGE_GUARDRAIL = "ALT_M_Fall_FormErection_02"
CP_PC = "ALT_T_CP_01"
CP_NOENTRY = "ALT_T_CP_03"
CP_LIFT_LIMIT = "ALT_S_CP_04"
FE_METALDECK = "ALT_S_FE_08"


def _inst(life, htype, idx=0):
    return [h for h in life.instances if h.hazard_type == htype][idx]


def test_applicable_by_hazard_type(library):
    h001 = {a.alternative_id for a in applicable_alternatives(library, "H001")}
    assert {ELIM, RELOCATE, GUARD, ADM, PPE} <= h001
    assert {a.alternative_id
            for a in applicable_alternatives(library, "H007")} == {EDGE_GUARDRAIL}
    h008 = {a.alternative_id for a in applicable_alternatives(library, "H008")}
    # v2.3 의 ALT_CP_DESIGNCHECK 는 v2.4 에 없다 — 나머지 4종만 확인한다.
    assert {CP_PC, FE_METALDECK, CP_LIFT_LIMIT, CP_NOENTRY} <= h008


def test_applicable_sorted_by_hoc(library):
    ranks = [a.hoc_rank for a in applicable_alternatives(library, "H001")]
    assert ranks == sorted(ranks)                 # 상위대책(낮은 rank) 먼저


def test_unconditional_filter(library):
    uncond = {a.alternative_id
              for a in applicable_alternatives(library, "H001", unconditional_only=True)}
    assert ELIM not in uncond                     # 조건부(opening.function) 제외
    assert GUARD in uncond                        # 무조건


def test_condition_holds(library):
    elim = library.rule_of(ELIM)                  # 조건부
    guard = library.rule_of(GUARD)                # 무조건
    assert condition_holds(guard, None, None) is True
    assert condition_holds(elim, None, "Z-A") is False
    assert condition_holds(elim, {"Z-A": {"opening.function=mep_penetration"}}, "Z-A") is True


def test_resolve_effective_day_from_install_duration(library, real_schedule, real_lifecycle):
    h = _inst(real_lifecycle, "H001")
    eff = resolve_effect(library, ControlApplication(GUARD, h.instance_id),
                         real_schedule, h)
    assert eff.kind == "scale"
    assert eff.effective_day == h.spawn_day + 1   # 설치 1일 → 익일 유효
    assert eff.channel_mult == {"fall": 0.1}      # TTL fallProbMultiplier


def test_resolve_effective_day_from_install_activity(library, real_schedule, real_lifecycle):
    h = _inst(real_lifecycle, "H001")
    aid = next(iter(real_schedule.activities))
    eff = resolve_effect(library, ControlApplication(GUARD, h.instance_id,
                                                     install_activity=aid), real_schedule, h)
    assert eff.effective_day == real_schedule.activities[aid].ef


def test_resolve_severity_only_for_ppe(library, real_schedule, real_lifecycle):
    h = _inst(real_lifecycle, "H001")
    eff = resolve_effect(library, ControlApplication(PPE, h.instance_id),
                         real_schedule, h)
    assert eff.channel_mult == {}                 # λ(확률) 불변
    assert eff.severity_mult.get("fatality_multiplier") == 0.27


def test_resolve_all_validates(library, real_schedule, real_lifecycle):
    h = _inst(real_lifecycle, "H001")
    with pytest.raises(ValueError):               # 미정의 대안
        resolve_all(library, [ControlApplication("NOPE", h.instance_id)], real_schedule, real_lifecycle)
    with pytest.raises(ValueError):               # 미정의 인스턴스
        resolve_all(library, [ControlApplication(GUARD, "NOPE")], real_schedule, real_lifecycle)
    with pytest.raises(ValueError):               # cell-type 불일치(H007 대안을 H001에)
        resolve_all(library, [ControlApplication(EDGE_GUARDRAIL, h.instance_id)],
                    real_schedule, real_lifecycle)


def test_sparql_applicable(library):
    res = dict(sparql_applicable(library, "collapse_zone"))   # TTL SPARQL 질의
    assert CP_NOENTRY in res
    assert res[CP_LIFT_LIMIT] == "EngineeringControls"
