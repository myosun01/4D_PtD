"""
controls.py — PtD 대책 적용 계층 (Phase 3)
==========================================
위험 **인스턴스 단위**로 TTL의 ExecutableAlternative를 적용한다 (ROADMAP §5 P3).

경계: 대책의 효과 수치·규칙은 전부 TTL(ptd_ttl.LIBRARY)에서 온다 — 여기 하드코딩 없음.
시간 타겟팅: 대책은 effective_day(설치완료) 이후에만 유효. 그 전(무방호)엔 base.

핵심 타입:
  ControlApplication  — {alternative(TTL AltID), targetInstance, installActivity}
  ControlEffect       — 인스턴스에 대해 해석된 효과(kind + 채널배율 + effective_day)
실행기:
  P3-3 SpatialChangeRule → remove / block_agent_entry / relocate(scale)
  P3-4 AgentParameterRule → 채널 per-step 확률 배율 + 심각도(fatality/injury) 배율
  P3-5 TemporalRule       → scheduleShift 파싱(선후행/양생 lag 재계산)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ptd_ttl import (SpatialChangeRule, AgentParameterRule, TemporalRule)

# appliesToCellType → 우리 lifecycle HazardType (이 타입 인스턴스에 적용 가능)
CELLTYPE_TO_HAZARD = {
    "floor_opening": "H001", "opening_edge_cells": "H001",
    "edge_cells": "H007",
    "collapse_zone": "H008",
    "drop_zone": "H009",
    "material_storage": "H004",
    "narrow_passage": "H002",           # v3.5: fourd B-2 확장과 정합
    "equipment_corridor": "H011",       # v3.5: 장비동선 zone 8개
    # route / elevated_work_zone → 현재 바인딩된 인스턴스 없음
}
# HazardType → λ 채널
HAZARD_CHANNEL = {"H001": "fall", "H007": "edge", "H008": "collapse_zone",
                  "H004": "material", "H009": "drop_zone",
                  "H002": "narrow", "H011": "narrow"}

# ── v3.5 Part C: 가설물(temp structure)을 대상으로 받는 경로 ──────────────
# 위험 인스턴스가 아니라 가설물을 조작하는 대안이 있다 (예: 시스템비계 대체,
# 작업발판 일체형 거푸집). 기존 hazard instance 경로는 그대로 두고 덧댄다 —
# temp_structures.json 이 없어도 기존 동작이 유지된다.
CELLTYPE_TO_TS = {
    "formwork_deck": "formwork_deck",
    "shoring": "shoring",
    "scaffold": "scaffold",
    "platform": "platform",
}
# 가설물 유형 → 그 가설물의 노출이 실리는 λ 채널.
# 근거: 데크·비계·발판은 보행면이라 추락(fall) 계열, 동바리는 붕괴 계열이다.
TS_CHANNEL = {"formwork_deck": "fall", "scaffold": "fall",
              "platform": "fall", "shoring": "collapse_zone"}
# 채널 → AgentParameterRule에서 뽑을 per-step 확률 배율 키.
# 값은 리스트이며 **앞에서부터 먼저 발견된 것**을 쓴다 (v3.6 [D] 수정).
#
# drop_zone 에 두 키가 쓰이고 있다:
#   RULE_HS_DEBRISNET  hazardWeightMultiplier=0.35   (기존 매핑이 받던 것)
#   RULE_HS_INTFORM    materialProbMultiplier=0.50   (받지 못해 효과 0이던 것)
# 이름상 성격이 다르지만(경로가중 vs 확률) 현재 코드는 이미 hazard_weight_multiplier
# 를 λ 배율로 쓰고 있다. **그 해석을 바꾸지 않고** material_prob_multiplier 도
# 받아들이는 최소 수정을 했다 — 기존 값의 의미는 하나도 바뀌지 않는다.
# 어느 이름이 옳은가는 원저자만 답할 수 있어 미해결로 남긴다
# (build/alternative_classification.md 참조).
_CHANNEL_PROB_KEY = {
    "fall": ["fall_prob_multiplier"],
    "edge": ["fall_prob_multiplier"],
    "collapse_zone": ["collapse_prob_multiplier"],
    "material": ["material_prob_multiplier"],
    "drop_zone": ["hazard_weight_multiplier", "material_prob_multiplier"],
    "narrow": ["trip_prob_multiplier"],
}


@dataclass(frozen=True)
class ControlApplication:
    """대책 1건: 어떤 TTL 대안을, 어떤 위험 인스턴스에, 어떤 설치 액티비티로."""
    alternative_id: str
    target_instance: str
    install_activity: Optional[str] = None


@dataclass
class ControlEffect:
    """인스턴스에 해석된 효과. d >= effective_day 에서만 유효."""
    instance_id: str
    alternative_id: str
    effective_day: int
    kind: str                                   # remove / block / scale / temporal / noop
    channel_mult: Dict[str, float] = field(default_factory=dict)   # λ 확률 배율(채널별)
    severity_mult: Dict[str, float] = field(default_factory=dict)  # fatality/injury (Phase 4 SWR)
    temporal_rule: Optional[object] = None


def condition_holds(rule, zone_facts: Optional[dict], target_zone: Optional[str]) -> bool:
    """규칙의 applicabilityCondition 충족 여부.
    무조건(None) → 항상 True. 조건부 → zone_facts에 해당 사실이 있어야 True(보수적).
    (zone.method/opening.function 등 프로젝트 사실은 현재 데이터에 없어 기본 미충족.)"""
    cond = getattr(rule, "applicability_condition", None)
    if not cond:
        return True
    facts = (zone_facts or {}).get(target_zone or "", set())
    return cond in facts


def applicable_alternatives(library, hazard_type: str,
                            zone_facts: Optional[dict] = None,
                            target_zone: Optional[str] = None,
                            unconditional_only: bool = False) -> List:
    """해당 위험타입에 적용 가능한 대안 목록 (HoC 순위 오름차순 = 상위대책 먼저).

    기본: appliesToCellType이 위험타입에 매칭되는 모든 대안(조건부 포함).
    unconditional_only=True → 조건부 제외. zone_facts 제공 시 → 조건 미충족 대안 제외."""
    out = []
    for alt in library.alternatives.values():
        rule = library.rule_of(alt.alternative_id)
        if rule is None or isinstance(rule, TemporalRule):
            continue                            # 시간 규칙은 격자 대상이 아님(별도 경로)
        ct = getattr(rule, "applies_to_cell_type", "")
        if CELLTYPE_TO_HAZARD.get(ct) != hazard_type:
            continue
        cond = getattr(rule, "applicability_condition", None)
        if unconditional_only and cond:
            continue
        if zone_facts is not None and not condition_holds(rule, zone_facts, target_zone):
            continue
        out.append(alt)
    return sorted(out, key=lambda a: (a.hoc_rank, a.alternative_id))


def sparql_applicable(library, cell_type: str):
    """P3-6 데모용: TTL SPARQL로 특정 appliesToCellType 대안을 HoC와 함께 질의.
    반환: [(alternativeID, hoCLevel), ...]. rdflib Graph 없으면 예외."""
    q = """
    PREFIX ptd: <http://construction-safety.org/ptd-hoc-ontology#>
    SELECT ?alt ?hoc WHERE {
      ?a a ptd:ExecutableAlternative ;
         ptd:alternativeID ?alt ;
         ptd:hasHoCLevel ?h ;
         ptd:hasSimulationRule ?r .
      ?r ptd:appliesToCellType ?ct .
      BIND(REPLACE(STR(?h), "^.*#", "") AS ?hoc)
      FILTER(STR(?ct) = "%s")
    }""" % cell_type
    return [(str(r[0]), str(r[1])) for r in library.query(q)]


def target_kind(instance):
    """대상이 위험 인스턴스인가 가설물인가. 가설물은 `ts_type` 을 가진 dict/객체."""
    tt = (instance.get("ts_type") if isinstance(instance, dict)
          else getattr(instance, "ts_type", None))
    return ("temp_structure", tt) if tt else ("hazard", None)


def _instance_channel(instance):
    """대상의 λ 채널. 위험 인스턴스면 HAZARD_CHANNEL, 가설물이면 TS_CHANNEL."""
    kind, tt = target_kind(instance)
    if kind == "temp_structure":
        return TS_CHANNEL.get(tt)
    return HAZARD_CHANNEL.get(instance.hazard_type)


def _instance_id(instance):
    if isinstance(instance, dict):
        return instance.get("ts_id") or instance.get("instance_id")
    return getattr(instance, "ts_id", None) or instance.instance_id


def _spawn_day(instance):
    if isinstance(instance, dict):
        sp = instance.get("spawn") or {}
        return int(sp.get("day") or 0)
    return int(instance.spawn_day)


def resolve_effect(library, ctrl: ControlApplication, schedule, instance) -> ControlEffect:
    """ControlApplication + 대상 → ControlEffect (TTL 값에서 해석).

    대상은 위험 인스턴스(HazardInstance) 또는 가설물(temp structure dict) 둘 다 받는다
    (v3.5 Part C). effective_day: install_activity 완료일(ef) 또는
    spawn_day + installDurationDays."""
    alt = library.alternatives[ctrl.alternative_id]
    rule = library.rule_of(alt.alternative_id)
    channel = _instance_channel(instance)

    if ctrl.install_activity and ctrl.install_activity in schedule.activities:
        eff_day = schedule.activities[ctrl.install_activity].ef
    else:
        eff_day = _spawn_day(instance) + int(alt.install_duration_days)

    base = dict(instance_id=_instance_id(instance), alternative_id=alt.alternative_id,
                effective_day=eff_day)

    if isinstance(rule, SpatialChangeRule):
        act = rule.simulation_action or ""
        if act.startswith("remove") or rule.risk_coefficient_multiplier == 0.0:
            return ControlEffect(kind="remove", **base)
        # [v3.6 D 수정] 정확히 "block_agent_entry" 만 받던 것을 접두 일치로 바꾼다.
        # RULE_K_HS_06 의 지시는 "block_agent_entry_to_drop_influence_zone" 이고
        # 대상(drop_zone)은 appliesToCellType 이 이미 지정한다. 지시가 라이브러리에
        # 있는데 코드가 읽지 못하던 배관 결함이다 — 값을 지어내는 수정이 아니다.
        if act.startswith("block_agent_entry"):
            return ControlEffect(kind="block", **base)
        # relocate 등: fall 배율 우선, 없으면 risk_coefficient_multiplier
        m = rule.fall_prob_multiplier
        if m is None:
            m = rule.risk_coefficient_multiplier
        m = 1.0 if m is None else float(m)
        return ControlEffect(kind="scale", channel_mult={channel: m} if channel else {}, **base)

    if isinstance(rule, AgentParameterRule):
        mults = rule.multipliers()
        ch_mult = {}
        for prob_key in _CHANNEL_PROB_KEY.get(channel) or ():
            if prob_key in mults:
                ch_mult[channel] = float(mults[prob_key])
                break
        sev = {k: float(mults[k]) for k in ("fatality_multiplier", "injury_multiplier")
               if k in mults}
        return ControlEffect(kind="scale", channel_mult=ch_mult, severity_mult=sev, **base)

    if isinstance(rule, TemporalRule):
        return ControlEffect(kind="temporal", temporal_rule=rule, **base)

    return ControlEffect(kind="noop", **base)


def resolve_all(library, controls: List[ControlApplication], schedule,
                lifecycle, temp_structures=None) -> Dict[str, ControlEffect]:
    """여러 대책 → {target_id: ControlEffect}. 대상 검증 포함.

    [v3.5 Part C] 대상은 위험 인스턴스 또는 가설물이다. temp_structures 는
    {ts_id: ts_dict} 또는 ts 리스트를 받으며, 주지 않으면 예전과 똑같이
    위험 인스턴스만 본다 — 후방호환."""
    by_id = {h.instance_id: h for h in lifecycle.instances}
    ts_by_id = {}
    if temp_structures:
        seq = (temp_structures.values() if isinstance(temp_structures, dict)
               and not all(isinstance(v, dict) and "ts_type" in v
                           for v in list(temp_structures.values())[:1])
               else temp_structures)
        if isinstance(temp_structures, dict):
            seq = temp_structures.values()
        for t in seq:
            if isinstance(t, list):                 # {level: [ts...]} 형태
                for x in t:
                    ts_by_id[x["ts_id"]] = x
            elif isinstance(t, dict) and "ts_id" in t:
                ts_by_id[t["ts_id"]] = t

    out: Dict[str, ControlEffect] = {}
    for ctrl in controls:
        if ctrl.alternative_id not in library.alternatives:
            raise ValueError(f"미정의 대안 '{ctrl.alternative_id}'")
        inst = by_id.get(ctrl.target_instance) or ts_by_id.get(ctrl.target_instance)
        if inst is None:
            raise ValueError(f"미정의 대상 '{ctrl.target_instance}' "
                             f"(위험 인스턴스·가설물 어느 쪽에도 없음)")
        alt = library.alternatives[ctrl.alternative_id]
        rule = library.rule_of(alt.alternative_id)
        if not isinstance(rule, TemporalRule):
            ct = getattr(rule, "applies_to_cell_type", "")
            kind, tt = target_kind(inst)
            if kind == "temp_structure":
                if CELLTYPE_TO_TS.get(ct) != tt:
                    raise ValueError(
                        f"{ctrl.alternative_id}(cell={ct})는 가설물 "
                        f"{_instance_id(inst)}({tt})에 적용 불가")
            elif CELLTYPE_TO_HAZARD.get(ct) != inst.hazard_type:
                raise ValueError(
                    f"{ctrl.alternative_id}(cell={ct})는 {inst.instance_id}"
                    f"({inst.hazard_type})에 적용 불가")
        out[ctrl.target_instance] = resolve_effect(library, ctrl, schedule, inst)
    return out


# ══════════════════════════════════════════════
# P3-5 TemporalRule 실행기 — scheduleShift 파싱
# ══════════════════════════════════════════════
import re

# 인식하는 구조화 패턴(파싱 규약):
_RE_FS_LAG = re.compile(r"set FS_lag\(\s*(\w+)\s*->\s*(\w+)\s*\)\s*=\s*(\d+)\s*days", re.I)
_RE_CURING = re.compile(r"min curing lag enforced", re.I)
_RE_FS_BEFORE = re.compile(r"(\w+)\(Z\)\s*FS-before\s*(\w+)\(Z\)", re.I)
# [v3.6 D 수정] 동바리 존치 — RULE_K_FS_02
#   "set precedence: formwork_stripping(Z) requires retention_period_elapsed(Z)"
# v3.6 에서 KCS 14 20 12 3.3.2(2)(3개 층 존치)를 temp_works.py R3 에 구현했으므로
# 이 지시의 대응이 명확해졌다. **스케줄을 바꾸는 지시가 아니라 zone 생성 규칙을
# 고르는 지시**이므로 apply_temporal_shift 는 스케줄을 건드리지 않는다
# (실행 경로는 variant 가 어느 hazard_zones 를 쓰느냐다).
_RE_RETENTION = re.compile(r"(\w+)\(Z\)\s*requires\s*retention_period_elapsed\(Z\)", re.I)


def parse_schedule_shift(shift_text: str) -> dict:
    """scheduleShift 원문 → 구조화 지시. 미인식은 kind='unsupported'(무시·기록)."""
    m = _RE_FS_LAG.search(shift_text)
    if m:
        return {"kind": "set_fs_lag", "from_work": m.group(1),
                "to_work": m.group(2), "lag_days": int(m.group(3))}
    if _RE_CURING.search(shift_text):
        return {"kind": "min_curing_lag"}
    m = _RE_RETENTION.search(shift_text)
    if m:
        return {"kind": "retention_period", "work": m.group(1),
                "executed_by": "temp_works.py R3 — KCS 14 20 12 3.3.2(2) 3개 층 존치",
                "schedule_mutation": False}
    m = _RE_FS_BEFORE.search(shift_text)
    if m:
        return {"kind": "fs_before", "first": m.group(1), "second": m.group(2)}
    return {"kind": "unsupported", "text": shift_text}


def apply_temporal_shift(schedule, shift_text: str, min_curing_days: int = 6) -> int:
    """TemporalRule을 schedule에 적용하고 재-CPM. 반환: 영향받은 액티비티 수.
    지원: set_fs_lag(선후행 lag 설정), min_curing_lag(양생 최소 lag 강제).
    workType 매칭으로 대상 선후행 관계를 찾는다(§3 workType 어휘)."""
    instr = parse_schedule_shift(shift_text)
    changed = 0
    if instr["kind"] == "set_fs_lag":
        fw, tw, lag = instr["from_work"], instr["to_work"], instr["lag_days"]
        # from_work/to_work 는 'slab_pour','opening_closure' 같은 개념명 → workType 매칭
        want_from = _WORK_ALIAS.get(fw, fw)
        want_to = _WORK_ALIAS.get(tw, tw)
        for a in schedule.activities.values():
            if a.work_type != want_to:
                continue
            for p in a.predecessors:
                pred = schedule.activities[p.activity]
                if pred.work_type == want_from and p.relation == "FS":
                    p.lag_days = lag
                    changed += 1
    elif instr["kind"] == "min_curing_lag":
        # 타설(concrete_pour) → 해체(formwork_stripping) FS lag 를 최소 min_curing_days 로
        for a in schedule.activities.values():
            if a.trade != "formwork_stripping":
                continue
            for p in a.predecessors:
                pred = schedule.activities[p.activity]
                if pred.trade == "concrete_pour" and p.relation == "FS":
                    if p.lag_days < min_curing_days:
                        p.lag_days = min_curing_days
                        changed += 1
    elif instr["kind"] == "retention_period":
        # 스케줄을 바꾸지 않는다 — 존치는 zone 생성 규칙(temp_works.py R3)이 실행한다.
        # 여기서 스케줄을 건드리면 같은 효과가 두 번 반영된다.
        pass
    # fs_before / unsupported: Phase 3 범위에선 재정렬 미구현(기록만)
    if changed:
        schedule.forward_pass()
    return changed


# 개념명 → §3 workType 어휘
_WORK_ALIAS = {"slab_pour": "slab", "opening_closure": "opening_closure",
               "formwork_stripping": "formwork_stripping"}
