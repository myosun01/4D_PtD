"""convert_schedule_csv.py — construction_schedule.csv → project/schedule.json v2

실제 공정표(178 태스크, 2024-01-01~2025-02-12)를 프로젝트 데이터의 새 원천으로 전환한다.

[고정 계약 준수]
- 날짜 입력 금지(ROADMAP §3): CSV의 start_date/end_date는 버린다. duration_days와
  predecessors(FS, lag 0)만 옮기고, 시작·종료는 엔진 CPM 전진계산이 산출한다.
  검증(tests/test_v2_convert.py #1)에서 엔진 ES/EF가 CSV 날짜를 전건 재현함을 확인한다.
- 달력: CSV에 일요일 시작 태스크 25건 → calendar.workdays="MON-SUN", holidays=[].
  (전 요일 작업일이므로 작업일 인덱스 == 2024-01-01로부터의 경과일.)
- trade 어휘(§2 고정): 철근배근→rebar / 거푸집(+동바리)→formwork_erection /
  타설→concrete_pour / 계단·문·창문·난간 설치→material_handling.
- zone: level명 → CONSTRUCTION_LEVELS 순서로 "L{i}:Z-A".

[스키마 v2 확장 — 기존 소비자 하위호환]
schedule.py Activity.load()는 지정 키만 읽고 나머지는 무시하므로 아래 신규 필드는
기존 CPM/run_project를 깨지 않는다(test #4에서 확인):
  - "isCuring": true         양생(대기) 태스크. crewSize 0, trade는 concrete_pour 유지
                             (lifecycle/collapse 의미론에서 '동바리 존치~탈형 대기'로 쓰임).
  - "hazardState": <str>     CSV hazard_state 원문 (edge_open/opening_open/
                             edge_protected/opening_covered/""). export의 hazardSpans 도출용.
  - "elementBinding": { "ifcClass", "elementType", "elementCount" }  부재 출현/수량용.

[양생·해체 규칙 명문화]
CSV에 '거푸집 해체' 태스크가 없다. 슬래브 '양생' 태스크의 description이
"동바리 존치/탈형 대기"이므로, collapse_zone(동바리 존치) 구간의 종료(despawn)를
'양생 완료'로 대체한다. 이 규칙은 export_timeline.py의 hazardSpans(collapse)에서
적용된다(스폰=슬래브 타설 시작, 디스폰=슬래브 양생 완료, 직하부 층).

[crewSize]
description의 일일 물량으로 인원을 역산할 근거가 없어 trade별 기본 상수로 채운다.
# TODO(캘리브레이션): 실제 인시(man-hour)/물량 확보 시 trade·물량 기반으로 교체.
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
from collections import defaultdict

from schedule import Schedule

# build_site_json과 동일 순서 — level명 → L{i} (site.json과 정합)
CONSTRUCTION_LEVELS = [
    "Basement", "Level_01", "Level_02a_Parking", "Level_02",
    "Level_03", "Level_04", "Level_05", "Roof",
]
LEVEL_ID = {nm: f"L{i+1}" for i, nm in enumerate(CONSTRUCTION_LEVELS)}
LEVEL_ORDER = [f"L{i}" for i in range(1, 9)]

BASE_DATE = dt.date(2024, 1, 1)   # 검증 기준 (day 0)
CELL_WALKABLE, CELL_OPENING, CELL_EDGE = 0, 2, 6

# trade별 기본 크루 (캘리브레이션 TODO)
CREW_DEFAULT = {
    "rebar": 6, "formwork_erection": 6, "concrete_pour": 8,
    "formwork_stripping": 6, "material_handling": 4,
}
CURING_CREW = 0

# 태스크명 키워드 → (trade, work_type 기본). 순서 중요(더 구체적 키워드 먼저).
_NAME_RULES = [
    ("양생", ("concrete_pour", "curing")),         # 대기 액티비티 — isCuring 처리
    ("철근배근", ("rebar", "rebar")),
    ("거푸집", ("formwork_erection", "formwork")),  # '거푸집', '거푸집+동바리' 포함
    ("타설", ("concrete_pour", "pour")),
    ("설치", ("material_handling", "install")),
]


def _pred_id(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    return f"T-{int(float(raw))}"


def classify(task_name: str):
    for kw, (trade, wt) in _NAME_RULES:
        if kw in task_name:
            return trade, wt
    raise ValueError(f"trade 분류 실패(태스크명에 알려진 키워드 없음): {task_name!r}")


def work_type_of(base_wt: str, ifc_class: str) -> str:
    """TTL LifecycleRuleTemplate 트리거 어휘에 맞춘 workType 배정.
    슬래브 타설='slab'(LCR_SLAB_* spawn), 계단·난간 설치='perimeter_protection'
    (LCR_SLAB_EDGE despawn), 문·창문 설치='opening_closure'(LCR_SLAB_OPENING despawn),
    양생='curing'(collapse despawn 대체). 나머지는 설명적."""
    if base_wt == "curing":
        return "curing"
    if base_wt == "pour":
        return "slab" if ifc_class == "IfcSlab" else "pour"
    if base_wt == "install":
        if ifc_class in ("IfcStair", "IfcRailing"):
            return "perimeter_protection"
        if ifc_class in ("IfcDoor", "IfcWindow"):
            return "opening_closure"
        return "install"
    return base_wt


def convert(csv_path: str) -> dict:
    with open(csv_path, encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))

    activities = []
    for r in rows:
        level = r["level"]
        if level not in LEVEL_ID:
            raise ValueError(f"CONSTRUCTION_LEVELS에 없는 level: {level!r}")
        trade, base_wt = classify(r["task_name"])
        wt = work_type_of(base_wt, r["ifc_class"])
        is_curing = (base_wt == "curing")
        pred = _pred_id(r["predecessors"])
        act = {
            "activityID": f"T-{r['task_id']}",
            "name": r["task_name"],
            "trade": trade,
            "zone": f"{LEVEL_ID[level]}:Z-A",
            "duration_days": int(r["duration_days"]),
            "predecessors": ([{"activity": pred, "relation": "FS", "lag_days": 0}]
                             if pred else []),
            "crewSize": CURING_CREW if is_curing else CREW_DEFAULT[trade],
            "dailyPattern": {"dwellMinutes": 360, "tasksPerWorker": 4},
            "workType": wt,
            # ── 스키마 v2 신규 필드 (하위호환) ──
            "isCuring": is_curing,
            "hazardState": (r["hazard_state"] or "").strip(),
            "elementBinding": {
                "ifcClass": r["ifc_class"],
                "elementType": r["element_type"],
                "elementCount": int(r["element_count"]),
            },
        }
        activities.append(act)

    return {
        "scheduleID": "PRJ001-CSV",
        "schemaVersion": "2.0",
        "sourceCsv": pathlib.Path(csv_path).name,
        "csvBaseDate": BASE_DATE.isoformat(),   # day 0 기준 (검증용, 엔진 비소비)
        "calendar": {"workdays": "MON-SUN", "holidays": []},
        "activities": activities,
    }


# ── 바인딩 합성 (택1: '바인딩 합성' 경로) ────────────────────────────────────
# 새 스케줄에 대해 기존 TTL 템플릿과 부합하는 lifecycle_bindings.json을 생성한다.
# 셀은 site.json 격자 그대로(좌표 파생 금지): 개구부=type-2, 단부=type-6, collapse
# 직하부=하부층 walkable(0)+edge(6). collapse despawn은 슬래브 '양생'(=탈형 대기)
# 완료로 대체(lifecycle.Trigger.matches의 문서화된 최소 수정으로 매칭).

def _level_cells(site):
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


def synthesize_bindings(sched_dict: dict, site: dict) -> dict:
    schedule = Schedule.load_from_dict(sched_dict) if hasattr(Schedule, "load_from_dict") \
        else _schedule_from_dict(sched_dict)
    raw = {a["activityID"]: a for a in sched_dict["activities"]}
    edge_cells, opening_cells, walkable_cells = _level_cells(site)

    # 레벨별 태스크 분류
    by_level = defaultdict(lambda: {"slab_pour": [], "slab_curing": [],
                                    "perimeter": [], "opening_close": []})
    for aid, a in raw.items():
        lvl = a["zone"].split(":")[0]
        ifc = a["elementBinding"]["ifcClass"]
        g = by_level[lvl]
        if ifc == "IfcSlab" and a["trade"] == "concrete_pour" and not a["isCuring"]:
            g["slab_pour"].append(aid)
        elif ifc == "IfcSlab" and a["isCuring"]:
            g["slab_curing"].append(aid)
        if a["workType"] == "perimeter_protection":
            g["perimeter"].append(aid)
        if a["workType"] == "opening_closure":
            g["opening_close"].append(aid)

    ef = {aid: schedule.activities[aid].ef for aid in raw}
    es = {aid: schedule.activities[aid].es for aid in raw}
    bindings = []

    for lvl in LEVEL_ORDER:
        g = by_level.get(lvl)
        if not g or not g["slab_pour"]:
            continue
        last_pour = max(g["slab_pour"], key=lambda x: ef[x])   # .completed = 최종 타설
        first_pour = min(g["slab_pour"], key=lambda x: es[x])  # .started = 최초 타설

        # H001 개구부 — site type-2 개구부 셀이 있는 층만 (없으면 노출 없음)
        if opening_cells[lvl]:
            close = max(g["opening_close"], key=lambda x: ef[x]) if g["opening_close"] else None
            bindings.append({
                "template": "LCR_SLAB_OPENING", "boundActivity": last_pour,
                "spawnLocation": {"level": lvl, "cells": opening_cells[lvl]},
                "despawnActivity": close})

        # H007 단부 — 모든 층 (type-6 단부 셀 존재). despawn은 정적 격자가 단부를
        # 항상 보유하므로 None(지속)로 둔다(기존 데이터와 동일 관행).
        if edge_cells[lvl]:
            bindings.append({
                "template": "LCR_SLAB_EDGE", "boundActivity": last_pour,
                "spawnLocation": {"level": lvl, "cells": edge_cells[lvl]},
                "despawnActivity": None})

        # H008 동바리붕괴 — 직하부 층. 타설 시작~양생 완료.
        idx = LEVEL_ORDER.index(lvl)
        if idx > 0 and g["slab_curing"]:
            below = LEVEL_ORDER[idx - 1]
            curing = max(g["slab_curing"], key=lambda x: ef[x])
            bindings.append({
                "template": "LCR_SHORING_COLLAPSE", "boundActivity": first_pour,
                "spawnLocation": {"level": below, "cells": walkable_cells[below]},
                "despawnActivity": curing})

    return {"bindings": bindings}


def _schedule_from_dict(sched_dict):
    """Schedule은 파일 로더만 있으므로 임시 파일 없이 dict에서 구성."""
    from schedule import Activity, Predecessor, Calendar
    acts = [Activity(
        activity_id=a["activityID"], name=a.get("name", a["activityID"]),
        trade=a["trade"], zone=a["zone"], duration_days=int(a["duration_days"]),
        predecessors=[Predecessor(p["activity"], p.get("relation", "FS"),
                                  int(p.get("lag_days", 0)))
                      for p in a.get("predecessors", [])],
        crew_size=int(a.get("crewSize", 0)), daily_pattern=a.get("dailyPattern", {}),
        work_type=a.get("workType", ""),
    ) for a in sched_dict["activities"]]
    return Schedule(sched_dict.get("scheduleID", ""),
                    Calendar(sched_dict.get("calendar", {})), acts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="construction_schedule.csv")
    ap.add_argument("--site", default="project/site.json")
    ap.add_argument("--out", default="project/schedule.json")
    ap.add_argument("--bindings-out", default="project/lifecycle_bindings.json")
    a = ap.parse_args()

    sched = convert(a.csv)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(sched, fp, ensure_ascii=False, indent=1)

    # lifecycle_bindings.json 재생성 (바인딩 합성) — 기존 TTL 템플릿 4종과 부합.
    with open(a.site, encoding="utf-8") as fp:
        site = json.load(fp)
    binds = synthesize_bindings(sched, site)
    bout = pathlib.Path(a.bindings_out)
    with open(bout, "w", encoding="utf-8") as fp:
        json.dump(binds, fp, ensure_ascii=False, indent=1)

    # 요약
    from collections import Counter
    trades = Counter(x["trade"] for x in sched["activities"])
    curing = sum(1 for x in sched["activities"] if x["isCuring"])
    tpl = Counter(b["template"] for b in binds["bindings"])
    print(f"저장: {out}  (액티비티 {len(sched['activities'])}, trade {dict(trades)}, "
          f"양생 {curing})")
    print(f"저장: {bout}  (바인딩 {len(binds['bindings'])}: {dict(tpl)})")


if __name__ == "__main__":
    main()
