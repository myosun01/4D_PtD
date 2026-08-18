# -*- coding: utf-8 -*-
"""v3.7 — 4D 작업자 알고리즘 이식 보강 회귀 테스트.

이 파일이 지키는 것:

  Part A  대책 효과가 `soft_route` 까지 실제로 도달하는가 (배관이 살아 있는가)
          — 현행 라이브러리에는 `hazardWeightMultiplier` 가 1건뿐이고 그것도
            drop_zone 이라 실전에서는 None 이 넘어간다. 그것이 **라이브러리 내용
            때문이지 코드 버그가 아님**을 합성 스텁으로 고정한다.
  Part B  `dwell_ratio` 가 파라미터로 노출되고 stage 스위치가 v3.6 값을 재현하는가
  Part C  ρ 개인차·foreman·출발 분산·체류 편차가 붙었는가
  경계    movement.py / social.py / site_model.py / lifecycle.py 미수정
"""
import hashlib
import pathlib
import random

import pytest

import config as C
import fourd
import fourd_workers as FW

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKUP_SHA = ROOT / "data" / "backup_v3.7" / "pre_v3.7_sha256.txt"

# ══════════════════════════════════════════════════════════
# 경계 — 2D 커널을 고치지 않았다
# ══════════════════════════════════════════════════════════
PROTECTED = ("movement.py", "social.py", "site_model.py", "lifecycle.py")


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", PROTECTED)
def test_protected_2d_files_unmodified(name):
    """v3.7 는 이 네 파일을 건드리지 않는다 — import 해서 쓴다."""
    if not BACKUP_SHA.exists():
        pytest.skip("data/backup_v3.7/pre_v3.7_sha256.txt 없음")
    want = {}
    for line in BACKUP_SHA.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        h, f = line.split(None, 1)
        want[f.strip().lstrip("*")] = h
    assert name in want, "백업 기록에 %s 가 없다" % name
    assert _sha(ROOT / name) == want[name], "%s 가 v3.7 이후 변경되었다" % name


def test_ported_from_2d_not_reimplemented():
    """2D 함수를 재구현하지 않고 import 해서 쓴다."""
    import movement
    import social
    assert FW.theta_route is movement.theta_route
    assert FW.social.init_rho is social.init_rho
    assert FW.social.apply_imitation is social.apply_imitation


def test_accident_sampling_not_ported():
    """사고 표집은 이식하지 않는다 — 4D 는 λ(기대건수) 방식이다."""
    src = (ROOT / "fourd_workers.py").read_text(encoding="utf-8")
    for banned in ("P_FALL_PER_STEP", "apply_witness_shock"):
        # 주석·문서에서 '미이식 사유'로 언급하는 것은 허용, 호출은 금지
        for line in src.splitlines():
            stripped = line.strip()
            if banned in line and not stripped.startswith("#"):
                assert "(" not in line.split(banned, 1)[1][:1], \
                    "%s 를 호출하면 안 된다" % banned


# ══════════════════════════════════════════════════════════
# Part A — effects 가 경로까지 도달하는가
# ══════════════════════════════════════════════════════════
class _Haz:
    def __init__(self, iid, level, htype):
        self.instance_id, self.level, self.hazard_type = iid, level, htype


class _Eff:
    def __init__(self, alt_id, day=0):
        self.alternative_id, self.effective_day = alt_id, day


class _Rule:
    def __init__(self, hwm):
        self._hwm = hwm

    def multipliers(self):
        return {} if self._hwm is None else {"hazard_weight_multiplier": self._hwm}


class _Lib:
    def __init__(self, hwm):
        self.alternatives = {"ALT_X": object()}
        self._rule = _Rule(hwm)

    def rule_of(self, alt_id):
        return self._rule


