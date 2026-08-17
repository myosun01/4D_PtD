# -*- coding: utf-8 -*-
"""Part B 실행기 — 4D 격자에서 개별 워커를 돌리고 궤적을 남긴다.

  · 84건 현행 바인딩(build/lifecycle_bindings_v2.json)을 명시 주입한다 (B-4)
  · 작업 위치는 액티비티가 대상으로 하는 IFC 요소 셀에서 유도한다 (B-1)
  · H002·H011 노출이 실제로 0이 아닌지 확인한다 (B-2)
  · 궤적 샘플링 간격을 실측해 기본값 근거를 남긴다 (B-3)

실행: python scripts/run_4d_workers.py [--days N] [--max-steps N] [--every N]
산출: output/worker_trajectory.csv, build/run_4d_workers_log.md
"""
import argparse
import io
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import fourd
import fourd_workers as FW

OUT_TRAJ = os.path.join("output", "worker_trajectory.csv")
OUT_LOG = os.path.join("build", "run_4d_workers_log.md")

# 궤적 샘플링 간격 후보 — 파일 크기를 실측해 기본값 근거를 만든다.
EVERY_CANDIDATES = (1, 5, 10, 20)
DEFAULT_EVERY = 10


def exposure_on_cells(result, life, hazard_types, key="exposure_steps"):
    """유형별 노출 합. 귀속 셀은 `fourd.instance_exposure_cells()` 로 통일한다 (v3.5 A-1).

    zone 셀만 보던 기존 방식은 H001 의 fall 노출이 구조상 생길 수 없는 자리
    (구멍이 된 버퍼)를 세고 있어 누수값을 냈다."""
    cells_by = defaultdict(set)
    for h in life.instances:
        if h.hazard_type in hazard_types:
            ch = fourd.HAZARD_CHANNEL_4D.get(h.hazard_type)
            for (r, c) in fourd.instance_exposure_cells(h):
                cells_by[h.hazard_type].add((h.level, ch, int(r), int(c)))
    out = defaultdict(float)
    for (lv, r, c, d, ch), v in result.get(key, {}).items():
        for haz, cells in cells_by.items():
            if (lv, ch, r, c) in cells:
                out[haz] += v
    return dict(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="기본: 전체 공기")
    ap.add_argument("--max-steps", type=int, default=80,
                    help="하루 스텝수 (기본 80 — 기존 gen_lambda_v2.py 와 동일)")
    ap.add_argument("--every", type=int, default=DEFAULT_EVERY,
                    help="궤적 샘플링 간격(N스텝마다 1줄)")
    ap.add_argument("--seed", default="v3.1-workers")
    ap.add_argument("--calibrate-every", action="store_true",
                    help="샘플링 간격별 파일 크기를 실측한다(느림)")
    ap.add_argument("--no-temp-structures", action="store_true",
                    help="가설물(build/temp_structures.json)을 끈다 — 후방호환 확인용")
    a = ap.parse_args()

    ts = None if a.no_temp_structures else fourd.load_temp_structures()

    w = io.StringIO()
    w.write("# Part B 실행 로그 — 4D 워커 + 궤적\n\n")

    t0 = time.time()
    sch, site, life, cfg, wl = FW.load_project_v2()
    t_load = time.time() - t0
    n_days = sch.duration if a.days is None else a.days

    w.write("## 입력\n\n")
    w.write("| 항목 | 값 |\n|---|---|\n")
    w.write("| 공정표 | project/schedule.json — %d 액티비티, 공기 %d일 |\n"
            % (len(sch.activities), sch.duration))
    w.write("| 바인딩 | build/lifecycle_bindings_v2.json — **%d건** (명시 주입, B-4) |\n"
            % len(life.instances))
    w.write("| 층 | %s |\n" % ", ".join(site.level_order))
    w.write("| 하루 스텝 | %d (config.WORKDAY_STEPS=%d 중 일부 — 기존 관행 승계) |\n"
            % (a.max_steps, C.WORKDAY_STEPS))
    w.write("| 시드 | `%s` |\n" % a.seed)
    w.write("| 가설물(TS) | %s |\n"
            % ("적용 — build/temp_structures.json (%d 유형, %d개)"
               % (len(set(t["ts_type"] for v in ts.values() for t in v)),
                  sum(len(v) for v in ts.values())) if ts else "없음(후방호환 경로)"))
    w.write("| 로드 시간 | %.1fs |\n\n" % t_load)

    # ── 샘플링 간격 실측 (B-3 근거) ──
    w.write("## 궤적 샘플링 간격 (B-3)\n\n")
    if a.calibrate_every:
        w.write("짧은 구간(30일)으로 간격별 파일 크기를 실측했다.\n\n")
        w.write("| every | 행 수 | 파일 크기 |\n|---|---|---|\n")
        probe = os.path.join("output", "_probe_trajectory.csv")
        for ev in EVERY_CANDIDATES:
            r = FW.run_project_workers(sch, site, life, cfg, wl, days=30,
                                       mc_runs=1, seed=a.seed,
                                       max_steps=a.max_steps,
                                       trajectory_path=probe, trajectory_every=ev,
                                       temp_structures=ts)
            sz = os.path.getsize(probe)
            w.write("| %d | %s | %.1f MB |\n"
                    % (ev, "{:,}".format(r["trajectory_rows"]), sz / 1e6))
        os.remove(probe)
        w.write("\n30일 기준이므로 전체 %d일은 대략 %.1f배다.\n\n"
                % (n_days, n_days / 30.0))
    else:
        w.write("이번 실행은 간격 실측을 건너뛰었다 (`--calibrate-every` 로 실측). "
                "적용 간격 = **%d**.\n\n" % a.every)

    # ── 본 실행 ──
    t0 = time.time()
    res = FW.run_project_workers(sch, site, life, cfg, wl, days=a.days,
                                 mc_runs=1, seed=a.seed, max_steps=a.max_steps,
                                 trajectory_path=OUT_TRAJ, trajectory_every=a.every,
                                 temp_structures=ts)
    t_run = time.time() - t0
    size_mb = os.path.getsize(OUT_TRAJ) / 1e6

    w.write("## 실행 결과\n\n")
    w.write("| 항목 | 값 |\n|---|---|\n")
    w.write("| 일수 | %d |\n" % n_days)
    w.write("| **1회 실행 시간** | **%.1fs** (mc_runs=1, max_steps=%d) |\n"
            % (t_run, a.max_steps))
    w.write("| 궤적 파일 | `%s` — %s행, %.1f MB (every=%d) |\n"
            % (OUT_TRAJ.replace("\\", "/"),
               "{:,}".format(res["trajectory_rows"]), size_mb, a.every))
    w.write("| λ 항목 수 | %s |\n" % "{:,}".format(len(res["lam"])))
    w.write("| 총 노출스텝 | %s |\n"
            % "{:,.0f}".format(sum(res["exposure_steps"].values())))
    w.write("\n")

    # ── B-1 작업위치 유도 ──
    st = res["work_location_stats"]
    pl = res["placement"]
    total_w = pl["derived"] + pl["fallback"]
    fb_ratio = 100.0 * pl["fallback"] / total_w if total_w else 0.0
    w.write("## B-1 작업 위치 유도\n\n")
    w.write("액티비티 → (GUID 경로) `build/task_locations.json` → "
            "`unity_bundle/manifest.json`(bbox, IFC 월드 m) → gridFrame(월드→셀)\n"
            "            (zone 경로) `build/task_locations.json` → "
            "`build/hazard_zones.json` 셀\n\n")
    w.write("| 항목 | 값 |\n|---|---|\n")
    w.write("| 파생 위치표 사용 | %s |\n"
            % ("예 (build/task_locations.json)" if st.get("locations_file")
               else "아니오 — element_task_mapping.json 만 (후방호환)"))
    w.write("| 참조 GUID / manifest 해석 | %d / %d |\n"
            % (st["guids_referenced"], st["guids_resolved"]))
    w.write("| zone 경로 사용 횟수 | %d |\n" % st.get("from_zone", 0))
    w.write("| 기하에서 유도된 워커-일 | %s (%.1f%%) |\n"
            % ("{:,}".format(pl["derived"]), 100.0 - fb_ratio))
    w.write("| 폴백(층 메인 컴포넌트 배회) | %s (**%.1f%%**) |\n"
            % ("{:,}".format(pl["fallback"]), fb_ratio))
    w.write("\n")
    if fb_ratio > 30.0:
        w.write("> **경고 — 폴백 비율 %.1f%% 가 30%% 를 넘는다.** 폴백은 층 전체를 "
                "배회하므로 위험구역과의 관계가 면적 비례일 뿐이다. "
                "이 상태로는 variant 실험을 돌릴 수 없다.\n\n" % fb_ratio)
    else:
        w.write("폴백 비율 %.1f%% — 30%% 기준 이하.\n\n" % fb_ratio)

    # ── 폴백 노출: 주 집계에서 제외하되 병기 (Phase 1-5) ──
    der = sum(res["exposure_steps"].values())
    fbk = sum(res["exposure_steps_fallback"].values())
    tot_both = der + fbk
    w.write("### 폴백 노출 처리 — 주 집계 제외, 두 값 병기\n\n")
    w.write("| 집계 | 노출스텝 | 비중 |\n|---|---|---|\n")
    w.write("| **주 집계 (유도 워커만)** | **%s** | %.1f%% |\n"
            % ("{:,.0f}".format(der), 100.0 * der / tot_both if tot_both else 0.0))
    w.write("| 폴백 워커 (부가) | %s | %.1f%% |\n"
            % ("{:,.0f}".format(fbk), 100.0 * fbk / tot_both if tot_both else 0.0))
    w.write("| 포함 합계 (참고) | %s | 100%% |\n\n" % "{:,.0f}".format(tot_both))
    w.write("λ 는 **주 집계에서만** 산출한다. 폴백은 값을 버리지 않고 병기해 "
            "대안 간 순위가 뒤집히는지 확인할 수 있게 둔다.\n\n")

    # ── B-2 H002/H011 ──
    w.write("## B-2 H002 · H011 노출\n\n")
    hz_all = ("H001", "H002", "H004", "H007", "H008", "H009", "H011")
    per_haz = exposure_on_cells(res, life, hz_all)
    per_haz_fb = exposure_on_cells(res, life, hz_all, "exposure_steps_fallback")
    w.write("| 위험유형 | 채널 | 인스턴스 수 | 노출스텝(주) | 노출스텝(폴백) |\n"
            "|---|---|---|---|---|\n")
    n_inst = defaultdict(int)
    for h in life.instances:
        n_inst[h.hazard_type] += 1
    for haz in hz_all:
        w.write("| %s | %s | %d | %s | %s |\n"
                % (haz, fourd.HAZARD_CHANNEL_4D.get(haz, "—"), n_inst[haz],
                   "{:,.0f}".format(per_haz.get(haz, 0.0)),
                   "{:,.0f}".format(per_haz_fb.get(haz, 0.0))))
    w.write("\n")
    narrow_ok = (per_haz.get("H002", 0.0) + per_haz.get("H011", 0.0)) > 0
    w.write("H002+H011 노출스텝 = **%s** — %s\n\n"
            % ("{:,.0f}".format(per_haz.get("H002", 0.0) + per_haz.get("H011", 0.0)),
               "0 아님 (B-2 충족)" if narrow_ok else "**여전히 0 (B-2 미충족)**"))
    w.write("`project/site.json` 정적 격자에는 NARROW(셀타입 5) 셀이 0개다. "
            "따라서 narrow 채널 노출은 전부 H002·H011 오버레이에서 온 것이다.\n\n")

    # ── 채널 합계 ──
    ct = FW.channel_totals(res)
    ct_fb = FW.channel_totals(res, "exposure_steps_fallback")
    w.write("## 채널별 노출스텝\n\n")
    w.write("| 채널 | 주 집계 | 폴백(부가) |\n|---|---|---|\n")
    for ch in sorted(set(ct) | set(ct_fb)):
        w.write("| %s | %s | %s |\n" % (ch, "{:,.0f}".format(ct.get(ch, 0.0)),
                                        "{:,.0f}".format(ct_fb.get(ch, 0.0))))
    w.write("\n")

    # ── 층별 분포 ──
    by_lv = defaultdict(float)
    for (lv, r, c, d, ch), v in res["exposure_steps"].items():
        by_lv[lv] += v
    w.write("## 층별 노출스텝 (주 집계)\n\n| 층 | 노출스텝 | 비중 |\n|---|---|---|\n")
    s = sum(by_lv.values()) or 1.0
    for lv in sorted(by_lv):
        w.write("| %s | %s | %.1f%% |\n"
                % (lv, "{:,.0f}".format(by_lv[lv]), 100.0 * by_lv[lv] / s))
    w.write("\n")

    w.write("## 미이식 (후속)\n\n")
    w.write("- `social.apply_witness_shock` — 사고 목격 시 ρ 하락. 4D 는 사고를 "
            "표집하지 않아(λ 방식) 발화 지점이 없다. 이식하려면 사고 표집부터 정해야 한다.\n")
    w.write("- `social.apply_imitation` — 주변 평균 ρ 모방. ρ 는 크루 생성 시 "
            "1회 표집 후 하루 동안 고정이다.\n")
    w.write("- 사고 표집(`P_FALL_PER_STEP` 등 2D 경로) — 4D 는 기대위험 λ 로 대체.\n\n")
    w.write("제외는 폐기가 아니다. 최소 구성이 4D 에서 도는 것을 확인했으므로, "
            "다음은 근거를 갖고 하나씩 추가한다.\n")

    with io.open(OUT_LOG, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())

    print("저장: %s (%s행, %.1f MB)" % (OUT_TRAJ, "{:,}".format(res["trajectory_rows"]), size_mb))
    print("저장: %s" % OUT_LOG)
    print("  실행 %.1fs / %d일 / 노출스텝 %s"
          % (t_run, n_days, "{:,.0f}".format(sum(res["exposure_steps"].values()))))
    print("  H002+H011 노출스텝 = %.0f — %s"
          % (per_haz.get("H002", 0.0) + per_haz.get("H011", 0.0),
             "OK" if narrow_ok else "FAIL"))
    print("  작업위치: 유도 %d / 폴백 %d" % (pl["derived"], pl["fallback"]))
    return 0 if narrow_ok else 1


if __name__ == "__main__":
    sys.exit(main())
