# -*- coding: utf-8 -*-
"""Phase 3. UNSURE 32건 판정 확정 (사람의 판단 결과를 직접 적용).

결정 트리를 다시 돌리지 않는다. 지시서에 명시된 판정을 그대로 반영한다.

exposure_channel 은 대안 문구가 아니라 **재해유형**이 결정한다.
"""
import io
import os
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, "scripts")
import ptd_common as C

LOG = "build/phase3_adjudication_log.md"

# 재해유형 → 노출 채널 (지시서 3-1)
CHANNEL_BY_ACCIDENT = {
    "떨어짐": "dwell_time",
    "무너짐": "zone_occupancy",
    "넘어짐": "passage_count",
    "물체에맞음": "passage_count",
    "부딪힘": "passage_count",
    "끼임": "proximity",
}

GROUP_A = ["KE_K_CP_09", "KE_S_CP_05", "KE_K_CP_07", "KE_T_CP_01",
           "KE_K_FE_11", "KE_S_CP_04", "KE_T_CP_03"]
REASON_A = ("H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 소멸")

GROUP_B = ["KE_T_HS_04", "KE_K_HS_06", "KE_T_HS_02", "KE_K_HS_05"]
REASON_B = ("LCR_DROP_ZONE 템플릿 추가로 NO_CHANNEL 논거 소멸")

GROUP_C = ["KE_T_HS_01", "KE_S_FE_09", "KE_T_HS_03", "KE_M_Struck_Rebar_01",
           "KE_K_FE_10", "KE_S_FE_07", "KE_S_FE_08",
           "KE_M_Struck_FormErection_01", "KE_K_CA_02", "KE_K_CA_03",
           "KE_M_Trip_FormErection_01", "KE_M_Trip_MatHandling_03",
           "KE_M_Trip_MatHandling_04", "KE_M_Trip_Rebar_01",
           "KE_M_Fall_FormErection_03", "KE_M_Trip_MatHandling_02",
           "KE_H001_06"]
REASON_C = ("채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정")

# 지시서가 열거하지 않은 UNSURE 1건.
# 실측 UNSURE 는 32건이나 지시서 목록은 31건이며, KE_K_RB_03(철근 전도방지
# 버팀대 / 물체에맞음 / 공학적)이 빠져 있다. 그룹 (c)와 성격이 같아 같은 처리를
# 적용하고 로그에 별도로 표시한다.
GROUP_C_EXTRA = ["KE_K_RB_03"]
REASON_C_EXTRA = ("채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정. "
                  "지시서 3-1 목록에 누락된 항목으로 그룹 (c)와 동일 처리")

# 3-3. 승격 + H011 채널 신규 구현
ST_03 = "KE_K_ST_03"
REASON_ST03 = ("H011_EquipmentCorridor 채널을 R6 로 신규 구현 "
               "(장비 에이전트 없이 주행 구역을 정적 zone 으로 두고 통과 횟수 계수)")

# 3-2. 구조검토·조립도 작성은 설계자 산출물이나 노출을 바꾸지 않는다
CP_02 = "KE_T_CP_02"
REASON_CP02 = ("구조검토·조립도 작성은 설계자 산출물이나 작업자의 위치·체류시간을 "
               "바꾸지 않는다. 승격하지 않는 항목에 실행 규칙이 붙어 있는 것은 "
               "모순이므로 AgentParameterRule 을 제거한다. "
               "kalis_unadopted 의 U_STRUCT_REVIEW(NO_EXPOSURE) 및 부록 C 서술과 정합")

RULE_COLS = ["rule_type", "rule_id", "simulation_action", "parameter_value",
             "parameter_source"]


