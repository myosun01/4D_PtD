# -*- coding: utf-8 -*-
"""v3.6 Part B — 대안 효과 전수 분류.

## 판정 기준

질문은 "계수가 있는가"가 아니라 **"BASE 와 ALT 가 모델 표현에서 다른가"**다.
다르면 시뮬레이션이 차이를 계산하고, 같으면 대안이 아니라 라벨일 뿐이다.
효과의 크기는 시뮬레이션이 산출한다 — 이 분류는 **산출할 수 있는지**를 판정한다.

## 분류

  [S] 시뮬레이션 가능   BASE≠ALT 가 모델에서 구분되고 controls 에 도달한다
  [P] 규칙 미작성       rule_type 이 비어 있다 (이번에 규칙을 쓰지 않는다)
  [C] 계수 미확보       AgentParameterRule 인데 parameter_value 가 없다
  [X] 모델 표현 불가    규칙이 있어도 BASE 와 ALT 가 모델에서 구분되지 않는다
  [D] 배관 결함         지시가 있는데 코드가 읽지 못한다 (고칠 수 있다)

**[X]·[C]·[D] 를 구분하는 것이 핵심이다.** 셋 다 "저감량 0"으로 나타나지만
원인과 대응이 전혀 다르다.

실행: python scripts/classify_alternatives.py
산출: build/alternative_classification.csv, build/alternative_classification.md
"""
import collections
import csv
import io
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import ptd_ttl
import fourd
import fourd_workers as FW
from controls import (ControlApplication, resolve_all, parse_schedule_shift,
                      CELLTYPE_TO_HAZARD, CELLTYPE_TO_TS)

OUT_CSV = "build/alternative_classification.csv"
OUT_MD = "build/alternative_classification.md"

# ── 판정 근거표 ────────────────────────────────────────────────────────
# 자동으로 결정되지 않는 것(모델 표현 가능성)은 **근거를 명시해 손으로 적는다.**
# 추측이 아니라 "모델에 그 개념이 있는가"를 확인한 결과다.
X_REASONS = {
    "KE_K_CP_07": ("결함 유래 collapse 인스턴스만 축소하는 지시인데, 모델의 H008 zone 에 "
                   "'결함 유래' 구분이 없다. 시스템동바리로 바꿔도 zone 형상·기간이 같다.",
                   "H008 zone 을 결함원인별로 나눌 수 있는 데이터(동바리 종류·조립 품질)"),
    "KE_K_FE_10": ("TS3 비계가 슬래브 외곽선을 1.5 m 밴드로 오프셋한 하나뿐이며, "
                   "시스템비계와 재래식의 형상 차이(경간·작업발판 일체 여부·통로 폭)가 "
                   "모델에 없다. 두 상태가 동일한 밴드로 파생된다.",
                   "KCS 21 60 10 등에서 규격 차이를 확보해 TS3 를 두 종류로 파생"),
    "KE_K_HS_05": ("적재 높이 제한으로 spawn 부피를 줄이는 지시인데, 모델의 H004 zone 은 "
                   "면적만 갖고 높이·적치 단수 개념이 없다.",
                   "적재물 높이/단수를 zone 속성으로 파생 (현재 적치 단수 3 은 임의값)"),
    "KE_K_RB_02": ("전용 이동통로를 추가해 우회시키는 지시인데, 모델에 통로(route) zone 이 "
                   "없고 appliesToCellType 도 v2.3 정본에 없다. 통로를 어디에 놓을지 정보가 없다.",
                   "배근면과 분리된 통로 위치를 IFC 또는 가설물 파생으로 확보"),
    "KE_K_ST_03": ("작업자 동선과 장비 동선을 분리하는 지시인데, 모델에 작업자 전용 동선 "
                   "개념이 없다. H011 zone 은 그대로 두고 사람만 피하게 할 수단이 없다.",
                   "작업자 전용 통로를 별도 TS 로 파생하고 A* 가 그것을 선호하도록"),
    "KE_M_Trip_MatHandling_05": ("통로 회랑을 보호해 적재물 spawn 을 배제하는 지시인데 "
                                 "cellType 이 route 이고 이 프로젝트에 route zone 이 없다.",
                                 "통로 zone 파생 (R5 의 보행가능영역에서 축을 추출)"),
    "KE_M_Trip_MatHandling_06": ("적재구역을 통로와 겹치지 않게 이전하는 지시인데, "
                                 "**어디로 옮길지**가 모델에 없다. 현재 해석은 배율 1.0 으로 "
                                 "떨어져 BASE 와 동일하다.",
                                 "이전 목적지를 정하는 규칙(빈 면적 탐색) 또는 대안 zone 세트"),
    "KE_S_H001_09": ("개구부를 동선에서 이격하는 지시인데, **이격 목적지**가 모델에 없다. "
                     "개구부를 어디로 옮길지 정하는 규칙이 없어 BASE 와 동일하다. "
                     "떨어짐 사다리의 대체급이 여기서 막힌다.",
                     "동선 zone 과 이전 가능 위치를 파생해 개구부 재배치 규칙을 정의"),
    "KE_T_HS_01": ("지상 조립으로 고소작업 자체를 없애는 지시인데 cellType 이 "
                   "elevated_work_zone 이고 이 프로젝트에 대응 위험유형이 없다.",
                   "고소작업 zone(H005) 파생"),
    "KE_M_Fall_FormErection_03": ("계수 0.30 은 있으나 cellType 이 elevated_work_zone 이라 "
                                  "대상 인스턴스가 없다. **계수 문제가 아니라 대상 부재다.**",
                                  "고소작업 zone(H005) 파생"),
    "KE_M_Trip_MatHandling_02": ("계수 0.80 은 있으나 cellType 이 route 라 대상이 없다. "
                                 "**계수 문제가 아니라 대상 부재다.**",
                                 "통로 zone 파생"),
    "KE_K_CP_09": ("'조립/해체 선후 강제'라는 지시인데 **어떤 작업 쌍인지 특정되지 않는다.** "
                   "무엇을 바꿔야 할지 알 수 없어 BASE 와 ALT 가 같아진다.",
                   "대상 작업 쌍을 명시한 scheduleShift 문구"),
    "KE_T_FE_04": ("영구계단 조기 설치 지시인데 **얼마나 앞당길지**가 없다('earlier'). "
                   "정량이 없어 스케줄을 바꿀 수 없다.",
                   "앞당기는 양 또는 목표 선후관계를 명시한 문구"),
    "KE_T_HS_03": ("'중첩=0 이 되도록 이동'인데 대상 작업 쌍이 특정되지 않는다.",
                   "대상 작업 쌍을 명시한 문구"),
}

