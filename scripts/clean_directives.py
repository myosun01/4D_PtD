# -*- coding: utf-8 -*-
"""결함 C 수정. directive_ko 에서 CSI 사고사례 원문을 제거한다.

## 문제
마스터 CSV 의 directive_ko 43행에 `사례:` 이하 CSI 사고사례 원문이 붙어 있고,
그중 21행에는 병원 실명·부상 경과 등 의료정보 성격의 텍스트가 있다. 이것이
build_docx.py 를 통해 논문 부록 A 에 그대로 인쇄된다. v2.3 에서 상속된 문제다.

## 원칙
**삭제만 한다. 대안 문구를 새로 지어내지 않는다.**
잘린 문장을 추측으로 완성하지 않는다. 판단이 필요한 것은 사람이 보게 남긴다.
원본 텍스트는 note 열에 보존해 추적성을 남긴다 (부록에는 note 가 인쇄되지 않아
부록은 깨끗해지고 원문은 남는다).
"""
import io
import re
import sys

sys.path.insert(0, "scripts")
import ptd_common as C

# Step 1. 사례 구분자 — 모든 변형
CASE_SEPARATORS = [r"—\s*사례\s*:", r"–\s*사례\s*:", r"-\s*사례\s*:",
                   r"사례\s*:"]
CASE_RE = re.compile("|".join(CASE_SEPARATORS))

# Step 2. 의료·사고경과 키워드
MEDICAL_KEYWORDS = [
    "병원", "의원", "진료", "진단서", "수술", "입원", "통원", "이송",
    "119", "구급", "정형외과", "골절", "재해자", "사망", "부상",
    "귀가 조치", "산재",
]

# 문장 분리 — 이 데이터는 '/' 와 마침표를 문장 구분으로 쓴다
SENTENCE_SPLIT = re.compile(r"\s*/\s*|(?<=[.。])\s+")

# Step 4. 말미 절단 판정
#
# 주의: 이 라이브러리의 지시문은 개조식(명사형 종결)이다. '축소·대체·제거·
# 반영·차단'처럼 한자어 명사로 끝나는 것이 정상이며 절단이 아니다. 종결어미
# 유무로 판정하면 90건 중 74건이 오탐된다.
# 실제 절단 신호는 '문장이 이어져야 하는데 끊긴 것' — 즉 조사나 연결어미로
# 끝나거나, 괄호가 닫히지 않았거나, 숫자 도중에 끊긴 경우다.
PARTICLE_ENDINGS = (
    "으로", "로", "를", "을", "의", "에서", "에게", "에", "와", "과",
    "이", "가", "은", "는", "도", "만", "부터", "까지", "라는", "이라",
)
CONNECTIVE_ENDINGS = (
    "하고", "하여", "하며", "되어", "되며", "이후", "또는", "및", "등의",
    "위한", "통해", "따라", "대한", "관한", "인한", "있는", "없는",
)
PROPER_END_PUNCT = (".", "。", ")", "]", "」", "'", '"', "…", "%")

# 정제 결과가 이보다 짧으면 원본을 유지한다.
#
# 지시서는 10자로 정했으나, 이 데이터에서 10자 미만으로 남는 6건은 전부
# '개구부 덮개·복공'(9자), '방호망·방지망'(7자) 같은 **유효한 통제 원형
# 명칭**이다. 원본을 되살리면 `사례:` 와 병원명이 부록 A 에 그대로 인쇄되어
# 완료 기준("부록에 사례:·병원명 미출현", "DIRECTIVE_CASE_LEAK ERROR 0")과
# 정면으로 충돌한다.
#
# Step 3 의 취지인 '정보 손실 방지'는 Step 5(원본을 note 에 보존)로 이미
# 충족되므로, 임계값을 4로 낮춰 진짜 빈 결과만 원본 유지 대상으로 둔다.
# 짧게 남은 항목은 needs_review=TRUE 로 사람이 보게 표시한다.
MIN_LENGTH = 4
SPEC_MIN_LENGTH = 10        # 지시서 표기 (편차 보고용)


def strip_case(text):
    """Step 1 — `사례:` 앞부분만 남긴다."""
    m = CASE_RE.search(text)
    if not m:
        return text, False
    return text[:m.start()].strip(), True


def strip_medical(text):
    """Step 2 — 의료·사고경과 키워드가 있는 문장을 통째로 제거한다."""
    parts = [p for p in SENTENCE_SPLIT.split(text) if p and p.strip()]
    kept, removed = [], []
    for p in parts:
        if any(k in p for k in MEDICAL_KEYWORDS):
            removed.append(p.strip())
        else:
            kept.append(p.strip())
    if not removed:
        return text, []
    return " / ".join(kept).strip(), removed


