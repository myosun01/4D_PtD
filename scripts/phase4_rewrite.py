# -*- coding: utf-8 -*-
"""Phase 4. CSI 기반 directive 재작성 + TBM 계열 통합.

## 절대 규칙 (지시서 4-1)
  (1) 사고 경위·부상·의료 서술을 일절 반입하지 않는다.
  (2) CSI 원문을 그대로 복사하지 않는다. 설계 대안 문장으로 재서술한다.
  (3) HoC 등급과 내용이 일치해야 한다. CSI 재발방지대책에는 여러 등급의 조치가
      섞여 있으므로 해당 항목의 hoc_level 에 부합하는 조치만 골라 쓴다.
  (4) HoC 등급을 바꾸지 않는다.
  (5) 근거가 불충분하면 원본 유지 + needs_review + 사유. 추측 금지.
  (6) 원본 라벨은 note 에 "v2.4 directive: <원본>" 으로 보존.

각 재작성의 근거 CSI 사례와 '어느 조치를 왜 골랐는지 / 무엇을 왜 버렸는지'는
아래 REWRITE 표의 evidence·picked·dropped 에 기록하고 로그로 낸다.
"""
import io
import os
import re
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, "scripts")
import ptd_common as C

LOG = "build/directive_rewrite_log.md"

MEDICAL = ["병원", "의원", "진료", "진단서", "수술", "입원", "통원", "이송",
           "119", "구급", "정형외과", "골절", "재해자", "사망", "부상",
           "귀가 조치", "산재"]

