# -*- coding: utf-8 -*-
"""Phase 0. v2.3 TTL(정본) → v2.4 마스터 CSV (90행 42열).

TTL 이 정본이다. KALIS 후보 CSV 는 15건의 kalis_frequency·spec·action_by 보완과
대조에만 쓰고 행을 추가하지 않는다 (다시 병합하면 15건 이중 계상).
"""
import csv
import io
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "scripts")
import ptd_common as C

import rdflib
from rdflib import RDF, RDFS

P = rdflib.Namespace(C.PTD_NS)


def load_kalis_candidates():
    """KALIS 후보 CSV → {ID(별표 제거): row}. '*'는 채택 표시이며 ID 일부가 아니다."""
    out = {}
    with io.open(C.SRC_KALIS_CAND, encoding="utf-8-sig", newline="") as f:
        for d in csv.DictReader(f):
            raw = (d.get("ID") or "").strip()
            if raw:
                out[raw.rstrip("*")] = d
    return out


def build_indexes(g):
    idx = {}

    cell = {}
    for c in g.subjects(RDF.type, P.CoverageCell):
        acc = g.value(c, P.hasAccidentType)
        trd = g.value(c, P.hasTrade)
        cell[C.uri_frag(c)] = (
            C.ACC_URI_TO_KO.get(C.uri_frag(acc), "") if acc is not None else "",
            C.TRADE_URI_TO_KO.get(C.uri_frag(trd), "") if trd is not None else "",
        )
    idx["cell"] = cell

    scn_cell = {}
    for s in g.subjects(RDF.type, P.RiskScenario):
        cv = g.value(s, P.belongsToCell)
        if cv is not None:
            scn_cell[C.uri_frag(s)] = C.uri_frag(cv)
    idx["scn_cell"] = scn_cell

    ref = {}
    for r in g.subjects(RDF.type, P.Reference):
        ref[C.uri_frag(r)] = (str(g.value(r, P.sourceDocument) or ""),
                              str(g.value(r, P.evidenceLevel) or ""))
    idx["ref"] = ref

    ea = defaultdict(list)
    for e in g.subjects(RDF.type, P.ExecutableAlternative):
        fe = g.value(e, P.fromEntry)
        if fe is None:
            continue
        rule = g.value(e, P.hasSimulationRule)
        info = {
            "alt_id": str(g.value(e, P.alternativeID) or C.uri_frag(e)),
            "install_cost": str(g.value(e, P.installCostLevel) or ""),
            "install_days": str(g.value(e, P.installDurationDays) or ""),
            "rule_id": "", "rule_type": "", "sim_action": "",
            "param_value": "", "param_source_raw": "", "sensitivity": "",
            "justification": "",
        }
        if rule is not None:
            info["rule_id"] = C.uri_frag(rule)
            for rt in C.RULE_TYPES:
                if (rule, RDF.type, P[rt]) in g:
                    info["rule_type"] = rt
                    break
            info["sim_action"] = (str(g.value(rule, P.simulationAction) or "")
                                  or str(g.value(rule, P.scheduleShift) or ""))
            info["param_source_raw"] = str(g.value(rule, P.parameterSourceType) or "")
            info["sensitivity"] = str(g.value(rule, P.sensitivityTarget) or "")
            info["justification"] = str(g.value(rule, P.parameterJustification) or "")
            params = []
            for pr, ov in g.predicate_objects(rule):
                nm = C.uri_frag(pr)
                if nm.endswith("Multiplier"):
                    params.append("%s=%s" % (nm, ov))
            info["param_value"] = ";".join(sorted(params))
        ea[C.uri_frag(fe)].append(info)
    idx["ea"] = ea
    return idx


