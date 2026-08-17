# -*- coding: utf-8 -*-
"""v3.5 Part B — appliesToCellType 을 마스터 CSV 자체 필드에서 유도한다.

## 왜 필요한가

대안 15건이 `appliesToCellType` 공란·오기로 `controls.resolve_all()` 에 도달하지
못한다. 이 값은 새 지식이 아니라 **기존 지식의 재표현**이어야 한다.

## 전제 확인 결과 — 지시서가 가정한 유도 경로는 존재하지 않는다

  · KnowledgeEntry 에 `hasHazardType` 이 **없다** (TTL 에서 이 술어를 가진 subject
    28개는 전부 LifecycleRuleTemplate 7 + RiskScenario 21 이고 KE 는 0개다)
  · CoverageCell 이 이 항목들을 가리키지 **않는다** (targetKnowledgeEntries 가
    가리키는 KE 는 전체 1개뿐)
  · 대상 항목들의 `scenario_ids` 는 전부 공란

따라서 `hazard_type` 연결을 통한 유도는 불가능하다. **accident_type 만으로
유도하는 것은 추측이다** (떨어짐 → H001 인지 H007 인지, 물체에맞음 → H004 인지
H009 인지 결정할 수 없다). 지시서가 금지한 바다.

## 대신 쓰는 두 원천 (둘 다 라이브러리 자체 기재값)

  R1 simulation_action  규칙이 조작할 대상을 **문자열이 명시**한다.
                        예 `cap_material_stack_height_limit_spawn_volume` → material_storage
                           `block_agent_entry_to_drop_influence_zone`     → drop_zone
                           `separate_worker_and_equipment_corridors`      → equipment_corridor
                        키워드는 아래 _ACTION_KEYS 에 명시하고, 매칭된 키워드를
                        cell_type_basis 에 기록한다.
  R2 exposure_channel   이 프로젝트의 zone 집합에서 **1:1 인 경우에만** 쓴다.
                        zone_occupancy 는 H008(동바리 붕괴) 뿐이므로 유일하다.
                        dwell_time(H001·H007)·passage_count(H002·H004·H009·H011)는
                        모호하므로 **쓰지 않는다.**

어느 원천으로도 결정되지 않으면 **비운다.** 목록을 로그에 남긴다.

실행: python scripts/derive_cell_types.py
산출: build/ptd_library_master_v2.4.csv (2열 갱신), build/cell_type_derivation.md
"""
import collections
import io
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import ptd_common as C

LOG = "build/cell_type_derivation.md"

# ── v3.5 규제 전거 기재 ────────────────────────────────────────────────
# 확인한 조항을 해당 entry 의 legal_basis 에 남긴다. TTL 에 직접 쓰지 않고
# 마스터 CSV → build_ttl.py 정규 경로를 탄다. 이미 값이 있으면 **덮어쓰지 않고**
# 없는 전거만 이어 붙인다. 전문은 build/limitations.md §1 참조.
_LEGAL = {
    # [4] 개구부 방호 조치 — 덮개 이탈방지·표지
    "KE_M_Fall_FormErection_01":
        "산업안전보건기준에 관한 규칙 제43조 (개구부 등의 방호 조치) — "
        "덮개는 뒤집히거나 떨어지지 않도록 설치 (개정 2019.12.26., 2022.10.18.)",
    "KE_C_WARN_01":
        "산업안전보건기준에 관한 규칙 제43조 (개구부 등의 방호 조치) — "
        "어두운 장소에서도 알아볼 수 있도록 개구부임을 표시 (개정 2022.10.18.)",
    # [5] 개구부 방호구 요건 (난간·덮개 하중)
    "KE_H001_05":
        "29 CFR 1926.502(i) — 개구부 안전난간은 방호되지 않은 모든 측면에 설치, "
        "덮개는 예상 하중의 2배 이상 지지",
}

# R1 — simulation_action 안의 대상 키워드 → cellType. 긴 것부터 검사한다.
_ACTION_KEYS = [
    ("equipment_corridor", "equipment_corridor"),
    ("equipment_corridors", "equipment_corridor"),
    ("drop_influence_zone", "drop_zone"),
    ("collapse_zone", "collapse_zone"),
    ("shoring_system", "collapse_zone"),
    ("scaffold_system", "scaffold"),
    ("material_stack", "material_storage"),
    ("storage_zone", "material_storage"),
    ("material_spawn", "material_storage"),
    ("elevated_work_zone", "elevated_work_zone"),
    ("formwork_hazard", "formwork_deck"),
    ("hazard_instances", None),          # 대상 불특정 — 유도하지 않음
    ("walkway", None),                   # route 계열 — 이 프로젝트에 대응 위험 없음
    ("route_corridor", "route"),
]

