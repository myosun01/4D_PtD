"""
ptd_ttl.py — HoC/PtD 라이브러리(TTL) 로더 v2 + 시나리오 적용
=============================================================
ptd_library.ttl(2층 구조: KnowledgeEntry 75 / ExecutableAlternative 25)을 읽어
엔진이 소비하는 것(EA 25 + 규칙 3유형 + 생멸 템플릿 4)을 dataclass로 추출한다.
KnowledgeEntry·CoverageCell·RiskScenario·Reference는 엔진이 소비하지 않으며
SPARQL 질의 API(Library.query)로만 접근한다 (ROADMAP §4).

v1 하위호환:
  - load_library(ttl_path) 시그니처 유지 (인자 생략 시 ptd_library.ttl)
  - 반환 Library 객체는 v1 dict 인터페이스(get/[]/in/keys)를 위임 제공
  - rdflib 부재·파일 부재 시 None 반환 → TTL_OK=False → apply()는 Base 폴백
  - apply()/identity_effects()/scenario_label()은 기존 viewer.py 계약 그대로

시뮬은 TTL의 값만 사용한다(대책 효과 인라인 하드코딩 없음).
"""
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

import config as C

PTD_NS = "http://construction-safety.org/ptd-hoc-ontology#"
DEFAULT_TTL_PATH = C.TTL_PATH

# 로더가 왜 실패했는지 — LIBRARY is None 일 때 사유 문자열이 여기 남는다.
# (조용한 None 금지: 호출부는 require_library() 로 사유와 함께 예외를 받을 수 있다.)
LOAD_ERROR: Optional[str] = None

# ── v2.4 parameterValue 파싱 ──────────────────────────────
# v2.3 은 계수를 개별 프로퍼티(ptd:fallProbMultiplier ...)로 실었고,
# v2.4 는 한 문자열 ptd:parameterValue "fallProbMultiplier=0.10" 에 싣는다.
# (복수 값은 세미콜론 구분: "fatalityMultiplier=0.27;injuryMultiplier=1.00")
# 로더는 두 표기를 모두 읽는다 — 개별 프로퍼티가 있으면 그것이 우선이고,
# 없을 때만 parameterValue 에서 채운다. TTL 을 두 벌로 만들지 않기 위한 장치다.
_PARAM_KEY_TO_FIELD = {
    "fallprobmultiplier": "fall_prob_multiplier",
    "hazardweightmultiplier": "hazard_weight_multiplier",
    "fatalitymultiplier": "fatality_multiplier",
    "injurymultiplier": "injury_multiplier",
    "collapseprobmultiplier": "collapse_prob_multiplier",
    "materialprobmultiplier": "material_prob_multiplier",
    "tripprobmultiplier": "trip_prob_multiplier",
    "riskcoefficientmultiplier": "risk_coefficient_multiplier",
}

# 파싱 경고 누적 — (rule_id, 원문, 사유). 조용히 None 으로 두지 않는다.
PARAM_WARNINGS: List[Tuple[str, str, str]] = []


def parse_parameter_value(text: Optional[str], rule_id: str = "") -> Dict[str, float]:
    """ "a=0.1;b=0.5" → {필드명: float}. 미인식 키·수치 아님은 경고로 남긴다.

    빈 문자열/None 은 '계수 미확보'이며 경고가 아니다 (0 이나 1.0 으로 채우지 않는다)."""
    out: Dict[str, float] = {}
    if not text or not str(text).strip():
        return out
    for part in str(text).split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            PARAM_WARNINGS.append((rule_id, part, "'=' 없음 — key=value 형식 아님"))
            continue
        key, _, raw = part.partition("=")
        field_name = _PARAM_KEY_TO_FIELD.get(key.strip().lower())
        if field_name is None:
            PARAM_WARNINGS.append((rule_id, part, "미인식 계수명 '%s'" % key.strip()))
            continue
        num = _f(raw.strip())
        if num is None:
            PARAM_WARNINGS.append((rule_id, part, "수치로 해석 불가 '%s'" % raw.strip()))
            continue
        out[field_name] = num
    return out


