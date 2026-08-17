"""export_timeline.py — 엔진 시간축 → unity_bundle/timeline.json (U-트랙, 스키마 v2)

원칙: 시간 계산의 정본은 엔진이다 (ROADMAP §1-3). 이 스크립트는 검증된 API
(schedule의 CPM 결과)를 호출해 직렬화만 한다. Unity가 어떤 날짜 로직도 재계산하지
않도록 일자별 상태를 완결적으로 기록한다. 좌표는 site.json 격자 인덱스 그대로
(좌표 변환 금지 — Unity가 gridFrame 매퍼로 처리).

[스키마 v2 — 부재군 출현·태스크 단위 위험으로 승격]
schedule.json v2(convert_schedule_csv.py 산출)의 elementBinding/hazardState를 소비해:
  - elementAppear : (level, ifcClass)별 점진 출현. 구조부재는 타설 태스크 일할
                    element_count, 설치부재는 설치 태스크 일할 수량. 공정표에 없는
                    클래스는 해당 레벨 벽체 타설 완료 익일 일괄 출현(폴백).
  - hazardSpans   : CSV hazard_state 전이에서 도출한 edge/opening 구간 + collapse
                    (슬래브 타설 시작~양생 완료, 직하부 층). 셀은 site.json 격자 그대로.
  - ghostPhase    : (level, ifcClass)별 작업 시작일(첫 철근/거푸집 ES) — 시공중 고스트용.
  - levelAppear   : v1 하위호환 유지(레벨별 타설 완료일).

[hazardSpans 구현 결정 — lifecycle.py 최소 변경 경로]
지시의 두 선택지(① 템플릿 spawnTrigger에 activity_start 추가 ② 바인딩 합성) 중
어느 것도 채택하지 않고 export 측 도출을 택한다. 사유:
  · fourd의 edge/fall 채널 λ는 site.json 정적 격자(EDGE=6, FLOOR_OPENING=2 셀)에서
    나오며(fourd.channel_cells) 위험 인스턴스에 의존하지 않는다. 따라서 '철근배근 기간
    λ_edge>0'은 격자에서 이미 보장되어 런타임 확장이 불필요하다.
  · hazardSpans는 레벨-집계 시각화 값으로 런타임 λ 엔진이 소비하지 않는다.
  · ① 은 ptd_library.ttl 직접 수정 금지(CLAUDE.md §1) 위반이라 불가.
  → 결과적으로 lifecycle.py·fourd.py를 전혀 수정하지 않는 가장 최소한의 경로.
    collapse despawn은 CSV에 formwork_stripping이 없어 '양생 완료'로 대체(문서화).

[의미론] 엔진 ef는 배타적(= 완료 익일). spawnDay/despawnDay/appear day는 이 좌표계다.

사용: python export_timeline.py [--schedule ...] [--site ...] [--manifest ...]
                                [--out unity_bundle/timeline.json] [--appear-rule ...]
"""
import argparse
import json
import pathlib
import sys
from collections import defaultdict

from schedule import Schedule

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCHEMA_VERSION = "2.0"
STRUCTURAL_TRADES = ("rebar", "formwork_erection", "concrete_pour",
                     "formwork_stripping")
STRUCTURAL_CLASSES = ("IfcColumn", "IfcWall", "IfcSlab", "IfcBeam")
# site.json 셀 타입 (build_site_json 계약)
CELL_WALKABLE, CELL_OPENING, CELL_EDGE = 0, 2, 6
LEVEL_ORDER = [f"L{i}" for i in range(1, 9)]


# ── levelAppear 규칙 (v1 하위호환, --appear-rule로 교체 가능) ─────────────────

def appear_pour_complete(level_acts):
    pours = [a for a in level_acts if a.trade == "concrete_pour"]
    if pours:
        return max(a.ef for a in pours)
    structural = [a for a in level_acts if a.trade in STRUCTURAL_TRADES]
    return max(a.ef for a in (structural or level_acts))