def test_path_effects_maps_fall_channel_to_floor_opening():
    """hazardWeightMultiplier 가 있으면 2D 셀타입 어휘로 옮겨진다."""
    eff = FW.path_effects_for_day({"i1": _Eff("ALT_X")},
                                  [_Haz("i1", "L1", "H001")], "L1", 5, _Lib(0.30))
    assert eff is not None
    assert eff[C.FLOOR_OPENING]["weight_mult"] == pytest.approx(0.30)
    # 손대지 않은 셀타입은 1.0 (영향 없음)
    assert eff[C.MATERIAL]["weight_mult"] == 1.0
    assert eff[C.NARROW]["weight_mult"] == 1.0


def test_path_effects_none_when_library_has_no_weight_multiplier():
    """λ 배율(fallProbMultiplier)을 경로 비용으로 전용하지 않는다 → None."""
    assert FW.path_effects_for_day({"i1": _Eff("ALT_X")},
                                   [_Haz("i1", "L1", "H001")], "L1", 5,
                                   _Lib(None)) is None


def test_path_effects_none_for_unmapped_channel():
    """drop_zone 등 2D 셀타입 대응이 없는 채널은 경로에 영향을 줄 수 없다."""
    assert FW.path_effects_for_day({"i1": _Eff("ALT_X")},
                                   [_Haz("i1", "L1", "H009")], "L1", 5,
                                   _Lib(0.35)) is None
    for ch in FW.CHANNELS_WITHOUT_PATH_EFFECT:
        assert ch not in FW._CHANNEL_TO_CELLTYPE


def test_path_effects_inactive_before_effective_day():
    """설치 전(무방호)에는 경로 가중이 붙지 않는다."""
    assert FW.path_effects_for_day({"i1": _Eff("ALT_X", day=10)},
                                   [_Haz("i1", "L1", "H001")], "L1", 3,
                                   _Lib(0.30)) is None
    assert FW.path_effects_for_day({"i1": _Eff("ALT_X", day=10)},
                                   [_Haz("i1", "L1", "H001")], "L1", 10,
                                   _Lib(0.30)) is not None


def test_path_effects_other_level_ignored():
    assert FW.path_effects_for_day({"i1": _Eff("ALT_X")},
                                   [_Haz("i1", "L2", "H001")], "L1", 5,
                                   _Lib(0.30)) is None


def test_effects_actually_change_soft_route():
    """전달한 effects 가 A* 비용을 실제로 바꾼다 — 배관이 죽어 있지 않다.

    개구부를 낀 좁은 통로를 만들고, 개구부 인접 가산(OPEN_EDGE_PEN)에 배율을
    준 경우와 아닌 경우의 경로 비용 지형이 달라지는지를 컨텍스트로 직접 본다.
    """
    import numpy as np
    import movement

    g = np.full((9, 9), C.WALKABLE, dtype=np.int8)
    g[4, 4] = C.FLOOR_OPENING
    g[3, 3] = g[3, 4] = g[3, 5] = C.NARROW

    movement._CTX.clear()
    base = movement._get_context(g, None)
    eff = {ct: {"prob_mult": 1.0, "fatal_mult": 1.0, "weight_mult": 1.0}
           for ct in (C.FLOOR_OPENING, C.MATERIAL, C.NARROW)}
    eff[C.NARROW]["weight_mult"] = 0.0        # 좁은 통로 위험가중 제거
    movement._CTX.clear()
    relaxed = movement._get_context(g, eff)

    def total_extra(ctx):
        return sum(e for cell in ctx["nbrs"].values() for (_r, _c, _b, e) in cell)

    assert total_extra(relaxed) < total_extra(base), \
        "weight_mult 를 낮췄는데 경로 비용 지형이 그대로다 — effects 가 무시되고 있다"
    movement._CTX.clear()


