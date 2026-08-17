# -*- coding: utf-8 -*-
"""Phase 2. project/schedule.json 을 보강 공정표 기준으로 동기화.

`project/schedule.json` 은 Part 1 이전 상태(원본 178건)라 신설 해체 작업
T-9001~T-9008 이 없다. 그 결과 hazard_zones 바인딩이 despawnActivity 로 이를
참조하면 LifecycleEngine 이 ValueError 를 낸다.

## 원본 변환기를 수정하지 않는다

`convert_schedule_csv.py` 의 `_NAME_RULES` 는 '거푸집' 을 '해체' 보다 먼저
매칭하므로, 신설 작업명 "슬래브 거푸집·동바리 해체" 가 `formwork_erection` 으로
분류된다. 원본 파일을 고치는 대신 여기서 규칙을 앞에 끼워 넣어
`formwork_stripping` 으로 잡는다.

`convert_schedule_csv.main()` 은 `project/lifecycle_bindings.json` 까지
재생성(합성)하지만, 우리는 `build/lifecycle_bindings_v2.json`(temp_works 파생)을
쓰므로 `convert()` 만 호출해 schedule.json 만 갱신한다.
"""
import io
import json
import os
import pathlib
import sys
from collections import Counter

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import convert_schedule_csv as CS

SRC_CSV = "build/construction_schedule_v2.csv"
OUT_JSON = "project/schedule.json"
BINDINGS = "build/lifecycle_bindings_v2.json"
BACKUP = "build/schedule_json_before_sync.json"

# '거푸집' 보다 먼저 평가되어야 한다 (해체 작업명에 '거푸집' 이 들어 있음).
STRIP_RULE = ("해체", ("formwork_stripping", "stripping"))

# v2.6 자재 반입·소진. LCR_MATERIAL_STORAGE 트리거가 요구하는 workType
# (delivery / consume_or_remove) 을 부여한다. 작업명에 '거푸집'·'철근'·'콘크리트'
# 가 들어 있으므로 그 규칙들보다 **앞에** 놓여야 한다.
MATERIAL_RULES = [
    ("소진", ("material_handling", "consume_or_remove")),
    ("반입", ("material_handling", "delivery")),
]