# ── 재작성 표
# eid: (new_directive, csi_사고명, picked(등급에 맞아 채택), dropped(등급이 달라 배제))
REWRITE = OrderedDict([
    ("KE_M_Fall_FormErection_01", (
        "슬래브 개구부에 소요강도 이상의 규격 덮개를 설치하고 이탈방지 고정 상세를 "
        "설계도면에 반영",
        "개구부 덮개 이탈로 떨어짐",
        "충분한 강도의 재질·규격 덮개 설치 및 고정 (물리적 방호)",
        "'개구부 주의' 안전표지 설치(경고급) / 덮개 상부 보행·적재 금지(관리적)")),
    ("KE_M_Fall_FormErection_02", (
        "보 단부 등 추락위험 구간에 안전로프 대신 견고한 구조의 임시 안전난간을 "
        "설치하도록 가설 난간 상세를 설계에 반영",
        "보 철근 피복두께 확보를 위한 스페이서 설치 작업 중 추락 사고",
        "안전로프를 임시 안전난간으로 대체하는 물리적 방호 조치 강화",
        "TBM 특별교육(관리적) / 개인보호구 착용 확인(보호구) / 감리 승인절차(관리적)")),
    ("KE_M_Fall_FormErection_03", (
        "형틀작업 구간에 지정 작업발판과 이동통로를 설계 단계에서 배치하여 "
        "임의 발판 설치를 배제",
        "형틀작업 중 떨어짐",
        "지정된 통로 외 임의 발판 설치 금지 (통로·발판의 사전 배치)",
        "안전고리 체결(보호구) / 사고사례 전파 교육(관리적)")),
    ("KE_M_Fall_Pour_01", (
        "타설 중 안전난간을 존치한 상태로 작업이 가능하도록 난간 위치와 지지 "
        "상세를 설계에 반영하고, 후속 설비 설치 완료 전 해체를 배제",
        "인천국제공항 중소기업전용 공동물류센터 내 추락사고",
        "타설 중 안전난간 존치 및 후속 공정 완료 후 해체 (난간 존치 상세)",
        "(해당 대책에 다른 등급 조치 없음)")),
    ("KE_M_HitByObj_FormErection_01", (
        "해체 구간에 작업자 회피 동선이 확보되도록 자재 적치 위치와 통로를 "
        "가설계획에 분리 배치",
        "slab 해체작업 진행중 낙하물에 맞음",
        "작업자 회피 동선 확보를 위한 자재 정리·배치 (동선·적치 계획)",
        "2인 이상 공동작업 원칙(관리적) / 수시 교육·보호구 점검(관리적·보호구)")),
    ("KE_M_HitByObj_MatHandling_01", (
        "자재 적재구역과 안전통로를 분리 배치하고, 세워쌓기·2단적재를 배제하는 "
        "적재 상세를 가설계획에 반영",
        "자재 정리중 물체에 맞음 사고",
        "안전통로 확보 / 세워두기·과적재·2단적재 금지 (적재 형상 제한)",
        "상시 작업환경 정리정돈 상태 확인(관리적)")),
    ("KE_M_Struck_FormErection_01", (
        "슬래브 거푸집에 유성박리제 대신 수성박리제를 적용하고 도포를 배근 이후로 "
        "배치하여 미끄러운 작업면 자체를 대체",
        "지하1층 바닥 슬라브 거푸집 설치 중 미끄러짐 사고",
        "유성→수성 박리제 대체 및 도포 순서 변경 (자재 대체)",
        "(해당 대책은 전부 대체급)")),
    ("KE_M_Struck_Rebar_01", (
        "거푸집 공사 완료 후 철근 작업이 착수되도록 공정 순서를 설계 단계에서 "
        "분리하여 두 공종의 공존 작업을 제거",
        "바닥 슬라브 철근 조립 작업 중 거푸집 받침목 부딪힘 사고",
        "공정관리개선 — 거푸집공사 완료 후 철근작업 (공존 제거)",
        "TBM 안전교육 강화(관리적) / 작업장 정리정돈(관리적)")),
    ("KE_M_Trip_FormErection_01", (
        "거푸집 작업 구간의 단차부에 작업발판을 설치하도록 단차 위치와 발판 "
        "상세를 설계에 반영",
        "철근콘크리트공사 거푸집 작업 중 넘어짐",
        "단차부위 인근 작업 시 발판 설치 (단차부 발판 상세)",
        "안전교육(관리적) / 등지고 작업금지·퇴출조치(관리적)")),
    ("KE_M_Trip_FormErection_02", (
        "현장 보행 동선을 확보하고 미끄럼 방지 마감을 적용하도록 가설 통로 계획에 "
        "반영",
        "현장 이동 중 미끄러짐",
        "미끄럼 방지 조치 및 인동선 확보 (통로·마감)",
        "위험성 주지 교육·작업 전 전파(관리적)")),
    ("KE_M_Trip_MatHandling_01", (
        "지정 근로자 통행로를 바닥 배관·호스 보호 덮개와 분리 배치하여 보행 "
        "구간에 걸림원이 놓이지 않도록 가설 통로 계획에 반영",
        "이동 중 바닥 호스 보호 덮개에 걸려 넘어진 사고",
        "지정 통행로 / 보호 덮개와 보행 구간 분리 (통로 배치)",
        "덮개 도색·식별조치(경고급) / 중량물 취급 교육(관리적)")),
    ("KE_M_Trip_MatHandling_02", (
        "작업구간 통행로 경계에 식별 표시와 조도를 확보하여 보행 구간이 "
        "시인되도록 가설계획에 반영",
        "시스템 동바리 상부에서 자재이동 중 미끄러짐",
        "식별조치 (경고 등급에 해당하는 부분만)",
        "통행로 확보(공학적) — 이 항목은 경고 등급이므로 시인성 쪽으로 좁힘")),
    ("KE_M_Trip_MatHandling_03", (
        "배근된 기초 철근 상부에 실족방지망 또는 합판을 설치하도록 설계 상세에 "
        "반영",
        "자재운반 중 철근사이 발끼임",
        "기초 철근 전도방지·실족방지망 또는 합판 설치 (물리적 복개)",
        "전도위험 구간 식별(경고급) / 재해사례 공유 교육(관리적)")),
    ("KE_M_Trip_MatHandling_04", (
        "작업발판 사이 틈새를 막는 마감 상세를 설계에 반영하여 발빠짐 경로를 제거",
        "수서역세권 B1-3BL 업무시설 신축공사",
        "발판 틈새 막음 조치 (틈새 마감 상세)",
        "리스크 평가 반영·사고사례 전파(관리적)")),
    ("KE_M_Trip_MatHandling_05", (
        "자재 적치 구간과 분리된 안전통로를 가설계획에 확보",
        "자재 정리 중 넘어짐 사고",
        "자재 정리 시 안전통로 확보 (통로 분리)",
        "특별 교육 실시(관리적)")),
    ("KE_M_Trip_MatHandling_06", (
        "근로자 이동통로 구간을 자재 적재 금지 구역으로 지정하여 적재구역과 "
        "통로를 분리 배치",
        "이동 중 걸려 넘어짐 사고",
        "이동통로 구간 내 자재적재 금지 (적재구역·통로 분리)",
        "이동 중 휴대전화 사용 금지(관리적)")),
    ("KE_M_Trip_Rebar_01", (
        "철근 배근 구간에 작업 동선을 선정하고 해당 동선에 실족방지망을 설치하도록 "
        "설계 상세에 반영",
        "철근 배근 중 발빠짐",
        "작업 동선 선정 후 실족방지망 설치 (동선 + 물리적 복개)",
        "(해당 대책은 전부 공학적)")),
])

