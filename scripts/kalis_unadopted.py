# -*- coding: utf-8 -*-
"""Phase 1-3. KALIS 원본 중 라이브러리 미채택 통제를 원형(archetype) 단위로 집계.

대상 범위 (지시서 §8)
  시설물분류(대) = 건축
  공종분류(중)   ∈ {철근콘크리트공사, 가설공사}
  인적피해       = v2.4 대상 6개 재해유형 (찔림·질식·감전·화재 등 제외)
  중복 제거      = (설계단계, 위험발생객체분류(중), 인적피해)

지시서는 이 범위를 "약 3,297건"으로 적었으나 실측은 3,227건이다.
찔림을 포함하면 3,322건이 되어 3,297 은 두 값 사이에 있다. 어느 키 조합으로도
정확히 재현되지 않으므로, 숫자를 맞추려 중복제거 키를 조작하지 않고
v2.4 범위와 일관된 정의(찔림 제외)를 쓰고 차이를 로그에 남긴다.
"""
import csv
import io
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "scripts")
import ptd_common as C

SPEC_EXPECTED = 3297        # 지시서 표기 (참고용)

IN_SCOPE_FACILITY = "건축"
IN_SCOPE_TRADES = {"철근콘크리트공사", "가설공사"}
IN_SCOPE_HARM_PREFIX = ("깔림", "떨어짐", "물체에 맞음", "부딪힘", "넘어짐", "끼임")

# 통제 원형. (code, label, hoc_level, adopted_as, keywords)
# 앞에서부터 먼저 매칭되는 원형을 채택한다 (구체적인 것을 위에).
ARCHETYPES = [
    # ── 이미 라이브러리에 채택된 원형
    ("C_SCAF_SYS", "시스템비계·시스템동바리 적용", "대체",
     "KE_K_FE_10;KE_K_CP_07",
     ["시스템비계", "시스템 비계", "시스템동바리", "시스템 동바리"]),
    ("C_SHORE_KEEP", "동바리 존치기간·해체시기 명기", "관리적",
     "KE_K_FS_02", ["존치기간", "존치 기간", "해체시기", "해체 시기"]),
    ("C_SEQ", "조립·해체 작업순서도 반영", "제거",
     "KE_K_CP_09", ["작업순서도", "해체 순서", "해체순서", "조립순서"]),
    ("C_GROUND", "지반 평탄화·지지력 확보", "공학적",
     "KE_K_FE_11",
     ["지반 안전성", "지반안전성", "지반 평탄", "버림콘크리트", "지지 지반"]),
    ("C_CERT", "가설기자재 인증품·품질관리", "관리적",
     "KE_K_CP_08", ["인증품", "가설자재 품질", "재사용 가설자재", "반입시험"]),
    ("C_LOAD", "적재하중 제한·다단적재 금지", "공학적",
     "KE_K_HS_05", ["적재하중", "다단적재", "다단 적재", "과적재"]),
    ("C_REBAR_TIP", "철근 전도방지 버팀대", "공학적",
     "KE_K_RB_03", ["전도방지", "전도 방지", "경사버팀대"]),
    ("C_FENCE", "가설울타리·낙하영향구역 분리", "공학적",
     "KE_K_HS_06", ["가설울타리", "가설휀스", "방호선반", "낙하물 방지망"]),
    ("C_LIGHT", "정리정돈·통로 조명", "경고",
     "KE_K_TR_08", ["조명", "정리정돈", "정리 정돈"]),
    ("C_MACH", "기계 방호장치", "공학적",
     "KE_K_CA_02;KE_K_CA_03", ["방호장치", "덮개 설치", "가공기계"]),
    ("C_LAYOUT", "작업자·장비 동선 분리 가설배치도", "공학적",
     "KE_K_ST_03", ["가설배치도", "동선 분리", "동선분리", "신호수"]),
    ("C_ROUTE", "작업자 전용 이동통로·실족방지 발판", "공학적",
     "KE_K_RB_02", ["이동통로", "실족방지", "작업통로", "안전통로"]),

    # ── 미채택 원형
    ("U_STRUCT_REVIEW", "구조검토·구조안전성 검토 실시", "관리적", "",
     ["구조검토", "구조 검토", "구조계산", "구조안전성", "구조 안전성",
      "안전성 검토", "안전성검토", "설계안전검토", "안전성 확인"]),
    ("U_SHOP_DRAWING", "조립도·상세도·작업도 작성", "관리적", "",
     ["조립도", "상세도", "작업도", "시공상세", "설치 도면 작성",
      "도면 작성", "접합상세"]),
    ("U_PLAN_DOC", "작업계획서·시공계획 수립", "관리적", "",
     ["작업계획", "시공계획", "계획서", "계획 수립", "관리계획",
      "대책 수립", "안전대책"]),
    ("U_EDU", "안전교육·특별교육 실시", "관리적", "",
     ["안전교육", "특별교육", "교육 실시", "TBM"]),
    ("U_GUARDRAIL", "안전난간·추락방지시설 설치", "공학적", "",
     ["안전난간", "추락방지시설", "추락 방지시설", "안전난간대", "방호난간"]),
    ("U_WORKPLATFORM", "작업발판·계단실 발판 설치", "공학적", "",
     ["작업발판", "작업 발판", "발판 설치", "승강설비"]),
    ("U_CONNECTOR", "연결재·벽이음 등 부재 접합 보강", "공학적", "",
     ["수평연결재", "벽연결", "벽이음", "플랫타이", "긴결", "연결 철물"]),
    ("U_ACCESS_CTRL", "위험구역 출입통제", "관리적", "",
     ["출입통제", "출입 통제", "위험구역 통제", "통제", "출입금지"]),
    ("U_POUR_CTRL", "타설 속도·순서·측압 관리", "관리적", "",
     ["타설 속도", "타설속도", "타설순서", "타설 순서", "측압"]),
    ("U_MARKING", "위험요소 도면 표기·표지", "경고", "",
     ["도면에 표기", "표기", "표지", "식별조치", "시인성"]),
    # 주의: '안전대'를 단독으로 쓰면 '안전대책'까지 걸린다. 위 U_PLAN_DOC 가
    # '안전대책'을 먼저 잡고, 여기서는 조사·후행어를 붙여 한정한다.
    ("U_PPE", "안전대·보호구 사용", "보호구", "",
     ["안전대 ", "안전대를", "안전대의", "안전대 부착", "안전대걸이",
      "보호구", "안전모", "안전고리"]),
    ("U_STD_COMPLY", "기준·시방서 준수 일반", "관리적", "",
     ["준수", "시방서", "기준에 적합", "안전기준", "법령"]),
]