def main():
    if not os.path.exists(SRC_CSV):
        raise SystemExit("[중단] %s 없음. scripts/augment_schedule.py 를 먼저 "
                         "실행하세요." % SRC_CSV)
    if not os.path.isdir("build"):
        os.makedirs("build")

    # 원본 파일은 건드리지 않고 런타임 규칙만 앞에 끼운다.
    if STRIP_RULE not in CS._NAME_RULES:
        CS._NAME_RULES.insert(0, STRIP_RULE)
    for rule in reversed(MATERIAL_RULES):
        if rule not in CS._NAME_RULES:
            CS._NAME_RULES.insert(0, rule)
    CS.CREW_DEFAULT.setdefault("formwork_stripping", 6)
    CS.CREW_DEFAULT.setdefault("material_handling", 4)

    # work_type_of() 는 base_wt 를 ifc_class 기준으로 다시 매핑한다.
    # delivery / consume_or_remove 는 그대로 통과시켜야 한다.
    _orig_wt = CS.work_type_of

    def _wt(base_wt, ifc_class):
        if base_wt in ("delivery", "consume_or_remove"):
            return base_wt
        return _orig_wt(base_wt, ifc_class)
    CS.work_type_of = _wt

    # convert_schedule_csv._pred_id 는 단일 선행만 파싱한다("2,9105" 에서 ValueError).
    # 자재 반입은 소비 공정에 **추가** 선행으로 붙으므로 다중 선행이 생긴다.
    # 원본을 고치지 않고, 여기서 첫 선행만 통과시킨 뒤 변환 후 전체 목록으로
    # 복원한다.
    def _pred_first(raw):
        raw = (raw or "").strip()
        if not raw:
            return None
        return "T-%d" % int(float(raw.split(",")[0]))
    CS._pred_id = _pred_first

    print("공정표 동기화")
    print("  원천 : %s" % SRC_CSV)
    print("  대상 : %s" % OUT_JSON)

    before = None
    if os.path.exists(OUT_JSON):
        with io.open(OUT_JSON, encoding="utf-8") as f:
            before = json.load(f)
        with io.open(BACKUP, "w", encoding="utf-8") as f:
            json.dump(before, f, ensure_ascii=False, indent=1)
        print("  백업 : %s (동기화 전 %d 액티비티)"
              % (BACKUP, len(before["activities"])))

    sched = CS.convert(SRC_CSV)
    acts = sched["activities"]

    # 다중 선행 복원 (위 _pred_first 로 잘려 나간 나머지)
    import csv as _csv
    by_act = {a["activityID"]: a for a in acts}
    n_multi = 0
    with io.open(SRC_CSV, encoding="utf-8-sig", newline="") as f:
        for r in _csv.DictReader(f):
            ids = [p.strip() for p in (r["predecessors"] or "").split(",")
                   if p.strip()]
            if len(ids) <= 1:
                continue
            a = by_act.get("T-%s" % r["task_id"])
            if a is None:
                continue
            a["predecessors"] = [
                {"activity": "T-%d" % int(float(p)), "relation": "FS",
                 "lag_days": 0} for p in ids]
            n_multi += 1
    if n_multi:
        print("  다중 선행 복원 : %d건" % n_multi)
    pathlib.Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with io.open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(sched, f, ensure_ascii=False, indent=1)

    trades = Counter(a["trade"] for a in acts)
    wts = Counter(a["workType"] for a in acts)
    print("  액티비티 : %d → %d"
          % (len(before["activities"]) if before else 0, len(acts)))
    print("  trade    : %s" % dict(trades))
    print("  workType : %s" % dict(wts))

    strip = [a for a in acts if a["trade"] == "formwork_stripping"]
    print("  해체 작업 : %d건 — %s"
          % (len(strip), ", ".join(a["activityID"] for a in strip)))

    # ── 검증: 바인딩이 참조하는 액티비티가 전부 실재하는가
    ids = set(a["activityID"] for a in acts)
    if not os.path.exists(BINDINGS):
        print("  [warn] %s 없음 — 바인딩 검증 생략" % BINDINGS)
        return 0
    with io.open(BINDINGS, encoding="utf-8") as f:
        binds = json.load(f)["bindings"]
    missing = []
    for b in binds:
        for key in ("boundActivity", "despawnActivity"):
            v = b.get(key)
            if v and v not in ids:
                missing.append((b.get("_zone_id"), key, v))
    print("")
    print("  바인딩 검증 : %d건" % len(binds))
    print("    미정의 참조 : %d건 %s"
          % (len(missing), "OK" if not missing else missing[:6]))

    # 참조 무결성 외에 lifecycle 의 레벨 정합도 미리 본다
    lv_bad = []
    by_id = {a["activityID"]: a for a in acts}
    for b in binds:
        act = by_id.get(b["boundActivity"])
        if act is None:
            continue
        act_level = act["zone"].split(":")[0]
        want = b["spawnLocation"]["level"]
        tpl = b["template"]
        if tpl in ("LCR_SHORING_COLLAPSE", "LCR_DROP_ZONE"):
            # v2.6: 바인딩에 명시적 lowerLevel 이 있으면 그것이 기대값이다
            # (lifecycle._below_level 의 후방호환 확장과 같은 규칙).
            expect = b.get("lowerLevel")
            if not expect:
                n = int(act_level.lstrip("L"))
                expect = "L%d" % (n - 1) if n >= 2 else None
        else:
            expect = act_level
        if expect != want:
            lv_bad.append((b.get("_zone_id"), tpl, act_level, want, expect))
    print("    레벨 정합 위반 : %d건" % len(lv_bad))
    for x in lv_bad[:8]:
        print("      %-18s %-22s act=%s spawn=%s 기대=%s" % x)
    if lv_bad:
        print("      → lifecycle.LifecycleEngine 은 locationSelector=zone.below 일 때")
        print("        spawnLocation.level == L(act-1) 을 요구한다. 위 항목은")
        print("        기하 직하부가 표고 인접층과 달라 생긴 불일치다.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
