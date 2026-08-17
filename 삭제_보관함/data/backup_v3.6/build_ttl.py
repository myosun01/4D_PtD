# -*- coding: utf-8 -*-
"""Phase 0-3. v2.4 마스터 CSV + v2.3 온톨로지 → v2.4 TTL.

## 결함 A 수정: 전량 재생성이 아니라 '이월'

마스터 CSV 는 1행 = 1 KnowledgeEntry 구조라 KE 가 아닌 개체(Reference,
CoverageCell, RiskScenario, AccidentType, Trade, HazardType,
LifecycleRuleTemplate, ConflictResolution ...)를 담을 자리가 없다.
이전 판은 CSV 만 보고 TTL 을 전량 재생성해 이 주변 온톨로지 8종 110개를
통째로 잃었고, ptd:hasReference / ptd:addressesScenario 등이 정의 없는 URI 를
가리키게 되었다.

이번 판은:
  · v2.3 그래프를 로드해서
  · CSV 로 새로 만들 계열(KnowledgeEntry / ExecutableAlternative /
    SimulationRule 3종) 인스턴스만 걷어내고
  · 나머지 온톨로지는 전부 이월한 뒤
  · CSV 에서 만든 트리플을 얹는다.

문자열 조작이 아니라 rdflib Graph 조작으로 한다.
"""
import csv
import io
import os
import sys
from collections import Counter

sys.path.insert(0, "scripts")
import ptd_common as C

# 신규 LifecycleRuleTemplate 선언 소스.
# 마스터 CSV 는 '1행 = 1 KnowledgeEntry' 42열 불변식 위에 서 있고
# adjudicate/validate/build_docx 가 전부 이를 전제하므로 템플릿 행을 섞을 수 없다.
# 템플릿은 비-KE 온톨로지이므로 이월 단계에서 별도 소스로 병합한다.
SRC_TEMPLATES = "lifecycle_templates.csv"

import rdflib
from rdflib import RDF, RDFS, OWL, XSD, Graph, Namespace, URIRef, Literal

P = Namespace(C.PTD_NS)

# CSV 에서 새로 생성하는 계열 — v2.3 인스턴스는 버린다.
REGENERATED_CLASSES = [
    "KnowledgeEntry", "ExecutableAlternative",
    "SpatialChangeRule", "TemporalRule", "AgentParameterRule",
]

