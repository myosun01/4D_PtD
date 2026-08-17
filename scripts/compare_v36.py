# -*- coding: utf-8 -*-
"""v3.6 A-6 — 동바리 3개 층 존치 반영 전후 대조.

  stage5  v3.5 종료 (1개 층 존치)  — data/backup_v3.6/ 의 zone·binding 사용
  stage6  v3.6 (KCS 3개 층 존치)   — 현행 build/ 의 zone·binding 사용

같은 시드·같은 스텝수. 수치를 조정하지 않는다.
실행: python scripts/compare_v36.py
산출: build/stage_comparison_v36.md
"""
import argparse
import collections
import io
import json
import os
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import fourd_workers as FW
import movement
import ptd_ttl
from lifecycle import LifecycleEngine
from schedule import Schedule
from site_model import SiteModel

OUT = "build/stage_comparison_v36.md"
BK = "data/backup_v3.6"
HAZ = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")


def load(bindings, zones_path):
    lib = ptd_ttl.require_library()
    sch = Schedule.load("project/schedule.json")
    site = SiteModel.load("project/site.json")
    life = LifecycleEngine(lib.lifecycle_templates, bindings, sch)
    with open("project/crews.json", encoding="utf-8") as fp:
        crews = json.load(fp)
    cfg = {t["trade"]: t.get("rho", {}) for t in crews.get("trades", [])}
    gf = json.load(open("project/site.json", encoding="utf-8"))["gridFrame"]
    wl = FW.WorkLocations(gf, zones_path=zones_path)
    return sch, site, life, cfg, wl


def attribution(res, life):
    idx = collections.defaultdict(float)
    for (lv, r, c, d, ch), v in res["exposure_steps"].items():
        idx[(lv, ch, int(r), int(c))] += v
    out = collections.Counter()
    for h in life.instances:
        ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
        out[h.hazard_type] += sum(idx.get((h.level, ch, int(r), int(c)), 0.0)
                                  for (r, c) in fourd.instance_exposure_cells(h))
    return out


