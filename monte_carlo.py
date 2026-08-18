"""시행별 결과를 잃지 않는 몬테카를로 요약과 수렴 진단."""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Iterable, Mapping, Sequence


def quantile(values: Sequence[float], probability: float) -> float:
    """정렬 표본의 선형 보간 분위수(Hyndman-Fan type 7)."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * probability
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    weight = pos - lo
    return xs[lo] * (1.0 - weight) + xs[hi] * weight


def _t_critical(confidence: float, degrees_freedom: int) -> float:
    """양측 Student-t 임계값의 Cornish-Fisher 근사.

    SciPy 의존성을 늘리지 않으면서 작은 표본에서 1.96 고정보다 보수적으로 만든다.
    몬테카를로 본실험의 권장 n>=30에서는 충분히 정확하다.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if degrees_freedom < 1:
        return float("inf")
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    v = float(degrees_freedom)
    z2, z3, z5, z7 = z * z, z ** 3, z ** 5, z ** 7
    return (z + (z3 + z) / (4.0 * v)
            + (5.0 * z5 + 16.0 * z3 + 3.0 * z) / (96.0 * v * v)
            + (3.0 * z7 + 19.0 * z5 + 17.0 * z3 - 15.0 * z)
            / (384.0 * v ** 3))


def summarize(values: Iterable[float], confidence: float = 0.95) -> dict:
    xs = [float(x) for x in values]
    n = len(xs)
    if not n:
        raise ValueError("values must not be empty")
    mean = math.fsum(xs) / n
    variance = (math.fsum((x - mean) ** 2 for x in xs) / (n - 1)
                if n > 1 else 0.0)
    sd = math.sqrt(max(0.0, variance))
    se = sd / math.sqrt(n)
    half = _t_critical(confidence, n - 1) * se if n > 1 else float("inf")
    relative = half / abs(mean) if mean else (0.0 if half == 0.0 else float("inf"))
    return {
        "n": n,
        "mean": mean,
        "stdev": sd,
        "standard_error": se,
        "confidence": confidence,
        "ci_low": mean - half,
        "ci_high": mean + half,
        "ci_half_width": half,
        "relative_half_width": relative,
        "min": min(xs),
        "p05": quantile(xs, 0.05),
        "p50": quantile(xs, 0.50),
        "p95": quantile(xs, 0.95),
        "max": max(xs),
    }


def summarize_rows(rows: Sequence[Mapping], metric_names: Sequence[str],
                   confidence: float = 0.95) -> dict:
    return {name: summarize([row[name] for row in rows], confidence)
            for name in metric_names}


def convergence_trace(values: Sequence[float], confidence: float = 0.95,
                      every: int = 10, minimum: int = 10) -> list:
    """사후 수렴표. 순차 중단 규칙으로 사용하지 않아 CI 과소포착을 피한다."""
    if every < 1 or minimum < 2:
        raise ValueError("every >= 1 and minimum >= 2 are required")
    out = []
    checkpoints = list(range(minimum, len(values) + 1, every))
    if len(values) >= 2 and (not checkpoints or checkpoints[-1] != len(values)):
        checkpoints.append(len(values))
    for n in checkpoints:
        row = summarize(values[:n], confidence)
        out.append({"n": n, "mean": row["mean"],
                    "ci_half_width": row["ci_half_width"],
                    "relative_half_width": row["relative_half_width"]})
    return out


def paired_differences(base_rows: Sequence[Mapping], alt_rows: Sequence[Mapping],
                       metric: str, confidence: float = 0.95) -> dict:
    """같은 replicate 번호끼리 결합한 CRN 대응차(대안-base) 요약."""
    base = {int(row["replicate"]): float(row[metric]) for row in base_rows}
    alt = {int(row["replicate"]): float(row[metric]) for row in alt_rows}
    ids = sorted(set(base) & set(alt))
    if not ids:
        raise ValueError("no matching replicate ids")
    result = summarize([alt[i] - base[i] for i in ids], confidence)
    result["replicate_ids"] = ids
    return result
