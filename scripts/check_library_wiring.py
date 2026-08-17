# -*- coding: utf-8 -*-
"""Part A 검증 — TTL 의 값이 controls.py 까지 실제로 도달하는지 점검한다.

배경: 라이브러리를 v2.3 → v2.4 로 재설계하면서 TTL 생성기가 내보내는 프로퍼티명과
로더가 읽는 프로퍼티명이 어긋나, controls.resolve_all() 이 전면 실패하고
AgentParameterRule 계수가 전부 None 이 되어 있었다. 이 스크립트는 그 복구가
실제로 되었는지를 '값이 도달했는가'로만 판정한다.

여기서는 아무 값도 만들어내지 않는다. TTL 에 없는 것은 없는 대로 보고한다.

실행: python scripts/check_library_wiring.py
산출: build/library_wiring_report.md (종료코드 0=수용 기준 충족)
"""
import io
import os
import sys
from collections import Counter

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import config as C
import ptd_ttl
import controls
from controls import (CELLTYPE_TO_HAZARD, ControlApplication, resolve_all,
                      parse_schedule_shift)
from lifecycle import LifecycleEngine
from schedule import Schedule

SCHEDULE = "project/schedule.json"
BINDINGS = "build/lifecycle_bindings_v2.json"     # 84건 현행 (project/ 는 21건 낡음)
OUT = "build/library_wiring_report.md"

# Part A 수용 기준 — 이 값들이 도달하지 않으면 종료코드 1.
ACCEPT = [
    ("ALT_H001_05 fallProbMultiplier", 0.10),
]


def fmt(v):
    return "—" if v is None else ("%g" % v if isinstance(v, float) else str(v))


