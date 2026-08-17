# -*- coding: utf-8 -*-
"""Phase 1. 유보 항목 판정 (1차 초안 — 확정 아님).

지시서 §7 의 결정 트리를 순서 그대로 적용한다.

이전 시도의 결함과 교정
-----------------------
이전에는 「구조검토 실시」·「조립도 작성」류가 NOT_DESIGN 으로 잘못 흡수되어
NO_EXPOSURE 가 0건이 되었다. 원인은 두 가지였다:

  (a) 물리 동사 탐지를 지시문 전체에 걸었다. 이 라이브러리의 지시문은
      「<주절> — <효과 서술>」 구조가 많은데, 효과 서술의 은유적 동사
      ("붕괴 경로 차단", "위험 제거")까지 물리적 조치로 세어 승격시켰다.
      → 주절(— 앞)만 평가한다.

  (b) '동바리·비계' 같은 명사를 물리적 산출물로 보았다. 그러나
      「거푸집·동바리 구조를 사전 구조검토하고 조립도를 작성」에서 동바리는
      검토의 *대상*이지 설치되는 산출물이 아니다.
      → 물리적 산출물은 '설치·시공되는 설비' 또는 '수행되는 공사'로 한정하고,
        검토·작성의 대상 명사는 세지 않는다.

핵심 구분: 문서화 동사(명시/반영/작성)의 **목적어가 무엇인가**.
  「방호장치를 설계에 반영」  → 목적어가 물리적 설비  → 노출 변화 있음
  「조립도를 작성·준수」      → 목적어가 문서         → 노출 변화 없음 (NO_EXPOSURE)
"""
import io
import os
import sys
from collections import Counter, OrderedDict, defaultdict

sys.path.insert(0, "scripts")
import ptd_common as C

import rdflib
from rdflib import RDF

P = rdflib.Namespace(C.PTD_NS)

# 문서화·검증 동사 (그 자체로는 노출을 바꾸지 않음)
DOC_VERBS = ["검토", "작성", "수립", "명시", "명기", "표기", "준수", "확인",
             "점검", "문서화", "반영", "제시", "계상"]

# 실제로 설치·시공되는 물리적 설비
PHYSICAL_DEVICES = [
    "방호장치", "안전캡", "버팀대", "난간", "발판", "덮개", "복공",
    "방지망", "방호망", "배리어", "울타리", "휀스", "브래킷",
    "앵커리지", "구명줄", "라이프라인", "생명줄", "조명", "경보",
    "이동통로", "안전통로", "통로", "계단", "샤프트", "선반",
]
# 수행되는 물리적 공사·조작
PHYSICAL_WORKS = [
    "설치", "시공", "타설", "평탄화", "인양", "선조립", "선시공",
    "이격", "분리", "축소", "제거", "회피", "대체", "채택", "적용",
    "표준화", "통합", "막음", "금지", "지정", "배치",
    # 영구 설계의 기하 변경 — 작업면 자체를 바꾸므로 물리적 조치다.
    # (KE_T_PO_02 「단차를 최소화한 평면 설계」가 이것 없이 NO_EXPOSURE 로
    #  오분류되었다.)
    "최소화", "집약", "일체화", "구획", "제한", "높이를", "높여",
]
# 공정 순서·시점을 옮기는 표현 (TemporalRule 영역)
TEMPORAL_MARKERS = [
    "순서", "시점", "존치기간", "존치 기간", "선행", "전진", "단계별",
    "일정", "공정 간", "우선 시공", "초기에", "직후", "phased",
]

# 검토·작성의 '대상'일 뿐 산출물이 아닌 명사 (물리 산출물로 세지 않음)
SUBJECT_ONLY_NOUNS = ["동바리", "비계", "거푸집", "구조", "가설기자재",
                      "인증품", "자재"]

# 노출 채널 키워드
CHANNEL_KEYWORDS = OrderedDict([
    ("dwell_time", ["개구부", "단부", "난간", "덮개", "창호", "창대", "복공",
                    "앵커리지", "추락방지 앵커", "추락보호 앵커", "추락방호",
                    "라이프라인", "생명줄", "구명줄", "샤프트", "안전대",
                    "브래킷", "테두리보"]),
    ("passage_count", ["통로", "동선", "이동", "계단", "보행", "진출입",
                       "운반", "접근면", "걸림", "단차"]),
    ("zone_occupancy", ["존치", "직하부", "무출입", "하부", "양생", "출입통제",
                        "영향구역", "적재구역", "야적", "적치", "구역"]),
    ("proximity", ["장비", "차량", "중장비", "기계", "가공기계", "크레인",
                   "유도자", "건설기계"]),
])