# R2 — 이 프로젝트 zone 집합에서 1:1 인 채널만
_CHANNEL_UNIQUE = {"zone_occupancy": "collapse_zone"}

# B-2 — v2.3 에서 이월된 오기의 교정. 근거를 함께 적는다.
_CORRECTIONS = {
    "KE_T_HS_04": (
        "drop_zone",
        "오기교정: v2.3 이월값 material_storage 는 적재구역을 가리켜 이 항목과 무관하다. "
        "directive_ko('작업발판 일체형 거푸집 — 해체 시 개별 부재 탈락·낙하 기회를 축소') "
        "와 accident_type(물체에맞음)이 모두 낙하물 노출을 가리키므로 drop_zone 으로 교정. "
        "전거: 산업안전보건기준에 관한 규칙 제331조의3 (legal_basis 열에 기재됨)."),
}


def load_v23_cell_types(path="ptd_library_v2.3.ttl"):
    """v2.3 정본이 이미 가진 appliesToCellType — **유도보다 우선한다.**

    유도는 빈칸을 채우는 장치일 뿐이며, 사람이 쓴 정본 값을 덮어쓰면 안 된다
    (예: RULE_FE_METALDECK 은 v2.3 에서 collapse_zone 이고 이것이 옳다.
     simulation_action 문자열만 보면 formwork_deck 으로 잘못 유도된다)."""
    out = {}
    if not os.path.exists(path):
        return out
    try:
        import rdflib
        from rdflib import Namespace
    except Exception:
        return out
    P = Namespace("http://construction-safety.org/ptd-hoc-ontology#")
    g = rdflib.Graph()
    g.parse(path, format="turtle")
    for s, o in g.subject_objects(P.appliesToCellType):
        out[str(s).split("#")[-1]] = str(o)
    return out


_V23 = None


def derive(row):
    """(cell_type, basis) — 유도 불가면 ('', 사유). 우선순위: 정본 > 교정 > 유도."""
    global _V23
    if _V23 is None:
        _V23 = load_v23_cell_types()
    eid = row["entry_id"]
    if eid in _CORRECTIONS:
        return _CORRECTIONS[eid]
    rid = row.get("rule_id") or ""
    if rid in _V23:
        return (_V23[rid], "v2.3 정본 값 (유도하지 않음 — 정본이 우선)")

    act = (row.get("simulation_action") or "").strip().lower()
    if act:
        for key, cell in _ACTION_KEYS:
            if key in act:
                if cell is None:
                    return ("", "R1 미결: simulation_action 의 '%s' 는 대상 격자를 "
                                "특정하지 않는다" % key)
                return (cell, "R1 simulation_action='%s' 에 '%s' 명시" % (act, key))

    ch = (row.get("exposure_channel") or "").strip()
    if ch in _CHANNEL_UNIQUE:
        return (_CHANNEL_UNIQUE[ch],
                "R2 exposure_channel='%s' — 이 프로젝트 zone 집합에서 1:1 (H008 뿐)" % ch)

    if ch in ("dwell_time", "passage_count"):
        return ("", "R2 미결: exposure_channel='%s' 는 복수 위험유형에 대응해 모호 "
                    "(accident_type='%s' 만으로는 결정 불가)"
                    % (ch, row.get("accident_type")))
    if ch == "proximity":
        return ("", "적용 불가: proximity(끼임) 채널은 현재 zone 집합에 대응 유형이 없다")
    return ("", "유도 원천 없음 (simulation_action·exposure_channel 모두 비었거나 미인식)")