# v2.4 신규 속성 선언 (판정 6 / 관계 4 / IFC 4 / 전거·이력 보강).
# v2.3 에서 이월된 선언과 같은 subject 면 병합되도록 그래프에 add 한다.
NEW_PROPERTIES = [
    # (localname, property_type, range, comment)
    ("designDecidable", OWL.DatatypeProperty, XSD.boolean, None),
    ("promoted", OWL.DatatypeProperty, XSD.string,
     "실행층 승격 판정. TRUE|FALSE|UNSURE. UNSURE 는 미판정이며 확정값이 아니다."),
    ("reasonCode", OWL.DatatypeProperty, XSD.string,
     "미승격 사유. NOT_DESIGN|NO_EXPOSURE|NO_CHANNEL"),
    # exposureChannel 은 KnowledgeEntry 와 LifecycleRuleTemplate 양쪽에서 쓰이므로
    # rdfs:domain 을 걸지 않는다 (NO_DOMAIN 참조). 도메인을 KnowledgeEntry 로
    # 고정하면 템플릿이 KnowledgeEntry 로 추론되어 버린다.
    ("exposureChannel", OWL.DatatypeProperty, XSD.string,
     "노출 산출 채널. dwell_time|passage_count|zone_occupancy|proximity|none"),
    ("derivedBy", OWL.DatatypeProperty, XSD.string,
     "이 개체를 생성한 파생 규칙의 출처 (스크립트·규칙 식별자)."),
    ("adjudicationNote", OWL.DatatypeProperty, XSD.string, None),
    ("hocRuleException", OWL.DatatypeProperty, XSD.boolean,
     "HoC 등급과 rule_type 의 대응이 예상과 다름. 오류가 아니라 검증 대상 "
     "가설의 관측 기록이다 — 분류를 수정하지 않는다."),
    ("supersedes", OWL.ObjectProperty, None, "이 항목이 무력화하는 다른 대안"),
    ("redundantWith", OWL.ObjectProperty, None,
     "동시 적용 시 효과가 중복되는 대안"),
    ("requires", OWL.ObjectProperty, None, "선행 조건이 되는 대안"),
    ("residualRisk", OWL.DatatypeProperty, XSD.string, None),
    ("ifcClass", OWL.DatatypeProperty, XSD.string, None),
    ("ifcPredefinedType", OWL.DatatypeProperty, XSD.string, None),
    ("targetPset", OWL.DatatypeProperty, XSD.string, None),
    ("geometryOperation", OWL.DatatypeProperty, XSD.string,
     "relocate|resize|add|remove|none"),
    ("sourceType", OWL.DatatypeProperty, XSD.string, None),
    ("sourceEdition", OWL.DatatypeProperty, XSD.string, None),
    ("legalBasis", OWL.DatatypeProperty, XSD.string, None),
    ("legalVerifiedDate", OWL.DatatypeProperty, XSD.date,
     "국가법령정보센터 현행본 대조일. 사람이 확인한 경우에만 존재."),
    ("parameterValue", OWL.DatatypeProperty, XSD.string, None),
    ("cellTypeBasis", OWL.DatatypeProperty, XSD.string,
     "appliesToCellType 을 무엇에서 유도했는지 (원천과 규칙). 추측 배정 방지용 감사 기록."),
    ("spec", OWL.DatatypeProperty, XSD.string, None),
    ("status", OWL.DatatypeProperty, XSD.string, None),
    ("needsReview", OWL.DatatypeProperty, XSD.boolean, None),
    ("kalisFrequency", OWL.DatatypeProperty, XSD.integer, None),
]

# 이월 대상에서 배제할 찔림 계열 온톨로지 개체 (주어·목적어 양방향)
PIERCE_ENTITIES = set(C.PIERCE_EXCLUDE_ENTITIES)


# 규칙 인스턴스에만 있고 마스터 CSV 에는 열이 없는 속성.
# 재생성 계열은 subject 통째로 걷어내지므로, 걷어내기 전에 rule_id 로 떠서
# add_rule 단계에서 같은 rule_id 에만 되붙인다. 값의 원천은 v2.3 정본이며
# 여기서 새로 만들어내는 값이 아니다. v2.3 에 없는 rule_id 는 비운다.
RULE_ATTRS_FROM_V23 = ("appliesToCellType", "applicabilityCondition")


def capture_rule_attrs(g):
    """{rule_id: {속성: 값}} — 재생성 계열 제거 직전에 v2.3 규칙에서 떠 둔다."""
    out = {}
    for cls in ("SpatialChangeRule", "TemporalRule", "AgentParameterRule"):
        for s in g.subjects(RDF.type, P[cls]):
            vals = {}
            for name in RULE_ATTRS_FROM_V23:
                for o in g.objects(s, P[name]):
                    vals[name] = str(o)
                    break
            if vals:
                out[C.uri_frag(s)] = vals
    return out