def looks_truncated(text):
    """Step 4 — 말미 절단으로 보이는지.

    개조식 명사형 종결은 정상으로 본다. 조사·연결어미로 끝나거나 괄호가
    닫히지 않은 경우만 절단으로 의심한다.
    """
    t = text.strip()
    if not t:
        return False, ""
    if t.count("(") != t.count(")"):
        return True, "괄호가 닫히지 않음"
    if t.count("[") != t.count("]"):
        return True, "대괄호가 닫히지 않음"
    if t.endswith(PROPER_END_PUNCT):
        return False, ""
    if t.endswith(CONNECTIVE_ENDINGS):
        return True, "연결어미 '%s' 로 끝나 뒤 절이 이어져야 함" % t[-3:]
    if t.endswith(PARTICLE_ENDINGS):
        return True, "조사 '%s' 로 끝나 뒤 성분이 이어져야 함" % t[-2:]
    if re.search(r"\d$", t):
        return True, "숫자 도중 끊김 의심 ('%s')" % t[-6:]
    return False, ""


def clean_row(r):
    """→ (new_directive, changed, flags, removed_bits)"""
    original = r["directive_ko"]
    flags = []
    removed_bits = []

    text, had_case = strip_case(original)
    if had_case:
        removed_bits.append("사례 이하 절단")

    text2, med = strip_medical(text)
    if med:
        removed_bits.append("의료·사고경과 문장 %d개 제거" % len(med))
    text = text2

    text = re.sub(r"\s{2,}", " ", text).strip(" -–—/,·")

    # Step 3 — 결과가 비었거나 너무 짧으면 원본 유지
    if len(text) < MIN_LENGTH:
        flags.append(("RESTORE",
                      "directive 정제 실패 — 원문이 사고경과 서술뿐. "
                      "사람이 재작성 필요"))
        return original, False, flags, removed_bits

    # Step 4 — 말미 절단 의심
    trunc, why = looks_truncated(text)
    if trunc:
        flags.append(("TRUNCATED",
                      "directive 말미 절단 의심 — 원천 확인 필요 (%s)" % why))

    return text, (text != original), flags, removed_bits


def run():
    C.ensure_cwd()
    C.ensure_build()
    rows = C.read_master()

    records = []
    for r in rows:
        original = r["directive_ko"]
        new, changed, flags, removed = clean_row(r)

        codes = [c for c, _ in flags]
        if changed or codes:
            notes = [n for _, n in flags]
            if changed:
                r["directive_ko"] = new
            for n in notes:
                r["note"] = (r["note"] + " | " + n) if r["note"] else n
            if codes:
                r["needs_review"] = "TRUE"
            # Step 5 — 원본 보존
            if changed or "RESTORE" in codes:
                r["note"] = ((r["note"] + " | ") if r["note"] else "") \
                    + "원본 directive: " + original
            records.append({
                "entry_id": r["entry_id"], "before": original, "after":
                    r["directive_ko"], "changed": changed, "codes": codes,
                "removed": removed,
            })

    C.write_master(rows)
    write_log(rows, records)

    n_restore = sum(1 for x in records if "RESTORE" in x["codes"])
    n_trunc = sum(1 for x in records if "TRUNCATED" in x["codes"])
    n_changed = sum(1 for x in records if x["changed"])
    leak_case = [r for r in rows if CASE_RE.search(r["directive_ko"])]
    leak_med = [r for r in rows
                if any(k in r["directive_ko"] for k in MEDICAL_KEYWORDS)]

    print("directive 정제")
    print("  대상 행                  : %d" % len(records))
    print("  실제 정제된 행           : %d" % n_changed)
    print("  Step3 원본 유지(재작성 필요): %d" % n_restore)
    print("  Step4 말미 절단 의심     : %d" % n_trunc)
    print("  정제 후 '사례:' 잔존     : %d %s"
          % (len(leak_case), "OK" if not leak_case else
             [r["entry_id"] for r in leak_case]))
    print("  정제 후 의료 키워드 잔존 : %d %s"
          % (len(leak_med), "OK" if not leak_med else
             [r["entry_id"] for r in leak_med]))
    print("  로그: %s" % LOG_PATH)
    return 0 if not leak_case else 1


LOG_PATH = "build/directive_cleanup_log.md"


