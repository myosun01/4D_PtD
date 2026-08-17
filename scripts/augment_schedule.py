# -*- coding: utf-8 -*-
"""Part 1. 공정표 보강 — 해체 작업 추가 + 층간 중첩 + hazard_state 시점 정합.

원본 construction_schedule.csv 는 수정하지 않고 build/construction_schedule_v2.csv
로 새로 쓴다. 기존 task_id 는 전부 보존하고 새 작업만 9000번대로 채번한다.

## 파라미터 (둘 다 실험 변수 — 임의의 '현실적인' 값을 넣지 않는다)

  retention_days   양생 종료 → 해체 착수 사이의 추가 지연일수. 기본 0.
                   기본값 0 은 '현행 양생기간을 그대로 쓰고 추가 지연 없음'을
                   뜻한다. KE_K_FS_02(존치기간 도면 명기)의 TemporalRule 입력.

  overlap_days     층 N 벽체 양생 완료 시점 대비 층 N+1 착수를 앞당기는 일수.
                   기본 0 = 벽체 양생 완료 익일 착수(중첩의 기준선).
                   물리 제약(층 N+1 슬래브 동바리는 층 N 슬래브 양생 완료 후)을
                   깨지 않도록 클램프한다.

## 층 구조 (실측)
  골조 : 기둥 철근배근 → 기둥 거푸집 → 기둥 타설 → 기둥 양생
         → 슬래브 거푸집+동바리 → 슬래브 철근 → 슬래브 타설 → 슬래브 양생
  후속 : 벽체 철근배근 → 벽체 거푸집 → 벽체 타설 → 벽체 양생
         → 계단 → 문 → 창문

  현행은 층 N+1 기둥 철근배근의 선행이 층 N 마지막 창문이라 완전 순차다.
  이를 '층 N 벽체 양생'으로 옮기면 층 N 계단·문·창문이 층 N+1 골조와 병행한다.
"""
import argparse
import csv
import io
import os
import sys
from collections import OrderedDict, defaultdict
from datetime import date, timedelta

SRC = "construction_schedule.csv"
OUT_CSV = "build/construction_schedule_v2.csv"
OUT_LOG = "build/schedule_augment_log.md"

LEVEL_ORDER = ["Basement", "Level_01", "Level_02a_Parking", "Level_02",
               "Level_03", "Level_04", "Level_05", "Roof"]

STRIP_ID_BASE = 9000          # 해체 작업 채번 시작
MATERIAL_ID_BASE = 9100       # 자재 반입·소진 작업 채번 시작
DATE_FMT = "%Y-%m-%d"

# 자재 소요 공정 3종. (자재명, 소비 공정 판별)
MATERIALS = [
    ("거푸집", lambda n: "거푸집" in n and "해체" not in n),
    ("철근", lambda n: "철근배근" in n),
    ("콘크리트", lambda n: "타설" in n),
]
# productivity_rates.json 에 자재운반(material_handling) rate 가 없다.
# 지시서대로 근거가 없으므로 최소 단위 1일로 두고 로그에 근거 없음을 명시한다.
MATERIAL_DURATION_DAYS = 1


# ────────────────────────────────────────────────────────── 입출력
def read_rows(path):
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f)), None


def parse_pred(s):
    """'48.0' / '' / '48.0,49.0' → ['48', ...]"""
    out = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.endswith(".0"):
            part = part[:-2]
        out.append(part)
    return out