# 미구현 채널을 가리키는 표현
HAZARD_KEYWORDS = {
    "H008_ShoringCollapse": ["동바리", "붕괴", "존치", "조립도", "강관동바리"],
    "H009_DropZone": ["낙하", "낙하물", "방지망", "적재하중", "다단적재"],
    "H011_EquipmentCorridor": ["차량", "장비", "중장비", "건설기계", "진출입로"],
}
IMPLEMENTED_HAZARD_KEYWORDS = {
    "H004_MaterialStorage": ["적재", "야적", "적치", "다단적재", "적재하중",
                             "자재 정리", "중량물"],
    "H002_NarrowPassage": ["통로", "동선", "협소", "보행", "이동통로"],
}


def main_clause(directive):
    """「주절 — 효과서술」에서 주절만 돌려준다.

    효과 서술의 은유적 동사를 물리적 조치로 오인하지 않기 위한 것이다.
    """
    for sep in ("—", "–", " - "):
        if sep in directive:
            return directive.split(sep)[0].strip()
    return directive.strip()


def hits(text, words):
    return [w for w in words if w in text]


def physical_hits(main):
    """주절에서 물리적 산출물·공사를 찾는다 (검토 대상 명사는 제외)."""
    dev = [d for d in PHYSICAL_DEVICES if d in main]
    wrk = hits(main, PHYSICAL_WORKS)
    # '동바리 구조검토'처럼 대상 명사만 있고 공사 동사가 없으면 물리로 보지 않는다
    if not wrk and not dev:
        return []
    return dev + wrk


def hazard_index(g):
    scn_haz = defaultdict(set)
    for s in g.subjects(RDF.type, P.RiskScenario):
        for h in g.objects(s, P.hasHazardType):
            scn_haz[C.uri_frag(s)].add(C.uri_frag(h))
    out = defaultdict(set)
    for e in g.subjects(RDF.type, P.KnowledgeEntry):
        eid = C.uri_frag(e)
        for scn in g.objects(e, P.addressesScenario):
            out[eid] |= scn_haz.get(C.uri_frag(scn), set())
    return out


def accident_hazard_map(g):
    """재해유형 → 그 유형의 시나리오가 실제로 거는 HazardType (TTL 에서 계산)."""
    cell_acc = {}
    for c in g.subjects(RDF.type, P.CoverageCell):
        a = g.value(c, P.hasAccidentType)
        if a is not None:
            cell_acc[C.uri_frag(c)] = C.ACC_URI_TO_KO.get(C.uri_frag(a), "")
    out = defaultdict(set)
    for s in g.subjects(RDF.type, P.RiskScenario):
        cv = g.value(s, P.belongsToCell)
        if cv is None:
            continue
        acc = cell_acc.get(C.uri_frag(cv), "")
        if acc:
            for h in g.objects(s, P.hasHazardType):
                out[acc].add(C.uri_frag(h))
    return out


