"""
schedule.py — project/schedule.json 파서 + CPM 전진계산 (Phase 1, P1-3)
=======================================================================
시간축의 단일 원천 (ROADMAP §1-3). 시작·종료일은 입력하지 않으며(§3)
CPM 전진계산(FS/SS/FF + lag)으로 산출한다.

시간 좌표: 작업일 인덱스 d = 0, 1, 2, … (일 해상도, §1-1).
액티비티는 [es, ef-1] 구간의 날에 in_progress, d >= ef 에 completed.
달력(calendar)은 작업일 인덱스 ↔ 실제 날짜 매핑에만 쓰인다
(workdays 패턴·holidays 건너뜀). startDate가 없으면 매핑은 제공하지 않는다.

API (ROADMAP P1-3):
    sch = Schedule.load("project/schedule.json")
    sch.activeSet(d)     -> set[activityID]   (그날 in_progress)
    sch.crewsOnSite(d)   -> {trade: 총 crewSize}
"""
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Set

TRADES = ("rebar", "formwork_erection", "concrete_pour",
          "formwork_stripping", "material_handling")
RELATIONS = ("FS", "SS", "FF")

_WEEKDAY = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


@dataclass
class Predecessor:
    activity: str
    relation: str = "FS"
    lag_days: int = 0


@dataclass
class Activity:
    activity_id: str
    name: str
    trade: str
    zone: str                       # "L3:Z-A"
    duration_days: int
    predecessors: List[Predecessor]
    crew_size: int
    daily_pattern: dict
    work_type: str
    es: Optional[int] = None        # earliest start (작업일 인덱스)
    ef: Optional[int] = None        # earliest finish (배타적: 마지막 작업일 + 1)

    @property
    def level(self) -> str:
        return self.zone.split(":")[0]

    @property
    def zone_id(self) -> str:
        return self.zone.split(":", 1)[1] if ":" in self.zone else self.zone

    def state(self, d: int) -> str:
        """일 경계 상태 전이 (§1-1): not_started / in_progress / completed."""
        if self.es is None:
            raise RuntimeError("forward_pass 전에는 상태를 판정할 수 없음")
        if d < self.es:
            return "not_started"
        if d < self.ef:
            return "in_progress"
        return "completed"


class Calendar:
    """workdays 패턴("MON-SAT" 등) + holidays. startDate가 있으면 날짜 매핑 제공."""

    def __init__(self, spec: dict):
        self.spec = spec or {}
        wd = str(self.spec.get("workdays", "MON-SAT")).upper()
        if "-" in wd:
            a, b = wd.split("-", 1)
            i, j = _WEEKDAY[a.strip()], _WEEKDAY[b.strip()]
            self.workdays = {k % 7 for k in range(i, i + (j - i) % 7 + 1)}
        else:
            self.workdays = {_WEEKDAY[t.strip()] for t in wd.split(",")}
        self.holidays = {date.fromisoformat(h) for h in self.spec.get("holidays", [])}
        sd = self.spec.get("startDate")
        self.start_date = date.fromisoformat(sd) if sd else None

    def is_workday(self, dt: date) -> bool:
        return dt.weekday() in self.workdays and dt not in self.holidays

    def to_date(self, d: int) -> Optional[date]:
        """작업일 인덱스 → 실제 날짜 (startDate 없으면 None)."""
        if self.start_date is None:
            return None
        dt, remaining = self.start_date, d
        while not self.is_workday(dt):
            dt += timedelta(days=1)
        while remaining > 0:
            dt += timedelta(days=1)
            if self.is_workday(dt):
                remaining -= 1
        return dt