def carry_over(src_path):
    """v2.3 그래프에서 재생성 계열과 찔림 계열을 걷어낸 나머지를 돌려준다."""
    g = Graph()
    g.parse(src_path, format="turtle")
    before = len(g)

    stats = {"before": before}

    # 1) 재생성 계열 인스턴스를 주어로 하는 트리플 제거
    regen_subjects = set()
    for cls in REGENERATED_CLASSES:
        for s in g.subjects(RDF.type, P[cls]):
            regen_subjects.add(s)
    # 제거 전에 규칙 전용 속성을 떠 둔다 (아래 RULE_ATTRS_FROM_V23 주석 참조)
    stats["rule_attrs"] = capture_rule_attrs(g)
    for s in regen_subjects:
        g.remove((s, None, None))
    stats["regen_subjects"] = len(regen_subjects)

    # 재생성 계열을 목적어로 하던 참조도 제거한다.
    # (예: ptd:CELL_X ptd:targetKnowledgeEntries ptd:KE_...)
    n_regen_obj = 0
    for s in regen_subjects:
        for t in list(g.triples((None, None, s))):
            g.remove(t)
            n_regen_obj += 1
    stats["regen_obj_refs"] = n_regen_obj

    # 2) 찔림 계열 — 주어 방향
    pierce_uris = set(P[e] for e in PIERCE_ENTITIES)
    n_pierce_subj = 0
    for u in pierce_uris:
        for t in list(g.triples((u, None, None))):
            g.remove(t)
            n_pierce_subj += 1
    # 3) 찔림 계열 — 목적어 방향 (다른 개체가 참조하는 경우)
    n_pierce_obj = 0
    for u in pierce_uris:
        for t in list(g.triples((None, None, u))):
            g.remove(t)
            n_pierce_obj += 1
    stats["pierce_subj"] = n_pierce_subj
    stats["pierce_obj"] = n_pierce_obj
    stats["after"] = len(g)
    return g, stats


# 여러 클래스에서 쓰이는 속성 — rdfs:domain 을 고정하지 않는다.
NO_DOMAIN = {"exposureChannel", "derivedBy"}


def add_new_property_declarations(g):
    """v2.4 신규 속성 선언을 얹는다 (기존 선언과 같은 subject 면 병합)."""
    added = 0
    for name, ptype, rng, comment in NEW_PROPERTIES:
        u = P[name]
        if (u, RDF.type, ptype) not in g:
            g.add((u, RDF.type, ptype))
            added += 1
        if name not in NO_DOMAIN and (u, RDFS.domain, None) not in g:
            g.add((u, RDFS.domain, P.KnowledgeEntry))
        if rng is not None and (u, RDFS.range, None) not in g:
            g.add((u, RDFS.range, rng))
        if comment and (u, RDFS.comment, None) not in g:
            g.add((u, RDFS.comment, Literal(comment, lang="ko")))
    return added