def main():
    C.ensure_cwd()
    C.ensure_build()
    rows = C.read_master()
    by = {r["entry_id"]: r for r in rows}
    changes = []

    def note(r, txt):
        r["adjudication_note"] = "v2.5 사람 판정: " + txt

    def promote(eid, reason, group):
        r = by.get(eid)
        if r is None:
            changes.append((eid, group, "-", "-", "행 없음"))
            return
        before = (r["promoted"], r["exposure_channel"])
        ch = CHANNEL_BY_ACCIDENT.get(r["accident_type"], "")
        if not ch:
            changes.append((eid, group, before[0], "?",
                            "재해유형 '%s' 미매핑 — 채널 지정 불가"
                            % r["accident_type"]))
            return
        r["promoted"] = "TRUE"
        r["reason_code"] = ""
        r["exposure_channel"] = ch
        note(r, "%s (재해유형 %s → %s)" % (reason, r["accident_type"], ch))
        changes.append((eid, group, before[0], ch, reason[:46]))

    for e in GROUP_A:
        promote(e, REASON_A, "a")
    for e in GROUP_B:
        promote(e, REASON_B, "b")
    for e in GROUP_C:
        promote(e, REASON_C, "c")
    for e in GROUP_C_EXTRA:
        promote(e, REASON_C_EXTRA, "c+")
    promote(ST_03, REASON_ST03, "3-3")

    # ── 3-2. KE_T_CP_02
    r = by[CP_02]
    removed = OrderedDict((c, r[c]) for c in RULE_COLS if r[c])
    r["promoted"] = "FALSE"
    r["reason_code"] = "NO_EXPOSURE"
    r["exposure_channel"] = "none"
    for c in RULE_COLS:
        r[c] = ""
    r["sensitivity_target"] = "FALSE"
    note(r, REASON_CP02)
    if removed:
        r["note"] = ((r["note"] + " | ") if r["note"] else "") + \
            "v2.5 규칙 제거: " + ", ".join("%s=%s" % kv for kv in removed.items())
    changes.append((CP_02, "3-2", "UNSURE", "none",
                    "FALSE/NO_EXPOSURE + 규칙 %d개 필드 제거" % len(removed)))

    # ── 3-4. status=excluded 는 판정 대상 아님
    n_excl = 0
    for r in rows:
        if r["status"] == "excluded":
            r["promoted"] = ""
            r["reason_code"] = ""
            r["exposure_channel"] = ""
            r["adjudication_note"] = ("[%s] 판정 대상 제외 (status=excluded)"
                                      % C.EXCLUDE_NOTE)
            n_excl += 1
            changes.append((r["entry_id"], "3-4", "UNSURE", "(빈칸)",
                            "excluded — 판정 대상 제외"))

    C.write_master(rows)

    p = Counter(r["promoted"] for r in rows)
    ch = Counter(r["exposure_channel"] for r in rows)
    print("Phase 3 판정 확정")
    print("  promoted : TRUE %d / FALSE %d / UNSURE %d / (빈칸) %d"
          % (p["TRUE"], p["FALSE"], p["UNSURE"], p[""]))
    print("  channel  : %s" % dict(ch))
    print("  excluded 판정 제외 : %d건" % n_excl)
    miss = [r["entry_id"] for r in rows
            if r["promoted"] == "TRUE" and not r["exposure_channel"]]
    print("  승격인데 채널 없음 : %d %s" % (len(miss), miss))
    print("  KE_T_CP_02 rule_type : %r" % by[CP_02]["rule_type"])

    write_log(rows, changes, removed)
    print("  로그: %s" % LOG)
    return 0 if (p["UNSURE"] == 0 and not miss) else 1


def write_log(rows, changes, removed):
    L = []
    a = L.append
    p = Counter(r["promoted"] for r in rows)
    a("# Phase 3 — UNSURE 판정 확정 로그\n")
    a("사람의 판단 결과를 직접 적용했다. 결정 트리를 다시 돌리지 않았다.\n")
    a("| promoted | 건수 |")
    a("|---|---:|")
    for k in ("TRUE", "FALSE", "UNSURE"):
        a("| %s | %d |" % (k, p[k]))
    a("| (빈칸 — excluded) | %d |\n" % p[""])

    a("## 재해유형 → 노출 채널 매핑\n")
    a("`exposure_channel` 은 대안 문구가 아니라 재해유형이 결정한다.\n")
    a("| 재해유형 | 채널 |")
    a("|---|---|")
    for k, v in CHANNEL_BY_ACCIDENT.items():
        a("| %s | `%s` |" % (k, v))
    a("")

    a("## 항목별 적용 내역\n")
    a("| entry_id | 그룹 | 전 | 채널 | 사유 |")
    a("|---|---|---|---|---|")
    for eid, grp, before, chan, why in changes:
        a("| `%s` | %s | %s | %s | %s |" % (eid, grp, before, chan, why))
    a("")

    a("## 지시서와 다른 점 1건\n")
    a("실측 UNSURE 는 **32건**이나 지시서 3-1 이 열거한 것은 **31건**이다. "
      "`KE_K_RB_03`(수직 철근 전도방지 버팀대 / 물체에맞음 / 공학적)이 목록에 "
      "없다. 그룹 (c)의 '채널 특정 불가' 항목들과 성격이 같아 동일 처리했고 "
      "(→ `passage_count`), 표에서 그룹 `c+` 로 구분했다. 다른 판정을 원하시면 "
      "알려주시기 바란다.\n")

    a("## KE_T_CP_02 — 규칙 제거\n")
    a("승격하지 않는 항목에 실행 규칙이 붙어 있는 모순을 해소했다. "
      "제거된 필드는 `note` 에 원문을 보존했다.\n")
    a("| 필드 | 제거된 값 |")
    a("|---|---|")
    for k, v in removed.items():
        a("| `%s` | %s |" % (k, v))
    a("")
    a("이 판정으로 `kalis_unadopted.py` 의 `U_STRUCT_REVIEW`(NO_EXPOSURE) 및 "
      "부록 C 본문 서술과 정합해진다.\n")

    a("## status=excluded 처리\n")
    a("`KE_K_PI_01` 은 판정 대상이 아니므로 `promoted`/`reason_code`/"
      "`exposure_channel` 을 빈칸으로 두었다. `adjudicate.py` 도 "
      "`status=excluded` 행을 건너뛰도록 수정해 재실행 시 다시 UNSURE 가 붙지 "
      "않는다.\n")

    with io.open(LOG, "w", encoding=C.OUTPUT_ENCODING) as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