class Schedule:
    def __init__(self, schedule_id: str, calendar: Calendar,
                 activities: List[Activity]):
        self.schedule_id = schedule_id
        self.calendar = calendar
        self.activities: Dict[str, Activity] = {a.activity_id: a for a in activities}
        if len(self.activities) != len(activities):
            raise ValueError("activityID 중복")
        self._validate()
        self.forward_pass()

    # ── 로딩 ──
    @classmethod
    def load(cls, path: str) -> "Schedule":
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
        acts = [Activity(
            activity_id=a["activityID"], name=a.get("name", a["activityID"]),
            trade=a["trade"], zone=a["zone"],
            duration_days=int(a["duration_days"]),
            predecessors=[Predecessor(p["activity"], p.get("relation", "FS"),
                                      int(p.get("lag_days", 0)))
                          for p in a.get("predecessors", [])],
            crew_size=int(a.get("crewSize", 0)),
            daily_pattern=a.get("dailyPattern", {}),
            work_type=a.get("workType", ""),
        ) for a in raw["activities"]]
        return cls(raw.get("scheduleID", ""), Calendar(raw.get("calendar", {})), acts)

    def _validate(self):
        for a in self.activities.values():
            if a.trade not in TRADES:
                raise ValueError(f"{a.activity_id}: 허용되지 않은 trade '{a.trade}' (§2 어휘 계약)")
            if a.duration_days < 1:
                raise ValueError(f"{a.activity_id}: duration_days >= 1 필요")
            for p in a.predecessors:
                if p.relation not in RELATIONS:
                    raise ValueError(f"{a.activity_id}: relation '{p.relation}' (FS/SS/FF만 허용)")
                if p.activity not in self.activities:
                    raise ValueError(f"{a.activity_id}: 선행 '{p.activity}' 미정의")

    # ── CPM 전진계산 ──
    def forward_pass(self):
        """FS/SS/FF + lag 전진계산 (작업일 단위, Kahn 위상정렬. 순환 시 오류)."""
        indeg = {aid: len(a.predecessors) for aid, a in self.activities.items()}
        succs: Dict[str, List[str]] = {aid: [] for aid in self.activities}
        for aid, a in self.activities.items():
            for p in a.predecessors:
                succs[p.activity].append(aid)

        queue = sorted(aid for aid, n in indeg.items() if n == 0)
        order = []
        while queue:
            aid = queue.pop(0)
            order.append(aid)
            for s in sorted(succs[aid]):
                indeg[s] -= 1
                if indeg[s] == 0:
                    queue.append(s)
        if len(order) != len(self.activities):
            cyc = sorted(aid for aid, n in indeg.items() if n > 0)
            raise ValueError(f"선후행 순환 감지: {cyc}")

        for aid in order:
            a = self.activities[aid]
            es = 0
            for p in a.predecessors:
                pred = self.activities[p.activity]
                if p.relation == "FS":
                    cand = pred.ef + p.lag_days
                elif p.relation == "SS":
                    cand = pred.es + p.lag_days
                else:  # FF: succ.ef >= pred.ef + lag
                    cand = pred.ef + p.lag_days - a.duration_days
                es = max(es, cand)
            a.es = max(es, 0)
            a.ef = a.es + a.duration_days

    # ── 조회 API (ROADMAP P1-3 이름 고정) ──
    @property
    def duration(self) -> int:
        """프로젝트 총 작업일수 (= max EF)."""
        return max(a.ef for a in self.activities.values())

    def activeSet(self, d: int) -> Set[str]:
        """d일에 in_progress인 activityID 집합."""
        return {aid for aid, a in self.activities.items()
                if a.state(d) == "in_progress"}

    def crewsOnSite(self, d: int) -> Dict[str, int]:
        """d일의 공종별 투입 인원 합 (활성 액티비티의 crewSize 합산)."""
        out: Dict[str, int] = {}
        for aid in self.activeSet(d):
            a = self.activities[aid]
            out[a.trade] = out.get(a.trade, 0) + a.crew_size
        return out

    # snake_case 별칭
    active_set = activeSet
    crews_on_site = crewsOnSite

    def critical_path(self) -> List[str]:
        """전진계산 기반 최장 경로 (ES를 결정한 선행자를 역추적, 동률 시 ID 순)."""
        def driver(a: Activity) -> Optional[str]:
            choice = None
            for p in a.predecessors:
                pred = self.activities[p.activity]
                if p.relation == "FS":
                    cand = pred.ef + p.lag_days
                elif p.relation == "SS":
                    cand = pred.es + p.lag_days
                else:  # FF
                    cand = pred.ef + p.lag_days - a.duration_days
                if cand == a.es and (choice is None or p.activity < choice):
                    choice = p.activity
            return choice

        end = max(sorted(self.activities), key=lambda k: self.activities[k].ef)
        path, cur = [], end
        while cur is not None:
            path.append(cur)
            cur = driver(self.activities[cur])
        return list(reversed(path))


def load_schedule(path: str) -> Schedule:
    return Schedule.load(path)