NULLISH = {"", "(해당없음)", "해당없음", "없음", "-", "<잔여위험요소로 반영>",
           "잔여위험요소로 반영"}

# 원형 단위 결정 트리 (Phase 1 과 동일 순서)
#   Step1 설계자가 결정하지 않음        → NOT_DESIGN
#   Step2 문서·검증 산출물에 그침        → NO_EXPOSURE
#   Step3 대상 채널 미구현              → NO_CHANNEL
#   Step4 그 외                        → 승격 후보
TREE = {
    # Step 1 — 시공자 준수사항·현장 관리 행위
    "U_EDU":            ("FALSE", "NOT_DESIGN"),
    "U_ACCESS_CTRL":    ("FALSE", "NOT_DESIGN"),
    "U_STD_COMPLY":     ("FALSE", "NOT_DESIGN"),
    # Step 2 — 설계자 산출물이나 검토·작성·표기에 그쳐 노출 불변
    "U_STRUCT_REVIEW":  ("FALSE", "NO_EXPOSURE"),
    "U_SHOP_DRAWING":   ("FALSE", "NO_EXPOSURE"),
    "U_PLAN_DOC":       ("FALSE", "NO_EXPOSURE"),
    "U_MARKING":        ("FALSE", "NO_EXPOSURE"),
    "U_PPE":            ("FALSE", "NO_EXPOSURE"),
    # Step 3 — 동바리 붕괴(H008) 채널 미구현
    "U_POUR_CTRL":      ("FALSE", "NO_CHANNEL"),
    # Step 4 — 물리적 설비 설치 → 승격 후보이나 채널 특정 필요
    "U_GUARDRAIL":      ("UNSURE", ""),
    "U_WORKPLATFORM":   ("UNSURE", ""),
    "U_CONNECTOR":      ("UNSURE", ""),
}


def classify(text):
    for code, label, hoc, adopted, kws in ARCHETYPES:
        if any(k in text for k in kws):
            return code, label, hoc, adopted
    return None


