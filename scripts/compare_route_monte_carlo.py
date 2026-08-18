# -*- coding: utf-8 -*-
"""같은 작업자 조건·공통난수로 실행한 두 route MC 결과의 대응 비교."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.path.insert(0, ".")

from monte_carlo import paired_differences

OUT_JSON = os.path.join("output", "route_mc_comparison.json")
OUT_REPORT = os.path.join("build", "route_mc_comparison.md")


def _load(path):
    with open(path, encoding="utf-8") as fp:
        doc = json.load(fp)
    if doc.get("meta", {}).get("variation_scope") != "route_only":
        raise ValueError("route_only 결과가 아님: %s" % path)
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("alternative")
    ap.add_argument("--confidence", type=float, default=0.95)
    args = ap.parse_args()
    base, alt = _load(args.base), _load(args.alternative)
    checks = ("seed", "runs", "day_start", "max_steps", "assignment_digest")
    mismatched = [key for key in checks
                  if base["meta"].get(key) != alt["meta"].get(key)]
    if mismatched:
        raise ValueError("대응비교 불가 — 조건 불일치: %s" % ", ".join(mismatched))

    base_rows = base["replicates"]
    alt_rows = alt["replicates"]
    metrics = ("total_exposure_steps", "fallback_exposure_steps", "total_lambda",
               "route_distance_cells")
    comparisons = {}
    for metric in metrics:
        row = paired_differences(base_rows, alt_rows, metric, args.confidence)
        base_mean = sum(float(item[metric]) for item in base_rows) / len(base_rows)
        row["base_mean"] = base_mean
        row["relative_change"] = row["mean"] / base_mean if base_mean else None
        comparisons[metric] = row
    doc = {"meta": {"base": args.base, "alternative": args.alternative,
                    "confidence": args.confidence,
                    "seed": base["meta"]["seed"],
                    "assignment_digest": base["meta"]["assignment_digest"]},
           "paired_differences_alternative_minus_base": comparisons}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=2)

    report = io.StringIO()
    report.write("# 경로선택 MC 대응 비교\n\n")
    report.write("동일 작업자 조건 해시와 동일 replicate 번호를 확인한 뒤 "
                 "`대안 - BASE`를 계산했다.\n\n")
    report.write("| 지표 | BASE 평균 | 대응차 평균 | 95% CI | 상대 변화 |\n")
    report.write("|---|---:|---:|---:|---:|\n")
    for name, row in comparisons.items():
        rel = row["relative_change"]
        report.write("| %s | %.6g | %+.6g | [%+.6g, %+.6g] | %s |\n"
                     % (name, row["base_mean"], row["mean"], row["ci_low"],
                        row["ci_high"], "—" if rel is None else "%+.2f%%" % (100 * rel)))
    os.makedirs(os.path.dirname(OUT_REPORT), exist_ok=True)
    with open(OUT_REPORT, "w", encoding="utf-8") as fp:
        fp.write(report.getvalue())
    print(OUT_JSON)
    print(OUT_REPORT)


if __name__ == "__main__":
    main()