def add_lifecycle_templates(g):
    """lifecycle_templates.csv → ptd:LifecycleRuleTemplate 인스턴스.

    TTL 에 손으로 덧붙이면 재생성 시 사라지므로 반드시 이 경로를 통한다.
    이미 같은 template_id 가 이월되어 있으면 건너뛴다(중복 선언 방지).
    """
    if not os.path.exists(SRC_TEMPLATES):
        return [], []
    existing = set(C.uri_frag(s)
                   for s in g.subjects(RDF.type, P.LifecycleRuleTemplate))
    added, skipped = [], []
    with io.open(SRC_TEMPLATES, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            tid = (r.get("template_id") or "").strip()
            if not tid:
                continue
            if tid in existing:
                skipped.append(tid)
                continue
            s = P[tid]
            g.add((s, RDF.type, P.LifecycleRuleTemplate))
            g.add((s, P.hasHazardType, P[r["hazard_type"].strip()]))
            g.add((s, P.spawnTrigger, Literal(r["spawn_trigger"].strip())))
            g.add((s, P.despawnTrigger, Literal(r["despawn_trigger"].strip())))
            g.add((s, P.locationSelector,
                   Literal(r["location_selector"].strip())))
            if r.get("exposure_channel", "").strip():
                g.add((s, P.exposureChannel,
                       Literal(r["exposure_channel"].strip())))
            for ref in (x.strip() for x in (r.get("references") or "").split(";")):
                if ref:
                    g.add((s, P.hasReference, P[ref]))
            if r.get("derived_by", "").strip():
                g.add((s, P.derivedBy, Literal(r["derived_by"].strip())))
            if r.get("comment", "").strip():
                g.add((s, RDFS.comment, Literal(r["comment"].strip(), lang="ko")))
            added.append(tid)
    return added, skipped


def materialize_entailed_types(g):
    """v2.3 이 참조하면서 선언하지 않은 개체의 타입을 명시화한다.

    v2.3 은 ptd:hasHazardType 의 목적어 9종 중 5종(H007~H011)만
    ptd:HazardType 으로 선언하고, H001_FloorOpening / H002_NarrowPassage /
    H004_MaterialStorage / H005_ElevatedWork 는 선언하지 않았다. 이월 과정이
    만든 문제가 아니라 v2.3 원본의 결함이며, v2.3 을 직접 검사해도 동일하게
    나온다.

    여기서 얹는 것은 '이 URI 가 hasHazardType 의 목적어로 쓰이고 있다'는
    이미 그래프에 있는 사실의 타입 명시일 뿐이다. 라벨·simulationProfile·
    implementationStatus 같은 내용은 원천에 없으므로 만들어 넣지 않는다.
    (implementationStatus 부재 = 구현됨 으로 읽히며, 이는 adjudicate.py 의
     기존 해석과 동일하다 — 판정 결과가 바뀌지 않는다.)
    """
    typed = set(g.subjects(RDF.type, None))
    added = []
    for o in set(g.objects(None, P.hasHazardType)):
        if isinstance(o, URIRef) and o not in typed:
            g.add((o, RDF.type, P.HazardType))
            g.add((o, RDFS.comment, Literal(
                "v2.4 에서 타입 명시화. v2.3 은 이 개체를 hasHazardType 의 "
                "목적어로 참조하면서 클래스 선언을 누락했다. 라벨·구현상태는 "
                "원천에 없어 채우지 않았다.", lang="ko")))
            added.append(C.uri_frag(o))
    return sorted(added)


def b(v):
    return Literal(v == "TRUE", datatype=XSD.boolean)


def add_entry(g, r):
    s = P[r["entry_id"]]
    g.add((s, RDF.type, P.KnowledgeEntry))
    if r["directive_ko"]:
        g.add((s, P.alternativeDescription, Literal(r["directive_ko"], lang="ko")))
    hoc = C.HOC_KO_TO_URI.get(r["hoc_level"])
    if hoc:
        g.add((s, P.hasHoCLevel, P[hoc]))
    g.add((s, P.designDecidable, b(r["design_decidable"])))
    g.add((s, P.status, Literal(r["status"])))

    for col, prop, lang in (("promoted", "promoted", None),
                            ("reason_code", "reasonCode", None),
                            ("exposure_channel", "exposureChannel", None),
                            ("adjudication_note", "adjudicationNote", "ko")):
        if r[col]:
            g.add((s, P[prop], Literal(r[col], lang=lang) if lang
                   else Literal(r[col])))
    g.add((s, P.hocRuleException, b(r["hoc_rule_exception"])))

    for x in (v for v in r["scenario_ids"].split(";") if v):
        g.add((s, P.addressesScenario, P[x]))
    if r["action_by"]:
        g.add((s, P.actionBy, Literal(r["action_by"])))
    if r["spec"]:
        g.add((s, P.spec, Literal(r["spec"], lang="ko")))

    for x in (v for v in r["source_id"].split(";") if v):
        g.add((s, P.hasReference, P[x]))
    for col, prop, lang in (("source_type", "sourceType", None),
                            ("source_edition", "sourceEdition", None),
                            ("legal_basis", "legalBasis", "ko"),
                            ("evidence_level", "evidenceLevel", None)):
        if r[col]:
            g.add((s, P[prop], Literal(r[col], lang=lang) if lang
                   else Literal(r[col])))
    if r["legal_verified_date"]:
        g.add((s, P.legalVerifiedDate,
               Literal(r["legal_verified_date"], datatype=XSD.date)))

    for col, prop in (("supersedes", "supersedes"),
                      ("redundant_with", "redundantWith"),
                      ("requires", "requires")):
        for x in (v.strip() for v in r[col].split(";") if v.strip()):
            g.add((s, P[prop], P[x]))
    if r["residual_risk"]:
        g.add((s, P.residualRisk, Literal(r["residual_risk"], lang="ko")))

    for col, prop in (("ifc_class", "ifcClass"),
                      ("ifc_predefined_type", "ifcPredefinedType"),
                      ("target_pset", "targetPset"),
                      ("geometry_operation", "geometryOperation")):
        if r[col]:
            g.add((s, P[prop], Literal(r[col])))

    if r["kalis_frequency"] and r["kalis_frequency"] != "0":
        g.add((s, P.kalisFrequency,
               Literal(int(r["kalis_frequency"]), datatype=XSD.integer)))
    g.add((s, P.needsReview, b(r["needs_review"])))
    if r["note"]:
        g.add((s, RDFS.comment, Literal(r["note"], lang="ko")))


def add_rule(g, r, rule_attrs=None):
    if not r["rule_type"] or not r["rule_id"]:
        return False
    alt = P["ALT_" + r["entry_id"].replace("KE_", "", 1)]
    rule = P[r["rule_id"]]

    g.add((alt, RDF.type, P.ExecutableAlternative))
    g.add((alt, P.alternativeID, Literal(C.uri_frag(alt))))
    g.add((alt, P.fromEntry, P[r["entry_id"]]))
    hoc = C.HOC_KO_TO_URI.get(r["hoc_level"])
    if hoc:
        g.add((alt, P.hasHoCLevel, P[hoc]))
    g.add((alt, P.hasSimulationRule, rule))
    if r["install_cost_level"]:
        g.add((alt, P.installCostLevel, Literal(r["install_cost_level"])))
    if r["install_duration_days"] != "":
        try:
            g.add((alt, P.installDurationDays,
                   Literal(int(r["install_duration_days"]), datatype=XSD.integer)))
        except ValueError:
            g.add((alt, P.installDurationDays,
                   Literal(r["install_duration_days"])))

    g.add((rule, RDF.type, P[r["rule_type"]]))
    if r["simulation_action"]:
        g.add((rule, P.simulationAction, Literal(r["simulation_action"])))
    if r["parameter_value"]:
        g.add((rule, P.parameterValue, Literal(r["parameter_value"])))
    if r["parameter_source"]:
        g.add((rule, P.parameterSourceType, Literal(r["parameter_source"])))
    g.add((rule, P.sensitivityTarget, b(r["sensitivity_target"])))
    if r["cost_note"]:
        g.add((rule, P.parameterJustification, Literal(r["cost_note"], lang="ko")))
    # v2.3 규칙 전용 속성 되붙이기 (마스터 CSV 에 열이 없어 유실되던 값)
    carried = dict((rule_attrs or {}).get(r["rule_id"], {}))
    # [v3.5] appliesToCellType 은 CSV 열이 정본이고, 비어 있을 때만 v2.3 이월값을 쓴다.
    csv_cell = (r.get("applies_to_cell_type") or "").strip()
    if csv_cell:
        carried["appliesToCellType"] = csv_cell
    for name, value in carried.items():
        g.add((rule, P[name], Literal(value)))
    if (r.get("cell_type_basis") or "").strip():
        g.add((rule, P.cellTypeBasis, Literal(r["cell_type_basis"], lang="ko")))
    return True


def instance_counts(g):
    c = Counter()
    for s, _, o in g.triples((None, RDF.type, None)):
        c[C.uri_frag(o)] += 1
    return c


def find_dangling(g):
    """rdf:type 선언이 없는 ptd:* 객체 URI 를 찾는다."""
    typed = set(s for s in g.subjects(RDF.type, None))
    # 속성 URI 는 선언되어 있으면 typed 에 포함된다.
    dangling = {}
    for s, p, o in g:
        if isinstance(o, URIRef) and str(o).startswith(C.PTD_NS):
            if o not in typed:
                dangling.setdefault(C.uri_frag(o), set()).add(C.uri_frag(p))
    return dangling


def build():
    C.ensure_cwd()
    C.ensure_build()
    rows = C.read_master()
    kept = [r for r in rows if r["status"] != "excluded"]
    dropped = [r for r in rows if r["status"] == "excluded"]

    print("TTL 생성 : %s" % C.OUT_TTL)
    print("")
    print("── 1) v2.3 온톨로지 이월")
    g, st = carry_over(C.SRC_TTL)
    print("   v2.3 트리플                    : %s" % "{:,}".format(st["before"]))
    print("   재생성 계열 인스턴스 제거      : %d개 개체" % st["regen_subjects"])
    print("   재생성 계열 역참조 제거        : %d 트리플" % st["regen_obj_refs"])
    print("   찔림 5종 주어 방향 제거        : %d 트리플" % st["pierce_subj"])
    print("   찔림 5종 목적어 방향 제거      : %d 트리플" % st["pierce_obj"])
    print("   이월된 트리플                  : %s" % "{:,}".format(st["after"]))

    print("")
    print("── 2) v2.4 신규 속성 선언")
    n_new = add_new_property_declarations(g)
    print("   신규 선언 추가                 : %d (기존과 중복은 병합)" % n_new)

    tpl_added, tpl_skipped = add_lifecycle_templates(g)
    if tpl_added or tpl_skipped:
        print("   LifecycleRuleTemplate 병합       : 신규 %d (%s)%s"
              % (len(tpl_added), ", ".join(tpl_added) or "-",
                 ("  이미 존재 %d" % len(tpl_skipped)) if tpl_skipped else ""))
        print("     └ 원천: %s (TTL 직접 수정 금지 — 재생성 시 사라짐)"
              % SRC_TEMPLATES)

    mat = materialize_entailed_types(g)
    if mat:
        print("   v2.3 누락 타입 명시화          : %d — %s"
              % (len(mat), ", ".join(mat)))
        print("     └ v2.3 원본의 결함이다(v2.3 직접 검사에도 동일 4종 + "
              "REF_S14 가 나온다).")
        print("       hasHazardType 목적어라는 기존 사실의 타입 선언만 얹었고,")
        print("       라벨·구현상태는 원천에 없어 채우지 않았다.")

    print("")
    print("── 3) 마스터 CSV → KnowledgeEntry / ExecutableAlternative / Rule")
    n_rule = 0
    rule_attrs = st.get("rule_attrs", {})
    for r in kept:
        add_entry(g, r)
        if add_rule(g, r, rule_attrs):
            n_rule += 1
    print("   KnowledgeEntry                 : %d" % len(kept))
    print("   ExecutableAlternative + Rule   : %d" % n_rule)

    # 규칙 전용 속성 이월 결과 — 되붙은 것과 v2.3 에 없어 비는 것을 나눠 보고한다.
    rule_ids = [r["rule_id"] for r in kept if r["rule_type"] and r["rule_id"]]
    for name in RULE_ATTRS_FROM_V23:
        got = [rid for rid in rule_ids if name in rule_attrs.get(rid, {})]
        miss = [rid for rid in rule_ids if name not in rule_attrs.get(rid, {})]
        print("   %-22s 이월 : %d / 미보유 %d"
              % (name, len(got), len(miss)))
        if miss:
            print("     └ v2.3 정본에 없어 비움(추정으로 채우지 않음): %s"
                  % ", ".join(sorted(set(miss))))
    print("   제외(status=excluded)          : %d %s"
          % (len(dropped), [r["entry_id"] for r in dropped]))

    g.bind("ptd", P)
    g.bind("owl", OWL)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)
    g.serialize(destination=C.OUT_TTL, format="turtle")

    # ── 검증
    print("")
    print("── 4) 검증")
    g2 = Graph()
    g2.parse(C.OUT_TTL, format="turtle")
    print("   rdflib 재파싱                  : OK — 트리플 %s"
          % "{:,}".format(len(g2)))

    src = Graph()
    src.parse(C.SRC_TTL, format="turtle")
    c23, c24 = instance_counts(src), instance_counts(g2)
    EXPECT = {"KnowledgeEntry": 89, "ExecutableAlternative": 38,
              "Reference": 31, "CoverageCell": 28, "RiskScenario": 21,
              "AccidentType": 6, "ConflictResolution": 6, "Trade": 5,
              # v2.3 5종 − 찔림 LCR_EXPOSED_REBAR 1 + 신규 3
              # (LCR_DROP_ZONE, LCR_NARROW_PASSAGE, LCR_EQUIPMENT_CORRIDOR) = 7
              "HazardType": 4, "LifecycleRuleTemplate": 7, "HoCLevel": 7}
    # 기대치와 달라지는 것이 설명 가능한 경우 그 사유를 명시한다.
    # (숫자를 맞추려 이월 대상을 조작하지는 않는다 — 사유를 적을 뿐이다.)
    explained = {}
    if mat:
        explained["HazardType"] = (
            "기대 4 = v2.3 5종 − 찔림 H010_ExposedRebar 1. "
            "여기에 v2.3 이 선언을 누락했던 %d종(%s)을 명시화해 +%d → %d."
            % (len(mat), ", ".join(mat), len(mat), EXPECT["HazardType"] + len(mat)))

    print("")
    print("   개체군            v2.3   v2.4   기대   판정")
    unexplained = []
    for k in ["KnowledgeEntry", "ExecutableAlternative", "Reference",
              "CoverageCell", "RiskScenario", "AccidentType",
              "ConflictResolution", "Trade", "HazardType",
              "LifecycleRuleTemplate", "HoCLevel"]:
        got, exp = c24.get(k, 0), EXPECT[k]
        if got == exp:
            verdict = "OK"
        elif k in explained and got == exp + len(mat):
            verdict = "차이 설명됨"
        else:
            verdict = "다름"
            unexplained.append((k, c23.get(k, 0), got, exp))
        print("   %-18s %4d   %4d   %4d   %s"
              % (k, c23.get(k, 0), got, exp, verdict))

    for k, why in explained.items():
        print("")
        print("   %s 차이 사유 : %s" % (k, why))

    if unexplained:
        print("")
        print("   [주의] 설명되지 않는 차이가 있다. 숫자를 맞추려 이월 대상을")
        print("          조작하지 않았으므로 아래를 그대로 보고한다:")
        for k, a, b_, e in unexplained:
            print("          %s: v2.3=%d → v2.4=%d (기대 %d)" % (k, a, b_, e))

    # 댕글링 참조
    dangling = find_dangling(g2)
    print("")
    if dangling:
        print("   [FAIL] 댕글링 참조 %d종 — rdf:type 선언 없는 ptd:* URI"
              % len(dangling))
        for name in sorted(dangling):
            print("          %-28s ← %s"
                  % (name, ", ".join(sorted(dangling[name]))))
        return 1
    print("   댕글링 참조                    : 0건 OK")

    # 찔림 부재 (주어·목적어 양방향)
    leaked = []
    for e in sorted(PIERCE_ENTITIES | C.PIERCE_EXCLUDE_ENTRIES):
        u = P[e]
        if list(g2.triples((u, None, None))) or list(g2.triples((None, None, u))):
            leaked.append(e)
    if leaked:
        print("   [FAIL] 찔림 계열 잔존          : %s" % leaked)
        return 1
    print("   찔림 5종 + KE_K_PI_01          : 주어·목적어 모두 부재 OK")
    return 0


if __name__ == "__main__":
    sys.exit(build())