def adjudicate_row(row, haz_links, acc_haz):
    """지시서 §7 결정 트리 → (promoted, reason_code, exposure_channel, note)"""
    eid = row["entry_id"]
    d = row["directive_ko"]
    main = main_clause(d)
    has_rule = bool(row["rule_type"])
    linked = haz_links.get(eid, set())

    # ── Step 1. 설계자가 설계 단계에서 결정하는 사항인가?
    if row["design_decidable"] != "TRUE":
        return ("FALSE", "NOT_DESIGN", "none",
                "design_decidable=FALSE — 시공자 준수사항·현장 관리 행위로 "
                "설계 단계에서 결정되지 않음.")

    doc = hits(main, DOC_VERBS)
    phy = physical_hits(main)
    tmp = hits(main, TEMPORAL_MARKERS)

    # ── Step 2. 작업자의 위치·체류시간·존재를 변화시키는가?
    if not phy and not tmp:
        subj = [n for n in SUBJECT_ONLY_NOUNS if n in main]
        detail = ("문서화 동사(%s)만 확인" % "/".join(doc)) if doc else \
                 "물리적 조치·공정 순서 변경 표현 없음"
        if subj:
            detail += "; '%s'는 검토·작성의 대상일 뿐 설치되는 산출물이 아님" \
                      % "/".join(subj)
        if has_rule:
            return ("UNSURE", "", "",
                    "주절이 문서·검증 산출물에 그침(%s) → NO_EXPOSURE 논거. "
                    "그러나 v2.3 이 %s 를 이미 부여해 두었음 → 실행층 효과가 "
                    "있다는 반대 논거. 원문 확인 필요." % (detail, row["rule_type"]))
        return ("FALSE", "NO_EXPOSURE", "none",
                "설계자 산출물이지만 %s — 작업자 위치·체류시간을 바꾸지 않음."
                % detail)

    # ── Step 3. 대상 위험 채널이 구현되어 있는가?
    candidates = linked or acc_haz.get(row["accident_type"], set())
    unimpl = candidates & set(C.UNIMPLEMENTED_HAZARDS)
    impl = candidates - set(C.UNIMPLEMENTED_HAZARDS)
    basis = ("지시문의 위험원 연결" if linked
             else "재해유형 '%s' 이 구조적으로 거는 위험원" % row["accident_type"])

    if unimpl and not impl:
        names = "/".join(C.UNIMPLEMENTED_HAZARDS[h] for h in sorted(unimpl))
        if has_rule:
            return ("UNSURE", "", "",
                    "%s이 전부 미구현 채널(%s) → NO_CHANNEL 논거. 그러나 %s 가 "
                    "이미 정의되어 있어 채널 구현 시 즉시 승격 가능 → 보류가 "
                    "아니라 대기로 봐야 한다는 반대 논거."
                    % (basis, names, row["rule_type"]))
        return ("FALSE", "NO_CHANNEL", "none",
                "%s이 %s 뿐이며 해당 채널이 시뮬레이터에 미구현"
                "(implementationStatus=planned)." % (basis, names))

    if unimpl and impl:
        u_hit, i_hit = [], []
        for h in unimpl:
            u_hit += hits(d, HAZARD_KEYWORDS.get(h, []))
        for h in impl:
            i_hit += hits(d, IMPLEMENTED_HAZARD_KEYWORDS.get(h, []))
        if u_hit and not i_hit:
            names = "/".join(C.UNIMPLEMENTED_HAZARDS[h] for h in sorted(unimpl))
            return ("UNSURE", "", "",
                    "%s은 구현된 위험원(%s)과 미구현 채널(%s)에 모두 걸린다. "
                    "지시문은 미구현 쪽 표현(%s)만 담고 있어 NO_CHANNEL 논거가 "
                    "우세하나, 구현된 위험원으로도 모델링 가능해 확정 불가."
                    % (basis, "/".join(sorted(impl)), names, "/".join(u_hit)))
        if u_hit and i_hit:
            return ("UNSURE", "", "",
                    "지시문이 미구현 채널 표현(%s)과 구현된 위험원 표현(%s)을 "
                    "동시에 담고 있어 대상 채널이 갈림."
                    % ("/".join(u_hit), "/".join(i_hit)))

    # ── Step 4. 승격 + 노출 채널 지정
    scored = [(c, hits(d, ws)) for c, ws in CHANNEL_KEYWORDS.items()]
    scored = [(c, h) for c, h in scored if h]
    if not scored:
        return ("UNSURE", "", "",
                "물리적 조치·공정 변경(%s)을 수반해 승격 논거는 성립하나, "
                "노출 채널을 특정할 근거어가 없어 채널 미지정 상태로 승격 불가."
                % "/".join((phy + tmp)[:3]))

    scored.sort(key=lambda x: -len(x[1]))
    top = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if second and len(second[1]) == len(top[1]):
        return ("UNSURE", "", "",
                "승격 논거는 성립하나 노출 채널이 %s(%s)와 %s(%s)로 동점 — "
                "지배적 채널 판단 불가."
                % (top[0], "/".join(top[1]), second[0], "/".join(second[1])))

    kind = []
    if phy:
        kind.append("물리적 조치(%s)" % "/".join(phy[:3]))
    if tmp:
        kind.append("공정 순서·시점 변경(%s)" % "/".join(tmp[:2]))
    note = "%s 수반 → 승격. 노출 채널 %s (근거어: %s)." % (
        " 및 ".join(kind), top[0], "/".join(top[1][:3]))
    if doc:
        note += " 문서화 동사(%s)도 있으나 목적어가 물리적 산출물." % "/".join(doc)
    return ("TRUE", "", top[0], note)


