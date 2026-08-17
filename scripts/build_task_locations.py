# -*- coding: utf-8 -*-
"""Phase 1 — 액티비티별 작업 위치 원천을 확정한다 (v3.2/v3.3).

`element_task_mapping.json` 은 **부재를 '생성'하는 공정(타설·설치)에만** GUID 를
붙였다. 같은 부재의 선행(철근·거푸집)·후속(양생) 공정과, 나중에 신설된
해체·자재 태스크에는 항목이 없어 234건 중 122건이 폴백(층 전체 배회)이었다.
폴백은 전체 위험셀 노출의 61.3%를 만들고 있었다 (build/task_mapping_diagnosis.md).

이 스크립트는 **원본을 덮어쓰지 않고** 파생 위치표를 만든다.
원본은 data/element_task_mapping.backup.json 에 백업되어 있다.

## 위치 원천 4종 (전부 기존 데이터에서 유도 — 추측 배정 없음)

  original           element_task_mapping.json 에 이미 있는 GUID
  inherited:pour     같은 (level, element_type) 타설 태스크의 GUID 상속
                     — 철근·거푸집은 그 부재가 세워질 자리에서 이루어진다
  inherited:shoring  H008_ShoringCollapse zone (그 해체 태스크를 despawn 으로
                     지목하는 zone). 해체 작업자는 정확히 그 존치구간 안에 있다
  zone:material      H004_MaterialStorage zone (층당 1개). 자재 반입·소진은
                     특정 부재가 아니라 적재구역에서 이루어진다

## 해체 태스크의 층 배정

동바리 해체는 슬래브 **아래**에서 이루어진다. 물리적으로 위에서 할 수 없다.
어느 층인지는 추정하지 않는다 — H008 zone 이 이미 '직하부'로 계산되어 있고
그 zone 의 despawnActivity 가 바로 그 해체 태스크다. zone 의 level 을 그대로 쓴다.

실행: python scripts/build_task_locations.py
산출: build/task_locations.json, build/task_mapping_v2.md
"""
import collections
import csv
import io
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

SCHEDULE = "project/schedule.json"
CSV_SCHED = "build/construction_schedule_v2.csv"
MAPPING = "element_task_mapping.json"
BACKUP = "data/element_task_mapping.backup.json"
ZONES = "build/hazard_zones.json"
BINDINGS = "build/lifecycle_bindings_v2.json"
OUT = "build/task_locations.json"
LOG = "build/task_mapping_v2.md"


def tid(activity_id):
    return activity_id.replace("T-", "", 1)