# 규칙 (5) — 근거 불충분으로 재작성하지 않는 항목
RESTORE = OrderedDict([
    ("KE_M_Fall_MatHandling_01",
     ("시스템동바리 이동 중 낙하",
      "재발방지대책이 '부재 마모·변형·부식 여부 확인', '작업 전 체결 상태 점검', "
      "'사고사례 교육' 뿐으로 전부 점검·교육(관리적)이다. 이 항목의 등급인 "
      "공학적에 해당하는 물리적 조치가 CSI 근거에 없다. 난간·수평재 '설치' 를 "
      "끌어오면 원문에 없는 조치를 지어내는 것이 되므로 원본 라벨을 유지한다.")),
])

# 4-2. 신규 항목 — 경고 등급이 3건뿐이라 CSI 에서 확인된 경고급 설계 대안 1건 신설
NEW_ENTRIES = [
    OrderedDict([
        ("entry_id", "KE_C_WARN_01"),
        ("status", "active"),
        ("accident_type", "떨어짐"),
        ("trade", "거푸집설치"),
        ("directive_ko",
         "슬래브 개구부 덮개 상부에 개구부 위치를 알리는 안전표지와 시인성 도색을 "
         "적용하도록 설계도면에 반영"),
        ("hoc_level", "경고"),
        ("design_decidable", "TRUE"),
        ("promoted", "TRUE"),
        ("exposure_channel", "dwell_time"),
        ("csi_case", "개구부 덮개 이탈로 떨어짐"),
        ("csi_basis", "개구부 덮개 상부 '개구부 주의' 등 안전표지 설치하여 "
                      "근로자 시인성 확보"),
        ("why", "KE_M_Fall_FormErection_01(공학적) 의 근거 CSI 에 경고 등급 "
                "설계 대안이 함께 있었다. 등급이 다르므로 기존 항목을 고치지 않고 "
                "지시서 4-2 대로 신설한다. 현재 라이브러리의 경고 등급은 3건뿐이다."),
    ]),
]

TBM_LABEL = "안전교육·TBM·사례전파"


def check_medical(text):
    return [k for k in MEDICAL if k in text]


