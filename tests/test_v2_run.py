"""V2 검증 #5 — run_project 스모크 (핵심 수용 기준).

새 CSV 데이터로 N일 MC 실행 후, 철근배근 기간(타설 전)에 λ_edge > 0 확인.
사유: edge 채널은 site.json 정적 격자(EDGE=6 셀)에서 파생되므로(fourd.channel_cells)
위험 인스턴스 없이도 크루가 그 층에 있으면 노출이 발생한다. 이것이 이번 개정에서
'철근배근 단계 단부 노출'을 격자 측에서 보장하는 근거다.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = ROOT / "project"


@pytest.fixture(scope="module")
def project(library):
    import fourd
    return fourd.load_project(str(PROJECT), library=library)


def test_rebar_period_has_edge_lambda(project, library):
    import fourd
    schedule, site, lifecycle, crews_cfg = project

    # day 0~2 = Basement 기둥 철근배근 (타설 전). 그 기간 in_progress 확인
    active0 = schedule.activeSet(0)
    assert active0, "day0 활성 액티비티 존재"
    trades0 = {schedule.activities[a].trade for a in active0}
    assert "rebar" in trades0 and "concrete_pour" not in trades0  # 철근배근기, 타설 전

    res = fourd.run_project(schedule, site, lifecycle, crews_cfg=crews_cfg,
                            days=6, mc_runs=2, seed="v2-smoke")

    edge_early = sum(res.channel_total("edge", d) for d in range(0, 3))
    assert edge_early > 0.0, "철근배근 기간 λ_edge > 0 (정적 EDGE 셀 노출)"


def test_run_project_smoke_30d(project):
    import fourd
    schedule, site, lifecycle, crews_cfg = project
    res = fourd.run_project(schedule, site, lifecycle, crews_cfg=crews_cfg,
                            days=30, mc_runs=1, seed="v2-30d")
    # 재현성: 동일 시드 → 동일 결과
    res2 = fourd.run_project(schedule, site, lifecycle, crews_cfg=crews_cfg,
                             days=30, mc_runs=1, seed="v2-30d")
    assert res.lam == res2.lam
    # 노출이 실제로 발생 (λ 총합 > 0)
    assert sum(res.lam.values()) > 0.0