def test_run_level_day_passes_path_eff_to_route(monkeypatch):
    """run_level_day_workers 가 Theta*에 path_eff와 keyed noise를 넘긴다."""
    import numpy as np
    import movement

    seen = []

    def spy(grid, start, goal, rho, rng, eff, nbrs=None, ctx=None,
            noise_seed=None):
        seen.append((eff, noise_seed))
        return movement.theta_route(grid, start, goal, rho, rng, eff, nbrs=nbrs,
                                    ctx=ctx, noise_seed=noise_seed)

    monkeypatch.setattr(FW, "theta_route", spy)

    g = np.full((12, 12), C.WALKABLE, dtype=np.int8)
    marker = {"sentinel": True}
    w = FW.Worker4D(wid=0, trade="rebar", activity_id="A", rho=0.5,
                    pos=(0, 0), targets=[(10, 10)], target=None, route=[],
                    state="travel", timer=0, move_accum=0.0, stuck=0,
                    target_derived=True, is_foreman=False, depart=0, visits=0)
    movement._CTX.clear()
    FW.run_level_day_workers(g, {}, [w], 30, random.Random(1), 5,
                             path_eff=marker, social_on=False, variation_on=False)
    movement._CTX.clear()
    assert seen and all(e is marker for e, _seed in seen), \
        "theta_route 에 effects 가 전달되지 않는다"


# ══════════════════════════════════════════════════════════
# Part B — 체류 비율
# ══════════════════════════════════════════════════════════
def test_dwell_ratio_default_is_config_value():
    assert C.DWELL_RATIO == 0.75          # 근거 없음 — limitations.md §2-B


def test_dwell_ratio_is_a_parameter_not_a_literal():
    """`horizon // 8` 하드코딩이 남아 있지 않다."""
    src = (ROOT / "fourd_workers.py").read_text(encoding="utf-8")
    assert "dwell_ratio" in src
    assert "horizon // 8" not in src


@pytest.mark.parametrize("stage,expect_ratio", [("v36", 0.125), ("a", 0.125),
                                                ("ab", 0.75), ("v37", 0.75)])
def test_stage_switch_selects_dwell_ratio(stage, expect_ratio):
    """stage 는 값을 바꾸는 것이 아니라 어느 확장까지 켤지를 고른다."""
    import inspect
    src = inspect.getsource(FW.run_project_workers)
    assert 'want_b = stage in ("ab", "v37")' in src
    assert "C.DWELL_RATIO if want_b else (1.0 / 8.0)" in src


# ══════════════════════════════════════════════════════════
# Part C — 확률적 변동
# ══════════════════════════════════════════════════════════
class _WL:
    """make_workers 가 쓰는 최소 인터페이스."""
    def __init__(self):
        self.stats = {}

    def targets_on_grid(self, activity_id, grid):
        return [(2, 2), (5, 5)]


def _make(n=6, stagger=10, social=True, seed=3):
    import numpy as np
    g = np.full((10, 10), C.WALKABLE, dtype=np.int8)
    comp = [(r, c) for r in range(10) for c in range(10)]
    return FW.make_workers([("A1", "rebar", n)], _WL(), g, comp, {},
                           random.Random(seed), stagger_steps=stagger,
                           use_social_rho=social)


def test_rho_is_individual_not_single_value():
    """하루 고정 단일 ρ 가 아니라 개인차가 있다."""
    workers, _ = _make(n=8)
    rhos = {w.rho for w in workers if not w.is_foreman}
    assert len(rhos) > 1
    assert all(C.RHO_MIN <= r <= C.RHO_MAX for r in rhos)


def test_one_foreman_per_crew_at_fixed_rho():
    """크루(액티비티)당 1명 — 이 배정 규칙에는 근거가 없다 (limitations.md)."""
    workers, stats = _make(n=5)
    fore = [w for w in workers if w.is_foreman]
    assert len(fore) == 1 and stats["foremen"] == 1
    assert fore[0].rho == C.RHO_FOREMAN


def test_departure_is_staggered():
    workers, _ = _make(n=10, stagger=10)
    assert any(w.state == "wait" for w in workers)
    assert all(0 <= w.depart <= 10 for w in workers)


