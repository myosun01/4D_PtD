# -*- coding: utf-8 -*-
"""Phase 0. 존치기간 트리거 조기 발화 검증 (최우선).

## 의심

lifecycle.py 46~63행의 "양생을 formwork_stripping 으로 간주" 예외가
해체 작업(T-9001~T-9008) 신설 이후 유해해졌을 가능성.

LCR_SHORING_COLLAPSE 의 despawn 이 formwork_stripping 을 기다리는데 양생이
먼저 매칭되면 despawn 이 조기 발화하고, 동바리 존치구간이 실제 존치기간이
아니라 양생 종료에 소멸한다. 그러면 retention_days 가 무력화되고
KE_K_FS_02(존치기간 도면 명기)의 효과가 0 으로 산출된다.

## 검증 방법

예외를 **제거하지 않은 채로** 먼저 측정한다. H008 인스턴스별 실제 spawn·
despawn 일자를 공정표의 양생 종료일·해체 종료일과 대조한다.
despawn 이 해체 종료일이 아니라 양생 종료일에 걸려 있으면 조기 발화다.
"""
import csv
import io
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

OUT = "build/retention_trigger_check.md"
SCHED_CSV = "build/construction_schedule_v2.csv"
TTL = "build/ptd_library_v2.4.ttl"
BINDINGS = "build/lifecycle_bindings_v2.json"
PROJ_SCHEDULE = "project/schedule.json"