D_ENTRIES = {
    "KE_K_HS_06": ("simulation_action 이 'block_agent_entry_to_drop_influence_zone' 인데 "
                   "controls 가 정확히 'block_agent_entry' 만 받아 통과하지 못했다.",
                   "접두 일치로 변경 (v3.6). 대상은 appliesToCellType=drop_zone 이 이미 지정."),
    "KE_K_FS_02": ("scheduleShift 'formwork_stripping(Z) requires retention_period_elapsed(Z)' "
                   "를 parse_schedule_shift 가 인식하지 못했다.",
                   "패턴 추가 (v3.6). v3.6 Part A 에서 KCS 3개 층 존치를 temp_works R3 에 "
                   "구현해 대응이 명확해졌다. 실행은 zone 생성이 하며 스케줄은 건드리지 않는다."),
    "KE_T_HS_04": ("계수 materialProbMultiplier=0.50 이 있는데 drop_zone 채널의 키가 "
                   "hazard_weight_multiplier 로 고정되어 있어 읽히지 않았다.",
                   "drop_zone 이 두 키를 모두 받도록 변경 (v3.6). **기존 값의 의미는 "
                   "바뀌지 않았다** — RULE_HS_DEBRISNET 의 hazardWeightMultiplier 해석은 그대로다. "
                   "다만 두 이름 중 어느 것이 옳은지는 원저자만 답할 수 있어 미해결."),
    "KE_T_FS_01": ("scheduleShift 'opening_closure(Z) FS-before formwork_stripping(Z)' 는 "
                   "parse 는 되지만 apply_temporal_shift 가 fs_before 를 실행하지 않는다 "
                   "(Phase 3 에서 '기록만'으로 남긴 항목).",
                   "**수정하지 않았다.** 선후관계 삽입은 CPM 재계산을 유발해 공기가 바뀔 수 "
                   "있고, 그 영향은 별도 검증이 필요하다. 미수정 사유를 남긴다."),
}