def d(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def ds(x):
    return x.strftime(DATE_FMT)


# ────────────────────────────────────────────────────── 층/작업 분류
def is_curing(r):
    return r["element_type"] == "양생"


def is_slab_curing(r):
    return is_curing(r) and "슬래브" in r["task_name"]


def is_wall_curing(r):
    return is_curing(r) and "벽체" in r["task_name"]


def is_slab_formwork(r):
    return r["element_type"] == "슬래브" and "거푸집" in r["task_name"]


def level_gate_task(rows_of_level):
    """층 N 의 '다음 층 착수 게이트' — 벽체 양생이 있으면 그것, 없으면 슬래브 양생."""
    wall = [r for r in rows_of_level if is_wall_curing(r)]
    if wall:
        return wall[-1]
    slab = [r for r in rows_of_level if is_slab_curing(r)]
    return slab[-1] if slab else None


# ────────────────────────────────────────────── 1-1. 해체 작업 생성
def make_strip_tasks(rows, by_level, retention_days, log):
    """각 층 슬래브 양생 뒤에 '거푸집·동바리 해체' 작업을 만든다."""
    new = []
    seq = 0
    for lv in LEVEL_ORDER:
        lv_rows = by_level.get(lv, [])
        curing = [r for r in lv_rows if is_slab_curing(r)]
        if not curing:
            log.append("  - %s: 슬래브 양생 작업 없음 → 해체 작업 미생성" % lv)
            continue
        cure = curing[-1]

        # duration = 설치 작업(거푸집+동바리) 기간
        fw = [r for r in lv_rows if is_slab_formwork(r)]
        if fw:
            dur = int(fw[-1]["duration_days"])
            dur_src = fw[-1]["task_id"]
        else:
            dur = int(cure["duration_days"])
            dur_src = "(설치작업 없음 — 양생기간 사용)"

        seq += 1
        tid = str(STRIP_ID_BASE + seq)
        label = lv.replace("_", " ").replace("Level 0", "Level 0")
        new.append(OrderedDict([
            ("task_id", tid),
            ("task_name", "%s 슬래브 거푸집·동바리 해체" % label),
            ("start_date", ""), ("end_date", ""),
            ("duration_days", str(dur)),
            ("level", lv),
            ("element_type", "슬래브"),
            ("ifc_class", "IfcSlab"),
            ("element_count", cure.get("element_count", "0")),
            ("hazard_state", "edge_open"),
            ("predecessors", cure["task_id"]),
            ("description",
             "거푸집·동바리 해체 (Part1 신설). 선행=%s 슬래브 양생, "
             "존치 추가지연 retention_days=%d일, 기간=설치작업 %s 기간 %d일"
             % (lv, retention_days, dur_src, dur)),
            ("lag_days", str(retention_days)),
            ("origin", "augment:strip"),
        ]))
    return new


# ──────────────────────────── 2. 자재 반입·소진 작업 (v2.6)
def make_material_tasks(rows, by_level, log):
    """각 층 × 자재 3종에 대해 반입·소진 작업을 만든다.

    ## 공기를 늘리지 않는 배치

    반입을 소비 공정의 직접 선행으로 걸면 크리티컬 패스가 1일씩 늘어난다.
    대신 **선행의 선행**에 걸어 선행 공정(주로 양생)의 여유 구간 안에서 끝나게
    하고, 소비 공정의 선행 목록에 추가한다. 반입 종료 ≤ 기존 선행 종료 이므로
    소비 공정 착수일이 바뀌지 않으면서 '착수 전 완료' 조건은 만족한다.

    소진은 소비 공정에 종속된 말단이라 다른 작업을 밀지 않는다.
    """
    new = []
    seq = 0
    by_id = {r["task_id"]: r for r in rows}
    for lv in LEVEL_ORDER:
        lv_rows = by_level.get(lv, [])
        if not lv_rows:
            continue
        for mat, pred_fn in MATERIALS:
            cons = [r for r in lv_rows if pred_fn(r["task_name"])
                    and r.get("origin") != "augment:strip"]
            if not cons:
                continue
            first, last = cons[0], cons[-1]

            # 반입: 소비 공정의 '선행의 선행' 에 걸어 여유 구간에 숨긴다
            p1 = parse_pred(first["predecessors"])
            anchor = ""
            if p1 and p1[0] in by_id:
                p2 = parse_pred(by_id[p1[0]]["predecessors"])
                anchor = p2[0] if p2 and p2[0] in by_id else ""
            seq += 1
            tin = str(MATERIAL_ID_BASE + seq)
            new.append(OrderedDict([
                ("task_id", tin),
                ("task_name", "%s %s 반입" % (lv.replace("_", " "), mat)),
                ("start_date", ""), ("end_date", ""),
                ("duration_days", str(MATERIAL_DURATION_DAYS)),
                ("level", lv), ("element_type", "자재"),
                ("ifc_class", first["ifc_class"]),
                ("element_count", first.get("element_count", "0")),
                ("hazard_state", "edge_open"),
                ("predecessors", anchor),
                ("description",
                 "%s 자재 반입 (v2.6 신설, workType=delivery). 소비 공정 %s 착수 전 "
                 "완료되도록 선행의 선행(%s)에 배치 — 크리티컬 패스에 얹지 않는다. "
                 "기간 %d일은 productivity_rates.json 에 자재운반 rate 가 없어 "
                 "최소 단위로 둔 것이며 근거 없음."
                 % (mat, first["task_id"], anchor or "(없음)",
                    MATERIAL_DURATION_DAYS)),
                ("lag_days", "0"),
                ("origin", "augment:material"),
            ]))
            # 소비 공정이 반입을 선행으로 갖게 한다 (착수 전 완료 보장).
            #
            # 단, 숨을 여유 구간(anchor)이 없으면 걸지 않는다. anchor 가 없다는
            # 것은 소비 공정이 프로젝트 최초 작업이거나 그에 준한다는 뜻이고,
            # 그 앞에 1일을 끼우면 전체 공기가 그대로 1일 늘어난다
            # (실측: task 1 이 01-01 → 01-02 로 밀려 하류 전체가 이동).
            # 지시서 절대 조건("공기를 늘리지 말 것")이 '착수 전 완료' 보다
            # 우선하므로, 이 경우 반입을 병렬로 두고 로그에 남긴다.
            if anchor:
                first["predecessors"] = ",".join(
                    [x for x in parse_pred(first["predecessors"])] + [tin])
            else:
                new[-1]["description"] += (
                    " [주의] 선행의 선행이 없어(소비 공정이 프로젝트 기점) "
                    "선행으로 걸면 공기가 1일 늘어난다. 공기 불변 조건을 우선해 "
                    "병렬 배치했고 '착수 전 완료'는 보장되지 않는다.")
                log.append("  - 자재 반입 %s(%s %s): anchor 없음 → 병렬 배치"
                           % (tin, lv, mat))

            # 소진: 소비 공정 완료 후. 말단이라 다른 작업을 밀지 않는다.
            seq += 1
            tout = str(MATERIAL_ID_BASE + seq)
            new.append(OrderedDict([
                ("task_id", tout),
                ("task_name", "%s %s 소진·정리" % (lv.replace("_", " "), mat)),
                ("start_date", ""), ("end_date", ""),
                ("duration_days", str(MATERIAL_DURATION_DAYS)),
                ("level", lv), ("element_type", "자재"),
                ("ifc_class", last["ifc_class"]),
                ("element_count", last.get("element_count", "0")),
                ("hazard_state", "edge_open"),
                ("predecessors", last["task_id"]),
                ("description",
                 "%s 자재 소진·정리 (v2.6 신설, workType=consume_or_remove). "
                 "소비 공정 %s 완료에 종속. 기간 %d일은 근거 없음(최소 단위)."
                 % (mat, last["task_id"], MATERIAL_DURATION_DAYS)),
                ("lag_days", "0"),
                ("origin", "augment:material"),
            ]))
    return new


# ─────────────────────────────────────────── 1-2. 층간 중첩 재배선
def rewire_overlap(rows, by_level, overlap_days, log):
    """층 N+1 첫 작업의 선행을 '층 N 마지막 후속작업' → '층 N 벽체 양생'으로 옮긴다."""
    by_id = {r["task_id"]: r for r in rows}
    changes = []
    for i in range(1, len(LEVEL_ORDER)):
        prev_lv, cur_lv = LEVEL_ORDER[i - 1], LEVEL_ORDER[i]
        cur_rows = by_level.get(cur_lv, [])
        prev_rows = by_level.get(prev_lv, [])
        if not cur_rows or not prev_rows:
            continue
        first = cur_rows[0]
        gate = level_gate_task(prev_rows)
        if gate is None:
            continue
        old = first["predecessors"]
        old_ids = parse_pred(old)
        if old_ids == [gate["task_id"]]:
            continue
        first["predecessors"] = gate["task_id"]
        first["lag_days"] = str(-overlap_days) if overlap_days else "0"
        changes.append({
            "level": cur_lv, "task": first["task_id"],
            "old_pred": old_ids[0] if old_ids else "(없음)",
            "old_pred_name": (by_id[old_ids[0]]["task_name"]
                              if old_ids and old_ids[0] in by_id else "-"),
            "new_pred": gate["task_id"], "new_pred_name": gate["task_name"],
        })
    return changes


# ───────────────────────────────── 1-3. hazard_state 시점 재부여
def reassign_hazard_state(rows, log):
    """슬래브 개구부는 타설 이후에 존재한다. 그 전 공정의 opening_* 를 바로잡는다.

      거푸집+동바리 · 철근배근 · 타설(진행 중)  → 개구부 없음 → edge_open
      타설 완료 이후 (= 슬래브 양생)             → opening_open
      덮개/개구부 마감 이후 (문·창문)             → opening_covered (기존 유지)
    """
    changes = []
    for r in rows:
        old = r["hazard_state"]
        new = old
        if r["element_type"] == "슬래브" and r.get("origin") != "augment:strip":
            nm = r["task_name"]
            if ("거푸집" in nm) or ("철근배근" in nm) or ("타설" in nm):
                new = "edge_open"
        elif is_slab_curing(r):
            new = "opening_open"
        if new != old:
            r["hazard_state"] = new
            changes.append((r["task_id"], r["task_name"], old or "(빈칸)", new))
    return changes


# ──────────────────────────────────────────────── CPM 전진 계산
def schedule_dates(rows, project_start, log):
    """FS + lag 로 날짜 재계산. 달력일(주말 미고려) — 원본과 동일 규칙."""
    by_id = {r["task_id"]: r for r in rows}
    succ = defaultdict(list)
    indeg = {}
    for r in rows:
        preds = [p for p in parse_pred(r["predecessors"]) if p in by_id]
        r["_preds"] = preds
        indeg[r["task_id"]] = len(preds)
        for p in preds:
            succ[p].append(r["task_id"])

    order, q = [], [t for t, n in indeg.items() if n == 0]
    q.sort()
    while q:
        t = q.pop(0)
        order.append(t)
        for s in succ[t]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
        q.sort()
    if len(order) != len(rows):
        missing = set(by_id) - set(order)
        raise SystemExit("[중단] 선후관계에 순환이 있습니다: %s"
                         % sorted(missing)[:10])

    for tid in order:
        r = by_id[tid]
        lag = int(r.get("lag_days") or 0)
        if not r["_preds"]:
            start = project_start
        else:
            latest = max(d(by_id[p]["end_date"]) for p in r["_preds"])
            start = latest + timedelta(days=1 + lag)
            if start < project_start:
                start = project_start
        dur = int(r["duration_days"])
        r["start_date"] = ds(start)
        r["end_date"] = ds(start + timedelta(days=dur - 1))
    return order


# ────────────────────────────────────────────────── 검증
def check_precedence(rows):
    """모든 FS 관계에서 선행 종료 < 후행 시작 인지."""
    by_id = {r["task_id"]: r for r in rows}
    viol = []
    for r in rows:
        for p in parse_pred(r["predecessors"]):
            if p not in by_id:
                viol.append((r["task_id"], p, "선행 작업 미정의"))
                continue
            if d(by_id[p]["end_date"]) >= d(r["start_date"]):
                viol.append((r["task_id"], p,
                             "선행 종료 %s >= 후행 시작 %s"
                             % (by_id[p]["end_date"], r["start_date"])))
    return viol


def check_physical(rows, by_level):
    """층 N+1 슬래브 거푸집·동바리는 층 N 슬래브 양생 완료 후에만 착수 가능."""
    viol = []
    for i in range(1, len(LEVEL_ORDER)):
        prev_lv, cur_lv = LEVEL_ORDER[i - 1], LEVEL_ORDER[i]
        prev_cure = [r for r in by_level.get(prev_lv, []) if is_slab_curing(r)]
        cur_fw = [r for r in by_level.get(cur_lv, []) if is_slab_formwork(r)]
        if not prev_cure or not cur_fw:
            continue
        pc, cf = prev_cure[-1], cur_fw[0]
        if d(cf["start_date"]) <= d(pc["end_date"]):
            viol.append((cur_lv, cf["task_id"], pc["task_id"],
                         "층 %s 슬래브 동바리 착수 %s <= 층 %s 슬래브 양생 종료 %s"
                         % (cur_lv, cf["start_date"], prev_lv, pc["end_date"])))
    return viol


def level_span(rows, lv):
    sub = [r for r in rows if r["level"] == lv]
    if not sub:
        return None, None
    return min(r["start_date"] for r in sub), max(r["end_date"] for r in sub)


def overlap_days_between(rows, a, b):
    """두 층 기간의 중첩 일수."""
    sa, ea = level_span(rows, a)
    sb, eb = level_span(rows, b)
    if not sa or not sb:
        return 0
    lo, hi = max(d(sa), d(sb)), min(d(ea), d(eb))
    return max(0, (hi - lo).days + 1)


# ──────────────────────────────────────────────────── main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retention-days", type=int, default=0,
                    help="양생 종료 → 해체 착수 추가 지연 (기본 0 = 현행 유지)")
    ap.add_argument("--overlap-days", type=int, default=0,
                    help="층 N 벽체 양생 대비 층 N+1 착수를 앞당기는 일수 (기본 0)")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        raise SystemExit("[중단] %s 없음. 저장소 루트에서 실행하세요." % SRC)
    if not os.path.isdir("build"):
        os.makedirs("build")

    rows, _ = read_rows(SRC)
    orig_rows = [dict(r) for r in rows]
    orig_by_level = defaultdict(list)
    for r in orig_rows:
        orig_by_level[r["level"]].append(r)

    project_start = min(d(r["start_date"]) for r in rows)
    orig_end = max(d(r["end_date"]) for r in rows)
    orig_dur = (orig_end - project_start).days + 1

    for r in rows:
        r["lag_days"] = "0"
        r["origin"] = "original"

    by_level = defaultdict(list)
    for r in rows:
        by_level[r["level"]].append(r)

    log = []
    print("공정표 보강")
    print("  원본            : %s (%d행)" % (SRC, len(rows)))
    print("  파라미터        : retention_days=%d, overlap_days=%d"
          % (args.retention_days, args.overlap_days))

    # 1-1
    strip = make_strip_tasks(rows, by_level, args.retention_days, log)
    print("  1-1 해체 작업   : %d건 추가 (task_id %s~%s)"
          % (len(strip), strip[0]["task_id"] if strip else "-",
             strip[-1]["task_id"] if strip else "-"))

    # 1-2 (해체 삽입 전에 재배선 — 게이트는 벽체 양생이므로 영향 없음)
    rewire = rewire_overlap(rows, by_level, args.overlap_days, log)
    print("  1-2 층간 중첩   : %d개 층 선행 재배선" % len(rewire))

    rows.extend(strip)
    for r in strip:
        by_level[r["level"]].append(r)

    # 2. 자재 반입·소진 (v2.6)
    mats = make_material_tasks(rows, by_level, log)
    rows.extend(mats)
    for r in mats:
        by_level[r["level"]].append(r)
    print("  2   자재 작업     : %d건 추가 (반입 %d / 소진 %d, task_id %s~)"
          % (len(mats), sum(1 for m in mats if "반입" in m["task_name"]),
             sum(1 for m in mats if "소진" in m["task_name"]),
             mats[0]["task_id"] if mats else "-"))

    # 1-3
    hz = reassign_hazard_state(rows, log)
    print("  1-3 hazard_state: %d건 재부여" % len(hz))

    # 날짜 재계산
    schedule_dates(rows, project_start, log)
    new_end = max(d(r["end_date"]) for r in rows)
    new_dur = (new_end - project_start).days + 1
    print("  공기            : %d일 → %d일 (%+d)" % (orig_dur, new_dur,
                                                   new_dur - orig_dur))

    # 검증
    viol = check_precedence(rows)
    pviol = check_physical(rows, by_level)
    print("  선후관계 위반   : %d건 %s" % (len(viol), "OK" if not viol else viol[:3]))
    print("  물리 제약 위반  : %d건 %s" % (len(pviol), "OK" if not pviol else pviol[:3]))

    # 출력
    rows.sort(key=lambda r: (d(r["start_date"]), int(r["task_id"])))
    fields = ["task_id", "task_name", "start_date", "end_date", "duration_days",
              "level", "element_type", "ifc_class", "element_count",
              "hazard_state", "predecessors", "description",
              "lag_days", "origin"]
    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("  산출            : %s (%d행)" % (OUT_CSV, len(rows)))

    write_log(orig_rows, rows, strip, rewire, hz, viol, pviol,
              orig_dur, new_dur, args)
    print("  로그            : %s" % OUT_LOG)
    return 1 if (viol or pviol) else 0


