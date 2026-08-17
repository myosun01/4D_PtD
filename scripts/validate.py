# -*- coding: utf-8 -*-
"""Phase 0-3. v2.4 마스터 CSV + 생성 TTL 정합성 검사 (지시서 §9).

심각도 4단:
  [ERROR]   즉시 수정 대상. 하나라도 있으면 실패.
  [PENDING] 미완이나 정상. 값을 만들어내지 않는다.
  [WARNING] 확인 권장.
  [INFO]    기록만. HoC ↔ rule_type 대응 예외는 오류가 아니다 (지시서 §5).

HoC ↔ rule_type 대응은 이 연구가 검증하려는 가설이지 데이터에 강제할 제약이
아니다. 제약으로 걸면 결론을 데이터에 주입하게 되므로 INFO 로만 출력한다.
"""
import io
import os
import re
import sys
from collections import Counter

sys.path.insert(0, "scripts")
import ptd_common as C

# 결함 C 재발 방지 — 한 번 정제한 뒤 다시 오염되면 즉시 잡는다.
from clean_directives import CASE_RE, MEDICAL_KEYWORDS

ERROR, PENDING, WARNING, INFO = "ERROR", "PENDING", "WARNING", "INFO"
SEV_ORDER = [ERROR, PENDING, WARNING, INFO]


def expected_rule_family(hoc):
    if hoc in C.HOC_EXPECT_STRUCTURAL:
        return {"SpatialChangeRule", "TemporalRule"}
    if hoc in C.HOC_EXPECT_PARAMETRIC:
        return {"AgentParameterRule"}
    return set(C.RULE_TYPES)


def validate(rows):
    F = []

    def add(sev, check, eid, msg):
        F.append((sev, check, eid, msg))

    idset = set(r["entry_id"] for r in rows)

    # ── ERROR: entry_id 중복
    seen = set()
    for r in rows:
        if r["entry_id"] in seen:
            add(ERROR, "DUP_ID", r["entry_id"], "entry_id 중복")
        seen.add(r["entry_id"])

    for r in rows:
        eid, hoc, rt = r["entry_id"], r["hoc_level"], r["rule_type"]

        # ── ERROR: promoted=FALSE 인데 reason_code 빈칸
        if r["promoted"] == "FALSE" and not r["reason_code"]:
            add(ERROR, "FALSE_NO_REASON", eid,
                "promoted=FALSE 이나 reason_code 가 빈칸")

        # ── ERROR: 관계 열이 존재하지 않는 ID 참조
        for col in ("supersedes", "redundant_with", "requires"):
            for ref in (x.strip() for x in r[col].split(";") if x.strip()):
                if ref not in idset:
                    add(ERROR, "DANGLING_REF", eid,
                        "%s 가 존재하지 않는 ID '%s' 참조" % (col, ref))

        # ── ERROR: directive_ko 에 CSI 사고사례 원문이 남아 있음 (결함 C)
        if CASE_RE.search(r["directive_ko"]):
            add(ERROR, "DIRECTIVE_CASE_LEAK", eid,
                "directive_ko 에 '사례:' 잔존 — 부록에 사고사례 원문이 인쇄된다")
        med = [k for k in MEDICAL_KEYWORDS if k in r["directive_ko"]]
        if med:
            add(ERROR, "DIRECTIVE_MEDICAL", eid,
                "directive_ko 에 의료·사고경과 키워드 잔존: %s" % "/".join(med))

        # ── PENDING: 승격했으나 규칙 미작성 (Phase 2 작업 대상)
        if r["promoted"] == "TRUE" and not rt:
            add(PENDING, "PROMOTED_NO_RULE", eid,
                "promoted=TRUE 이나 rule_type 빈칸 — Phase 2 규칙 작성 대상")

        # ── PENDING: 계수 미확보
        if rt == "AgentParameterRule" and not r["parameter_value"]:
            add(PENDING, "APR_NO_PARAM", eid,
                "AgentParameterRule 이나 parameter_value 빈칸 "
                "(원천에 계수 없음 — 지어내지 않음)")

        # ── PENDING: heuristic 인데 민감도 대상 아님 (자동 교정 가능)
        if r["parameter_source"] == "heuristic" and r["sensitivity_target"] != "TRUE":
            add(PENDING, "HEURISTIC_NOT_SENS", eid,
                "parameter_source=heuristic 이나 sensitivity_target=%s "
                "— migrate 단계에서 자동 교정 대상"
                % (r["sensitivity_target"] or "빈칸"))

        # ── WARNING
        if r["legal_basis"] and not r["legal_verified_date"]:
            add(WARNING, "LEGAL_UNVERIFIED", eid,
                "legal_basis 가 있으나 legal_verified_date 미기재 "
                "(현행본 대조는 사람이 수행)")
        if r["needs_review"] == "TRUE":
            add(WARNING, "NEEDS_REVIEW", eid, "needs_review=TRUE")

        # ── INFO: HoC ↔ rule_type 대응 예외 (제약 아님)
        if rt and rt not in expected_rule_family(hoc):
            reason = C.KNOWN_HOC_EXCEPTIONS.get(eid, "예상 대응과 다름")
            add(INFO, "HOC_RULE_EXCEPTION", eid,
                "HoC=%s + rule_type=%s — %s" % (hoc, rt, reason))
            if r["hoc_rule_exception"] != "TRUE":
                add(ERROR, "EXCEPTION_NOT_FLAGGED", eid,
                    "HoC↔rule_type 예외인데 hoc_rule_exception≠TRUE")

    return F