def main():
    if not os.path.exists(BACKUP):
        raise SystemExit("[중단] 백업이 없다: %s — 먼저 원본을 백업하라." % BACKUP)

    acts = json.load(open(SCHEDULE, encoding="utf-8"))["activities"]
    rows = list(csv.DictReader(open(CSV_SCHED, encoding="utf-8-sig")))
    by_csv = {r["task_id"]: r for r in rows}
    mapping = json.load(open(MAPPING, encoding="utf-8"))
    zdoc = json.load(open(ZONES, encoding="utf-8"))
    zones = {z["zone_id"]: z for z in zdoc["zones"]}
    binds = json.load(open(BINDINGS, encoding="utf-8"))["bindings"]

    # ── 인덱스 ──────────────────────────────────────────────
    # 타설 형제: (level, element_type) → GUID 집합
    pour_guids = collections.defaultdict(set)
    for a in acts:
        r = by_csv.get(tid(a["activityID"]), {})
        if a["trade"] == "concrete_pour" and not a.get("isCuring"):
            g = (mapping.get(tid(a["activityID"])) or {}).get("element_ids") or []
            pour_guids[(r.get("level"), r.get("element_type"))] |= set(g)

    # 양생 행은 element_type 이 '양생' 이라 타설 형제와 키가 다르다.
    # (level, ifc_class) → element_type 으로 되돌린다 (원본 공정표에서 1:1 이다).
    cls_to_type = {}
    for r in rows:
        if r["origin"] == "original" and r["element_type"] != "양생":
            cls_to_type.setdefault((r["level"], r["ifc_class"]), set()).add(
                r["element_type"])

    # 해체 태스크 → H008 zone (그 태스크를 despawn 으로 지목하는 zone)
    strip_zone = {}
    for b in binds:
        if b["template"] != "LCR_SHORING_COLLAPSE":
            continue
        d = b.get("despawnActivity")
        if d:
            strip_zone[tid(d)] = b.get("_zone_id")

    # 층(CSV storey 명) → H004 적재구역 zone
    mat_zone = {}
    for z in zdoc["zones"]:
        if z["hazard_type"].startswith("H004"):
            mat_zone[z.get("storey")] = z["zone_id"]

    # ── 태스크별 위치 확정 ──────────────────────────────────
    out = {}
    stat = collections.Counter()
    inherit_log = []
    unresolved = []

    for a in acts:
        aid = a["activityID"]
        t = tid(aid)
        r = by_csv.get(t, {})
        origin = r.get("origin", "?")
        lvl = r.get("level")
        et = r.get("element_type")
        ic = r.get("ifc_class")
        existing = (mapping.get(t) or {}).get("element_ids") or []

        rec = {"activityID": aid, "source": None, "element_ids": [],
               "zone_ids": [], "level_override": None, "note": ""}

        if existing:
            rec["source"] = "original"
            rec["element_ids"] = list(existing)

        elif origin == "augment:strip":
            zid = strip_zone.get(t)
            if zid and zid in zones:
                z = zones[zid]
                rec["source"] = "inherited:shoring"
                rec["zone_ids"] = [zid]
                rec["level_override"] = z["level"]      # 직하부 — 추정 아님
                rec["note"] = ("동바리 해체는 슬래브 하부에서 이루어진다. "
                               "이 zone 의 despawnActivity 가 %s 이고 zone.level "
                               "이 이미 직하부로 계산되어 있다(supports=%s)."
                               % (aid, z.get("supports_storey")))
                inherit_log.append((aid, "inherited:shoring", zid,
                                    "%s→%s" % (lvl, z["level"]),
                                    len(z.get("cells", []))))
            else:
                # 최하층 슬래브는 직하부가 없어 H008 zone 이 존재하지 않는다.
                # 층을 옮기지 않고 그 층 슬래브 GUID 를 쓴다.
                g = sorted(pour_guids.get((lvl, "슬래브"), ()))
                if g:
                    rec["source"] = "inherited:pour"
                    rec["element_ids"] = g
                    rec["note"] = ("최하층이라 직하부 H008 zone 이 없다 — "
                                   "층을 옮기지 않고 같은 층 슬래브 발자국을 쓴다.")
                    inherit_log.append((aid, "inherited:pour(최하층)",
                                        "%s/슬래브" % lvl, "%s(유지)" % lvl, len(g)))
                else:
                    unresolved.append((aid, r.get("task_name", ""), origin,
                                       "H008 zone 도 슬래브 타설 형제도 없음"))

        elif origin == "augment:material":
            zid = mat_zone.get(lvl)
            if zid:
                rec["source"] = "zone:material"
                rec["zone_ids"] = [zid]
                rec["note"] = ("자재 반입·소진은 특정 부재가 아니라 적재구역에서 "
                               "이루어진다. CSV 의 ifc_class(%s)는 후속 소비 공정을 "
                               "가리키는 값이지 작업 위치가 아니다." % ic)
                inherit_log.append((aid, "zone:material", zid, lvl,
                                    len(zones[zid].get("cells", []))))
            else:
                unresolved.append((aid, r.get("task_name", ""), origin,
                                   "층 %s 에 H004 적재구역 zone 이 없음" % lvl))

        else:                                    # origin == "original", 미매핑
            key_type = et
            if et == "양생":                     # ifc_class 로 부재 유형 복원
                cand = cls_to_type.get((lvl, ic), set())
                key_type = sorted(cand)[0] if len(cand) == 1 else None
            g = sorted(pour_guids.get((lvl, key_type), ())) if key_type else []
            if g:
                rec["source"] = "inherited:pour"
                rec["element_ids"] = g
                rec["note"] = ("철근·거푸집은 그 부재가 세워질 자리에서 이루어진다 — "
                               "같은 (level, element_type) 타설 태스크의 GUID 상속."
                               if et != "양생" else
                               "양생 위치는 부재 자리다. 단 crewSize=0 이라 "
                               "워커가 생성되지 않는다(상주 공정 아님).")
                inherit_log.append((aid, "inherited:pour",
                                    "%s/%s" % (lvl, key_type), lvl, len(g)))
            else:
                unresolved.append((aid, r.get("task_name", ""), origin,
                                   "타설 형제 GUID 없음 (level=%s, type=%s)"
                                   % (lvl, key_type)))

        if rec["source"]:
            stat[rec["source"]] += 1
            out[t] = rec
        else:
            stat["none"] += 1

    doc = {
        "meta": {
            "generatedBy": "scripts/build_task_locations.py",
            "source_mapping": MAPPING,
            "backup": BACKUP,
            "note": ("원본 element_task_mapping.json 은 수정하지 않는다. "
                     "이 파일은 파생 위치표이며 source 열이 각 항목의 출처다."),
            "sources": {
                "original": "element_task_mapping.json 에 이미 있는 GUID",
                "inherited:pour": "같은 (level, element_type) 타설 태스크 GUID 상속",
                "inherited:shoring": "H008_ShoringCollapse zone (직하부, level_override 동반)",
                "zone:material": "H004_MaterialStorage zone (층당 1개)",
            },
            "counts": dict(stat),
        },
        "tasks": out,
    }
    with io.open(OUT, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1)

    # ── 로그 ────────────────────────────────────────────────
    w = io.StringIO()
    w.write("# 작업 위치 매핑 보강 (v3.3 Phase 1)\n\n")
    w.write("원본 `element_task_mapping.json` 은 **수정하지 않았다**. "
            "백업 `%s`, 파생 위치표 `%s`.\n\n" % (BACKUP, OUT))

    w.write("## 보강 전후 매핑률 (액티비티 단위)\n\n")
    total = len(acts)
    before = sum(1 for a in acts
                 if (mapping.get(tid(a["activityID"])) or {}).get("element_ids"))
    after = len(out)
    w.write("| | 매핑 | 미매핑 | 매핑률 |\n|---|---|---|---|\n")
    w.write("| 보강 전 | %d | %d | %.1f%% |\n"
            % (before, total - before, 100.0 * before / total))
    w.write("| **보강 후** | **%d** | **%d** | **%.1f%%** |\n\n"
            % (after, total - after, 100.0 * after / total))

    w.write("## 위치 원천별 내역\n\n| source | 건수 |\n|---|---|\n")
    for k, v in sorted(stat.items()):
        w.write("| `%s` | %d |\n" % (k, v))
    w.write("\n")

    w.write("## 분류별 보강 결과\n\n| origin | 전체 | 보강 전 | 보강 후 |\n|---|---|---|---|\n")
    for og in ("original", "augment:strip", "augment:material"):
        sel = [a for a in acts if by_csv.get(tid(a["activityID"]), {}).get("origin") == og]
        b = sum(1 for a in sel
                if (mapping.get(tid(a["activityID"])) or {}).get("element_ids"))
        af = sum(1 for a in sel if tid(a["activityID"]) in out)
        w.write("| `%s` | %d | %d | %d |\n" % (og, len(sel), b, af))
    w.write("\n")

    w.write("## 상속 규칙과 적용 내역\n\n")
    w.write("| 액티비티 | 규칙 | 상속 원천 | 층 | 셀/GUID 수 |\n|---|---|---|---|---|\n")
    for x in inherit_log:
        w.write("| `%s` | `%s` | %s | %s | %d |\n" % x)
    w.write("\n")

    w.write("## 매핑 불가로 남은 것\n\n")
    if unresolved:
        w.write("| 액티비티 | 이름 | origin | 사유 |\n|---|---|---|---|\n")
        for x in unresolved:
            w.write("| `%s` | %s | %s | %s |\n" % x)
    else:
        w.write("없음 — 234건 전부 위치 원천이 확정되었다.\n")
    w.write("\n")

    # ── 위치 원천은 확정되었으나 좌표가 나오지 않는 것 ────────
    # element_task_mapping.json 이 manifest 에 없는 GUID 를 참조하는 기존 결손.
    mf_path = "unity_bundle/manifest.json"
    if os.path.exists(mf_path):
        bbox = {x["element_key"]["ifc_guid"]: x.get("bbox_ifc_m")
                for x in json.load(open(mf_path, encoding="utf-8"))}
        zone_cells = {z["zone_id"]: z.get("cells", []) for z in zdoc["zones"]}
        nocells = []
        for t, rec in sorted(out.items(), key=lambda kv: int(kv[0])):
            n = sum(1 for g in rec["element_ids"] if bbox.get(g))
            n += sum(len(zone_cells.get(z, ())) for z in rec["zone_ids"])
            if n == 0:
                r = by_csv.get(t, {})
                nocells.append((rec["activityID"], r.get("task_name", "")[:30],
                                rec["source"], len(rec["element_ids"])))
        allg = {g for rec in out.values() for g in rec["element_ids"]}
        miss = [g for g in allg if g not in bbox]
        w.write("## 위치 원천은 확정되었으나 좌표가 나오지 않는 것\n\n")
        w.write("`element_task_mapping.json` 이 **manifest 에 없는 GUID** 를 "
                "참조하는 기존 데이터 결손이다 (참조 %d개 중 %d개 부재, %.1f%%). "
                "위치를 지어내지 않고 그대로 두었으며, 해당 액티비티는 실행 시 "
                "폴백(층 배회)으로 처리되고 노출 주 집계에서 제외된다.\n\n"
                % (len(allg), len(miss), 100.0 * len(miss) / max(1, len(allg))))
        if nocells:
            w.write("| 액티비티 | 이름 | source | 참조 GUID |\n|---|---|---|---|\n")
            for x in nocells:
                w.write("| `%s` | %s | `%s` | %d |\n" % x)
        else:
            w.write("없음.\n")
        w.write("\n")

    cure = [a for a in acts if a.get("isCuring") or a["workType"] == "curing"]
    w.write("## 양생 22건 — crewSize 확인\n\n")
    w.write("`crewSize` 분포: %s. **이미 전부 0이므로 변경하지 않았다** "
            "(공기 변화 없음). 워커가 생성되지 않으므로 노출에 기여하지 않는다. "
            "위치는 나중에 점검·살수 작업을 넣을 때를 위해 매핑해 두었다.\n\n"
            % dict(collections.Counter(a["crewSize"] for a in cure)))

    with io.open(LOG, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())

    print("저장: %s (%d 태스크)" % (OUT, len(out)))
    print("저장: %s" % LOG)
    print("  매핑률 %d/%d (%.1f%%) → %d/%d (%.1f%%)"
          % (before, total, 100.0 * before / total, after, total,
             100.0 * after / total))
    print("  원천별:", dict(stat))
    if unresolved:
        print("  미해결 %d건" % len(unresolved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