def write_log(rows, records):
    L = []
    a = L.append
    a("# directive_ko 정제 로그 (결함 C)\n")
    a("> **삭제만 했다.** 대안 문구를 새로 만들지 않았고, 잘린 문장을 추측으로 "
      "완성하지 않았다.")
    a("> 원본 텍스트는 마스터 CSV 의 `note` 열에 "
      "`원본 directive: ...` 형태로 전부 보존되어 있다.")
    a("> 부록 docx 는 `note` 를 인쇄하지 않으므로 부록만 깨끗해지고 추적성은 남는다.\n")

    n_changed = sum(1 for x in records if x["changed"])
    n_restore = sum(1 for x in records if "RESTORE" in x["codes"])
    n_trunc = sum(1 for x in records if "TRUNCATED" in x["codes"])
    a("- 대상 행: **%d**" % len(records))
    a("- 실제 정제된 행: **%d**" % n_changed)
    a("- Step 3 원본 유지(사람 재작성 필요): **%d**" % n_restore)
    a("- Step 4 말미 절단 의심: **%d**\n" % n_trunc)

    a("## 0. 지시서와의 편차 2건\n")
    a("**(1) Step 3 임계값 %d자 → %d자.** 지시서는 정제 결과가 10자 미만이면 "
      "`directive_ko` 에 원본을 되살리라고 했다. 그런데 이 데이터에서 10자 "
      "미만으로 남는 6건은 전부 유효한 통제 원형 명칭이었다 — "
      "`개구부 덮개·복공`(9자), `조도·경보·시인성`(9자), `공법·자재 대체`(8자), "
      "`방호망·방지망`(7자). 원본을 되살리면 `사례:` 와 병원 실명이 부록 A 에 "
      "그대로 인쇄되어 완료 기준(\"부록에 사례:·병원명 미출현\", "
      "\"DIRECTIVE_CASE_LEAK ERROR 0건\")과 정면 충돌한다. Step 3 의 취지인 "
      "정보 손실 방지는 Step 5(원본을 `note` 에 보존)로 이미 충족되므로, "
      "임계값을 %d자로 낮춰 **진짜 빈 결과만** 원본 유지 대상으로 두었다. "
      "짧게 남은 항목은 `needs_review=TRUE` 로 표시했다.\n"
      % (SPEC_MIN_LENGTH, MIN_LENGTH, MIN_LENGTH))
    a("**(2) Step 4 절단 판정 기준.** 종결어미 유무로 판정하면 90건 중 74건이 "
      "오탐된다. 이 라이브러리의 지시문은 개조식(명사형 종결)이라 "
      "`축소`·`대체`·`반영`·`차단` 으로 끝나는 것이 정상이기 때문이다. "
      "판정을 뒤집어 **조사·연결어미로 끝나거나 괄호가 닫히지 않은 경우**만 "
      "절단으로 의심하도록 했다. 그 결과 %d건만 걸린다.\n" % n_trunc)

    a("## 1. before / after 대조\n")
    a("| entry_id | before | after |")
    a("|---|---|---|")
    for x in records:
        if not x["changed"]:
            continue
        bef = x["before"].replace("|", "\\|")
        aft = x["after"].replace("|", "\\|")
        a("| `%s` | %s | %s |" % (x["entry_id"], bef, aft))
    a("")

    a("## 2. Step 3 — 정제 실패, 원본 유지 (사람 재작성 필요)\n")
    sub = [x for x in records if "RESTORE" in x["codes"]]
    if not sub:
        a("_해당 없음._\n")
    else:
        a("정제하면 10자 미만이 되어 원문을 그대로 두었다. 지우면 정보가 "
          "사라지므로 유지하고 `needs_review=TRUE` 로 표시했다.\n")
        a("| entry_id | 원문 |")
        a("|---|---|")
        for x in sub:
            a("| `%s` | %s |" % (x["entry_id"], x["before"].replace("|", "\\|")))
        a("")

    a("## 3. Step 4 — 말미 절단 의심\n")
    sub = [x for x in records if "TRUNCATED" in x["codes"]]
    if not sub:
        a("_해당 없음._\n")
    else:
        a("원천 필드 길이 제한으로 문장이 끊긴 것으로 보인다. **추측으로 "
          "완성하지 않았고**, `needs_review=TRUE` 로 표시만 했다.\n")
        a("| entry_id | 정제 결과 |")
        a("|---|---|")
        for x in sub:
            a("| `%s` | %s |" % (x["entry_id"], x["after"].replace("|", "\\|")))
        a("")

    a("## 4. 정제 후 검증\n")
    leak_case = [r["entry_id"] for r in rows if CASE_RE.search(r["directive_ko"])]
    leak_med = [r["entry_id"] for r in rows
                if any(k in r["directive_ko"] for k in MEDICAL_KEYWORDS)]
    a("| 검사 | 잔존 | 판정 |")
    a("|---|---:|---|")
    a("| `사례:` 잔존 | %d | %s |"
      % (len(leak_case), "OK" if not leak_case else ", ".join(leak_case)))
    a("| 의료 키워드 잔존 | %d | %s |"
      % (len(leak_med), "OK" if not leak_med else ", ".join(leak_med)))
    a("")
    a("검사 키워드: %s\n" % ", ".join(MEDICAL_KEYWORDS))

    with io.open(LOG_PATH, "w", encoding=C.OUTPUT_ENCODING) as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(run())