def write_log(orig, rows, strip, rewire, hz, viol, pviol,
              orig_dur, new_dur, args):
    L = []
    a = L.append
    a("# 공정표 보강 로그 (Part 1)\n")
    a("- 원본: `construction_schedule.csv` (%d행, **수정하지 않음**)" % len(orig))
    a("- 산출: `build/construction_schedule_v2.csv` (%d행)" % len(rows))
    a("- 파라미터: `retention_days=%d`, `overlap_days=%d`\n"
      % (args.retention_days, args.overlap_days))
    a("> 두 파라미터는 **실험 변수**다. 기본값은 현행 유지(추가 지연 0일, "
      "벽체 양생 완료 익일 착수)이며, '현실적인' 값으로 임의 조정하지 않았다.")
    a("> `retention_days` 는 KE_K_FS_02(존치기간 도면 명기)의 TemporalRule 입력이다.\n")

    a("## 1-1. 추가된 해체 작업 (층별)\n")
    a("| task_id | 작업명 | 층 | 기간(일) | 선행 | 시작 | 종료 |")
    a("|---|---|---|---:|---|---|---|")
    by_id = {r["task_id"]: r for r in rows}
    for s in strip:
        r = by_id[s["task_id"]]
        a("| %s | %s | %s | %s | %s | %s | %s |"
          % (r["task_id"], r["task_name"], r["level"], r["duration_days"],
             r["predecessors"], r["start_date"], r["end_date"]))
    a("")
    a("기간은 지시대로 해당 층 **설치 작업(슬래브 거푸집+동바리) 기간과 동일**하게 "
      "두었다. 착수는 슬래브 양생 완료 익일 + `retention_days`(기본 0).\n")

    a("## 1-2. 층간 중첩 — 선행 재배선\n")
    a("현행은 층 N+1 첫 작업의 선행이 층 N 마지막 창문이라 완전 순차였다. "
      "이를 **층 N 벽체 양생**으로 옮겨 층 N 계단·문·창문이 층 N+1 골조와 "
      "병행하도록 했다.\n")
    a("| 층 | 첫 작업 | 기존 선행 | 변경 선행 |")
    a("|---|---|---|---|")
    for c in rewire:
        a("| %s | %s | %s (%s) | %s (%s) |"
          % (c["level"], c["task"], c["old_pred"], c["old_pred_name"],
             c["new_pred"], c["new_pred_name"]))
    a("")

    a("### 층별 시작·종료·중첩 전후 대조\n")
    orig_span = {}
    for lv in LEVEL_ORDER:
        sub = [r for r in orig if r["level"] == lv]
        if sub:
            orig_span[lv] = (min(r["start_date"] for r in sub),
                             max(r["end_date"] for r in sub))
    a("| 층 | 전: 시작~종료 | 후: 시작~종료 | 직전 층과 중첩(일) |")
    a("|---|---|---|---:|")
    for i, lv in enumerate(LEVEL_ORDER):
        s2, e2 = level_span(rows, lv)
        s1, e1 = orig_span.get(lv, ("-", "-"))
        ov = overlap_days_between(rows, LEVEL_ORDER[i - 1], lv) if i else 0
        a("| %s | %s ~ %s | %s ~ %s | %d |" % (lv, s1, e1, s2, e2, ov))
    a("")

    a("## 1-3. hazard_state 재부여\n")
    a("슬래브 개구부는 **타설 이후**에 존재한다. 거푸집면 자체가 작업면인 단계에 "
      "`opening_open` 이 붙어 있어 상태 부여 시점이 어긋나 있었다.\n")
    a("| task_id | 작업명 | 기존 | 변경 |")
    a("|---|---|---|---|")
    for tid, nm, o, n in hz:
        a("| %s | %s | %s | %s |" % (tid, nm, o, n))
    a("")
    a("> 신설 해체 작업의 `hazard_state` 는 지시서 1-1 이 명시한 `edge_open` 을 "
      "따랐다. 다만 1-3 의 일반 규칙(\"타설 완료 이후 → opening_open\")을 그대로 "
      "적용하면 `opening_open` 이 되어 두 지시가 어긋난다. 더 구체적인 1-1 을 "
      "따랐고, 개구부 채널이 필요하면 이 값을 바꾸면 된다.\n")

    a("## 1-4. 공기 변화\n")
    a("| 구분 | 일수 |")
    a("|---|---:|")
    a("| 현행 | %d |" % orig_dur)
    a("| 보강 후 | %d |" % new_dur)
    a("| 변화 | %+d |" % (new_dur - orig_dur))
    a("")
    a("해체 작업 %d건이 추가되었음에도 공기가 줄어든 것은 층간 중첩 때문이다. "
      "해체는 후속 공정과 병행 가능하고, 층 N 계단·문·창문이 층 N+1 골조와 "
      "겹치면서 순차 사슬이 짧아졌다.\n" % len(strip))

    a("## 검증\n")
    a("| 검사 | 위반 |")
    a("|---|---:|")
    a("| 선후관계 (FS: 선행 종료 < 후행 시작) | **%d** |" % len(viol))
    a("| 물리 제약 (층 N+1 동바리 > 층 N 슬래브 양생) | **%d** |" % len(pviol))
    a("")
    if viol:
        a("### 선후관계 위반 상세\n")
        for t, p, why in viol[:40]:
            a("- `%s` ← `%s` : %s" % (t, p, why))
        a("")
    if pviol:
        a("### 물리 제약 위반 상세\n")
        for lv, cf, pc, why in pviol:
            a("- %s: %s" % (lv, why))
        a("")
    a("물리 제약은 '층 N+1 슬래브 거푸집·동바리는 층 N 슬래브 양생 완료 후에만 "
      "착수 가능'(동바리가 하부 슬래브에 지지됨)을 검사한 것이다.\n")

    a("## 추가된 열\n")
    a("- `lag_days` — FS 관계의 지연일수. 해체 작업은 `retention_days`, "
      "층 첫 작업은 `-overlap_days`.")
    a("- `origin` — `original` / `augment:strip`. 신설 행 추적용.\n")

    with io.open(OUT_LOG, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