def appear_last_structural(level_acts):
    structural = [a for a in level_acts if a.trade in STRUCTURAL_TRADES]
    return max(a.ef for a in (structural or level_acts))


APPEAR_RULES = {
    "pour_complete": appear_pour_complete,
    "last_structural": appear_last_structural,
}


# ── 원천 로더 ────────────────────────────────────────────────────────────────

def _load_raw_activities(schedule_path):
    """schedule.json 원문 액티비티 (elementBinding/hazardState/isCuring 접근용)."""
    with open(schedule_path, encoding="utf-8") as fp:
        return json.load(fp)["activities"]


def _level_of(zone):
    return zone.split(":")[0]


def _cells_by_type(site):
    """levelID → (edge_cells, opening_cells, walkable_cells). 격자 인덱스 그대로."""
    edge, opening, walkable = {}, {}, {}
    for lv in site["levels"]:
        lid = lv["levelID"]
        e, o, w = [], [], []
        for r, row in enumerate(lv["grid"]["cells"]):
            for c, val in enumerate(row):
                if val == CELL_EDGE:
                    e.append([r, c])
                elif val == CELL_OPENING:
                    o.append([r, c])
                if val in (CELL_WALKABLE, CELL_EDGE):
                    w.append([r, c])
        edge[lid], opening[lid], walkable[lid] = e, o, w
    return edge, opening, walkable


# ── v1 섹션 (하위호환) ───────────────────────────────────────────────────────

def build_level_appear(schedule, rule):
    by_level = defaultdict(list)
    for a in schedule.activities.values():
        by_level[a.level].append(a)
    return {lv: int(rule(acts)) for lv, acts in sorted(by_level.items())}


def build_activities(schedule):
    return [{"activityID": a.activity_id, "name": a.name, "trade": a.trade,
             "zone": a.zone, "es": int(a.es), "ef": int(a.ef),
             "crewSize": int(a.crew_size)}
            for a in sorted(schedule.activities.values(),
                            key=lambda x: x.activity_id)]


def build_crew_by_day(schedule):
    rows = []
    for d in range(schedule.duration):
        agg = defaultdict(int)
        for aid in sorted(schedule.activeSet(d)):
            a = schedule.activities[aid]
            agg[(a.trade, a.level)] += a.crew_size
        for (trade, level), count in sorted(agg.items()):
            rows.append({"day": d, "trade": trade, "level": level,
                         "count": int(count)})
    return rows


# ── v2 섹션 ──────────────────────────────────────────────────────────────────

def build_element_appear(raw_acts, schedule, manifest):
    """(level, ifcClass)별 점진 출현. 구조·설치 부재는 element_count>0 태스크의
    일할 수량으로 해당 태스크 시작일(es)에 출현. CSV에 없는 클래스는 폴백."""
    groups = defaultdict(list)
    csv_classes_by_level = defaultdict(set)
    for a in raw_acts:
        eb = a.get("elementBinding") or {}
        lvl = _level_of(a["zone"])
        cls = eb.get("ifcClass")
        if cls:
            csv_classes_by_level[lvl].add(cls)
        cnt = int(eb.get("elementCount", 0))
        if cnt > 0:
            es = schedule.activities[a["activityID"]].es
            groups[(lvl, cls)].append({"day": int(es), "count": cnt})

    # 폴백 기준일: 레벨별 벽체 타설 완료(ef). 없으면 레벨 마지막 액티비티 ef.
    wall_pour_ef, level_last_ef = {}, {}
    for a in raw_acts:
        act = schedule.activities[a["activityID"]]
        lvl = _level_of(a["zone"])
        level_last_ef[lvl] = max(level_last_ef.get(lvl, 0), act.ef)
        eb = a.get("elementBinding") or {}
        if (a["trade"] == "concrete_pour" and not a.get("isCuring")
                and eb.get("ifcClass") == "IfcWall"):
            wall_pour_ef[lvl] = max(wall_pour_ef.get(lvl, 0), act.ef)

    manifest_counts = defaultdict(int)
    for m in manifest:
        lvl = (m["storey"] or {}).get("levelID")
        if lvl:
            manifest_counts[(lvl, m["ifc_class"])] += 1

    for (lvl, cls), cnt in manifest_counts.items():
        if cls in csv_classes_by_level.get(lvl, set()) or (lvl, cls) in groups:
            continue
        day = wall_pour_ef.get(lvl, level_last_ef.get(lvl, 0))
        groups[(lvl, cls)].append({"day": int(day), "count": int(cnt),
                                   "fallback": True})

    out = []
    for (lvl, cls), apps in sorted(groups.items()):
        out.append({"level": lvl, "ifcClass": cls,
                    "appearances": sorted(apps, key=lambda x: x["day"])})
    return out


