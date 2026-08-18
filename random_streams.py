"""플랫폼과 프로세스 수에 무관한 난수 스트림 파생 유틸리티.

Python의 내장 ``hash``는 프로세스마다 달라질 수 있으므로 몬테카를로 시행 번호,
작업자 ID, 경로 구간으로부터 직접 시드를 만들 때 사용하지 않는다. 이 모듈은
SHA-256 기반의 작은 순수 함수만 제공한다. 같은 입력은 Windows/Linux와 직렬/병렬
실행에서 같은 값을 만든다.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any


def _normalise(value: Any):
    """JSON으로 안정적으로 직렬화할 수 있는 표준 표현으로 바꾼다."""
    if is_dataclass(value):
        value = asdict(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"__float__": repr(value)}
        return value
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, dict):
        return {str(k): _normalise(value[k])
                for k in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_normalise(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return {"__type__": type(value).__qualname__, "__repr__": repr(value)}


def stable_bytes(base: Any, *parts: Any) -> bytes:
    payload = _normalise((base,) + parts)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def stable_seed(base: Any, *parts: Any) -> int:
    """``random.Random``에 넣을 128-bit 정수 시드를 안정적으로 만든다."""
    return int.from_bytes(hashlib.sha256(stable_bytes(base, *parts)).digest()[:16],
                          "big")


def stable_uniform(base: Any, *parts: Any) -> float:
    """[0, 1) 균등값. 호출 순서가 아니라 키에 결합된 공통난수(CRN)다."""
    raw = hashlib.sha256(stable_bytes(base, *parts)).digest()
    # IEEE-754 double이 정확히 표현할 수 있는 53 bit를 사용한다.
    return (int.from_bytes(raw[:8], "big") >> 11) / float(1 << 53)


def stable_index(size: int, base: Any, *parts: Any) -> int:
    if size <= 0:
        raise ValueError("size must be positive")
    return stable_seed(base, *parts) % int(size)