def classify_reference(citation, declared_level):
    """이미 있는 인용문을 분류만 한다. 출처를 만들어내지 않는다."""
    st, ev = C.REF_LEVEL_MAP.get(declared_level, ("", ""))
    if not st:
        for cand, pats in C.CITATION_TYPE_PATTERNS:
            if any(p in citation for p in pats):
                st = cand
                break
    if not st and re.search(r"\(\d{4}\)", citation):
        st = "학술"
    if st == "기술기준" and not ev:
        ev = "standard"

    edition = ""
    for pat in (r"(\d+(?:st|nd|rd|th)\s*Ed\.?\s*\d{4})",
                r"(고용노동부령\s*제\d+호)", r"(제\d+호)",
                r"개방본\s*(\d{8})", r"\((\d{4})\)"):
        m = re.search(pat, citation)
        if m:
            edition = m.group(1)
            break
    return st, ev, edition


def expected_rule_family(hoc):
    if hoc in C.HOC_EXPECT_STRUCTURAL:
        return {"SpatialChangeRule", "TemporalRule"}
    if hoc in C.HOC_EXPECT_PARAMETRIC:
        return {"AgentParameterRule"}
    return set(C.RULE_TYPES)          # 공학적 등 — 양쪽 허용


def migrate():
    C.ensure_cwd()
    C.ensure_build()
    log = []

    def emit(m):
        log.append(m)
        print(m)

    emit("=== Phase 0 이관 : v2.3 TTL(정본) → v2.4 마스터 CSV ===")
    g = rdflib.Graph()
    g.parse(C.SRC_TTL, format="turtle")
    idx = build_indexes(g)
    kal = load_kalis_candidates()

    entries = sorted(C.uri_frag(s) for s in g.subjects(RDF.type, P.KnowledgeEntry))
    kalis_in_ttl = sorted(e for e in entries if e.startswith("KE_K_"))
    legacy_in_ttl = sorted(e for e in entries if not e.startswith("KE_K_"))

    emit("")
    emit("── 행 수 대조")
    emit("  TTL KnowledgeEntry 총계        : %d" % len(entries))
    emit("  그중 KALIS 유래 (KE_K_*)       : %d" % len(kalis_in_ttl))
    emit("  그중 기존 라이브러리           : %d" % len(legacy_in_ttl))
    emit("  KALIS 후보 CSV 행 수           : %d" % len(kal))
    orphan_csv = sorted(set(kal) - set(entries))
    orphan_ttl = sorted(set(kalis_in_ttl) - set(kal))
    emit("  고아: 후보 CSV 에만 존재       : %d %s"
         % (len(orphan_csv), orphan_csv if orphan_csv else ""))
    emit("  고아: TTL KE_K_* 에만 존재     : %d %s"
         % (len(orphan_ttl), orphan_ttl if orphan_ttl else ""))
    emit("  검산: 기존 %d + KALIS %d = %d %s"
         % (len(legacy_in_ttl), len(kalis_in_ttl),
            len(legacy_in_ttl) + len(kalis_in_ttl),
            "OK" if len(legacy_in_ttl) + len(kalis_in_ttl) == len(entries)
            else "불일치"))
    emit("  KALIS 후보 CSV 는 대조·보완용 — 행을 추가하지 않음")

    rows = []
    for eid in entries:
        s = P[eid]
        r = C.blank_row()
        notes, review = [], False
        r["entry_id"] = eid

        # ── status
        if eid in C.PIERCE_EXCLUDE_ENTRIES:
            r["status"] = "excluded"
            notes.append(C.EXCLUDE_NOTE)
        else:
            r["status"] = ("draft"
                           if str(g.value(s, P.collectionStatus) or "") == "seed"
                           else "active")

        # ── 재해유형 / 공종
        acc = trd = ""
        cv = g.value(s, P.belongsToCell)
        if cv is not None:
            acc, trd = idx["cell"].get(C.uri_frag(cv), ("", ""))
        if not acc:
            for scn in g.objects(s, P.addressesScenario):
                cf = idx["scn_cell"].get(C.uri_frag(scn))
                if cf and cf in idx["cell"] and idx["cell"][cf][0]:
                    acc, trd = idx["cell"][cf]
                    break
        if not acc and eid in kal:
            ct = (kal[eid].get("cellTarget") or "").strip()
            if ct in idx["cell"]:
                acc, trd = idx["cell"][ct]
        if not trd and eid in kal:
            trd = C.KALIS_TRADE_TO_KO.get((kal[eid].get("Trade") or "").strip(), "")
        if not acc or not trd:
            review = True
            notes.append("재해유형/공종 미결정 — 원천에 셀 연결 없음")
        r["accident_type"], r["trade"] = acc, trd

        r["scenario_ids"] = C.join_ids(
            sorted(C.uri_frag(o) for o in g.objects(s, P.addressesScenario)))

        # ── 내용
        desc = (str(g.value(s, P.alternativeDescription) or "")
                or str(g.value(s, RDFS.label) or ""))
        if not desc and eid in kal:
            desc = (kal[eid].get("Directive") or "").strip()
        r["directive_ko"] = desc

        hv = g.value(s, P.hasHoCLevel)
        r["hoc_level"] = C.HOC_URI_TO_KO.get(C.uri_frag(hv), "") if hv is not None else ""

        if eid in kal:
            spec = (kal[eid].get("Spec") or "").strip()
            r["spec"] = "" if spec in ("–", "-", "—") else spec
            ab = (kal[eid].get("ActionBy") or "").strip()
            r["action_by"] = ";".join(x.strip() for x in ab.split(",") if x.strip())
        if not r["action_by"]:
            ab = str(g.value(s, P.actionBy) or "")
            if ab:
                r["action_by"] = ";".join(x.strip() for x in ab.split(",") if x.strip())

        # ── 판정 (design_decidable 만. 나머지는 adjudicate.py)
        r["design_decidable"] = ("TRUE"
                                 if str(g.value(s, P.isDesignDecidable) or "").lower() == "true"
                                 else "FALSE")

        # ── 전거
        refs = sorted(C.uri_frag(o) for o in g.objects(s, P.hasReference))
        r["source_id"] = C.join_ids(refs)
        if refs:
            cit, lvl = idx["ref"].get(refs[0], ("", ""))
            st, ev, ed = classify_reference(cit, lvl)
            r["source_type"], r["evidence_level"], r["source_edition"] = st, ev, ed
            if lvl and not ev:
                review = True
                notes.append("원천 evidenceLevel='%s' — 목표 열거형에 대응 없음" % lvl)
            if not st:
                review = True
                notes.append("source_type 분류 불가")
            legal = [idx["ref"][x][0] for x in refs
                     if idx["ref"].get(x, ("", ""))[1] == "law"]
            r["legal_basis"] = " ; ".join(legal)
        else:
            review = True
            notes.append("전거 없음")
        # legal_verified_date 는 사람이 대조한 뒤에만 → 항상 빈칸

        # ── 시뮬레이션
        eas = idx["ea"].get(eid, [])
        if eas:
            e0 = eas[0]
            if len(eas) > 1:
                review = True
                notes.append("복수 ExecutableAlternative: "
                             + ",".join(x["alt_id"] for x in eas))
            r["rule_type"] = e0["rule_type"]
            r["rule_id"] = e0["rule_id"]
            r["simulation_action"] = e0["sim_action"]
            r["install_cost_level"] = e0["install_cost"]
            r["install_duration_days"] = e0["install_days"]
            r["cost_note"] = e0["justification"]
            if e0["rule_type"] == "AgentParameterRule":
                r["parameter_value"] = e0["param_value"]
            psr = e0["param_source_raw"]
            mapped = C.PARAM_SOURCE_MAP.get(psr, "")
            r["parameter_source"] = mapped
            if psr and not mapped:
                review = True
                notes.append("원천 parameterSourceType='%s' — 목표 열거형에 대응 없음"
                             % psr)
            # heuristic 계수는 민감도 대상 (자동 교정)
            if mapped == "heuristic":
                r["sensitivity_target"] = "TRUE"
            else:
                r["sensitivity_target"] = ("TRUE"
                                           if e0["sensitivity"].lower() == "true"
                                           else "FALSE")
        else:
            r["sensitivity_target"] = "FALSE"

        # ── HoC ↔ rule_type 예외 기록 (제약 아님, 관측 대상)
        exc = ""
        if r["rule_type"] and r["rule_type"] not in expected_rule_family(r["hoc_level"]):
            exc = "TRUE"
            notes.append(C.KNOWN_HOC_EXCEPTIONS.get(
                eid, "HoC(%s)와 rule_type(%s) 대응이 예상과 다름 — 분류 유지, "
                     "가설 검증 대상으로 기록" % (r["hoc_level"], r["rule_type"])))
        r["hoc_rule_exception"] = exc or "FALSE"
        # 지시서 §5 의 KE_T_HS_04 지침: 규칙 쪽이 잠정적이므로 민감도 대상
        if eid == "KE_T_HS_04" and exc:
            r["sensitivity_target"] = "TRUE"

        # ── 관계 4종: TTL 에 구조적 속성 없음. 추론으로 채우지 않는다.
        prose = " ".join(filter(None, [
            str(g.value(s, P.promotionNote) or ""),
            str(g.value(s, RDFS.comment) or ""),
        ]))
        mentioned = set(re.findall(r"\b(?:ALT|KE|RULE)_[A-Za-z0-9_]+", prose)) - {eid}
        if mentioned:
            review = True
            notes.append("관계 후보(미판정, 서술문 근거): " + ",".join(sorted(mentioned)))

        # ── IFC 4종: 원천에 값 없음. 슬롯만 유지.

        # ── 이력
        r["in_experiment_set"] = ""
        kf = g.value(s, P.kalisFrequency)
        if kf is None and eid in kal:
            kf = (kal[eid].get("kalisN") or "").strip()
        r["kalis_frequency"] = str(kf) if kf else "0"

        raw_ev = str(g.value(s, P.evidenceLevel) or "")
        if raw_ev:
            notes.append("원천 KE evidenceLevel=%s" % raw_ev)
        ps = str(g.value(s, P.promotionStatus) or "")
        if ps:
            notes.append("원천 promotionStatus=%s" % ps)
        if eid in kal and (kal[eid].get("fillsRung") or "").strip():
            notes.append("fillsRung=" + kal[eid]["fillsRung"].strip())

        r["needs_review"] = "TRUE" if review else "FALSE"
        r["note"] = " | ".join(notes)
        rows.append(r)

    C.write_master(rows)

    from collections import Counter
    emit("")
    emit("── 산출")
    emit("  %s" % C.MASTER_CSV)
    emit("  행 %d / 열 %d" % (len(rows), len(C.COLUMNS)))
    emit("  status : " + ", ".join(
        "%s=%d" % (k, sum(1 for r in rows if r["status"] == k))
        for k in ("active", "draft", "excluded")))
    exc = [r["entry_id"] for r in rows if r["hoc_rule_exception"] == "TRUE"]
    emit("  hoc_rule_exception=TRUE : %d %s" % (len(exc), exc))
    emit("  needs_review=TRUE       : %d"
         % sum(1 for r in rows if r["needs_review"] == "TRUE"))

    assert len(rows) == len(entries), "행 유실!"
    emit("  검증: TTL KnowledgeEntry %d = CSV 행 %d (유실 0건)"
         % (len(entries), len(rows)))

    with io.open(C.MIGRATE_LOG, "w", encoding=C.OUTPUT_ENCODING) as f:
        f.write("\n".join(log) + "\n")
    print("\n  로그: %s" % C.MIGRATE_LOG)
    return rows


if __name__ == "__main__":
    migrate()