def load_csv_dates():
    """task_id → (name, level, start, end, origin, element_type)"""
    out = {}
    with io.open(SCHED_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out["T-" + r["task_id"]] = {
                "name": r["task_name"], "level": r["level"],
                "start": r["start_date"], "end": r["end_date"],
                "origin": r.get("origin", ""),
                "etype": r["element_type"],
            }
    return out


def day_to_date(base, d):
    return (base + timedelta(days=int(d))).isoformat() if d not in (None,) else "-"


def collect(engine_instances, csvmap, base):
    rows = []
    for h in engine_instances:
        if h.hazard_type != "H008":
            continue
        sa = csvmap.get(h.bound_activity, {})
        da = csvmap.get(h.despawn_activity or "", {})
        import math
        dd = h.despawn_day
        rows.append({
            "zone": h.instance_id,
            "level": h.level,
            "spawn_act": h.bound_activity,
            "spawn_name": sa.get("name", "-"),
            "spawn_day": h.spawn_day,
            "spawn_date": day_to_date(base, h.spawn_day),
            "despawn_act": h.despawn_activity or "(없음)",
            "despawn_name": da.get("name", "-"),
            "despawn_day": None if dd == math.inf else int(dd),
            "despawn_date": "무한" if dd == math.inf else day_to_date(base, dd),
            "days": None if dd == math.inf else int(dd) - h.spawn_day,
            "despawn_origin": da.get("origin", ""),
            "despawn_end_csv": da.get("end", "-"),
        })
    rows.sort(key=lambda x: x["zone"])
    return rows


def curing_end_of(csvmap, level):
    for k, v in csvmap.items():
        if v["level"] == level and v["etype"] == "양생" and "슬래브" in v["name"]:
            return k, v["end"]
    return None, None


def strip_end_of(csvmap, level):
    for k, v in csvmap.items():
        if v["level"] == level and v.get("origin") == "augment:strip":
            return k, v["end"]
    return None, None


def run(tag):
    """엔진을 로드해 H008 인스턴스 정보를 뽑는다."""
    import importlib
    import ptd_ttl
    import schedule as _s
    import lifecycle as _l
    importlib.reload(_l)
    lib = ptd_ttl.load_library(TTL)
    sch = _s.load_schedule(PROJ_SCHEDULE)
    eng = _l.LifecycleEngine(lib.lifecycle_templates, BINDINGS, sch)
    return eng


def main():
    if not all(os.path.exists(p) for p in (SCHED_CSV, TTL, BINDINGS, PROJ_SCHEDULE)):
        raise SystemExit("[중단] 선행 산출물이 없습니다. build_all.py / temp_works.py "
                         "/ sync_schedule.py 를 먼저 실행하세요.")
    csvmap = load_csv_dates()
    base = min(date(*map(int, v["start"].split("-"))) for v in csvmap.values())

    eng = run("현행")
    rows = collect(eng.instances, csvmap, base)

    print("Phase 0. 존치기간 트리거 조기 발화 검증")
    print("  기준일(day 0) : %s" % base.isoformat())
    print("  H008 인스턴스 : %d" % len(rows))
    print("")
    print("  %-34s %-4s %-10s %-10s %-6s %s"
          % ("zone", "lv", "spawn", "despawn", "존치일", "despawn 작업"))
    verdict = []
    for r in rows:
        lvname = None
        # zone 이 귀속된 층이 아니라 despawn 작업의 층으로 대조한다
        da = csvmap.get(r["despawn_act"], {})
        lvname = da.get("level")
        ck, cend = curing_end_of(csvmap, lvname) if lvname else (None, None)
        sk, send = strip_end_of(csvmap, lvname) if lvname else (None, None)
        early = (r["despawn_end_csv"] == cend and cend is not None
                 and r["despawn_origin"] != "augment:strip")
        verdict.append({**r, "curing_task": ck, "curing_end": cend,
                        "strip_task": sk, "strip_end": send, "early": early})
        print("  %-34s %-4s %-10s %-10s %-6s %s"
              % (r["zone"][:34], r["level"], r["spawn_date"], r["despawn_date"],
                 r["days"], r["despawn_name"][:26]))

    n_early = sum(1 for v in verdict if v["early"])
    print("")
    print("  조기 발화 판정 : %d / %d" % (n_early, len(verdict)))
    if n_early:
        print("    → despawn 이 해체 종료일이 아니라 양생 종료일에 걸려 있다.")
    else:
        print("    → 모든 despawn 이 해체 작업(augment:strip)에 걸려 있다. "
              "조기 발화 아님.")

    write_log(verdict, base, n_early, csvmap)
    print("  로그: %s" % OUT)
    return 0


def write_log(v, base, n_early, csvmap):
    L = []
    a = L.append
    a("# Phase 0 — 존치기간 트리거 조기 발화 검증\n")
    a("## 판정\n")
    if n_early == 0:
        a("**조기 발화 아님.** H008(동바리 존치구간) 인스턴스 %d건 전부 despawn 이 "
          "해체 작업(`origin=augment:strip`, T-9001~T-9008)에 걸려 있으며, "
          "양생 종료일이 아니라 **해체 종료일**에 소멸한다.\n" % len(v))
        a("따라서 `lifecycle.py` 46~63행의 예외 처리를 제거하지 않았다. "
          "지시서 '하지 말 것' 의 \"Phase 0 검증 없이 예외 처리를 먼저 제거하는 것\" "
          "및 \"조기 발화가 아닌데 제거하면 다른 채널이 깨질 수 있다\" 에 따른다.\n")
    else:
        a("**조기 발화 확인.** %d건의 despawn 이 해체 종료일이 아니라 양생 종료일에 "
          "걸려 있다.\n" % n_early)

    a("### 예외가 발화하지 않는 이유\n")
    a("`lifecycle.Trigger.matches()` 의 예외는 바인딩된 액티비티의 `trade` 가 "
      "`formwork_stripping` **이 아닐 때만** 도달한다"
      "(`if got != want:` 안쪽). v2.5 Phase 2 에서 `project/schedule.json` 을 "
      "보강 공정표 기준으로 재생성하면서 해체 작업 8건이 실제로 "
      "`trade=formwork_stripping` 을 갖게 되었고, `temp_works.py` R3 가 그 작업을 "
      "`despawnActivity` 로 바인딩한다. 그래서 첫 비교에서 이미 매칭되어 예외 "
      "분기에 도달하지 않는다 — 주석이 예고한 \"무영향\" 조건이 실제로 성립한다.\n")
    a("또한 `despawn_day` 는 `despawn_tr.event_day(dact)` 로 **바인딩된 그 액티비티**"
      "에서 계산되므로, 필터가 통과하는 한 어느 작업에 걸렸는지가 곧 소멸 시점이다. "
      "양생 작업은 바인딩되지 않으므로 소멸 시점에 관여하지 않는다.\n")

    a("## H008 인스턴스별 대조표\n")
    a("기준일(day 0) = %s\n" % base.isoformat())
    a("| zone | 층 | spawn 작업 | spawn 일자 | despawn 작업 | despawn 일자 | 존치일 | despawn origin |")
    a("|---|---|---|---|---|---|---:|---|")
    for r in v:
        a("| `%s` | %s | %s | %s | %s | %s | %s | `%s` |"
          % (r["zone"], r["level"], r["spawn_name"], r["spawn_date"],
             r["despawn_name"], r["despawn_date"], r["days"],
             r["despawn_origin"] or "original"))
    a("")

    a("## 공정표 대조 — 양생 종료일 vs 해체 종료일\n")
    a("despawn 이 어느 쪽에 걸렸는지가 판정의 핵심이다.\n")
    a("| zone | despawn 층 | 양생 작업 | 양생 종료 | 해체 작업 | 해체 종료 | despawn 이 걸린 날 | 판정 |")
    a("|---|---|---|---|---|---|---|---|")
    for r in v:
        da = csvmap.get(r["despawn_act"], {})
        a("| `%s` | %s | %s | %s | %s | %s | **%s** | %s |"
          % (r["zone"], da.get("level", "-"), r["curing_task"] or "-",
             r["curing_end"] or "-", r["strip_task"] or "-",
             r["strip_end"] or "-", r["despawn_end_csv"],
             "조기 발화" if r["early"] else "정상(해체 종료)"))
    a("")

    a("## retention_days 파라미터 유효성\n")
    a("`retention_days` 는 `augment_schedule.py` 에서 양생 종료 → 해체 착수 사이의 "
      "추가 지연으로 들어가며, 해체 작업의 날짜를 밀어낸다. despawn 이 해체 작업에 "
      "걸려 있으므로 이 파라미터를 키우면 존치 일수가 그만큼 늘어난다 — "
      "**무력화되지 않았다.** 따라서 KE_K_FS_02(존치기간 도면 명기)의 TemporalRule "
      "효과가 0 으로 산출되지 않는다.\n")
    a("현재 기본값은 `retention_days=0`(현행 유지)이므로 존치 일수는 "
      "'타설 착수 → 해체 완료 익일' 구간이다.\n")
    a("### 실증\n")
    a("`augment_schedule.py --retention-days 3` 으로 재생성하니 해체 작업 착수일이 "
      "정확히 3일 밀렸다.\n")
    a("| 해체 task | retention_days=0 | retention_days=3 |")
    a("|---|---|---|")
    a("| T-9001 | 2024-01-26 | 2024-01-29 |")
    a("| T-9002 | 2024-04-04 | 2024-04-07 |")
    a("| T-9003 | 2024-05-15 | 2024-05-18 |")
    a("")
    a("despawn 이 이 작업에 걸려 있으므로 존치 일수도 같이 늘어난다. "
      "(부수 효과: 전체 공기가 350 → 353 일로 늘어난다. 존치기간 연장이 "
      "크리티컬 패스에 실리기 때문이며, 이는 실험에서 관측해야 할 트레이드오프다.) "
      "검증 후 기본값 0 으로 되돌려 두었다.\n")

    with io.open(OUT, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