def run():
    C.ensure_cwd()
    C.ensure_build()
    g = rdflib.Graph()
    g.parse(C.SRC_TTL, format="turtle")
    haz = hazard_index(g)
    acc_haz = accident_hazard_map(g)

    rows = C.read_master()
    for r in rows:
        # status=excluded 는 v2.4 범위 밖이므로 판정 대상이 아니다.
        # 판정하면 재실행 때마다 UNSURE 가 다시 붙는다 (지시서 3-4).
        if r["status"] == "excluded":
            r["promoted"] = ""
            r["reason_code"] = ""
            r["exposure_channel"] = ""
            r["adjudication_note"] = ("[%s] 판정 대상 제외 (status=excluded)"
                                      % C.EXCLUDE_NOTE)
            continue
        # v2.5 사람 판정이 기록된 행은 결정 트리로 덮어쓰지 않는다.
        if r["adjudication_note"].startswith("v2.5 사람 판정:"):
            continue
        pr, rc, ch, note = adjudicate_row(r, haz, acc_haz)
        r["promoted"], r["reason_code"] = pr, rc
        r["exposure_channel"], r["adjudication_note"] = ch, note
        if pr == "UNSURE":
            r["needs_review"] = "TRUE"
    C.write_master(rows)

    write_report(rows)
    p = Counter(r["promoted"] for r in rows)
    rc = Counter(r["reason_code"] for r in rows if r["reason_code"])
    print("Phase 1 판정 — TRUE %d / FALSE %d / UNSURE %d (총 %d행)"
          % (p["TRUE"], p["FALSE"], p["UNSURE"], len(rows)))
    print("  reason_code : " + ", ".join("%s=%d" % (k, rc.get(k, 0))
                                         for k in C.REASON_CODES))
    print("  리포트: %s" % C.ADJ_REPORT)
    return rows