def main():
    C.ensure_cwd()
    rows = C.read_master()
    if "applies_to_cell_type" not in rows[0]:
        # 구 42열 CSV 를 읽은 경우 — 열을 채워 넣는다
        for r in rows:
            r.setdefault("applies_to_cell_type", "")
            r.setdefault("cell_type_basis", "")

    # ── 규제 전거 기재 (기존 값은 덮어쓰지 않고 없는 것만 이어 붙인다) ──
    legal_log = []
    by_id = {r["entry_id"]: r for r in rows}
    for eid, cite in _LEGAL.items():
        r = by_id.get(eid)
        if r is None:
            legal_log.append((eid, "—", "CSV 에 해당 entry 없음 — 기재하지 않음"))
            continue
        cur = (r.get("legal_basis") or "").strip()
        if cite in cur:
            legal_log.append((eid, "이미 있음", cur[:60]))
        elif cur:
            r["legal_basis"] = cur + " | " + cite
            legal_log.append((eid, "추가(병기)", cite[:60]))
        else:
            r["legal_basis"] = cite
            legal_log.append((eid, "신규", cite[:60]))

    stat = collections.Counter()
    filled, unresolved = [], []
    for r in rows:
        if not r.get("rule_type") or not r.get("rule_id"):
            r["applies_to_cell_type"] = ""
            r["cell_type_basis"] = ""
            continue
        if r["rule_type"] == "TemporalRule":
            r["applies_to_cell_type"] = ""
            r["cell_type_basis"] = "TemporalRule — 격자 대상 아님(별도 경로)"
            stat["temporal"] += 1
            continue
        cell, basis = derive(r)
        r["applies_to_cell_type"] = cell
        r["cell_type_basis"] = basis
        if cell:
            filled.append((r["entry_id"], r["rule_id"], cell, basis))
            stat["derived"] += 1
        else:
            unresolved.append((r["entry_id"], r["rule_id"], r["accident_type"],
                               r.get("exposure_channel"), basis))
            stat["unresolved"] += 1

    C.write_master(rows)

    w = io.StringIO()
    w.write("# appliesToCellType 유도 (v3.5 Part B)\n\n")
    w.write("마스터 CSV 44열 (v3.5 에서 `applies_to_cell_type`·`cell_type_basis` 추가).\n")
    w.write("TTL 에 직접 쓰지 않는다 — 마스터 CSV → `build_ttl.py` 정규 경로를 탄다.\n\n")

    w.write("## 전제 확인 — 지시서가 가정한 유도 경로는 존재하지 않았다\n\n")
    w.write("- KnowledgeEntry 에 `hasHazardType` **없음** (이 술어를 가진 subject 28개는 "
            "LifecycleRuleTemplate 7 + RiskScenario 21, KE 는 0개)\n")
    w.write("- `CoverageCell.targetKnowledgeEntries` 가 가리키는 KE 는 전체 **1개**뿐이고 "
            "대상 항목은 하나도 포함되지 않음\n")
    w.write("- 대상 항목의 `scenario_ids` 전부 공란\n\n")
    w.write("따라서 hazard_type 경유 유도는 불가능하다. accident_type 단독 유도는 "
            "추측이므로(떨어짐 → H001/H007 결정 불가) 하지 않았다.\n\n")

    w.write("## 사용한 유도 규칙\n\n")
    w.write("| 규칙 | 원천 | 조건 |\n|---|---|---|\n")
    w.write("| R1 | `simulation_action` | 문자열이 대상 격자를 명시할 때 (키워드 매칭, 매칭어를 basis 에 기록) |\n")
    w.write("| R2 | `exposure_channel` | 이 프로젝트 zone 집합에서 1:1 일 때만 — `zone_occupancy`→H008 |\n")
    w.write("| B-2 | 오기 교정 | `KE_T_HS_04` (아래 별도 절) |\n\n")

    w.write("## 유도 성공 %d건\n\n" % len(filled))
    w.write("| entry_id | rule_id | cellType | 근거 |\n|---|---|---|---|\n")
    for eid, rid, cell, basis in sorted(filled):
        w.write("| `%s` | `%s` | `%s` | %s |\n" % (eid, rid, cell, basis))
    w.write("\n")

    w.write("## 유도 불가 %d건 — 비워 둔다\n\n" % len(unresolved))
    w.write("| entry_id | rule_id | accident_type | exposure_channel | 사유 |\n|---|---|---|---|---|\n")
    for eid, rid, acc, ch, basis in sorted(unresolved):
        w.write("| `%s` | `%s` | %s | %s | %s |\n" % (eid, rid, acc, ch, basis))
    w.write("\n**추측으로 채우지 않았다.** 이 항목들은 `resolve_all()` 에서 "
            "'적용 불가'로 남는 것이 정상이다.\n\n")

    w.write("## B-2 오기 교정\n\n")
    for eid, (cell, basis) in _CORRECTIONS.items():
        w.write("- `%s` → `%s`\n  - %s\n" % (eid, cell, basis))
    w.write("\n")

    w.write("## TemporalRule %d건\n\n격자 대상이 아니므로 비운다 "
            "(`controls.applicable_alternatives` 가 별도 경로로 처리).\n\n" % stat["temporal"])

    w.write("## 규제 전거 기재 (v3.5)\n\n")
    w.write("확인한 조항을 `legal_basis` 열에 남긴다. 기존 값은 덮어쓰지 않고 병기한다. "
            "전문은 `build/limitations.md` §1 참조.\n\n")
    w.write("| entry_id | 처리 | 전거 |\n|---|---|---|\n")
    for eid, how, cite in legal_log:
        w.write("| `%s` | %s | %s |\n" % (eid, how, cite))
    w.write("\n")

    with io.open(LOG, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())

    print("갱신: %s (44열)" % C.MASTER_CSV)
    print("저장: %s" % LOG)
    print("  유도 %d / 불가 %d / TemporalRule %d"
          % (stat["derived"], stat["unresolved"], stat["temporal"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