def test_no_stagger_means_everyone_starts_at_zero():
    """스태거 폭이 0 이면 스태거가 없는 것이다 — 값을 올려 만들지 않는다."""
    workers, _ = _make(n=6, stagger=0)
    assert all(w.depart == 0 and w.state == "travel" for w in workers)


def test_stagger_ratio_is_converted_from_2d():
    assert C.STAGGER_RATIO == pytest.approx(C.START_STAGGER_S / C.WORKDAY_STEPS)


def test_dwell_jitter_varies_timer():
    """체류시간 개인차가 붙어 진입/종료가 한꺼번에 몰리지 않는다."""
    import numpy as np
    g = np.full((7, 7), C.WALKABLE, dtype=np.int8)
    timers = set()
    for seed in range(30):
        w = FW.Worker4D(wid=0, trade="rebar", activity_id="A", rho=0.5,
                        pos=(3, 3), targets=[(3, 3)], target=None, route=[],
                        state="travel", timer=0, move_accum=0.0, stuck=0,
                        target_derived=True, is_foreman=False, depart=0, visits=0)
        FW.run_level_day_workers(g, {}, [w], 1, random.Random(seed), 20,
                                 social_on=False, variation_on=True)
        timers.add(w.timer)
    assert len(timers) > 1, "DWELL_JITTER_FRAC 이 적용되지 않았다"


def test_variation_off_gives_uniform_dwell():
    import numpy as np
    g = np.full((7, 7), C.WALKABLE, dtype=np.int8)
    timers = set()
    for seed in range(10):
        w = FW.Worker4D(wid=0, trade="rebar", activity_id="A", rho=0.5,
                        pos=(3, 3), targets=[(3, 3)], target=None, route=[],
                        state="travel", timer=0, move_accum=0.0, stuck=0,
                        target_derived=True, is_foreman=False, depart=0, visits=0)
        FW.run_level_day_workers(g, {}, [w], 1, random.Random(seed), 20,
                                 social_on=False, variation_on=False)
        timers.add(w.timer)
    assert timers == {20}


def test_imitation_runs_within_one_level_only():
    """모방은 이 함수에 넘어온 workers(=한 층 인원) 안에서만 작동한다."""
    import inspect
    src = inspect.getsource(FW.run_level_day_workers)
    assert "social.apply_imitation" in src
    # 층을 넘나드는 인원 수집이 없다 — 인자로 받은 workers 만 쓴다
    assert "apply_imitation(proxies, step)" in src


def test_imitation_proxy_does_not_require_social_change():
    w = FW.Worker4D(wid=0, trade="rebar", activity_id="A", rho=0.4,
                    pos=(1, 1), targets=[(1, 1)], target=None, route=[],
                    state="travel", timer=0, move_accum=0.0, stuck=0,
                    target_derived=True, is_foreman=False, depart=0, visits=0)
    p = FW._ImitationProxy(w)
    assert (p.pos, p.rho, p.is_foreman, p.injured) == ((1, 1), 0.4, False, False)


# ══════════════════════════════════════════════════════════
# 재현성 (CLAUDE.md 절대원칙 5)
# ══════════════════════════════════════════════════════════
def test_same_seed_same_result():
    import numpy as np
    g = np.full((14, 14), C.WALKABLE, dtype=np.int8)
    g[7, 7] = C.NARROW
    ch = {"narrow": frozenset({(7, 7)})}

    def once():
        workers, _ = _make(n=4, stagger=5, seed=11)
        exp, _fb = FW.run_level_day_workers(g, ch, workers, 40,
                                            random.Random(11), 8,
                                            social_on=True, variation_on=True)
        return {k: dict(v) for k, v in exp.items()}, [w.rho for w in workers]

    import movement
    movement._CTX.clear()
    a = once()
    movement._CTX.clear()
    b = once()
    assert a == b