def run():
    C.ensure_cwd()
    C.ensure_build()

    total = 0
    scoped = []
    with io.open(C.SRC_KALIS_PROFILE, encoding=C.PROFILE_ENCODING,
                 errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            total += 1
            if r.get("시설물분류(대)") != IN_SCOPE_FACILITY:
                continue
            if r.get("공종분류(중)") not in IN_SCOPE_TRADES:
                continue
            harm = (r.get("인적피해") or "").strip()
            if not any(harm.startswith(h) for h in IN_SCOPE_HARM_PREFIX):
                continue
            scoped.append(r)

    # 중복 제거
    seen, uniq = set(), []
    for r in scoped:
        k = ((r.get("설계단계") or "").strip(),
             r.get("위험발생객체분류(중)"), r.get("인적피해"))
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    buckets = defaultdict(list)
    unclassified, nullish = [], 0
    for r in uniq:
        text = (r.get("설계단계") or "").strip()
        if text in NULLISH:
            nullish += 1
            continue
        hit = classify(text)
        if hit is None:
            unclassified.append(text)
        else:
            buckets[hit].append(text)

    out = []
    for (code, label, hoc, adopted), texts in buckets.items():
        if adopted:
            continue
        promoted, reason = TREE.get(code, ("UNSURE", ""))
        ex = [t for t, _ in Counter(texts).most_common(3)]
        out.append({
            "archetype": code, "archetype_label": label, "hoc_level": hoc,
            "count": len(texts), "promoted": promoted, "reason_code": reason,
            "example_1": ex[0] if len(ex) > 0 else "",
            "example_2": ex[1] if len(ex) > 1 else "",
            "example_3": ex[2] if len(ex) > 2 else "",
        })
    out.sort(key=lambda x: -x["count"])

    # 원형에 담기지 않은 행도 표에 남긴다 (조용히 사라지면 안 됨)
    if unclassified:
        ex = [t for t, _ in Counter(unclassified).most_common(3)]
        out.append({
            "archetype": "U_UNCLASSIFIED",
            "archetype_label": "원형 미분류 — 키워드 사전에 걸리지 않은 설계단계 기술",
            "hoc_level": "", "count": len(unclassified),
            "promoted": "UNSURE", "reason_code": "",
            "example_1": ex[0] if len(ex) > 0 else "",
            "example_2": ex[1] if len(ex) > 1 else "",
            "example_3": ex[2] if len(ex) > 2 else "",
        })
    if nullish:
        out.append({
            "archetype": "U_NULL",
            "archetype_label": "설계단계 공란·(해당없음)·잔여위험요소 표기",
            "hoc_level": "", "count": nullish,
            "promoted": "FALSE", "reason_code": "NO_EXPOSURE",
            "example_1": "(해당없음)", "example_2": "없음",
            "example_3": "<잔여위험요소로 반영>",
        })

    fields = ["archetype", "archetype_label", "hoc_level", "count",
              "promoted", "reason_code", "example_1", "example_2", "example_3"]
    with io.open(C.KALIS_UNADOPTED, "w", encoding=C.OUTPUT_ENCODING,
                 newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)

    adopted_n = sum(len(v) for k, v in buckets.items() if k[3])
    unadopted_n = sum(r["count"] for r in out
                      if r["archetype"] not in ("U_UNCLASSIFIED", "U_NULL"))
    n_arch = sum(1 for r in out
                 if r["archetype"] not in ("U_UNCLASSIFIED", "U_NULL"))

    print("KALIS 미채택 원형 집계")
    print("  원본 전체                    : %s행" % "{:,}".format(total))
    print("  범위 필터 후                 : %s행" % "{:,}".format(len(scoped)))
    print("  중복 제거 후                 : %s행  (지시서 표기 ~%s / 차이 %+d)"
          % ("{:,}".format(len(uniq)), "{:,}".format(SPEC_EXPECTED),
             len(uniq) - SPEC_EXPECTED))
    print("    └ 찔림 포함 시 3,322 — 지시서의 3,297 은 두 값 사이. "
          "v2.4 범위(찔림 제외)를 따랐다.")
    print("  채택 원형에 해당             : %s행" % "{:,}".format(adopted_n))
    print("  미채택 원형                  : %s행 (%d개 원형)"
          % ("{:,}".format(unadopted_n), n_arch))
    print("  설계단계 공란/해당없음        : %s행" % "{:,}".format(nullish))
    print("  원형 미분류                  : %s행" % "{:,}".format(len(unclassified)))
    print("  대조 합계                    : %d = %d %s"
          % (adopted_n + unadopted_n + nullish + len(unclassified), len(uniq),
             "OK" if adopted_n + unadopted_n + nullish + len(unclassified)
             == len(uniq) else "불일치"))
    print("  산출: %s" % C.KALIS_UNADOPTED)
    return out


if __name__ == "__main__":
    run()