def _first_es(items, state):
    return next((es for es, ef, a in items
                 if (a.get("hazardState") or "") == state), None)


def build_hazard_spans(raw_acts, schedule, site):
    """CSV hazard_state 전이 기반 edge/opening 구간 + collapse(직하부).
    edge:    첫 edge_open.es ~ 첫 edge_protected.es (없으면 None=지속)
    opening: 첫 opening_open.es ~ 첫 opening_covered.es
    collapse: 슬래브 타설 첫 시작(es) ~ 슬래브 양생 완료(ef), 직하부 층."""
    edge_cells, opening_cells, walkable_cells = _cells_by_type(site)

    by_level = defaultdict(list)
    for a in raw_acts:
        act = schedule.activities[a["activityID"]]
        by_level[_level_of(a["zone"])].append((act.es, act.ef, a))
    for lvl in by_level:
        by_level[lvl].sort(key=lambda x: x[0])

    spans = []
    for lvl, items in sorted(by_level.items()):
        eo, ep = _first_es(items, "edge_open"), _first_es(items, "edge_protected")
        if eo is not None:
            spans.append({"level": lvl, "kind": "edge", "hazardType": "H007",
                          "spawnDay": int(eo),
                          "despawnDay": int(ep) if ep is not None else None,
                          "cells": edge_cells.get(lvl, [])})
        oo, oc = _first_es(items, "opening_open"), _first_es(items, "opening_covered")
        if oo is not None:
            spans.append({"level": lvl, "kind": "opening", "hazardType": "H001",
                          "spawnDay": int(oo),
                          "despawnDay": int(oc) if oc is not None else None,
                          "cells": opening_cells.get(lvl, [])})

    # collapse: 슬래브 타설~양생, 직하부 층 (기존 LCR_SHORING_COLLAPSE 의미론 유지,
    # despawn만 '양생 완료'로 대체 — CSV에 formwork_stripping 없음).
    # 양생 태스크는 element_type="양생"이고 부재 식별은 ifc_class가 정본이므로
    # 슬래브 판별에 ifcClass=="IfcSlab"를 쓴다(elementType 아님).
    slab_pour_es, slab_curing_ef = {}, {}
    for a in raw_acts:
        eb = a.get("elementBinding") or {}
        if eb.get("ifcClass") != "IfcSlab":
            continue
        act = schedule.activities[a["activityID"]]
        lvl = _level_of(a["zone"])
        if a["trade"] == "concrete_pour" and not a.get("isCuring"):
            slab_pour_es[lvl] = min(slab_pour_es.get(lvl, 10 ** 9), act.es)
        elif a.get("isCuring"):
            slab_curing_ef[lvl] = max(slab_curing_ef.get(lvl, 0), act.ef)

    for lvl, es in sorted(slab_pour_es.items()):
        idx = LEVEL_ORDER.index(lvl)
        if idx == 0:                       # 최하층 → 직하부 없음 (스킵)
            continue
        below = LEVEL_ORDER[idx - 1]
        despawn = slab_curing_ef.get(lvl)
        spans.append({"level": below, "kind": "collapse", "hazardType": "H008",
                      "spawnDay": int(es),
                      "despawnDay": int(despawn) if despawn else None,
                      "cells": walkable_cells.get(below, [])})
    return spans


