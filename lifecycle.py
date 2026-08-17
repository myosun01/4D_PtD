"""
lifecycle.py — 위험요소 생멸 엔진 (Phase 1, P1-4)
==================================================
지식(TTL의 LifecycleRuleTemplate 4종: 트리거·위치선택자·위험유형)과
프로젝트 사실(project/lifecycle_bindings.json: 어느 액티비티·어느 셀)을
조인하여 일자별 HazardInstance 집합 `hazards(d)`를 만든다 (ROADMAP §1-2, §3).

생멸 시점 의미론 (일 경계, §1-1):
  spawn 트리거 ".completed"            → 액티비티 완료 익일(= ef)에 spawn
  spawn 트리거 ".started"/".in_progress" → 액티비티 시작일(= es)에 spawn
  despawn 트리거 ".completed"          → 완료 익일(= ef)에 despawn
  → 활성 구간: spawn_day <= d < despawn_day  (despawnActivity 없으면 무한)

예: 타설 [10,11] 완료 → 개구부는 d=12에 spawn.
    마감 d=17 완료 → d=17까지 활성, d=18에 despawn.
    동바리(started 트리거)는 타설 시작일부터 해체 완료일까지 활성 (§2 collapse_zone).
"""
import json
import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from schedule import Schedule

# 트리거 원문 예: "activity[trade=concrete_pour, workType=slab].completed"
_TRIGGER_RE = re.compile(r"^activity\[(?P<filters>[^\]]*)\]\.(?P<state>\w+)$")
# 바인딩이 구체 액티비티를 지정하므로 zone=Z/SAME 등 변수 필터는 검사 대상에서 제외
_CHECKED_FILTERS = ("trade", "workType")


@dataclass(frozen=True)
class Trigger:
    filters: Dict[str, str]
    state: str                       # completed / started / in_progress

    def event_day(self, act) -> int:
        """트리거가 발화하는 작업일 인덱스 (일 경계 의미론)."""
        if self.state == "completed":
            return act.ef            # 완료 익일
        if self.state in ("started", "in_progress"):
            return act.es
        raise ValueError(f"알 수 없는 트리거 상태 '{self.state}'")

    def matches(self, act) -> bool:
        """바인딩된 액티비티가 템플릿의 trade/workType 필터에 부합하는지."""
        for k in _CHECKED_FILTERS:
            want = self.filters.get(k)
            if want is None:
                continue
            got = act.trade if k == "trade" else act.work_type
            if got != want:
                # [불가피한 최소 수정 — 사유] 실제 공정표(construction_schedule.csv)에는
                # '거푸집 해체(formwork_stripping)' 태스크가 없다. 슬래브 '양생' 태스크의
                # description이 "동바리 존치/탈형 대기"이므로, 동바리 존치 구간의 종료
                # (LCR_SHORING_COLLAPSE despawn = formwork_stripping.completed)를 '양생 완료'로
                # 간주한다. work_type=="curing"인 양생 태스크만 formwork_stripping 필터를
                # 만족시키며, 실제 formwork_stripping 태스크가 있는 합성 테스트는 첫 비교에서
                # 이미 매칭되어 이 분기에 도달하지 않는다(무영향). (convert_schedule_csv.py 참조)
                if k == "trade" and want == "formwork_stripping" \
                        and getattr(act, "work_type", "") == "curing":
                    continue
                return False
        return True


def parse_trigger(text: str) -> Trigger:
    m = _TRIGGER_RE.match(text.strip())
    if not m:
        raise ValueError(f"트리거 파싱 실패: {text!r}")
    filters = {}
    for part in m.group("filters").split(","):
        part = part.strip()
        if part:
            k, _, v = part.partition("=")
            filters[k.strip()] = v.strip()
    return Trigger(filters=filters, state=m.group("state"))


@dataclass(frozen=True)
class HazardInstance:
    instance_id: str
    hazard_type: str                 # "H001" 등
    template_id: str
    level: str                       # "L2" 등
    cells: Tuple[Tuple[int, int], ...]
    spawn_day: int
    despawn_day: float               # 배타적. despawnActivity 없으면 math.inf
    bound_activity: str
    despawn_activity: Optional[str]

    def active(self, d: int) -> bool:
        return self.spawn_day <= d < self.despawn_day