def main():
    out = io.StringIO()
    w = out.write
    ok = True

    w("# 라이브러리 → 코드 도달 점검 (Part A)\n\n")
    w("생성: `python scripts/check_library_wiring.py`  ·  "
      "라이브러리: `%s`\n\n" % C.TTL_PATH.replace(os.getcwd() + os.sep, ""))

    # ── 1. 로드 ──────────────────────────────────────────────
    lib = ptd_ttl.LIBRARY
    w("## 1. TTL 로드\n\n")
    if lib is None:
        w("**실패** — %s\n" % (ptd_ttl.LOAD_ERROR or "사유 불명"))
        with io.open(OUT, "w", encoding="utf-8") as fp:
            fp.write(out.getvalue())
        print("TTL 로드 실패:", ptd_ttl.LOAD_ERROR)
        return 1

    w("| 항목 | 수 |\n|---|---|\n")
    w("| ExecutableAlternative | %d |\n" % len(lib.alternatives))
    w("| SpatialChangeRule | %d |\n" % len(lib.spatial_rules))
    w("| AgentParameterRule | %d |\n" % len(lib.agent_rules))
    w("| TemporalRule | %d |\n" % len(lib.temporal_rules))
    w("| LifecycleRuleTemplate | %d |\n" % len(lib.lifecycle_templates))
    w("\n")
    if ptd_ttl.PARAM_WARNINGS:
        w("`parameterValue` 파싱 경고 %d건:\n\n" % len(ptd_ttl.PARAM_WARNINGS))
        for rid, raw, why in ptd_ttl.PARAM_WARNINGS:
            w("- `%s` — `%s` : %s\n" % (rid, raw, why))
        w("\n")
    else:
        w("`parameterValue` 파싱 경고: 0건\n\n")

    # ── 2. resolve_all ──────────────────────────────────────
    sch = Schedule.load(SCHEDULE)
    life = LifecycleEngine(lib.lifecycle_templates, BINDINGS, sch)
    by_haz = {}
    for h in life.instances:
        by_haz.setdefault(h.hazard_type, h)          # 유형별 대표 인스턴스 1개

    w("## 2. `resolve_all()` 통과 여부\n\n")
    w("대안마다 그 위험유형의 실제 인스턴스 1건을 붙여 해석을 시도한다 "
      "(바인딩 %d건, 위험유형 %d종).\n\n" % (len(life.instances), len(by_haz)))

    passed, failed = [], []
    effects = {}
    for aid in sorted(lib.alternatives):
        rule = lib.rule_of(aid)
        if rule is None:
            failed.append((aid, "-", "연결된 규칙 없음"))
            continue
        if isinstance(rule, ptd_ttl.TemporalRule):
            continue                                  # 별도 경로(§4)에서 점검
        ct = getattr(rule, "applies_to_cell_type", "")
        haz = CELLTYPE_TO_HAZARD.get(ct)
        if not ct:
            failed.append((aid, rule.rule_id, "appliesToCellType 없음 (v2.3 정본에도 부재)"))
            continue
        if haz is None:
            failed.append((aid, rule.rule_id,
                           "appliesToCellType='%s' → 매핑되는 위험유형 없음" % ct))
            continue
        inst = by_haz.get(haz)
        if inst is None:
            failed.append((aid, rule.rule_id,
                           "위험유형 %s 인스턴스가 이 프로젝트에 없음" % haz))
            continue
        try:
            eff = resolve_all(lib, [ControlApplication(aid, inst.instance_id)],
                              sch, life)
            e = eff[inst.instance_id]
            effects[aid] = e
            passed.append((aid, rule.rule_id, ct, haz, e.kind, e.channel_mult))
        except Exception as exc:
            failed.append((aid, rule.rule_id, "%s: %s" % (type(exc).__name__, exc)))

    w("**통과 %d / 실패 %d**\n\n" % (len(passed), len(failed)))
    w("| 대안 | 규칙 | cellType | 위험 | kind | 채널배율 |\n|---|---|---|---|---|---|\n")
    for aid, rid, ct, haz, kind, cm in passed:
        cm_s = ", ".join("%s=%g" % (k, v) for k, v in sorted(cm.items())) or "—"
        w("| `%s` | `%s` | %s | %s | %s | %s |\n" % (aid, rid, ct, haz, kind, cm_s))
    w("\n")

    # ── 3. AgentParameterRule 계수 ──────────────────────────
    w("## 3. AgentParameterRule 계수 도달\n\n")
    w("| 규칙 | cellType | 읽힌 계수 | 출처 |\n|---|---|---|---|\n")
    n_nocoef = []
    for rid in sorted(lib.agent_rules):
        r = lib.agent_rules[rid]
        m = r.multipliers()
        if not m:
            n_nocoef.append(rid)
        w("| `%s` | %s | %s | %s |\n"
          % (rid, r.applies_to_cell_type or "—",
             ", ".join("%s=%g" % (k, v) for k, v in sorted(m.items())) or "**계수 미확보**",
             r.parameter_source_type or "—"))
    w("\n계수 미확보 %d건: %s\n\n"
      % (len(n_nocoef), ", ".join("`%s`" % x for x in n_nocoef) or "없음"))
    w("계수 미확보는 TTL 원천에 값이 없다는 뜻이며 0 이나 1.0 으로 채우지 않았다. "
      "해당 대안은 적용해도 효과가 없다.\n\n")

    # 수용 기준 — ALT_H001_05
    guard = lib.rule_of("ALT_H001_05")
    got = getattr(guard, "fall_prob_multiplier", None)
    w("**수용 기준** `ALT_H001_05` → `%s` fallProbMultiplier = **%s** (기대 0.1) — %s\n\n"
      % (guard.rule_id if guard else "—", fmt(got),
         "OK" if got == 0.10 else "FAIL"))
    if got != 0.10:
        ok = False

    # ── 4. TemporalRule ────────────────────────────────────
    w("## 4. TemporalRule 파싱\n\n")
    w("| 규칙 | 원문 | 파싱 결과 |\n|---|---|---|\n")
    n_parsed = 0
    unsupported = []
    for rid in sorted(lib.temporal_rules):
        r = lib.temporal_rules[rid]
        instr = parse_schedule_shift(r.schedule_shift) if r.schedule_shift else \
            {"kind": "empty"}
        if instr["kind"] not in ("unsupported", "empty"):
            n_parsed += 1
            res = "`%s` %s" % (instr["kind"],
                              {k: v for k, v in instr.items() if k != "kind"} or "")
        else:
            unsupported.append(rid)
            res = "**미인식**"
        w("| `%s` | %s | %s |\n" % (rid, r.schedule_shift or "*(없음)*", res))
    w("\n파싱 성공 %d / 미인식 %d\n\n" % (n_parsed, len(unsupported)))
    if n_parsed < 1:
        ok = False

    # ── 5. 도달하지 못하는 대안 ─────────────────────────────
    w("## 5. 여전히 코드에 도달하지 못하는 대안\n\n")
    if failed:
        w("| 대안 | 규칙 | 사유 |\n|---|---|---|\n")
        for aid, rid, why in failed:
            w("| `%s` | `%s` | %s |\n" % (aid, rid, why))
    else:
        w("없음.\n")
    w("\n")
    reasons = Counter(why.split("(")[0].split(":")[0].strip() for _, _, why in failed)
    if reasons:
        w("사유별 집계:\n\n")
        for why, n in reasons.most_common():
            w("- %s — %d건\n" % (why, n))
        w("\n")

    w("미인식 TemporalRule %d건 (`%s`) 은 `controls.parse_schedule_shift` 가 아는 "
      "세 패턴(set FS_lag / min curing lag enforced / FS-before) 중 어느 것도 아니다. "
      "의미를 추측해 매핑하지 않았다.\n"
      % (len(unsupported), "`, `".join(unsupported) if unsupported else "-"))

    with io.open(OUT, "w", encoding="utf-8") as fp:
        fp.write(out.getvalue())

    print("저장: %s" % OUT)
    print("  EA %d / resolve_all 통과 %d 실패 %d / TemporalRule 파싱 %d"
          % (len(lib.alternatives), len(passed), len(failed), n_parsed))
    print("  ALT_H001_05 fallProbMultiplier = %s" % fmt(got))
    print("  판정: %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