def main():
    lib = ptd_ttl.require_library()
    sch, site, life, cfg, wl = FW.load_project_v2()
    ts = fourd.load_temp_structures()
    ts_flat = [t for v in ts.values() for t in v]
    rows = list(csv.DictReader(open("build/ptd_library_master_v2.4.csv",
                                    encoding="utf-8-sig")))
    prom = [r for r in rows if r["promoted"] == "TRUE"]

    by_haz, by_ts = {}, {}
    for h in life.instances:
        by_haz.setdefault(h.hazard_type, h)
    for t in ts_flat:
        by_ts.setdefault(t["ts_type"], t)
    alt_of = {a.from_entry: aid for aid, a in lib.alternatives.items()}

    out = []
    for r in sorted(prom, key=lambda x: x["entry_id"]):
        eid = r["entry_id"]
        aid = alt_of.get(eid)
        rt = (r["rule_type"] or "").strip()
        rec = {"entry_id": eid, "hoc_level": r["hoc_level"],
               "accident_type": r["accident_type"], "alternative_id": aid or "",
               "rule_type": rt, "rule_id": r["rule_id"],
               "applies_to_cell_type": r.get("applies_to_cell_type", ""),
               "parameter_value": r["parameter_value"],
               "class": "", "reason": "", "base_alt_difference": "",
               "fix_applied": "", "enabling_condition": ""}

        if not rt:
            rec["class"] = "P"
            rec["reason"] = "rule_type 이 비어 있다 (규칙 미작성)"
            rec["base_alt_difference"] = "미정 — 규칙이 없어 판정 불가"
            out.append(rec); continue

        if eid in D_ENTRIES:
            why, fix = D_ENTRIES[eid]
            rec["class"] = "D"
            rec["reason"] = why
            rec["fix_applied"] = fix
        elif eid in X_REASONS:
            why, cond = X_REASONS[eid]
            rec["class"] = "X"
            rec["reason"] = why
            rec["enabling_condition"] = cond
        elif rt == "AgentParameterRule" and not (r["parameter_value"] or "").strip():
            rec["class"] = "C"
            rec["reason"] = ("AgentParameterRule 인데 parameter_value 가 비어 있다. "
                             "원천에 계수가 존재하지 않는다 (지어내지 않음).")
            rec["base_alt_difference"] = "없음 — 배율이 없어 BASE 와 동일"

        # 실제 도달 여부 확인 (분류가 [S] 후보인 것만)
        rule = lib.rule_of(aid) if aid else None
        if rt == "TemporalRule":
            k = parse_schedule_shift(getattr(rule, "schedule_shift", "") or "")["kind"]
            if not rec["class"]:
                rec["class"] = "S" if k not in ("unsupported",) else "X"
                rec["reason"] = "TemporalRule 파싱 `%s`" % k
            rec["base_alt_difference"] = rec["base_alt_difference"] or (
                "공정·생멸 시점이 이동 (%s)" % k)
        else:
            ct = getattr(rule, "applies_to_cell_type", "") if rule else ""
            haz = CELLTYPE_TO_HAZARD.get(ct)
            tsk = CELLTYPE_TO_TS.get(ct)
            tgt = by_haz.get(haz) if haz else (by_ts.get(tsk) if tsk else None)
            eff = None
            if tgt is not None and aid:
                try:
                    e = resolve_all(lib, [ControlApplication(
                        aid, tgt["ts_id"] if tsk else tgt.instance_id)],
                        sch, life, temp_structures=ts)
                    eff = list(e.values())[0]
                except Exception as ex:
                    rec["reason"] = rec["reason"] or ("resolve 실패: %s" % str(ex)[:80])
            if not rec["class"]:
                if eff is None:
                    rec["class"] = "X"
                    rec["reason"] = ("appliesToCellType=%r 에 대응하는 대상이 이 "
                                     "프로젝트에 없다" % ct)
                elif eff.kind in ("remove", "block"):
                    rec["class"] = "S"
                    rec["reason"] = "SpatialChangeRule `%s` — 격자에서 직접 구분된다" % eff.kind
                    rec["base_alt_difference"] = (
                        "zone 이 사라진다" if eff.kind == "remove" else "진입이 차단된다")
                elif eff.channel_mult or eff.severity_mult:
                    rec["class"] = "S"
                    rec["reason"] = "채널 배율 적용 %s" % (eff.channel_mult or eff.severity_mult)
                    rec["base_alt_difference"] = "λ 배율 %s" % (eff.channel_mult or eff.severity_mult)
                else:
                    rec["class"] = "C"
                    rec["reason"] = "해석은 되나 배율이 비어 효과가 없다"
                    rec["base_alt_difference"] = "없음"
            elif eff is not None and (eff.channel_mult or eff.kind in ("remove", "block")):
                rec["base_alt_difference"] = rec["base_alt_difference"] or (
                    "수정 후: kind=%s %s" % (eff.kind, eff.channel_mult))
        out.append(rec)

    cols = ["entry_id", "hoc_level", "accident_type", "alternative_id", "rule_type",
            "rule_id", "applies_to_cell_type", "parameter_value", "class",
            "reason", "base_alt_difference", "fix_applied", "enabling_condition"]
    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    # ── 리포트 ──────────────────────────────────────────────
    cnt = collections.Counter(x["class"] for x in out)
    HOC = ["위험회피", "제거", "대체", "공학적", "경고", "관리적", "보호구"]
    cross = collections.defaultdict(collections.Counter)
    for x in out:
        cross[x["hoc_level"]][x["class"]] += 1

    w = io.StringIO()
    w.write("# 대안 효과 전수 분류 (v3.6 Part B)\n\n")
    w.write("`promoted=TRUE` **%d건** 전수. 판정 기준은 \"계수가 있는가\"가 아니라 "
            "**\"BASE 와 ALT 가 모델 표현에서 다른가\"**다.\n\n" % len(out))
    w.write("| 분류 | 뜻 | 건수 |\n|---|---|---|\n")
    for k, d in (("S", "시뮬레이션 가능 — variant 생성 대상"),
                 ("P", "규칙 미작성"),
                 ("C", "계수 미확보 (원천에 값이 없음)"),
                 ("X", "모델 표현 불가 (BASE≡ALT)"),
                 ("D", "배관 결함 (지시는 있는데 코드가 못 읽음)")):
        w.write("| **[%s]** | %s | **%d** |\n" % (k, d, cnt[k]))
    w.write("| | **합계** | **%d** |\n\n" % sum(cnt.values()))

    w.write("## HoC 등급 × 분류 교차표\n\n")
    w.write("| HoC 등급 | S | P | C | X | D | 계 |\n|---|---|---|---|---|---|---|\n")
    for h in HOC:
        c = cross.get(h)
        if not c:
            continue
        w.write("| %s | %d | %d | %d | %d | %d | %d |\n"
                % (h, c["S"], c["P"], c["C"], c["X"], c["D"], sum(c.values())))
    w.write("| **계** | **%d** | **%d** | **%d** | **%d** | **%d** | **%d** |\n\n"
            % (cnt["S"], cnt["P"], cnt["C"], cnt["X"], cnt["D"], sum(cnt.values())))

    for cls, title in (("S", "시뮬레이션 가능"), ("D", "배관 결함 — 수정 내역"),
                       ("X", "모델 표현 불가 — 사유와 가능 조건"),
                       ("C", "계수 미확보")):
        sel = [x for x in out if x["class"] == cls]
        w.write("## [%s] %s — %d건\n\n" % (cls, title, len(sel)))
        if cls == "X":
            w.write("| entry_id | HoC | 왜 BASE 와 ALT 가 구분되지 않는가 | 무엇이 있으면 구분되는가 |\n"
                    "|---|---|---|---|\n")
            for x in sel:
                w.write("| `%s` | %s | %s | %s |\n"
                        % (x["entry_id"], x["hoc_level"], x["reason"],
                           x["enabling_condition"]))
        elif cls == "D":
            w.write("| entry_id | HoC | 결함 | 조치 |\n|---|---|---|---|\n")
            for x in sel:
                w.write("| `%s` | %s | %s | %s |\n"
                        % (x["entry_id"], x["hoc_level"], x["reason"], x["fix_applied"]))
        else:
            w.write("| entry_id | HoC | 사고유형 | 근거 | BASE↔ALT 차이 |\n|---|---|---|---|---|\n")
            for x in sel:
                w.write("| `%s` | %s | %s | %s | %s |\n"
                        % (x["entry_id"], x["hoc_level"], x["accident_type"],
                           x["reason"], x["base_alt_difference"]))
        w.write("\n")

    w.write("## [P] 규칙 미작성 — %d건\n\n이번 범위가 아니다 (규칙을 쓰지 않았다).\n\n"
            % cnt["P"])
    w.write(", ".join("`%s`" % x["entry_id"] for x in out if x["class"] == "P"))
    w.write("\n\n")

    # ── variant 후보 (사다리별) ──
    w.write("## variant 후보 — 사다리별\n\n")
    lad = collections.defaultdict(lambda: collections.defaultdict(list))
    for x in out:
        if x["class"] == "S":
            lad[x["accident_type"]][x["hoc_level"]].append(x["entry_id"])
    for acc in sorted(lad, key=lambda a: -sum(len(v) for v in lad[a].values())):
        grades = lad[acc]
        w.write("### %s — [S] %d건 / 등급 %d개\n\n"
                % (acc, sum(len(v) for v in grades.values()), len(grades)))
        w.write("| HoC 등급 | entry_id |\n|---|---|\n")
        for h in HOC:
            if h in grades:
                w.write("| %s | %s |\n" % (h, ", ".join("`%s`" % e for e in grades[h])))
        if len(grades) < 2:
            w.write("\n> **등급이 %d개뿐이라 축 1(HoC 위계) 실험 대상에서 제외한다.**\n"
                    % len(grades))
        w.write("\n")

    w.write("## 이 분류가 결과다\n\n")
    w.write("상위 등급은 형상·시점 변화라 계수가 필요 없어 [S]가 되기 쉽고, "
            "하위 등급은 계수가 필요해 [C]가 되기 쉽다는 가설을 위 교차표가 검증한다. "
            "**억지로 [S]를 늘리지 않았다.** 분류가 어느 등급에 몰리는지가 정보다.\n")

    with io.open(OUT_MD, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())

    print("저장: %s / %s" % (OUT_CSV, OUT_MD))
    print("  분류: " + " ".join("%s=%d" % (k, cnt[k]) for k in "SPCXD"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