# ── 공용 변환 ──────────────────────────────────────────────
def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _b(v):
    return str(v).strip().lower() == "true"


def _local(uri) -> str:
    return str(uri).split("#")[-1]


# ── 규칙 3유형 + 템플릿 dataclass (ROADMAP §4 로더 v2 요구 ②) ──
@dataclass(frozen=True)
class SpatialChangeRule:
    rule_id: str
    simulation_action: str
    applies_to_cell_type: str
    applicability_condition: Optional[str] = None
    risk_coefficient_multiplier: Optional[float] = None
    fall_prob_multiplier: Optional[float] = None
    hazard_weight_multiplier: Optional[float] = None
    evidence_level: Optional[str] = None
    parameter_source_type: Optional[str] = None
    sensitivity_target: bool = False


@dataclass(frozen=True)
class AgentParameterRule:
    rule_id: str
    applies_to_cell_type: str
    applicability_condition: Optional[str] = None
    fall_prob_multiplier: Optional[float] = None
    hazard_weight_multiplier: Optional[float] = None
    fatality_multiplier: Optional[float] = None
    injury_multiplier: Optional[float] = None
    collapse_prob_multiplier: Optional[float] = None
    material_prob_multiplier: Optional[float] = None
    trip_prob_multiplier: Optional[float] = None
    evidence_level: Optional[str] = None
    parameter_source_type: Optional[str] = None
    sensitivity_target: bool = False

    def multipliers(self) -> Dict[str, float]:
        """None이 아닌 채널별 계수만 {계수명: 값}으로 반환."""
        out = {}
        for k in ("fall_prob_multiplier", "hazard_weight_multiplier",
                  "fatality_multiplier", "injury_multiplier",
                  "collapse_prob_multiplier", "material_prob_multiplier",
                  "trip_prob_multiplier"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out


@dataclass(frozen=True)
class TemporalRule:
    rule_id: str
    schedule_shift: str                       # 원문 보존 (파싱은 Phase 3)
    applicability_condition: Optional[str] = None
    evidence_level: Optional[str] = None
    parameter_source_type: Optional[str] = None
    sensitivity_target: bool = False


@dataclass(frozen=True)
class LifecycleRuleTemplate:
    template_id: str
    spawn_trigger: str
    despawn_trigger: str
    location_selector: str
    hazard_type: str                          # "H001" 등 (H001_FloorOpening의 접두)
    hazard_type_full: str = ""


@dataclass(frozen=True)
class ExecutableAlternative:
    alternative_id: str
    from_entry: str                           # KE id
    hoc_level: str                            # TTL HoCLevel 로컬명
    hoc_rank: int                             # 1=최상위(RiskAvoidance) … 7=PPE
    rule_id: str
    install_cost_level: str
    install_duration_days: int


@dataclass
class Library:
    """TTL 라이브러리 v2. 엔진 소비 데이터 + SPARQL 질의 API + v1 dict 호환."""
    alternatives: Dict[str, ExecutableAlternative] = field(default_factory=dict)
    spatial_rules: Dict[str, SpatialChangeRule] = field(default_factory=dict)
    agent_rules: Dict[str, AgentParameterRule] = field(default_factory=dict)
    temporal_rules: Dict[str, TemporalRule] = field(default_factory=dict)
    lifecycle_templates: Dict[str, LifecycleRuleTemplate] = field(default_factory=dict)
    hoc_rank: Dict[str, int] = field(default_factory=dict)   # HoCLevel명 → 순위
    graph: object = None                      # rdflib Graph (질의 API용)
    legacy: dict = field(default_factory=dict)  # v1 형태 {hid:{name,base_risk,levels}}

    # ── 조회 ──
    def rule_of(self, alternative_id: str):
        """EA → 연결된 규칙 dataclass (3유형 중 하나)."""
        alt = self.alternatives[alternative_id]
        for pool in (self.spatial_rules, self.agent_rules, self.temporal_rules):
            if alt.rule_id in pool:
                return pool[alt.rule_id]
        return None

    def alternatives_by_hoc(self) -> Dict[str, List[ExecutableAlternative]]:
        """HoC 레벨명 → EA 목록 (레벨 순위순 정렬)."""
        out: Dict[str, List[ExecutableAlternative]] = {}
        for alt in self.alternatives.values():
            out.setdefault(alt.hoc_level, []).append(alt)
        return dict(sorted(out.items(), key=lambda kv: self.hoc_rank.get(kv[0], 99)))

    def sensitivity_targets(self) -> List[str]:
        """sensitivityTarget=true 규칙 ID 목록 (Phase 5 스윕 러너용)."""
        ids = []
        for pool in (self.spatial_rules, self.agent_rules, self.temporal_rules):
            ids += [r.rule_id for r in pool.values() if r.sensitivity_target]
        return sorted(ids)

    def query(self, sparql: str):
        """KnowledgeEntry 등 비소비 계층에 대한 SPARQL 질의 API."""
        if self.graph is None:
            raise RuntimeError("rdflib Graph 없음 (폴백 모드)")
        return self.graph.query(sparql, initNs={"ptd": PTD_NS})

    # ── v1 dict 인터페이스 위임 (하위호환) ──
    def __getitem__(self, k):  return self.legacy[k]
    def __contains__(self, k): return k in self.legacy
    def get(self, k, d=None):  return self.legacy.get(k, d)
    def keys(self):            return self.legacy.keys()
    def items(self):           return self.legacy.items()
    def values(self):          return self.legacy.values()


# ── TTL 파싱 ───────────────────────────────────────────────
def _hoc_ranks(g, PTD) -> Dict[str, int]:
    """isHigherThan 체인에서 순위 도출 (1=최상위). TTL에서만 온다 — 하드코딩 없음."""
    from rdflib import RDF
    nodes = {_local(s) for s in g.subjects(RDF.type, PTD.HoCLevel)}
    higher = {}                                # child(낮음) → parent(높음)
    for s, o in g.subject_objects(PTD.isHigherThan):
        higher[_local(o)] = _local(s)
    rank = {}

    def depth(n, seen=()):
        if n in rank:
            return rank[n]
        if n not in higher or n in seen:       # 최상위 또는 순환 방지
            rank[n] = 1
        else:
            rank[n] = depth(higher[n], seen + (n,)) + 1
        return rank[n]

    for n in nodes:
        depth(n)
    return rank


def _build_legacy(lib: "Library") -> dict:
    """v2 데이터 → v1 형태 {hid: {name, base_risk, levels:{1..5}}} 재구성.
    apply()/viewer.py의 기존 5단계 시나리오 의미론을 보존하기 위한 호환 뷰.
    (효과 수치는 전부 TTL 규칙에서 옴 — 여기는 매핑만 한다.)"""
    # TTL appliesToCellType 명 → 기존 위험 ID (config.HAZARD_TO_CELL의 역방향 의미)
    celltype_to_hid = {
        "floor_opening": "H001", "opening_edge_cells": "H001",
        "narrow_hazard_zone": "H002", "narrow_passage": "H002",
        "material_storage": "H004",
    }
    # HoC 7단계 → 기존 5단계 시나리오 슬롯 (UI 매핑이며 효과 수치가 아님)
    level_slot = {"RiskAvoidance": 1, "Elimination": 1, "Substitution": 2,
                  "EngineeringControls": 3, "WarningSystems": 4,
                  "AdministrativeControls": 4, "PPE": 5}

    hazards = {hid: {"name": hid, "base_risk": None, "levels": {}}
               for hid in C.HAZARD_TO_CELL}

    def candidate_priority(alt, rule):
        # 무조건부 규칙 우선, 그다음 ID 순 (결정론적)
        return (getattr(rule, "applicability_condition", None) is not None,
                alt.alternative_id)

    picked: Dict[Tuple[str, int], Tuple] = {}
    for alt in lib.alternatives.values():
        rule = lib.rule_of(alt.alternative_id)
        if rule is None or isinstance(rule, TemporalRule):
            continue                            # 시간 규칙은 격자 효과 없음(Phase 3)
        hid = celltype_to_hid.get(rule.applies_to_cell_type)
        lv = level_slot.get(alt.hoc_level)
        if hid is None or lv is None or hid not in hazards:
            continue
        key = (hid, lv)
        if key in picked and candidate_priority(*picked[key]) <= candidate_priority(alt, rule):
            continue
        picked[key] = (alt, rule)

    for (hid, lv), (alt, rule) in picked.items():
        if isinstance(rule, SpatialChangeRule):
            action = rule.simulation_action
            remove_fraction = 0.0
            if action.startswith("remove"):
                rcm = rule.risk_coefficient_multiplier
                remove_fraction = 1.0 if rcm is None else max(0.0, 1.0 - rcm)
            hazards[hid]["levels"][lv] = {
                "action": action,
                "fall_mult": rule.fall_prob_multiplier,
                "struck_mult": None,
                "weight_mult": rule.hazard_weight_multiplier,
                "fatal_mult": None, "injury_mult": None,
                "risk_tolerance": None,
                "remove_fraction": remove_fraction,
                "alternative_id": alt.alternative_id,
            }
        else:                                   # AgentParameterRule
            struck = (rule.material_prob_multiplier
                      if rule.material_prob_multiplier is not None
                      else rule.trip_prob_multiplier)
            hazards[hid]["levels"][lv] = {
                "action": "agent_parameter",
                "fall_mult": rule.fall_prob_multiplier,
                "struck_mult": struck,
                "weight_mult": rule.hazard_weight_multiplier,
                "fatal_mult": rule.fatality_multiplier,
                "injury_mult": rule.injury_multiplier,
                "risk_tolerance": None,
                "remove_fraction": 0.0,
                "alternative_id": alt.alternative_id,
            }
    return hazards


def load_library(ttl_path: Optional[str] = None):
    """TTL → Library (v2). rdflib 부재·파일 부재 시 None (v1과 동일한 Base 폴백).

    v1 하위호환: 위치 인자 ttl_path 유지, 생략 시 config.TTL_PATH."""
    global LOAD_ERROR
    LOAD_ERROR = None
    try:
        from rdflib import Graph, Namespace, RDF
    except Exception as e:
        LOAD_ERROR = ("rdflib 미설치 — Base 폴백으로 동작한다 (%s). "
                      "설치: pip install rdflib" % e)
        return None

    path = ttl_path or DEFAULT_TTL_PATH
    if not os.path.exists(path):
        LOAD_ERROR = ("TTL 파일 없음: %s — 재생성: python scripts/build_all.py "
                      "(build_ttl.py 가 %s 를 만든다)" % (path, C.TTL_PATH))
        return None

    g = Graph()
    g.parse(path, format="turtle")
    PTD = Namespace(PTD_NS)

    def val(s, p):
        for o in g.objects(s, PTD[p]):
            return str(o)
        return None

    lib = Library(graph=g)
    lib.hoc_rank = _hoc_ranks(g, PTD)

    def mults(s, rid):
        """개별 프로퍼티(v2.3) 우선, 없으면 parameterValue(v2.4)에서 채운다."""
        packed = parse_parameter_value(val(s, "parameterValue"), rid)

        def pick(prop, field_name):
            direct = _f(val(s, prop))
            return direct if direct is not None else packed.get(field_name)
        return pick

    for s in g.subjects(RDF.type, PTD.SpatialChangeRule):
        rid = _local(s)
        pick = mults(s, rid)
        r = SpatialChangeRule(
            rule_id=rid,
            simulation_action=val(s, "simulationAction") or "",
            applies_to_cell_type=val(s, "appliesToCellType") or "",
            applicability_condition=val(s, "applicabilityCondition"),
            risk_coefficient_multiplier=pick("riskCoefficientMultiplier",
                                             "risk_coefficient_multiplier"),
            fall_prob_multiplier=pick("fallProbMultiplier", "fall_prob_multiplier"),
            hazard_weight_multiplier=pick("hazardWeightMultiplier",
                                          "hazard_weight_multiplier"),
            evidence_level=val(s, "evidenceLevel"),
            parameter_source_type=val(s, "parameterSourceType"),
            sensitivity_target=_b(val(s, "sensitivityTarget")),
        )
        lib.spatial_rules[r.rule_id] = r

    for s in g.subjects(RDF.type, PTD.AgentParameterRule):
        rid = _local(s)
        pick = mults(s, rid)
        r = AgentParameterRule(
            rule_id=rid,
            applies_to_cell_type=val(s, "appliesToCellType") or "",
            applicability_condition=val(s, "applicabilityCondition"),
            fall_prob_multiplier=pick("fallProbMultiplier", "fall_prob_multiplier"),
            hazard_weight_multiplier=pick("hazardWeightMultiplier",
                                          "hazard_weight_multiplier"),
            fatality_multiplier=pick("fatalityMultiplier", "fatality_multiplier"),
            injury_multiplier=pick("injuryMultiplier", "injury_multiplier"),
            collapse_prob_multiplier=pick("collapseProbMultiplier",
                                          "collapse_prob_multiplier"),
            material_prob_multiplier=pick("materialProbMultiplier",
                                          "material_prob_multiplier"),
            trip_prob_multiplier=pick("tripProbMultiplier", "trip_prob_multiplier"),
            evidence_level=val(s, "evidenceLevel"),
            parameter_source_type=val(s, "parameterSourceType"),
            sensitivity_target=_b(val(s, "sensitivityTarget")),
        )
        lib.agent_rules[r.rule_id] = r

    for s in g.subjects(RDF.type, PTD.TemporalRule):
        # 원문 보존 (요구 ③). v2.3 은 ptd:scheduleShift, v2.4 는 ptd:simulationAction
        # 에 같은 성격의 조작 서술을 싣는다 — 있는 쪽을 그대로 보존한다(의미 변환 없음).
        shift = val(s, "scheduleShift") or val(s, "simulationAction") or ""
        r = TemporalRule(
            rule_id=_local(s),
            schedule_shift=shift,
            applicability_condition=val(s, "applicabilityCondition"),
            evidence_level=val(s, "evidenceLevel"),
            parameter_source_type=val(s, "parameterSourceType"),
            sensitivity_target=_b(val(s, "sensitivityTarget")),
        )
        lib.temporal_rules[r.rule_id] = r

    for s in g.subjects(RDF.type, PTD.LifecycleRuleTemplate):
        haz_full = _local(next(g.objects(s, PTD.hasHazardType), ""))
        t = LifecycleRuleTemplate(
            template_id=_local(s),
            spawn_trigger=val(s, "spawnTrigger") or "",
            despawn_trigger=val(s, "despawnTrigger") or "",
            location_selector=val(s, "locationSelector") or "",
            hazard_type=haz_full.split("_")[0] if haz_full else "",
            hazard_type_full=haz_full,
        )
        lib.lifecycle_templates[t.template_id] = t

    for s in g.subjects(RDF.type, PTD.ExecutableAlternative):
        hoc = _local(next(g.objects(s, PTD.hasHoCLevel), ""))
        alt = ExecutableAlternative(
            alternative_id=val(s, "alternativeID") or _local(s),
            from_entry=_local(next(g.objects(s, PTD.fromEntry), "")),
            hoc_level=hoc,
            hoc_rank=lib.hoc_rank.get(hoc, 99),
            rule_id=_local(next(g.objects(s, PTD.hasSimulationRule), "")),
            install_cost_level=val(s, "installCostLevel") or "",
            install_duration_days=_i(val(s, "installDurationDays")) or 0,
        )
        lib.alternatives[alt.alternative_id] = alt

    lib.legacy = _build_legacy(lib)
    return lib


LIBRARY = load_library(C.TTL_PATH)
TTL_OK = LIBRARY is not None

# 조용한 None 금지 — 왜 비었는지를 import 시점에 즉시 알린다.
# (여기서 raise 하지 않는 이유: rdflib 부재 시 Base 폴백으로 계속 도는 것이
#  CLAUDE.md 가 유지하라고 못 박은 계약이다. 대신 사유를 눈에 보이게 남기고,
#  라이브러리가 반드시 필요한 호출부는 require_library() 로 예외를 받는다.)
if LIBRARY is None:
    print("[ptd_ttl] 라이브러리 미로드 — %s" % (LOAD_ERROR or "사유 불명"),
          file=sys.stderr)

if PARAM_WARNINGS:
    print("[ptd_ttl] parameterValue 파싱 경고 %d건:" % len(PARAM_WARNINGS),
          file=sys.stderr)
    for rid, raw, why in PARAM_WARNINGS:
        print("  %-26s %-40s %s" % (rid, raw, why), file=sys.stderr)


def require_library():
    """라이브러리가 반드시 필요한 경로용 — 없으면 사유를 담아 예외."""
    if LIBRARY is None:
        raise RuntimeError("PtD 라이브러리를 로드하지 못했다: %s"
                           % (LOAD_ERROR or "사유 불명"))
    return LIBRARY


# ── 시나리오 적용 (v1 계약 유지 — viewer.py 소비) ────────────
def identity_effects():
    """무대책(Base): 모든 위험 셀 배율 1.0."""
    return {ct: {"prob_mult": 1.0, "fatal_mult": 1.0, "weight_mult": 1.0}
            for ct in (C.FLOOR_OPENING, C.MATERIAL, C.NARROW)}


def apply(grid: np.ndarray, scenario: str, rng=None):
    """HoC 시나리오 적용 → (수정된 grid, effects).
    effects[cell] = {prob_mult, fatal_mult, weight_mult} (TTL 값에서 산출)."""
    import random as _r
    rng = rng or _r.Random(0)
    g = grid.copy()
    effects = identity_effects()
    level = C.HOC_SCENARIOS.get(scenario, C.HOC_SCENARIOS["base"])["level"]
    if level == 0 or not TTL_OK:
        return g, effects

    for hid in C.ACTIVE_HAZARDS:
        cell = C.HAZARD_TO_CELL.get(hid)
        haz = LIBRARY.get(hid)
        if cell is None or haz is None:
            continue
        lv = haz["levels"].get(level)
        if not lv:
            continue

        # 1) 격자 수정(제거/면적축소)
        frac = lv.get("remove_fraction") or 0.0
        if frac > 0:
            cells = list(zip(*np.where(g == cell)))
            rng.shuffle(cells)
            for (r, c) in cells[:int(round(len(cells) * frac))]:
                g[r, c] = C.WALKABLE

        # 2) 사고확률 배율
        pm = lv.get("fall_mult") if cell == C.FLOOR_OPENING else lv.get("struck_mult")
        if pm is None:
            pm = lv.get("weight_mult")
        if pm is None:
            pm = 1.0
        if cell in (C.MATERIAL, C.NARROW) and lv.get("injury_mult") is not None:
            pm *= lv["injury_mult"]

        # 3) 치명도 배율
        fm = lv.get("fatal_mult")
        fm = fm if fm is not None else 1.0

        # 4) 회피 가중 배율(관리적 L4는 강하게 우회)
        wm = lv.get("weight_mult")
        wm = wm if wm is not None else 1.0
        if lv.get("risk_tolerance") is not None:
            wm = max(wm, 2.0)

        effects[cell] = {"prob_mult": pm, "fatal_mult": fm, "weight_mult": wm}

    return g, effects


def scenario_label(scenario: str) -> str:
    return C.HOC_SCENARIOS.get(scenario, C.HOC_SCENARIOS["base"])["label"]
