"""P3-6 — 폐루프: base 실행 → λ 상위 인스턴스 → 적용가능 대안(HoC순) → 적용 → 재실행 → 전후 비교.
Phase 3 DoD: 대안 1개 적용 전후로 λ 차이가 산출됨."""
import fourd


def test_rank_instances_descending(project4d, library):
    sch, site, life, cfg = project4d
    base = fourd.run_project(sch, site, life, cfg, days=140, mc_runs=1, seed=0,
                             max_steps=80, library=library)
    ranked = fourd.rank_instances_by_lambda(base, life)
    vals = [v for _h, v in ranked]
    assert vals == sorted(vals, reverse=True)
    assert any(v > 0 for v in vals)               # 노출된 인스턴스 존재


def test_closed_loop_reduces_lambda(project4d, library):
    sch, site, life, cfg = project4d
    rep = fourd.closed_loop_demo(sch, site, life, cfg, library, days=140, mc_runs=1,
                                 seed=0, max_steps=80)
    assert rep["base_total"] > 0
    assert rep["after_total"] < rep["base_total"]          # 대책 적용 후 감소
    assert rep["delta"] > 0
    # 선택 대안 = 적용가능 목록의 HoC 최상위
    assert rep["chosen_alternative"] == rep["applicable_alternatives"][0][0]
    # 선택 대안이 대상 위험타입에 실제 적용가능
    applicable_ids = {aid for aid, _hoc in rep["applicable_alternatives"]}
    assert rep["chosen_alternative"] in applicable_ids