class LifecycleEngine:
    """템플릿(TTL) × 바인딩(JSON) 조인 → 일자별 위험 인스턴스."""

    def __init__(self, templates: Dict[str, object], bindings_path: str,
                 schedule: Schedule):
        self.templates = templates
        self.schedule = schedule
        with open(bindings_path, encoding="utf-8") as fp:
            self.bindings = json.load(fp)["bindings"]
        self.instances: List[HazardInstance] = self._build()

    def _below_level(self, level: str, binding: Optional[Dict] = None) -> Optional[str]:
        """직하부 층 ID.

        [v2.6 후방호환 확장] 바인딩에 명시적 `lowerLevel`이 있으면 그것을 쓰고,
        없으면 기존 `L(n-1)` 산술로 폴백한다. 기존 동작은 그대로이며 선택지만
        추가된다.

        사유: 이 건물은 층이 수직으로 포개지지 않는 구간이 있어(서측 주차데크)
        표고 순서상의 인접층이 기하학적 직하부와 다르다. 예컨대 Level_02(L4)의
        실제 직하부는 L3(주차데크)이 아니라 L2(Level_01 본체)다. 파생기가
        슬래브 풋프린트 교집합으로 판정한 직하부를 그대로 전달받기 위한 것이다.
        """
        if binding:
            explicit = binding.get("lowerLevel")
            if explicit:
                return explicit
        n = int(level.lstrip("L"))
        return f"L{n-1}" if n >= 2 else None

    def _build(self) -> List[HazardInstance]:
        out = []
        for i, b in enumerate(self.bindings):
            tid = b["template"]
            if tid not in self.templates:
                raise ValueError(f"바인딩 {i}: 미정의 템플릿 '{tid}' (TTL LifecycleRuleTemplate 4종만 허용)")
            tpl = self.templates[tid]
            spawn_tr = parse_trigger(tpl.spawn_trigger)
            despawn_tr = parse_trigger(tpl.despawn_trigger)

            act = self.schedule.activities.get(b["boundActivity"])
            if act is None:
                raise ValueError(f"바인딩 {i}: boundActivity '{b['boundActivity']}' 미정의")
            if not spawn_tr.matches(act):
                raise ValueError(
                    f"바인딩 {i}: {act.activity_id}(trade={act.trade}, workType={act.work_type})가 "
                    f"{tid} spawn 필터 {spawn_tr.filters}에 부합하지 않음")

            despawn_id = b.get("despawnActivity")
            despawn_day: float = math.inf
            if despawn_id is not None:
                dact = self.schedule.activities.get(despawn_id)
                if dact is None:
                    raise ValueError(f"바인딩 {i}: despawnActivity '{despawn_id}' 미정의")
                if not despawn_tr.matches(dact):
                    raise ValueError(
                        f"바인딩 {i}: {despawn_id}(trade={dact.trade}, workType={dact.work_type})가 "
                        f"{tid} despawn 필터 {despawn_tr.filters}에 부합하지 않음")
                despawn_day = despawn_tr.event_day(dact)

            # 위치선택자 정합성: zone.below면 직하부 층, 그 외는 액티비티와 동일 층
            level = b["spawnLocation"]["level"]
            expected = (self._below_level(act.level, b)
                        if tpl.location_selector == "zone.below" else act.level)
            if expected is None:
                raise ValueError(f"바인딩 {i}: {act.activity_id}는 최하층 — zone.below 불가")
            if level != expected:
                raise ValueError(
                    f"바인딩 {i}: spawnLocation.level={level} ≠ 기대 {expected} "
                    f"(locationSelector={tpl.location_selector})")

            out.append(HazardInstance(
                instance_id=f"HZ-{i:03d}-{tid}-{act.activity_id}",
                hazard_type=tpl.hazard_type,
                template_id=tid,
                level=level,
                cells=tuple((int(r), int(c)) for r, c in b["spawnLocation"]["cells"]),
                spawn_day=spawn_tr.event_day(act),
                despawn_day=despawn_day,
                bound_activity=act.activity_id,
                despawn_activity=despawn_id,
            ))
        return out

    def hazards(self, d: int) -> List[HazardInstance]:
        """d일에 활성인 위험 인스턴스 목록 (ROADMAP P1-4 API)."""
        return [h for h in self.instances if h.active(d)]

    def timeline(self, days: Optional[int] = None) -> List[Dict]:
        """일자별 {day, hazard 수, 유형별 수} 요약 — 검증·리포트용."""
        n = days if days is not None else self.schedule.duration
        rows = []
        for d in range(n):
            hs = self.hazards(d)
            by_type: Dict[str, int] = {}
            for h in hs:
                by_type[h.hazard_type] = by_type.get(h.hazard_type, 0) + 1
            rows.append({"day": d, "n_hazards": len(hs), "by_type": by_type})
        return rows


def load_lifecycle(bindings_path: str, schedule: Schedule,
                   library=None) -> LifecycleEngine:
    """편의 로더 — library 생략 시 ptd_ttl.LIBRARY 사용 (rdflib 필요)."""
    if library is None:
        import ptd_ttl
        library = ptd_ttl.LIBRARY
    if library is None:
        raise RuntimeError("TTL 라이브러리 로드 실패 (rdflib/ptd_library.ttl 필요)")
    return LifecycleEngine(library.lifecycle_templates, bindings_path, schedule)
