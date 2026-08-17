"""P3-2/3/4 — 대책 실행기: AgentParameterRule 배율 / SpatialChangeRule remove·block·relocate /
설치 무방호 창(installDurationDays). 전후 λ 차이로 검증.

대안 ID 는 v2.4 표기다 (v2.3→v2.4 대응표는 tests/test_p3_controls.py 상단 참조)."""
import pytest

import fourd
from controls import ControlApplication

GUARD = "ALT_H001_05"            # RULE_H001_GUARD  (fall × 0.10, 설치 1일)
PPE = "ALT_H001_08"              # RULE_PPE_H001    (fatality × 0.27)
CP_PC = "ALT_T_CP_01"            # RULE_CP_PC       (remove collapse zone)
CP_NOENTRY = "ALT_T_CP_03"       # RULE_CP_NOENTRY  (block_agent_entry)
CP_LIFT_LIMIT = "ALT_S_CP_04"    # RULE_CP_LIFT_LIMIT (collapse × 0.50)


def _inst(life, htype, idx=0):
    return [h for h in life.instances if h.hazard_type == htype][idx]


def _run(project4d, controls, lo, hi, level, seed=11, max_steps=80):
    sch, site, life, cfg = project4d
    return fourd.run_project(sch, site, life, cfg, days=hi, day_start=lo, mc_runs=1,
                             seed=seed, max_steps=max_steps, controls=controls,
                             extra_crews={(d, level): [("rebar", 6)] for d in range(lo, hi)})


def test_agent_rule_scales_lambda(project4d):
    # P3-4: H001 + 난간(fall×0.1) → fall λ 감소(0<ctl<base)
    _s, _si, life, _c = project4d
    h = _inst(life, "H001")
    lo, hi = h.spawn_day, min(int(h.despawn_day), h.spawn_day + 10)
    base = _run(project4d, None, lo, hi, h.level).channel_total("fall")
    ctl = _run(project4d, [ControlApplication(GUARD, h.instance_id)], lo, hi, h.level).channel_total("fall")
    assert 0 < ctl < base


def test_install_window_unprotected_then_protected(project4d):
    # P3-2: 설치 완료(effective_day=spawn+1) 전날(무방호)은 base와 동일, 이후는 감소
    _s, _si, life, _c = project4d
    h = _inst(life, "H001")
    ctrl = [ControlApplication(GUARD, h.instance_id)]
    lo, hi = h.spawn_day, h.spawn_day + 3
    base = _run(project4d, None, lo, hi, h.level)
    ctl = _run(project4d, ctrl, lo, hi, h.level)
    s = h.spawn_day
    assert ctl.channel_total("fall", day=s) == base.channel_total("fall", day=s)   # 무방호일 동일
    if base.channel_total("fall", day=s + 1) > 0:
        assert ctl.channel_total("fall", day=s + 1) < base.channel_total("fall", day=s + 1)


def test_spatial_remove_zeroes_instance(project4d):
    # P3-3 remove: collapse 인스턴스(직접 셀) 제거 → 그 인스턴스 귀속 λ가 정확히 0
    _s, _si, life, _c = project4d
    h = _inst(life, "H008")
    lo, hi = h.spawn_day, min(int(h.despawn_day), h.spawn_day + 5)
    base = _run(project4d, None, lo, hi, h.level)
    ctl = _run(project4d, [ControlApplication(CP_PC, h.instance_id)], lo, hi, h.level)
    base_inst = {hh.instance_id: v for hh, v in fourd.rank_instances_by_lambda(base, life)}
    ctl_inst = {hh.instance_id: v for hh, v in fourd.rank_instances_by_lambda(ctl, life)}
    assert base_inst[h.instance_id] > 0            # base엔 이 인스턴스 collapse 노출 존재
    assert ctl_inst[h.instance_id] == 0.0          # remove → 기여 0


def test_spatial_block_collapse(project4d):
    # P3-3 block_agent_entry: H008 직하부 크루가 collapse 셀 진입 불가 → collapse λ 0
    _s, _si, life, _c = project4d
    h = _inst(life, "H008")
    lo, hi = h.spawn_day, min(int(h.despawn_day), h.spawn_day + 5)
    base = _run(project4d, None, lo, hi, h.level).channel_total("collapse_zone")
    ctl = _run(project4d, [ControlApplication(CP_NOENTRY, h.instance_id)], lo, hi, h.level).channel_total("collapse_zone")
    assert base > 0
    assert ctl == 0.0


def test_ppe_does_not_change_lambda(project4d):
    # PPE(fatality×0.27)는 λ(발생 기대) 불변 — 심각도(SWR)는 Phase 4
    _s, _si, life, _c = project4d
    h = _inst(life, "H001")
    lo, hi = h.spawn_day, h.spawn_day + 6
    base = _run(project4d, None, lo, hi, h.level).channel_total("fall")
    ppe = _run(project4d, [ControlApplication(PPE, h.instance_id)], lo, hi, h.level).channel_total("fall")
    assert ppe == base


def test_collapse_agent_rule_scales(project4d):
    # P3-4: H008 + 분할타설 양중제한(collapse×0.50) → collapse λ 감소.
    # v2.3 은 ALT_CP_DESIGNCHECK(collapse×0.3)를 썼으나 그 대안·규칙은 v2.4 에 없다.
    # 같은 채널에 계수를 거는 v2.4 대안(ALT_S_CP_04)으로 대체했다 — 계수는 TTL 값 그대로.
    _s, _si, life, _c = project4d
    h = _inst(life, "H008")
    lo, hi = h.spawn_day, min(int(h.despawn_day), h.spawn_day + 5)
    base = _run(project4d, None, lo, hi, h.level).channel_total("collapse_zone")
    ctl = _run(project4d, [ControlApplication(CP_LIFT_LIMIT, h.instance_id)], lo, hi, h.level).channel_total("collapse_zone")
    assert 0 < ctl < base