def validate_ttl(rows):
    """생성된 TTL 에 대한 검사 (ERROR 급)."""
    F = []
    if not os.path.exists(C.OUT_TTL):
        F.append((ERROR, "TTL_MISSING", "-", "%s 가 없음" % C.OUT_TTL))
        return F
    body = io.open(C.OUT_TTL, encoding="utf-8").read()

    for r in rows:
        if r["status"] == "excluded" and "ptd:%s " % r["entry_id"] in body:
            F.append((ERROR, "EXCLUDED_IN_TTL", r["entry_id"],
                      "status=excluded 행이 TTL 에 포함됨"))
    for ent in sorted(C.PIERCE_EXCLUDE_ENTITIES):
        if "ptd:%s" % ent in body:
            F.append((ERROR, "PIERCE_ENTITY_IN_TTL", ent,
                      "찔림 관련 온톨로지 개체가 TTL 에 잔존"))

    # 댕글링 참조 — 결함 A 재발 방지. 온톨로지가 다시 탈락하면 즉시 잡힌다.
    try:
        import rdflib
        from rdflib import RDF, URIRef
        g = rdflib.Graph()
        g.parse(C.OUT_TTL, format="turtle")
        typed = set(g.subjects(RDF.type, None))
        dangling = {}
        for s, p, o in g:
            if isinstance(o, URIRef) and str(o).startswith(C.PTD_NS) \
                    and o not in typed:
                dangling.setdefault(C.uri_frag(o), set()).add(C.uri_frag(p))
        for name in sorted(dangling):
            F.append((ERROR, "TTL_DANGLING_URI", name,
                      "rdf:type 선언 없는 ptd:* URI 를 %s 가 참조"
                      % ", ".join(sorted(dangling[name]))))
    except ImportError:
        pass
    return F


def main():
    C.ensure_cwd()
    C.ensure_build()
    rows = C.read_master()

    L = []

    def out(s=""):
        print(s)
        L.append(s)

    out("=" * 66)
    out("PtD v2.4 정합성 검사")
    out("=" * 66)
    out("대상 CSV : %s" % C.MASTER_CSV)
    out("대상 TTL : %s" % C.OUT_TTL)
    out("행 %d / 열 %d" % (len(rows), len(rows[0]) if rows else 0))

    hdr_ok = (list(rows[0].keys()) == C.COLUMNS) if rows else False
    out("열 구성 스키마 일치 : %s" % ("OK" if hdr_ok else "불일치"))

    F = validate(rows) + validate_ttl(rows)
    if not hdr_ok:
        F.append((ERROR, "SCHEMA_MISMATCH", "-", "열 구성이 42열 스키마와 다름"))

    for sev in SEV_ORDER:
        items = [i for i in F if i[0] == sev]
        if not items:
            continue
        out("")
        out("── [%s] %d건" % (sev, len(items)))
        limit = None if sev == ERROR else 10
        shown = items if limit is None else items[:limit]
        for _, check, eid, msg in shown:
            out("   %-22s %-30s %s" % (check, eid, msg))
        if limit is not None and len(items) > limit:
            out("   ... 외 %d건 (전체는 CSV 참조)" % (len(items) - limit))

    out("")
    out("── 검사별 집계")
    sev_of = {
        "DUP_ID": ERROR, "FALSE_NO_REASON": ERROR, "DANGLING_REF": ERROR,
        "EXCLUDED_IN_TTL": ERROR, "PIERCE_ENTITY_IN_TTL": ERROR,
        "EXCEPTION_NOT_FLAGGED": ERROR, "SCHEMA_MISMATCH": ERROR,
        "DIRECTIVE_CASE_LEAK": ERROR, "DIRECTIVE_MEDICAL": ERROR,
        "TTL_DANGLING_URI": ERROR,
        "PROMOTED_NO_RULE": PENDING, "APR_NO_PARAM": PENDING,
        "HEURISTIC_NOT_SENS": PENDING,
        "LEGAL_UNVERIFIED": WARNING, "NEEDS_REVIEW": WARNING,
        "HOC_RULE_EXCEPTION": INFO,
    }
    cnt = Counter(i[1] for i in F)
    for check in ["DUP_ID", "FALSE_NO_REASON", "DANGLING_REF",
                  "EXCLUDED_IN_TTL", "PIERCE_ENTITY_IN_TTL",
                  "EXCEPTION_NOT_FLAGGED", "SCHEMA_MISMATCH",
                  "DIRECTIVE_CASE_LEAK", "DIRECTIVE_MEDICAL",
                  "TTL_DANGLING_URI",
                  "PROMOTED_NO_RULE", "APR_NO_PARAM", "HEURISTIC_NOT_SENS",
                  "LEGAL_UNVERIFIED", "NEEDS_REVIEW", "HOC_RULE_EXCEPTION"]:
        out("   %-24s %-9s %d" % (check, sev_of[check], cnt.get(check, 0)))

    n = dict((s, sum(1 for i in F if i[0] == s)) for s in SEV_ORDER)
    out("")
    out("결과 : ERROR %d / PENDING %d / WARNING %d / INFO %d"
        % (n[ERROR], n[PENDING], n[WARNING], n[INFO]))
    if n[ERROR] == 0:
        out("  → ERROR 0건. 완료 기준 충족 "
            "(PENDING·WARNING·INFO 는 허용된다).")
    else:
        out("  → ERROR 가 남아 실패. 자동 수정하지 않는다.")
    out("")
    out("주: HOC_RULE_EXCEPTION 은 INFO 다. HoC 등급과 rule_type 의 대응은")
    out("    검증하려는 가설이지 제약이 아니므로 분류를 수정하지 않는다.")

    with io.open(C.VALIDATE_REPORT, "w", encoding=C.OUTPUT_ENCODING) as f:
        f.write("\n".join(L) + "\n")
    print("\n  리포트: %s" % C.VALIDATE_REPORT)
    return 1 if n[ERROR] else 0


if __name__ == "__main__":
    sys.exit(main())
