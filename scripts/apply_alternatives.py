# -*- coding: utf-8 -*-
"""v4.0 Phase 0-1 — variant 생성기.

`build/alternative_classification.csv` 의 **class=S 10건만** variant 로 만든다.
규칙을 새로 쓰거나 계수를 지어내지 않는다.

## 규칙 유형별 적용 기구 (mechanism)

  SpatialChangeRule / remove   → **zone 제거**. 대상 위험유형의 zone·binding 을
                                 실제로 걷어낸 파일을 만든다.
  SpatialChangeRule / block    → **controls 효과**. 격자를 WALL 로 막는 것이라
                                 zone 파일로 표현되지 않는다. 런타임에 적용한다.
  TemporalRule                 → **공정표 변경**. controls.apply_temporal_shift 로
                                 스케줄을 바꿔 저장한다. zone 의 spawn/despawn 은
                                 LifecycleEngine 이 그 스케줄에서 다시 계산한다.
  AgentParameterRule           → **controls 효과**. zone 은 그대로 두고 채널 배율을
                                 부여한다. `install_duration_days` 가 있으면
                                 `effective_day` 전까지 무방호 노출이 발생한다 —
                                 controls.py 가 이미 구현하고 있으므로 새로 만들지 않는다.

## 산출
  build/variants/<variant_id>/hazard_zones.json
  build/variants/<variant_id>/lifecycle_bindings_v2.json
  build/variants/<variant_id>/schedule.json
  build/variant_manifest.json
  build/apply_alternatives_log.md

실행: python scripts/apply_alternatives.py
"""
import collections
import copy
import csv
import io
import json
import os
import shutil
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import ptd_ttl
import controls as CT
from controls import (ControlApplication, resolve_all, parse_schedule_shift,
                      apply_temporal_shift, CELLTYPE_TO_HAZARD, CELLTYPE_TO_TS,
                      SpatialChangeRule, AgentParameterRule, TemporalRule)
from lifecycle import LifecycleEngine
from schedule import Schedule

CLASSIFICATION = "build/alternative_classification.csv"
BASE_ZONES = "build/hazard_zones.json"
BASE_BINDINGS = "build/lifecycle_bindings_v2.json"
BASE_SCHEDULE = "project/schedule.json"
OUT_DIR = "build/variants"
MANIFEST = "build/variant_manifest.json"
LOG = "build/apply_alternatives_log.md"

HOC_RANK_KO = {"위험회피": 1, "제거": 2, "대체": 3, "공학적": 4,
               "경고": 5, "관리적": 6, "보호구": 7}


def load_json(p):
    with open(p, encoding="utf-8") as fp:
        return json.load(fp)


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False)


def zone_signature(zdoc):
    """zone 집합의 동일성 판정용 서명 — id·셀수·생멸 트리거."""
    sig = []
    for z in zdoc["zones"]:
        sig.append((z["zone_id"], len(z.get("cells", [])),
                    (z.get("spawn") or {}).get("activity_id"),
                    (z.get("despawn") or {}).get("activity_id")))
    return tuple(sorted(sig))


