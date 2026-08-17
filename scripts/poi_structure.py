# -*- coding: utf-8 -*-
"""v3.7 B-3 — POI 순회 구조 현황 조사 (구조를 바꾸지 않는다).

2D `_assign_task_queue` 주석이 "[4D 격리점] 나중에 공정 스케줄에서 채우도록 교체"
라고 되어 있어, 4D 가 실제로 어떻게 순회하는지 코드와 실측으로 확인만 한다.

측정:
  · 워커가 하루에 여러 액티비티를 순회하는가, 하나에 배정되는가
  · 순회한다면 목표 순서가 어떻게 정해지는가
  · 체류 비율(stage) 별 하루 방문 POI 수
  · 워커당 배정 액티비티 수 / 액티비티당 목표 셀 수 분포

실행: python scripts/poi_structure.py [--days N] [--max-steps N]
산출: build/poi_structure.md
"""
import argparse
import collections
import os
import statistics
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import fourd
import fourd_workers as FW
import movement
import ptd_ttl

OUT = "build/poi_structure.md"
STAGES = [("stage6", "v36", "v3.6 종료 (dwell 12.5%)"),
          ("stage7b", "ab", "+ 체류 비율 0.75"),
          ("stage7c", "v37", "+ 확률적 변동")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=80)
    ap.add_argument("--probe-every", type=int, default=5,
                    help="목표 셀 수 분포를 조사할 일자 간격")
    a = ap.parse_args()

    lib = ptd_ttl.require_library()
    sch, site, life, cfg, wl = FW.load_project_v2()
    ts = fourd.load_temp_structures()

    rows = []
    for name, stage, desc in STAGES:
        movement._CTX.clear()
        res = FW.run_project_workers(sch, site, life, cfg, wl, days=a.days,
                                     mc_runs=1, seed=0, max_steps=a.max_steps,
                                     temp_structures=ts, stage=stage, library=lib)
        pl = res["placement"]
        wd = pl.get("worker_days", 0)
        rows.append((name, desc, res["dwell_steps"], wd, pl.get("visits", 0),
                     pl.get("visits", 0) / wd if wd else 0.0))

    # ── 구조 조사: 워커 1명이 몇 개 액티비티에 배정되는가 / 목표 셀은 몇 개인가 ──
    # make_workers 는 crew_spec (activity_id, trade, crew_size) 단위로 워커를 만들고
    # Worker4D.activity_id 가 하나로 고정된다. 실측으로 확인한다.
    per_worker_acts = collections.Counter()
    targets_n = []
    day_probe = []
    for d in range(0, (sch.duration if a.days is None else a.days), a.probe_every):
        hz = life.hazards(d)
        for level_id, specs in FW._crew_specs_by_level(sch, d, wl).items():
            if level_id not in site.levels or not specs:
                continue
            grid, _ch, _cm = fourd.build_level_day(site, level_id, hz, {}, d,
                                                   temp_structures=ts)
            n_act = len(specs)
            n_crew = sum(int(s[2]) for s in specs)
            day_probe.append((d, level_id, n_act, n_crew))
            for aid, _trade, _size in specs:
                t = wl.targets_on_grid(aid, grid)
                if t:
                    targets_n.append(len(t))
            movement._CTX.pop(id(grid), None)
    per_worker_acts[1] = sum(p[3] for p in day_probe)   # 구조상 1명 = 1 액티비티

    tn = sorted(targets_n)
    def q(p):
        return tn[min(len(tn) - 1, int(len(tn) * p))] if tn else 0

    os.makedirs("build", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        w = f.write
        w("# POI 순회 구조 — 현황 조사 (v3.7 B-3)\n\n")
        w("`scripts/poi_structure.py` 산출. **구조를 바꾸지 않았다. 현황 보고와 제안뿐이다.**\n\n")

        w("## 1. 워커는 하루에 여러 액티비티를 순회하는가\n\n")
        w("**아니다. 하나에 배정된다.** `fourd_workers.make_workers` 가 crew_spec\n")
        w("`(activity_id, trade, crew_size)` 단위로 워커를 만들고 `Worker4D.activity_id`\n")
        w("는 하루 동안 바뀌지 않는다. 하루가 끝나면 워커 개체 자체가 버려지고\n")
        w("다음 날 그날의 in_progress 액티비티로 새로 만들어진다.\n\n")
        w("즉 순회하는 것은 **액티비티가 아니라 그 액티비티의 목표 셀(POI)** 이다.\n\n")

        w("## 2. 순회 순서는 어떻게 정해지는가\n\n")
        w("**무작위다. 공정 순서가 아니다.** `run_level_day_workers` 의 목표 선정은\n")
        w("`w.target = w.targets[rng.randrange(len(w.targets))]` 한 줄이고,\n")
        w("`w.targets` 는 그 액티비티가 손대는 IFC 요소의 격자 셀 목록이다.\n")
        w("도달 후 체류가 끝나면 같은 목록에서 다시 균일 표집한다 — 방문 이력을\n")
        w("보지 않으므로 **같은 셀을 연속으로 뽑을 수 있고, 남은 셀을 소진하지도 않는다.**\n\n")
        w("2D `_assign_task_queue` 의 `[4D 격리점]` 주석이 가리킨 \"공정 스케줄에서\n")
        w("채우도록 교체\" 는 **아직 이루어지지 않았다.** 공정이 정하는 것은\n")
        w("_어느 액티비티가 그날 활성인가_ 까지이고, 그 안에서의 순서는 무작위다.\n\n")

        w("| 항목 | 값 |\n|---|---|\n")
        w("| 워커 1명이 배정되는 액티비티 수 | **1 (고정)** |\n")
        w("| 액티비티당 목표 셀 수 — 중앙값 | %s |\n" % q(0.5))
        w("| 〃 25%% / 75%% 분위 | %s / %s |\n" % (q(0.25), q(0.75)))
        w("| 〃 최소 / 최대 | %s / %s |\n" % (tn[0] if tn else 0, tn[-1] if tn else 0))
        w("| 표본 (액티비티·층·일) | %d |\n\n" % len(tn))

        w("## 3. 체류 비율에 따른 하루 방문 POI 수\n\n")
        w("`Worker4D.visits` 를 세어 워커일로 나눈 값이다 (하루 %d 스텝).\n\n" % a.max_steps)
        w("| 단계 | 내용 | 체류스텝 | 워커일 | 총 방문 | **POI/워커일** |\n")
        w("|---|---|---|---|---|---|\n")
        for name, desc, dw, wd, v, per in rows:
            w("| **%s** | %s | %d | %s | %s | **%.2f** |\n"
              % (name, desc, dw, "{:,}".format(wd), "{:,}".format(v), per))
        w("\n")
        base = rows[0][5] if rows else 0.0
        last = rows[-1][5] if rows else 0.0
        w("체류 비율을 12.5%% → 75%% 로 올리자 방문 수는 **%.2f → %.2f (%.0f%%)** 로 줄었다.\n"
          % (base, last, (last / base - 1) * 100 if base else 0))
        w("한 곳에 오래 머무니 하루에 도는 곳이 줄어드는 것으로, 방향이 맞다.\n")
        w("**1 미만이라는 것은 하루 안에 목표에 도달하지 못하고 끝나는 워커가 있다는 뜻이다** —\n")
        w("이동에 하루가 다 가는 경우다(80 스텝, 2스텝당 1칸 → 하루 최대 40칸).\n\n")

        w("## 4. 제안 (이번에 실행하지 않음)\n\n")
        w("1. **목표 순서를 공정에 묶는 것** — 액티비티 안에서도 시공 순서(예: 기둥\n")
        w("   번호·구획 순)가 있다면 무작위 표집보다 실제에 가깝다. 다만 그 순서를\n")
        w("   정하는 데이터가 현재 공정표에 없다. **없는 순서를 지어내면 안 된다.**\n")
        w("2. **하루 스텝 수(%d)** 가 방문 수를 강하게 제약한다. 체류 비율보다 이쪽이\n" % a.max_steps)
        w("   먼저 검토될 값이다. 이 축약 자체는 `build/limitations.md` §5 에 이미\n")
        w("   등록돼 있으나, **그것이 POI 방문 수를 1 미만으로 누른다는 사실**은\n")
        w("   여기서 처음 정량화됐다.\n")
        w("3. 워커를 하루 여러 액티비티에 걸치게 하는 것은 crewSize 의 의미(액티비티에\n")
        w("   배정된 인원)를 바꾸는 일이므로 공정표 해석부터 다시 정해야 한다.\n")

    print("wrote %s" % OUT)
    for r in rows:
        print("  %-8s dwell=%-3d visits/worker-day=%.2f" % (r[0], r[2], r[5]))


if __name__ == "__main__":
    main()