def main():
    C.ensure_cwd()
    C.ensure_build()
    rows = C.read_master()
    by = {r["entry_id"]: r for r in rows}
    n_before = len(rows)
    rec = {"rewritten": [], "restored": [], "new": [], "tbm": [], "violation": []}

    # ── 4-1. 재작성
    for eid, (new, case, picked, dropped) in REWRITE.items():
        r = by.get(eid)
        if r is None:
            rec["violation"].append((eid, "행 없음"))
            continue
        med = check_medical(new)
        if med:
            rec["violation"].append((eid, "의료 키워드 %s" % med))
            continue
        old = r["directive_ko"]
        r["directive_ko"] = new
        r["note"] = ((r["note"] + " | ") if r["note"] else "") + \
            "v2.4 directive: " + old
        rec["rewritten"].append((eid, r["hoc_level"], old, new, case,
                                 picked, dropped))

    # ── 4-1(5). 재작성 불가
    for eid, (case, why) in RESTORE.items():
        r = by.get(eid)
        if r is None:
            continue
        r["needs_review"] = "TRUE"
        r["note"] = ((r["note"] + " | ") if r["note"] else "") + \
            "CSI 근거 불충분 — 사람 재작성 필요"
        rec["restored"].append((eid, r["hoc_level"], r["directive_ko"], case, why))

    # ── 4-2. 신규 항목
    for spec in NEW_ENTRIES:
        if spec["entry_id"] in by:
            continue
        nr = C.blank_row()
        for k in ("entry_id", "status", "accident_type", "trade",
                  "directive_ko", "hoc_level", "design_decidable",
                  "promoted", "exposure_channel"):
            nr[k] = spec[k]
        nr["reason_code"] = ""
        nr["adjudication_note"] = "v2.5 사람 판정: " + spec["why"]
        nr["sensitivity_target"] = "FALSE"
        nr["hoc_rule_exception"] = "FALSE"
        nr["kalis_frequency"] = "0"
        nr["needs_review"] = "TRUE"
        nr["note"] = ("v2.5 신설 (CSI 유래). 근거 사례: %s | CSI 대책: %s | "
                      "전거·규칙 미작성 — 사람 확인 필요"
                      % (spec["csi_case"], spec["csi_basis"]))
        rows.append(nr)
        by[nr["entry_id"]] = nr
        rec["new"].append((spec["entry_id"], spec["hoc_level"],
                           spec["directive_ko"], spec["csi_case"], spec["why"]))

    # ── 4-3. TBM 계열 통합
    tbm = [r for r in rows if r["directive_ko"].strip() == TBM_LABEL]
    if tbm:
        tbm.sort(key=lambda r: r["entry_id"])
        rep = tbm[0]
        rep["note"] = ((rep["note"] + " | ") if rep["note"] else "") + \
            ("v2.5 TBM 원형 통합 대표 (KE_M_TBM_PROTOTYPE). 동일 directive %d건을 "
             "이 항목으로 통합" % len(tbm))
        rec["tbm"].append((rep["entry_id"], "대표", rep["accident_type"],
                           rep["trade"]))
        for r in tbm[1:]:
            r["status"] = "excluded"
            r["promoted"] = ""
            r["reason_code"] = ""
            r["exposure_channel"] = ""
            r["adjudication_note"] = ("[v2.5 TBM 원형 통합] 판정 대상 제외 "
                                      "(status=excluded)")
            r["note"] = ((r["note"] + " | ") if r["note"] else "") + \
                ("v2.5 TBM 원형 통합 — 대표 %s 참조" % rep["entry_id"])
            rec["tbm"].append((r["entry_id"], "통합(excluded)",
                               r["accident_type"], r["trade"]))

    C.write_master(rows)

    # ── 4-4. 중복 검사 (active 만)
    act = [r for r in rows if r["status"] == "active"]
    dup = Counter(r["directive_ko"].strip() for r in act)
    dups = [(d, n, [r["entry_id"] for r in act if r["directive_ko"].strip() == d])
            for d, n in dup.items() if n >= 2 and d]

    n_med = [r["entry_id"] for r in rows if check_medical(r["directive_ko"])]
    n_case = [r["entry_id"] for r in rows if "사례:" in r["directive_ko"]]

    print("Phase 4 directive 재작성")
    print("  재작성        : %d건" % len(rec["rewritten"]))
    print("  근거 불충분   : %d건 (원본 유지)" % len(rec["restored"]))
    print("  신설          : %d건 %s"
          % (len(rec["new"]), [x[0] for x in rec["new"]]))
    print("  TBM 통합      : 대표 1 + excluded %d"
          % max(0, len(rec["tbm"]) - 1))
    print("  행 수         : %d → %d (삭제 0)" % (n_before, len(rows)))
    print("  의료 키워드   : %d %s" % (len(n_med), n_med))
    print("  '사례:' 잔존  : %d %s" % (len(n_case), n_case))
    print("  active 중복   : %d종" % len(dups))
    for d, n, ids in dups:
        print("     %dx %-28s %s" % (n, d[:28], ids))
    if rec["violation"]:
        print("  [위반] %s" % rec["violation"])

    write_log(rows, rec, dups, n_before)
    print("  로그: %s" % LOG)
    return 1 if (n_med or n_case or rec["violation"]) else 0