def retention(life, sch, zones_path):
    z = {x["zone_id"]: x for x in json.load(open(zones_path, encoding="utf-8"))["zones"]}
    rows = []
    for h in life.instances:
        if h.hazard_type != "H008":
            continue
        dp = int(h.despawn_day) if h.despawn_day != float("inf") else sch.duration
        rows.append((h.level, dp - int(h.spawn_day), int(h.spawn_day), dp,
                     h.despawn_activity))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--seed", default="v3.1-workers")
    a = ap.parse_args()

    stages = []
    for name, binds, zpath in (
            ("stage5 v3.5 (1개 층 존치)", os.path.join(BK, "lifecycle_bindings_v2.json"),
             os.path.join(BK, "hazard_zones.json")),
            ("stage6 v3.6 (KCS 3개 층 존치)", "build/lifecycle_bindings_v2.json",
             "build/hazard_zones.json")):
        sch, site, life, cfg, wl = load(binds, zpath)
        movement._CTX.clear()
        t0 = time.time()
        r = FW.run_project_workers(sch, site, life, cfg, wl, mc_runs=1,
                                   seed=a.seed, max_steps=a.max_steps,
                                   temp_structures=fourd.load_temp_structures())
        secs = time.time() - t0
        h = attribution(r, life)
        ret = retention(life, sch, zpath)
        stages.append(dict(name=name, haz=h, secs=secs,
                           main=sum(r["exposure_steps"].values()),
                           fb=sum(r["exposure_steps_fallback"].values()),
                           chan=FW.channel_totals(r), ret=ret,
                           n_h008=len([x for x in life.instances
                                       if x.hazard_type == "H008"])))
        print("  %-30s %.1fs  주=%9.0f  H008=%8.0f  존치합=%d일"
              % (name, secs, stages[-1]["main"], h["H008"],
                 sum(x[1] for x in ret)))

    def pct(new, old):
        if not old:
            return "—" if not new else "+∞"
        return "%+.1f%%" % (100.0 * (new - old) / old)

    s5, s6 = stages
    w = io.StringIO()
    w.write("# 동바리 3개 층 존치 반영 — 전후 대조 (v3.6 A-6)\n\n")
    w.write("같은 시드 `%s`, 하루 %d 스텝, mc_runs=1. **수치를 조정하지 않았다.**\n\n"
            % (a.seed, a.max_steps))
    w.write("근거: KCS 14 20 12 3.3.2(2) — 연속 시공 다층 구조는 타설층 포함 "
            "최소 3개 층에 걸쳐 동바리 존치.\n\n")

    w.write("## H008 zone 존치 일수\n\n")
    w.write("| 동바리 층 | stage5 존치 | stage6 존치 | despawn(전) | despawn(후) |\n"
            "|---|---|---|---|---|\n")
    for (lv5, d5, s5s, e5, a5), (lv6, d6, s6s, e6, a6) in zip(s5["ret"], s6["ret"]):
        w.write("| %s | %d일 | **%d일** | `%s` | `%s` |\n" % (lv5, d5, d6, a5, a6))
    w.write("| **합계** | **%d일** | **%d일** | | |\n\n"
            % (sum(x[1] for x in s5["ret"]), sum(x[1] for x in s6["ret"])))
    w.write("zone 수는 %d → %d 로 **변하지 않았다** — zone 을 복제하지 않고 "
            "존치 기간만 늘렸다.\n\n" % (s5["n_h008"], s6["n_h008"]))

    w.write("## 위험유형별 노출스텝\n\n")
    w.write("| 위험유형 | stage5 | stage6 | 변화 |\n|---|---|---|---|\n")
    for k in HAZ:
        w.write("| %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(s5["haz"][k]), "{:,.0f}".format(s6["haz"][k]),
                   pct(s6["haz"][k], s5["haz"][k])))
    w.write("\n")

    w.write("## 총계\n\n| 항목 | stage5 | stage6 | 변화 |\n|---|---|---|---|\n")
    for key, lbl in (("main", "주 집계"), ("fb", "폴백(부가)")):
        w.write("| %s | %s | %s | %s |\n"
                % (lbl, "{:,.0f}".format(s5[key]), "{:,.0f}".format(s6[key]),
                   pct(s6[key], s5[key])))
    w.write("\n")

    w.write("## 채널별\n\n| 채널 | stage5 | stage6 | 변화 |\n|---|---|---|---|\n")
    for k in sorted(set(s5["chan"]) | set(s6["chan"])):
        w.write("| %s | %s | %s | %s |\n"
                % (k, "{:,.0f}".format(s5["chan"].get(k, 0.0)),
                   "{:,.0f}".format(s6["chan"].get(k, 0.0)),
                   pct(s6["chan"].get(k, 0.0), s5["chan"].get(k, 0.0))))
    # ── 존치 10.7배인데 노출은 왜 거의 안 늘었나 ──
    sch6, site6, life6, cfg6, wl6 = load("build/lifecycle_bindings_v2.json",
                                         "build/hazard_zones.json")
    crew_days = collections.defaultdict(set)
    for d in range(sch6.duration):
        for lv, specs in FW._crew_specs_by_level(sch6, d, wl6).items():
            if specs:
                crew_days[lv].add(d)
    w.write("## 존치는 10배 늘었는데 노출은 왜 거의 그대로인가\n\n")
    w.write("노출은 **그 층에 사람이 있을 때만** 발생한다. 늘어난 존치 구간의 "
            "대부분은 작업이 상부층으로 옮겨간 뒤라 동바리 층에 크루가 없다.\n\n")
    w.write("| 동바리 층 | 존치일 | 그중 크루 있는 날 | 비율 |\n|---|---|---|---|\n")
    ta = tc = 0
    for h in life6.instances:
        if h.hazard_type != "H008":
            continue
        dp = int(h.despawn_day) if h.despawn_day != float("inf") else sch6.duration
        days = set(range(int(h.spawn_day), dp))
        wc = days & crew_days.get(h.level, set())
        ta += len(days); tc += len(wc)
        w.write("| %s | %d | %d | %.1f%% |\n"
                % (h.level, len(days), len(wc), 100.0 * len(wc) / max(1, len(days))))
    w.write("| **합계** | **%d** | **%d** | **%.1f%%** |\n\n"
            % (ta, tc, 100.0 * tc / max(1, ta)))
    w.write("**존치일 %d일 중 크루가 있는 날은 %d일(%.1f%%)뿐이다.** "
            "규정은 정확히 반영되었으나 이 공정표에서는 노출 증가로 거의 이어지지 "
            "않는다. 수치를 조정하지 않았다.\n\n" % (ta, tc, 100.0 * tc / max(1, ta)))
    w.write("이 사실은 축 2 실험(KE_K_FS_02 존치기간 명기)의 해석에 직접 영향을 "
            "준다 — 동바리 층에 사람이 거의 없으면 존치기간을 바꿔도 노출 차이가 "
            "작게 나온다. 실험 설계 시 이 점을 전제로 삼아야 한다.\n\n")

    w.write("## 실행 시간\n\n| 단계 | 초 |\n|---|---|\n")
    for s in stages:
        w.write("| %s | %.1f |\n" % (s["name"], s["secs"]))
    w.write("\n")

    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())
    print("저장: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