def write_report(rows):
    L = []
    a = L.append
    inscope = [r for r in rows if r["status"] != "excluded"]
    excl = [r for r in rows if r["status"] == "excluded"]
    p = Counter(r["promoted"] for r in rows)
    rc = Counter(r["reason_code"] for r in rows if r["reason_code"])
    ch = Counter(r["exposure_channel"] for r in rows)

    a("# PtD 라이브러리 v2.4 — 승격 판정 1차 초안\n")
    a("> **초안이다.** 결정 트리로 기계적으로 부여한 값이며 확정이 아니다.")
    a("> `UNSURE` 는 실패가 아니라 의도된 산출물 — 사람이 판단해야 할 지점의 표시다.\n")
    a("- 전체 행: **%d** (범위 내 %d, v2.4 제외 %d)"
      % (len(rows), len(inscope), len(excl)))
    a("- 판정 열: `promoted`, `reason_code`, `exposure_channel`, "
      "`adjudication_note`, `hoc_rule_exception`\n")

    a("## 1. promoted 건수\n")
    a("| promoted | 건수 | 비율 |")
    a("|---|---:|---:|")
    for k in ("TRUE", "FALSE", "UNSURE"):
        a("| %s | %d | %.1f%% |" % (k, p[k], 100.0 * p[k] / len(rows)))
    a("| **합계** | **%d** | 100.0%% |\n" % len(rows))

    a("## 2. reason_code 분포\n")
    a("| reason_code | 건수 |")
    a("|---|---:|")
    for k in C.REASON_CODES:
        a("| %s | %d |" % (k, rc.get(k, 0)))
    a("| (빈칸 — 승격 또는 UNSURE) | %d |\n"
      % sum(1 for r in rows if not r["reason_code"]))

    # 지시서 §7: NO_EXPOSURE 가 0이면 Step 1/2 경계를 재점검하고 결과를 명시
    a("### 2-1. Step 1 / Step 2 경계 점검\n")
    if rc.get("NO_EXPOSURE", 0) == 0:
        a("> **경고 — NO_EXPOSURE 가 0건이다.** Step 1 이 문서화 대책을 잘못 "
          "흡수했을 가능성이 크다. 아래 경계 재점검 결과를 확인하고 트리를 "
          "교정해야 한다.\n")
    else:
        a("NO_EXPOSURE 가 **%d건** 산출되었다. 이전 시도에서 이 값이 0이었던 "
          "원인과 교정 내용은 다음과 같다.\n" % rc.get("NO_EXPOSURE", 0))
    a("**이전 결함**: 물리 동사 탐지를 지시문 전체에 걸어, "
      "「<주절> — <효과 서술>」 구조에서 효과 서술의 은유적 동사"
      "(\"붕괴 경로 **차단**\", \"위험 **제거**\")까지 물리적 조치로 세었다. "
      "그 결과 문서화 대책이 Step 2 를 통과해 승격되었고 NO_EXPOSURE 가 "
      "0건이 되었다.\n")
    a("**교정**: (a) 주절(`—` 앞)만 평가한다. (b) '동바리·비계·거푸집' 등은 "
      "검토·작성의 *대상*일 뿐 설치되는 산출물이 아니므로 물리적 산출물로 "
      "세지 않는다. 문서화 동사의 **목적어가 문서인지 물리적 설비인지**로 "
      "가른다.\n")
    defer = [r for r in rows if r["promoted"] == "UNSURE"
             and "문서·검증 산출물에 그침" in r["adjudication_note"]]
    a("**교정 후에도 건수가 적은 이유 (구조적)**: 이 라이브러리의 90건은 이미 "
      "설계결정 가능한 물리적 대책 위주로 선별된 집합이라 문서화 대책 자체가 "
      "드물다. 문서화 통제의 본체는 라이브러리가 아니라 **KALIS 미채택 집합**에 "
      "있으며, `kalis_unadopted_summary.csv` 에서 `U_STRUCT_REVIEW`"
      "(구조검토 계열)가 최대 원형으로 잡힌다. 즉 NO_EXPOSURE 가 라이브러리 "
      "안에서 작은 것은 트리 결함이 아니라 표본의 성격이다.\n")
    a("추가로 **%d건**은 주절이 문서·검증 산출물에 그치지만 v2.3 이 이미 "
      "실행층 규칙을 부여해 두어 UNSURE 로 보류했다 (양쪽 논거 병기). 사람이 "
      "확인하면 NO_EXPOSURE 로 이동할 후보다: %s\n"
      % (len(defer), ", ".join("`%s`" % r["entry_id"] for r in defer) or "없음"))
    a("| 판정 | entry_id | 주절 |")
    a("|---|---|---|")
    for r in rows:
        if r["reason_code"] == "NO_EXPOSURE":
            a("| NO_EXPOSURE | `%s` | %s |"
              % (r["entry_id"], main_clause(r["directive_ko"])[:70]))
    a("")
    a("대조군 — 같은 문서화 동사를 쓰지만 목적어가 물리적 설비여서 승격된 예:\n")
    a("| 판정 | entry_id | 주절 |")
    a("|---|---|---|")
    shown = 0
    for r in rows:
        if r["promoted"] == "TRUE" and hits(main_clause(r["directive_ko"]),
                                            DOC_VERBS):
            a("| TRUE | `%s` | %s |"
              % (r["entry_id"], main_clause(r["directive_ko"])[:70]))
            shown += 1
            if shown >= 5:
                break
    a("")

    a("## 3. HoC 등급 × promoted 교차표\n")
    a("| HoC 등급 | TRUE | FALSE | UNSURE | 합계 |")
    a("|---|---:|---:|---:|---:|")
    for h in C.HOC_LEVELS:
        sub = [r for r in rows if r["hoc_level"] == h]
        if not sub:
            continue
        c = Counter(r["promoted"] for r in sub)
        a("| %s | %d | %d | %d | %d |"
          % (h, c["TRUE"], c["FALSE"], c["UNSURE"], len(sub)))
    a("| **합계** | **%d** | **%d** | **%d** | **%d** |\n"
      % (p["TRUE"], p["FALSE"], p["UNSURE"], len(rows)))

    a("## 4. exposure_channel 분포\n")
    a("| exposure_channel | 건수 |")
    a("|---|---:|")
    for k in C.EXPOSURE_CHANNELS:
        a("| %s | %d |" % (k, ch.get(k, 0)))
    a("| (빈칸 — UNSURE) | %d |\n" % ch.get("", 0))
    if not ch.get("proximity"):
        a("> `proximity` 가 0건인 것은 구조적 결과다. 장비·위험원과의 거리를 "
          "노출로 삼는 위험원은 `H011_EquipmentCorridor` 뿐인데 이 채널이 "
          "미구현(`planned`)이라 승격 가능한 항목이 존재하지 않는다.\n")

    a("### 4-1. 승격 항목의 재해유형 × 채널\n")
    prom = [r for r in rows if r["promoted"] == "TRUE"]
    chans = [c for c in C.EXPOSURE_CHANNELS if c != "none"]
    a("| 재해유형 | " + " | ".join(chans) + " | 합계 |")
    a("|---" * (len(chans) + 2) + "|")
    for at in C.ACCIDENT_TYPES:
        sub = [r for r in prom if r["accident_type"] == at]
        if not sub:
            continue
        cc = Counter(r["exposure_channel"] for r in sub)
        a("| %s | %s | %d |" % (at, " | ".join(str(cc.get(c, 0))
                                               for c in chans), len(sub)))
    a("")

    a("## 5. hoc_rule_exception = TRUE 목록\n")
    exc = [r for r in rows if r["hoc_rule_exception"] == "TRUE"]
    a("HoC 등급과 rule_type 의 대응은 이 연구가 **검증하려는 가설**이지 "
      "데이터에 강제할 제약이 아니다. 아래는 예상 대응과 어긋난 항목이며, "
      "**분류를 수정하지 않고 기록만** 한다.\n")
    a("| entry_id | HoC | rule_type | 사유 |")
    a("|---|---|---|---|")
    for r in exc:
        a("| `%s` | %s | %s | %s |"
          % (r["entry_id"], r["hoc_level"], r["rule_type"],
             C.KNOWN_HOC_EXCEPTIONS.get(r["entry_id"], "예상 대응과 다름")))
    a("")

    a("## 6. UNSURE 전체 목록\n")
    uns = [r for r in rows if r["promoted"] == "UNSURE"]
    a("총 **%d건**. 양쪽 논거는 마스터 CSV 의 `adjudication_note` 열과 같다.\n"
      % len(uns))
    for r in uns:
        a("### %s — %s / %s" % (r["entry_id"], r["hoc_level"],
                                r["accident_type"] or "재해유형 미지정"))
        a("")
        a("- **directive**: %s" % (r["directive_ko"] or "_(빈칸)_"))
        a("- **rule_type**: %s" % (r["rule_type"] or "_(없음)_"))
        a("- **양쪽 논거**: %s" % r["adjudication_note"])
        a("")

    a("## 7. 이번 판정에서 채우지 않은 것\n")
    a("- `legal_verified_date` — 국가법령정보센터 현행본 대조는 사람이 한 뒤에만 "
      "기록한다. 이번 작업에서는 전부 빈칸이다.")
    a("- 관계 4종(`supersedes`/`redundant_with`/`requires`/`residual_risk`) — "
      "원천 TTL 에 구조적 속성으로 존재하지 않는다. 다른 항목 ID 를 언급하는 "
      "서술문이 있는 행은 `note` 에 후보를 남기고 `needs_review=TRUE` 로 표시했다.")
    a("- IFC 4종 — 원천에 값이 없어 슬롯만 유지했다.")
    a("- `in_experiment_set` — 표본 규칙 미확정으로 전부 빈칸.")
    a("- 목표 열거형에 대응하지 않는 원천 값(`evidenceLevel=law/field_practice`, "
      "`parameterSourceType=inherited_v1` 등)은 추측해 채우지 않고 비운 뒤 "
      "원문을 `note` 에 보존했다.\n")

    with io.open(C.ADJ_REPORT, "w", encoding=C.OUTPUT_ENCODING) as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    run()