def main():
    lib = ptd_ttl.require_library()
    rows = [r for r in csv.DictReader(open(CLASSIFICATION, encoding="utf-8-sig"))
            if r["class"] == "S"]
    print("[S] 대상 %d건" % len(rows))

    base_zones = load_json(BASE_ZONES)
    base_binds = load_json(BASE_BINDINGS)
    base_sched_raw = load_json(BASE_SCHEDULE)
    base_sched = Schedule.load(BASE_SCHEDULE)
    base_life = LifecycleEngine(lib.lifecycle_templates, BASE_BINDINGS, base_sched)
    base_sig = zone_signature(base_zones)
    base_n_cells = sum(len(z.get("cells", [])) for z in base_zones["zones"])

    # 위험유형별 인스턴스
    inst_by_haz = collections.defaultdict(list)
    for h in base_life.instances:
        inst_by_haz[h.hazard_type].append(h)
    zid_of = {}
    for b, inst in zip(base_binds["bindings"], base_life.instances):
        zid_of[inst.instance_id] = b.get("_zone_id")

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    variants = []
    skipped = []
    warnings = []

    # ── BASE 자체도 manifest 에 넣는다 (비교 기준) ──
    save_json(os.path.join(OUT_DIR, "BASE", "hazard_zones.json"), base_zones)
    save_json(os.path.join(OUT_DIR, "BASE", "lifecycle_bindings_v2.json"), base_binds)
    save_json(os.path.join(OUT_DIR, "BASE", "schedule.json"), base_sched_raw)
    base_active = 0
    for h in base_life.instances:
        dp = h.despawn_day if h.despawn_day != float("inf") else base_sched.duration
        base_active += max(0, int(min(dp, base_sched.duration)) - int(h.spawn_day))
    variants.append({
        "variant_id": "BASE", "alternative_id": None, "entry_id": None,
        "hoc_level": None, "hoc_rank": None, "accident_type": None,
        "rule_type": None, "mechanism": "none",
        "target_hazard_type": None, "target_instances": [],
        "dir": os.path.join(OUT_DIR, "BASE").replace("\\", "/"),
        "delta": {"zones": len(base_zones["zones"]), "zones_removed": 0,
                  "cells": base_n_cells, "cells_delta": 0,
                  "duration_days": base_sched.duration, "duration_delta": 0,
                  "instance_active_days_total": base_active},
    })

    for r in rows:
        aid = r["alternative_id"]
        eid = r["entry_id"]
        rule = lib.rule_of(aid) if aid in lib.alternatives else None
        if rule is None:
            skipped.append((aid, eid, "라이브러리에 규칙 없음"))
            continue

        vdir = os.path.join(OUT_DIR, aid)
        ct = getattr(rule, "applies_to_cell_type", "")
        haz = CELLTYPE_TO_HAZARD.get(ct)
        tsk = CELLTYPE_TO_TS.get(ct)
        targets = inst_by_haz.get(haz, [])

        rec = {"variant_id": aid, "alternative_id": aid, "entry_id": eid,
               "hoc_level": r["hoc_level"],
               "hoc_rank": HOC_RANK_KO.get(r["hoc_level"]),
               "accident_type": r["accident_type"],
               "rule_type": r["rule_type"], "rule_id": r["rule_id"],
               "applies_to_cell_type": ct,
               "target_hazard_type": haz,
               "target_instances": [h.instance_id for h in targets],
               "dir": vdir.replace("\\", "/")}

        zones = copy.deepcopy(base_zones)
        binds = copy.deepcopy(base_binds)
        sched_raw = copy.deepcopy(base_sched_raw)
        delta = {}

        # ── TemporalRule — 공정표 변경 ──
        if isinstance(rule, TemporalRule):
            instr = parse_schedule_shift(rule.schedule_shift or "")
            rec["mechanism"] = "schedule_shift"
            rec["schedule_instruction"] = instr
            if instr["kind"] == "unsupported":
                skipped.append((aid, eid, "scheduleShift 미인식 — variant 미생성"))
                continue
            if instr["kind"] == "retention_period":
                # 스케줄을 바꾸지 않는 지시다 (실행은 zone 생성 규칙).
                skipped.append((aid, eid,
                                "retention_period 는 zone 생성 규칙이 실행하며 "
                                "현행 BASE 가 이미 3개 층 존치(KCS)라 BASE 와 같아진다. "
                                "비교 기준을 BASE_current(1개 층)로 두는 Phase 3 소관."))
                continue
            sch2 = Schedule.load(BASE_SCHEDULE)
            changed = apply_temporal_shift(sch2, rule.schedule_shift or "")
            delta["schedule_activities_changed"] = changed
            delta["duration_days"] = sch2.duration
            delta["duration_delta"] = sch2.duration - base_sched.duration
            if changed == 0:
                # 지시가 가리키는 선후관계가 이 공정표에 존재하지 않는다.
                # 억지로 variant 를 만들지 않는다.
                skipped.append((aid, eid,
                                "apply_temporal_shift 가 0건을 바꿨다 — 지시 %r 이 "
                                "가리키는 선후관계가 이 공정표에 없다. "
                                "variant 미생성." % (rule.schedule_shift or "")[:70]))
                continue
            # 변경된 lag 를 원문 JSON 에 반영
            for a in sched_raw["activities"]:
                obj = sch2.activities.get(a["activityID"])
                if obj is None:
                    continue
                for p_raw, p_obj in zip(a.get("predecessors", []), obj.predecessors):
                    p_raw["lag_days"] = p_obj.lag_days
            rec["target_instances"] = []

        # ── SpatialChangeRule / remove — zone 제거 ──
        elif isinstance(rule, SpatialChangeRule) and (
                (rule.simulation_action or "").startswith("remove")
                or rule.risk_coefficient_multiplier == 0.0):
            if not targets:
                skipped.append((aid, eid, "대상 위험유형 %s 인스턴스 없음" % haz))
                continue
            rec["mechanism"] = "zone_removal"
            drop_zids = {zid_of[h.instance_id] for h in targets}
            keep_idx = [i for i, b in enumerate(base_binds["bindings"])
                        if b.get("_zone_id") not in drop_zids]
            binds["bindings"] = [base_binds["bindings"][i] for i in keep_idx]
            zones["zones"] = [z for z in base_zones["zones"]
                              if z["zone_id"] not in drop_zids]
            zones["meta"] = dict(zones.get("meta", {}))
            zones["meta"]["variant"] = aid
            zones["meta"]["removed_zones"] = sorted(drop_zids)
            delta["zones_removed"] = len(drop_zids)

        # ── 그 밖 (block / AgentParameterRule) — controls 효과 ──
        else:
            if not targets:
                skipped.append((aid, eid, "대상 위험유형 %s 인스턴스 없음" % haz))
                continue
            rec["mechanism"] = "controls_effect"
            ctrls = [ControlApplication(aid, h.instance_id) for h in targets]
            eff = resolve_all(lib, ctrls, base_sched, base_life)
            sample = list(eff.values())[0]
            rec["effect_kind"] = sample.kind
            rec["channel_mult"] = sample.channel_mult
            rec["severity_mult"] = sample.severity_mult
            rec["install_duration_days"] = int(
                lib.alternatives[aid].install_duration_days)
            rec["effective_days"] = sorted({e.effective_day for e in eff.values()})
            # 효과가 실질적인가
            trivial = (sample.kind == "scale"
                       and not sample.severity_mult
                       and all(abs(v - 1.0) < 1e-9
                               for v in (sample.channel_mult or {1: 1.0}).values()))
            if trivial:
                warnings.append((aid, "controls 효과가 배율 1.0 뿐 — BASE 와 구분되지 "
                                      "않는다. [X] 였어야 할 항목이다."))

        # 파일 저장
        save_json(os.path.join(vdir, "hazard_zones.json"), zones)
        save_json(os.path.join(vdir, "lifecycle_bindings_v2.json"), binds)
        save_json(os.path.join(vdir, "schedule.json"), sched_raw)

        delta.setdefault("zones", len(zones["zones"]))
        delta.setdefault("zones_removed", 0)
        delta["cells"] = sum(len(z.get("cells", [])) for z in zones["zones"])
        delta["cells_delta"] = delta["cells"] - base_n_cells
        delta.setdefault("duration_days", base_sched.duration)
        delta.setdefault("duration_delta", 0)

        # 존속기간 변화 (variant 의 스케줄로 다시 계산)
        try:
            s2 = Schedule.load(os.path.join(vdir, "schedule.json"))
            l2 = LifecycleEngine(lib.lifecycle_templates,
                                 os.path.join(vdir, "lifecycle_bindings_v2.json"), s2)
            act = 0
            for h in l2.instances:
                dp = h.despawn_day if h.despawn_day != float("inf") else s2.duration
                act += max(0, int(min(dp, s2.duration)) - int(h.spawn_day))
            delta["instance_active_days_total"] = act
        except Exception as ex:
            delta["instance_active_days_total"] = None
            warnings.append((aid, "존속기간 재계산 실패: %s" % str(ex)[:60]))

        # ── BASE 와 실제로 다른가 ──
        # zone 서명(id·셀수·트리거)만으로는 schedule_shift 를 잡지 못한다 —
        # 트리거 액티비티는 그대로이고 **계산된 생멸 일자**가 바뀌기 때문이다.
        # 따라서 서명 + 활성일 합 + 공기를 함께 본다.
        same_sig = zone_signature(zones) == base_sig
        same_days = (delta.get("instance_active_days_total")
                     == variants[0]["delta"].get("instance_active_days_total"))
        same_dur = delta.get("duration_delta", 0) == 0
        rec["zone_signature_same_as_base"] = same_sig
        rec["identical_to_base"] = bool(same_sig and same_days and same_dur
                                        and rec["mechanism"] != "controls_effect")
        if rec["identical_to_base"]:
            warnings.append((aid, "zone 집합·활성일·공기가 모두 BASE 와 동일하다 — "
                                  "[X] 였어야 할 항목이다"))
        rec["delta"] = delta
        variants.append(rec)
        print("  %-28s %-16s %s" % (aid, rec["mechanism"], delta))

    # ── variant 간 중복 검출 ──
    # 서로 다른 대안이 모델에서 **같은 변형**을 만들면 저감량도 같게 나온다.
    # 오류는 아니지만 사다리 비교 해석에 영향을 주므로 명시한다.
    dup_key = {}
    duplicates = []
    for v in variants[1:]:
        k = (v["mechanism"], v.get("target_hazard_type"),
             json.dumps(v.get("channel_mult") or {}, sort_keys=True),
             v.get("effect_kind"),
             v["delta"].get("zones"), v["delta"].get("cells"),
             v["delta"].get("instance_active_days_total"),
             v["delta"].get("duration_days"))
        if k in dup_key:
            duplicates.append((dup_key[k], v["variant_id"]))
            v["duplicate_of"] = dup_key[k]
        else:
            dup_key[k] = v["variant_id"]

    doc = {"generatedBy": "scripts/apply_alternatives.py",
           "base": {"zones": BASE_ZONES, "bindings": BASE_BINDINGS,
                    "schedule": BASE_SCHEDULE},
           "note": ("class=S 10건만 대상. mechanism 이 controls_effect 인 variant 는 "
                    "zone 파일이 BASE 와 같고 런타임에 효과가 적용된다."),
           "variants": variants}
    save_json(MANIFEST, doc)

    # ── 로그 ──
    w = io.StringIO()
    w.write("# variant 생성 (v4.0 Phase 0-1)\n\n")
    w.write("`build/alternative_classification.csv` 의 **class=S %d건**만 대상. "
            "규칙을 새로 쓰거나 계수를 지어내지 않았다.\n\n" % len(rows))
    w.write("생성된 variant: **%d개** (BASE 포함), 미생성 %d건.\n\n"
            % (len(variants), len(skipped)))

    w.write("## variant 목록\n\n")
    w.write("| variant | 사고유형 | HoC | 규칙 | 기구 | 대상 | zone | 셀 | 공기 |\n")
    w.write("|---|---|---|---|---|---|---|---|---|\n")
    for v in variants:
        d = v["delta"]
        w.write("| `%s` | %s | %s | %s | %s | %s | %d (%+d) | %s (%+d) | %d (%+d) |\n"
                % (v["variant_id"], v["accident_type"] or "—", v["hoc_level"] or "—",
                   (v["rule_type"] or "—").replace("Rule", ""), v["mechanism"],
                   v["target_hazard_type"] or "—",
                   d.get("zones", 0), -d.get("zones_removed", 0),
                   "{:,}".format(d.get("cells", 0)), d.get("cells_delta", 0),
                   d.get("duration_days", 0), d.get("duration_delta", 0)))
    w.write("\n")

    w.write("## 존속기간 변화 (전 인스턴스 활성일 합)\n\n")
    w.write("| variant | 활성일 합 | BASE 대비 |\n|---|---|---|\n")
    b_act = variants[0]["delta"].get("instance_active_days_total")
    for v in variants:
        a = v["delta"].get("instance_active_days_total")
        w.write("| `%s` | %s | %s |\n"
                % (v["variant_id"], "{:,}".format(a) if a is not None else "—",
                   ("%+d" % (a - b_act)) if (a is not None and b_act is not None) else "—"))
    w.write("\n")

    w.write("## controls 효과 상세 (mechanism=controls_effect)\n\n")
    w.write("| variant | kind | 채널배율 | 심각도배율 | 설치일 | effective_day |\n")
    w.write("|---|---|---|---|---|---|\n")
    for v in variants:
        if v.get("mechanism") != "controls_effect":
            continue
        ed = v.get("effective_days") or []
        w.write("| `%s` | %s | %s | %s | %s | %s |\n"
                % (v["variant_id"], v.get("effect_kind"), v.get("channel_mult"),
                   v.get("severity_mult") or "—", v.get("install_duration_days"),
                   ("%d~%d" % (min(ed), max(ed))) if ed else "—"))
    w.write("\n**설치 기간 중 무방호 노출**: `install_duration_days` 가 1 이상인 "
            "variant 는 `effective_day` 전까지 BASE 와 동일한 노출이 발생한다. "
            "`controls.py` 의 기존 의미론이며 새로 만들지 않았다.\n\n")

    w.write("## 미생성 — 적용 불가\n\n")
    if skipped:
        w.write("| 대안 | entry | 사유 |\n|---|---|---|\n")
        for a, e, why in skipped:
            w.write("| `%s` | `%s` | %s |\n" % (a, e, why))
        w.write("\n**억지로 적용해 variant 를 만들지 않았다.**\n")
    else:
        w.write("없음.\n")
    w.write("\n")

    w.write("## variant 간 중복\n\n")
    if duplicates:
        w.write("서로 다른 대안이 모델에서 **같은 변형**을 만든다. 오류는 아니지만 "
                "저감량이 동일하게 나오므로 사다리 비교 해석에 영향을 준다.\n\n")
        w.write("| 원본 | 중복 |\n|---|---|\n")
        for a, b in duplicates:
            w.write("| `%s` | `%s` |\n" % (a, b))
    else:
        w.write("없음.\n")
    w.write("\n")

    w.write("## 검증 — BASE 와 실제로 다른가\n\n")
    if warnings:
        w.write("| variant | 경고 |\n|---|---|\n")
        for a, msg in warnings:
            w.write("| `%s` | %s |\n" % (a, msg))
        w.write("\n**위 항목은 분류가 [S]가 아니었어야 할 가능성이 있다.**\n")
    else:
        w.write("전 variant 가 BASE 와 구분된다 — zone 집합이 BASE 와 동일하면서 "
                "변형 기구가 zone/schedule 인 항목 0건, 배율이 1.0 뿐인 항목 0건.\n")
    w.write("\n")

    with io.open(LOG, "w", encoding="utf-8") as fp:
        fp.write(w.getvalue())

    print("저장: %s / %s" % (MANIFEST, LOG))
    print("  variant %d (BASE 포함) / 미생성 %d / 경고 %d"
          % (len(variants), len(skipped), len(warnings)))
    for a, m in warnings:
        print("  [경고] %s — %s" % (a, m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
