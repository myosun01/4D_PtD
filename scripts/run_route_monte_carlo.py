# -*- coding: utf-8 -*-
"""고정 작업자 조건 + 확률적 Theta* 경로선택 몬테카를로 실행기.

예시:
    python scripts/run_route_monte_carlo.py --runs 100 --max-steps 480 --jobs 4

Unity 궤적을 만들지 않는다. 시행별 원자료와 통계 진단을 먼저 확정한 뒤 대표 시행만
별도 시각화하는 연구용 실행기다.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import io
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import fourd
import fourd_workers as FW
from monte_carlo import convergence_trace, summarize_rows

DEFAULT_MANIFEST = os.path.join("build", "variant_manifest.json")


def _load_case(variant_id, manifest_path):
    if variant_id == "BASE":
        sch, site, life, cfg, wl = FW.load_project_v2()
        return sch, site, life, cfg, wl, {}

    import ptd_ttl
    from controls import ControlApplication, resolve_all
    from lifecycle import LifecycleEngine
    from schedule import Schedule
    from site_model import SiteModel

    with open(manifest_path, encoding="utf-8") as fp:
        manifest = json.load(fp)
    variants = {row["variant_id"]: row for row in manifest["variants"]}
    if variant_id not in variants:
        raise ValueError("variant_manifest에 없는 ID: %s" % variant_id)
    variant = variants[variant_id]
    directory = variant["dir"]
    lib = ptd_ttl.require_library()
    sch = Schedule.load(os.path.join(directory, "schedule.json"))
    site = SiteModel.load("project/site.json")
    life = LifecycleEngine(lib.lifecycle_templates,
                           os.path.join(directory, "lifecycle_bindings_v2.json"), sch)
    with open("project/crews.json", encoding="utf-8") as fp:
        cfg = {row["trade"]: row.get("rho", {})
               for row in json.load(fp).get("trades", [])}
    with open("project/site.json", encoding="utf-8") as fp:
        grid_frame = json.load(fp)["gridFrame"]
    wl = FW.WorkLocations(grid_frame,
                          zones_path=os.path.join(directory, "hazard_zones.json"))
    effects = {}
    if variant.get("mechanism") == "controls_effect":
        targets = [hazard for hazard in life.instances
                   if hazard.hazard_type == variant["target_hazard_type"]]
        applications = [ControlApplication(variant["alternative_id"],
                                           hazard.instance_id)
                        for hazard in targets]
        effects = resolve_all(lib, applications, sch, life)
    return sch, site, life, cfg, wl, effects


def _run_batch(job):
    (start, count, seed, days, day_start, max_steps, use_temp,
     variant_id, manifest_path) = job
    sch, site, life, cfg, wl, effects = _load_case(variant_id, manifest_path)
    temp = fourd.load_temp_structures() if use_temp else None
    t0 = time.perf_counter()
    result = FW.run_project_workers(
        sch, site, life, cfg, wl, days=days, day_start=day_start,
        mc_runs=count, seed=seed, max_steps=max_steps,
        temp_structures=temp, controls_effects=effects,
        variation_scope="route_only",
        record_replicates=True, replicate_start=start,
        collect_cell_maps=False)
    return {
        "replicates": result["replicates"],
        "assignment_digest": result["assignment_digest"],
        "route_cache": result["route_cache"],
        "seconds": time.perf_counter() - t0,
        "work_location_stats": result["work_location_stats"],
        "days": result["days"],
        "horizon": result["horizon"],
    }


def _batches(runs, jobs, seed, days, day_start, max_steps, use_temp,
             variant_id, manifest_path):
    size = int(math.ceil(runs / float(jobs)))
    out = []
    for start in range(0, runs, size):
        out.append((start, min(size, runs - start), seed, days, day_start,
                    max_steps, use_temp, variant_id, manifest_path))
    return out


def _flatten_rows(rows):
    channels = sorted({ch for row in rows
                       for ch in row["channel_exposure_steps"]})
    flat = []
    for row in rows:
        item = {
            "replicate": row["replicate"],
            "seed": row["seed"],
            "assignment_digest": row["assignment_digest"],
            "route_digest": row["route_digest"],
            "route_calls": row["route_calls"],
            "route_cells": row["route_cells"],
            "route_distance_cells": row["route_distance_cells"],
            "total_exposure_steps": row["total_exposure_steps"],
            "fallback_exposure_steps": row["fallback_exposure_steps"],
            "total_lambda": row["total_lambda"],
        }
        for ch in channels:
            item["exposure_%s" % ch] = row["channel_exposure_steps"].get(ch, 0.0)
            item["lambda_%s" % ch] = row["channel_lambda"].get(ch, 0.0)
        flat.append(item)
    return flat, channels


def _write_csv(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fp:
        wr = csv.DictWriter(fp, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


def _fmt(value):
    if not math.isfinite(float(value)):
        return "—"
    return "{:,.6g}".format(value)


def _report(doc):
    meta, stats = doc["meta"], doc["summary"]
    out = io.StringIO()
    out.write("# 경로선택 몬테카를로 실행 보고서\n\n")
    out.write("## 실험 통제\n\n")
    out.write("| 항목 | 설정 |\n|---|---|\n")
    out.write("| 반복 | %d회 |\n" % meta["runs"])
    out.write("| 조건 | `%s` |\n" % meta["variant_id"])
    out.write("| 변동 범위 | `route_only` — Theta* 경로 충격만 시행별 재표집 |\n")
    out.write("| 고정 | 일·층별 인원, 작업자 ID, 시작조건, 목적지, ρ, 출발시각, 작업구역 |\n")
    out.write("| 작업 상태 | 목적지 도착 후 해당 일의 horizon 끝까지 고정 |\n")
    out.write("| 시드 | `%s` |\n" % meta["seed"])
    out.write("| 작업자 조건 해시 | `%s` |\n" % meta["assignment_digest"])
    out.write("| 경로 digest 다양성 | %d / %d (반복 경로 허용) |\n"
              % (meta["unique_route_digests"], meta["runs"]))
    out.write("| 실행 | %d 프로세스, %.1f초 |\n\n"
              % (meta["jobs"], meta["wall_seconds"]))
    if meta["unique_route_digests"] == 1:
        out.write("> **경고:** 모든 시행의 경로 digest가 같다. 이 배치에서는 경로 확률변동이 "
                  "관측되지 않았으므로 본실험 결과로 사용하지 않는다.\n\n")

    out.write("## 시행별 분포 요약\n\n")
    out.write("Student-t 양측 %.1f%% 신뢰구간과 경험적 5/50/95 분위수다.\n\n"
              % (100.0 * meta["confidence"]))
    out.write("| 지표 | 평균 | 표준편차 | CI 반폭 | 반폭/평균 | p05 | p50 | p95 |\n")
    out.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for name, row in stats.items():
        rel = row["relative_half_width"]
        rel_text = "—" if not math.isfinite(rel) else "%.2f%%" % (100.0 * rel)
        out.write("| %s | %s | %s | %s | %s | %s | %s | %s |\n"
                  % (name, _fmt(row["mean"]), _fmt(row["stdev"]),
                     _fmt(row["ci_half_width"]), rel_text, _fmt(row["p05"]),
                     _fmt(row["p50"]), _fmt(row["p95"])))

    out.write("\n## 총 노출 수렴 진단\n\n")
    out.write("이 표는 고정된 반복 수를 실행한 뒤 확인하는 사후 진단이다. 매 10회마다 "
              "멈추는 순차검정으로 사용하지 않는다.\n\n")
    out.write("| n | 평균 | 95% CI 반폭 | 반폭/평균 |\n|---:|---:|---:|---:|\n")
    for row in doc["convergence"]["total_exposure_steps"]:
        rel = row["relative_half_width"]
        out.write("| %d | %s | %s | %s |\n"
                  % (row["n"], _fmt(row["mean"]), _fmt(row["ci_half_width"]),
                     "—" if not math.isfinite(rel) else "%.2f%%" % (100.0 * rel)))
    out.write("\n## 산출물\n\n")
    out.write("- `%s`: 시행별 원자료\n" % meta["output_csv"])
    out.write("- `%s`: 통계·수렴·메타데이터\n" % meta["output_json"])
    out.write("- `%s`: 이 보고서\n" % meta["output_report"])
    return out.getvalue()


def main():
    auto_jobs = min(4, max(1, (os.cpu_count() or 2) // 2))
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100,
                    help="고정 반복 수(기본 100, 최소 2)")
    ap.add_argument("--days", type=int, default=None,
                    help="마지막 day 인덱스의 배타 상한(기본 전체 공기)")
    ap.add_argument("--day-start", type=int, default=0)
    ap.add_argument("--max-steps", type=int, default=480)
    ap.add_argument("--seed", default="route-mc-v1")
    ap.add_argument("--variant", default="BASE",
                    help="build/variant_manifest.json의 variant_id")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--jobs", type=int, default=auto_jobs,
                    help="병렬 프로세스 수(기본 CPU 절반, 최대 4)")
    ap.add_argument("--confidence", type=float, default=0.95)
    ap.add_argument("--no-temp-structures", action="store_true")
    args = ap.parse_args()
    if args.runs < 2:
        ap.error("--runs must be >= 2")
    if args.jobs < 1:
        ap.error("--jobs must be >= 1")
    if not 0.0 < args.confidence < 1.0:
        ap.error("--confidence must be in (0, 1)")
    jobs = min(args.jobs, args.runs)
    if args.variant != "BASE" and not os.path.exists(args.manifest):
        ap.error("variant manifest not found: %s" % args.manifest)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.variant)
    out_csv = os.path.join("output", "route_mc_%s_replicates.csv" % slug)
    out_json = os.path.join("output", "route_mc_%s_summary.json" % slug)
    out_report = os.path.join("build", "route_mc_%s_report.md" % slug)
    batches = _batches(args.runs, jobs, args.seed, args.days, args.day_start,
                       args.max_steps, not args.no_temp_structures,
                       args.variant, args.manifest)

    wall0 = time.perf_counter()
    if len(batches) == 1:
        results = [_run_batch(batches[0])]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(_run_batch, batches))
    wall_seconds = time.perf_counter() - wall0

    digests = {result["assignment_digest"] for result in results}
    if len(digests) != 1:
        raise RuntimeError("병렬 배치의 작업자 조건 해시가 다르다: %r" % sorted(digests))
    rows = sorted((row for result in results for row in result["replicates"]),
                  key=lambda row: row["replicate"])
    expected = list(range(args.runs))
    actual = [row["replicate"] for row in rows]
    if actual != expected:
        raise RuntimeError("시행 번호가 중복되거나 빠졌다: %r" % actual)

    flat, channels = _flatten_rows(rows)
    metric_names = ["total_exposure_steps", "fallback_exposure_steps",
                    "total_lambda", "route_distance_cells"]
    metric_names += ["exposure_%s" % ch for ch in channels]
    summary = summarize_rows(flat, metric_names, args.confidence)
    convergence = {
        name: convergence_trace([row[name] for row in flat], args.confidence)
        for name in ("total_exposure_steps", "total_lambda")}
    meta = {
        "runs": args.runs,
        "variant_id": args.variant,
        "days": results[0]["days"],
        "day_start": args.day_start,
        "max_steps": args.max_steps,
        "seed": args.seed,
        "jobs": jobs,
        "confidence": args.confidence,
        "variation_scope": "route_only",
        "assignment_digest": next(iter(digests)),
        "unique_route_digests": len({row["route_digest"] for row in rows}),
        "wall_seconds": wall_seconds,
        "batch_seconds": [result["seconds"] for result in results],
        "temporary_structures": not args.no_temp_structures,
        "cell_maps_collected": False,
        "trajectory_logged": False,
        "output_csv": out_csv.replace("\\", "/"),
        "output_json": out_json.replace("\\", "/"),
        "output_report": out_report.replace("\\", "/"),
    }
    doc = {"meta": meta, "summary": summary, "convergence": convergence,
           "replicates": rows}
    _write_csv(flat, out_csv)
    with open(out_json, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(out_report), exist_ok=True)
    with open(out_report, "w", encoding="utf-8") as fp:
        fp.write(_report(doc))

    print("완료: %d회, 경로 digest %d개, %.1f초" %
          (args.runs, meta["unique_route_digests"], wall_seconds))
    print(out_csv)
    print(out_json)
    print(out_report)


if __name__ == "__main__":
    main()