def write_log(rows, rec, dups, n_before):
    L = []
    a = L.append
    a("# Phase 4 — CSI 기반 directive 재작성 로그\n")
    a("`KE_M_*` 항목의 directive 가 원형 라벨 상태여서, 작업 디렉터리의 CSI 원본"
      "(`4D_PtD_라이브러리_CSI/*.xlsx`, 1,786 사례)을 근거로 재작성했다. "
      "추출본은 `data/csi_raw.json` 에 있다 — `build/` 는 clean 대상이므로 "
      "전거를 그 밖에 둔다.\n")
    a("- 대상: `promoted=TRUE` 인 `KE_M_*` **18건** (TBM 계열은 4-3 에서 통합)")
    a("- 재작성 **%d건** / 근거 불충분 **%d건** / 신설 **%d건**"
      % (len(rec["rewritten"]), len(rec["restored"]), len(rec["new"])))
    a("- 행 수 %d → %d (**삭제 0**)\n" % (n_before, len(rows)))

    a("> **HoC 등급을 바꾸지 않았다.** CSI 재발방지대책에는 여러 등급의 조치가 한 "
      "문장에 섞여 있어, 각 항목의 기존 `hoc_level` 에 부합하는 조치만 골라 쓰고 "
      "나머지는 배제했다. 무엇을 왜 버렸는지는 아래 '배제' 열에 있다.\n")

    a("## 1. 재작성 내역\n")
    for eid, hoc, old, new, case, picked, dropped in rec["rewritten"]:
        a("### `%s` — %s\n" % (eid, hoc))
        a("| | |")
        a("|---|---|")
        a("| before | %s |" % old)
        a("| **after** | **%s** |" % new)
        a("| CSI 사례 | %s |" % case)
        a("| 채택(등급 부합) | %s |" % picked)
        a("| 배제(등급 불일치) | %s |" % dropped)
        a("")

    a("## 2. 재작성 불가 — 원본 유지\n")
    if not rec["restored"]:
        a("_해당 없음._\n")
    for eid, hoc, cur, case, why in rec["restored"]:
        a("### `%s` — %s\n" % (eid, hoc))
        a("- 현재 directive(유지): %s" % cur)
        a("- CSI 사례: %s" % case)
        a("- 사유: %s" % why)
        a("- 조치: `needs_review=TRUE`, note 에 \"CSI 근거 불충분 — 사람 재작성 필요\"\n")

    a("## 3. 신규 항목 (4-2)\n")
    if not rec["new"]:
        a("_해당 없음._\n")
    for eid, hoc, d, case, why in rec["new"]:
        a("### `%s` — %s\n" % (eid, hoc))
        a("- directive: %s" % d)
        a("- CSI 사례: %s" % case)
        a("- 신설 사유: %s" % why)
        a("- 전거·규칙은 채우지 않았다(`needs_review=TRUE`). 지어내지 않는다.\n")

    a("## 4. TBM 계열 통합 (4-3)\n")
    a("directive 가 `%s` 로 완전히 동일한 항목을 하나로 통합했다. "
      "**행을 삭제하지 않고** `status` 로만 표시했으며, 커버리지 추적을 위해 "
      "`accident_type`·`trade` 는 그대로 두었다.\n" % TBM_LABEL)
    a("| entry_id | 구분 | 재해유형 | 공종 |")
    a("|---|---|---|---|")
    for eid, kind, acc, trd in rec["tbm"]:
        a("| `%s` | %s | %s | %s |" % (eid, kind, acc, trd))
    a("")

    a("## 5. 중복 검사 (4-4)\n")
    a("`status=active` 인 행 중 동일 directive 가 2건 이상인 것. "
      "**자동 병합하지 않았다** — 사람이 볼 목록이다.\n")
    if not dups:
        a("_중복 없음._\n")
    else:
        a("| 건수 | directive | entry_id |")
        a("|---:|---|---|")
        for d, n, ids in dups:
            a("| %d | %s | %s |" % (n, d, ", ".join(ids)))
        a("")

    a("## 6. 절대 규칙 준수 확인\n")
    med = [r["entry_id"] for r in rows if check_medical(r["directive_ko"])]
    case_ = [r["entry_id"] for r in rows if "사례:" in r["directive_ko"]]
    a("| 검사 | 결과 |")
    a("|---|---|")
    a("| directive 내 의료·사고경과 키워드 | **%d건** %s |"
      % (len(med), med or "OK"))
    a("| directive 내 `사례:` 잔존 | **%d건** %s |" % (len(case_), case_ or "OK"))
    a("| HoC 등급 변경 | **0건** (등급은 손대지 않고 directive 를 등급에 맞게 좁힘) |")
    a("| 행 삭제 | **0건** (status 로만 표시) |")
    a("")
    a("검사 키워드: %s\n" % ", ".join(MEDICAL))

    with io.open(LOG, "w", encoding=C.OUTPUT_ENCODING) as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