def build_ghost_phase(raw_acts, schedule):
    """(level, ifcClass)별 작업 시작일 = 첫 rebar/formwork 태스크 ES."""
    first_work = {}
    for a in raw_acts:
        if a["trade"] not in ("rebar", "formwork_erection"):
            continue
        act = schedule.activities[a["activityID"]]
        key = (_level_of(a["zone"]), (a.get("elementBinding") or {}).get("ifcClass"))
        first_work[key] = min(first_work.get(key, 10 ** 9), act.es)
    return [{"level": lvl, "ifcClass": cls, "workStartDay": int(d)}
            for (lvl, cls), d in sorted(first_work.items())]


def manifest_level_ids(manifest_path):
    with open(manifest_path, encoding="utf-8") as fp:
        manifest = json.load(fp)
    return {(m["storey"] or {}).get("levelID") for m in manifest}


# ── 조립 ─────────────────────────────────────────────────────────────────────

def build_timeline(schedule, raw_acts, manifest, site, appear_rule_name="pour_complete"):
    rule = APPEAR_RULES[appear_rule_name]
    level_appear = build_level_appear(schedule, rule)
    manifest_levels = {(m["storey"] or {}).get("levelID") for m in manifest}
    always = sorted(manifest_levels - set(level_appear),
                    key=lambda v: (v is not None, v or ""))
    cal = schedule.calendar.spec or {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "projectDays": int(schedule.duration),
        "calendar": {"workdays": cal.get("workdays", "MON-SUN"),
                     "holidays": list(cal.get("holidays", []))},
        "appearRule": appear_rule_name,
        "elementAppearRule": ("구조부재(IfcColumn/Wall/Slab/Beam)=타설 태스크 일할 "
                              "element_count로 점진 출현; 설치부재=설치 태스크 일할 수량; "
                              "공정표 미포함 클래스=해당 레벨 벽체 타설 완료 익일 일괄 출현(폴백)"),
        "levelAppear": level_appear,
        "alwaysVisibleLevels": always,
        "activities": build_activities(schedule),
        "elementAppear": build_element_appear(raw_acts, schedule, manifest),
        "hazardSpans": build_hazard_spans(raw_acts, schedule, site),
        "ghostPhase": build_ghost_phase(raw_acts, schedule),
        "crewByDay": build_crew_by_day(schedule),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", default="project/schedule.json")
    ap.add_argument("--site", default="project/site.json")
    ap.add_argument("--manifest", default="unity_bundle/manifest.json")
    ap.add_argument("--out", default="unity_bundle/timeline.json")
    ap.add_argument("--appear-rule", default="pour_complete",
                    choices=sorted(APPEAR_RULES))
    a = ap.parse_args()

    sch = Schedule.load(a.schedule)
    raw = _load_raw_activities(a.schedule)
    with open(a.manifest, encoding="utf-8") as fp:
        manifest = json.load(fp)
    with open(a.site, encoding="utf-8") as fp:
        site = json.load(fp)

    tl = build_timeline(sch, raw, manifest, site, a.appear_rule)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(tl, fp, ensure_ascii=False, indent=1)

    ea = tl["elementAppear"]
    hs = tl["hazardSpans"]
    print(f"저장: {out}  (공기 {tl['projectDays']}일, 액티비티 {len(tl['activities'])}, "
          f"elementAppear {len(ea)}군, hazardSpans {len(hs)}"
          f"[edge {sum(1 for s in hs if s['kind']=='edge')}/"
          f"opening {sum(1 for s in hs if s['kind']=='opening')}/"
          f"collapse {sum(1 for s in hs if s['kind']=='collapse')}], "
          f"ghostPhase {len(tl['ghostPhase'])})")
    print(f"  levelAppear {tl['levelAppear']}")


if __name__ == "__main__":
    main()
