"""P2-3~P2-5 — 4D 일 루프 DoD 검증.

DoD: 8층 실제 프로젝트로 N일 MC가 돌고 output/lambda_daily.csv 산출,
일자별 공종 투입 곡선이 schedule.json과 정합, collapse λ는 위험 활성 시에만>0,
동일 시드 → 비트 동일(재현성), 그리고 2D 베이스라인(run_one_day) 불변.
"""
import csv
import hashlib

import numpy as np

import config as C
import fourd


def test_run_project_produces_lambda(project4d):
    sch, site, life, cfg = project4d
    res = fourd.run_project(sch, site, life, cfg, days=60, mc_runs=1, seed=0, max_steps=60)
    assert res.lam, "λ 결과가 비어있음"
    assert all(v > 0 for v in res.lam.values())
    # 실제 데이터에서 워커가 단부/개구부 인접에 노출 → 최소 한 채널 활성
    channels = {ch for (_lv, _r, _c, _d, ch) in res.lam}
    assert channels & {"edge", "fall"}
    # 8층 프로젝트: 여러 층에서 발생 가능(직렬이라 하루 1층이지만 날마다 층 이동)
    levels = {lv for (lv, _r, _c, _d, _ch) in res.lam}
    assert levels <= set(site.level_order)


def test_crew_curve_matches_schedule(project4d):
    # DoD: 일자별 공종 투입 곡선이 schedule.crewsOnSite 와 정합
    sch, site, life, cfg = project4d
    res = fourd.run_project(sch, site, life, cfg, days=120, mc_runs=1, seed=0, max_steps=30)
    for d in (0, 5, 40, 90, 119):
        expected = sch.crewsOnSite(d)
        for trade, crew in expected.items():
            rec = res.exposure_by_trade.get((d, trade))
            assert rec is not None and rec["crew"] == crew, (d, trade, crew, rec)


def test_collapse_channel_only_when_active(project4d):
    # P2-4: 위험(H008) 활성일 + 직하부 크루 → collapse λ>0 ; 비활성일 → 0
    sch, site, life, cfg = project4d
    h = next(h for h in life.instances if h.hazard_type == "H008")
    active_day = h.spawn_day + 1
    inactive_day = max(0, h.spawn_day - 20)

    def collapse_lambda(day):
        res = fourd.run_project(sch, site, life, cfg, days=day + 1, mc_runs=1, seed=3,
                                max_steps=100, extra_crews={(day, h.level): [("rebar", 5)]})
        return res.channel_total("collapse_zone", day=day)

    assert collapse_lambda(active_day) > 0
    assert collapse_lambda(inactive_day) == 0.0


def test_reproducible_same_seed(project4d):
    # CLAUDE.md 재현성: 동일 시드 → 비트 동일 결과
    sch, site, life, cfg = project4d
    kw = dict(days=25, mc_runs=2, seed=7, max_steps=50)
    a = fourd.run_project(sch, site, life, cfg, **kw)
    b = fourd.run_project(sch, site, life, cfg, **kw)
    assert a.lam == b.lam
    c = fourd.run_project(sch, site, life, cfg, days=25, mc_runs=2, seed=8, max_steps=50)
    assert c.lam != a.lam                            # 다른 시드 → 다른 결과


def test_channels_without_cells_are_zero(project4d):
    # site 에 MATERIAL/NARROW 셀이 없고 H009 바인딩도 없음 → 해당 채널 λ 0
    sch, site, life, cfg = project4d
    res = fourd.run_project(sch, site, life, cfg, days=60, mc_runs=1, seed=0, max_steps=60)
    assert res.channel_total("material") == 0.0
    assert res.channel_total("narrow") == 0.0
    assert res.channel_total("drop_zone") == 0.0


def test_write_outputs(project4d, tmp_path):
    sch, site, life, cfg = project4d
    res = fourd.run_project(sch, site, life, cfg, days=20, mc_runs=1, seed=0, max_steps=40)
    lam_path, exp_path = fourd.write_outputs(res, out_dir=str(tmp_path))
    # lambda_daily.csv 스키마
    with open(lam_path, encoding="utf-8") as fp:
        rows = list(csv.reader(fp))
    assert rows[0] == ["level", "row", "col", "day", "channel", "lambda"]
    assert len(rows) > 1
    for r in rows[1:]:
        assert r[4] in fourd.CHANNELS and float(r[5]) > 0
    # exposure_by_trade.csv 스키마 + crew 정합
    with open(exp_path, encoding="utf-8") as fp:
        erows = list(csv.reader(fp))
    assert erows[0] == ["day", "trade", "crew", "exposure_steps"]
    for r in erows[1:]:
        assert r[1] in ("rebar", "formwork_erection", "concrete_pour",
                        "formwork_stripping", "material_handling")


def test_2d_baseline_preserved():
    # 절대 원칙: 기존 2D 엔진(run_one_day)을 훼손하지 않았음을 회귀로 고정.
    import movement as M
    import ptd_ttl
    g0 = M.build_grid()
    g, eff = ptd_ttl.apply(g0, "base")
    fe = M.fall_edge_cells(g)
    _acc, _exp, risk = M.run_one_day(g, eff, fe, seed=12345)
    md5 = hashlib.md5(np.ascontiguousarray(risk).tobytes()).hexdigest()
    assert md5 == "231dd0829174d280af5508b2f54ff842"
