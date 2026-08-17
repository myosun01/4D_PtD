# check_p3.py — Phase 3 스모크: PtD 대책 폐루프
# base 실행 → λ 상위 위험 인스턴스 → 적용가능 대안(TTL, HoC순) → 최상위 적용 → 재실행 → 전후 비교
# 실행: python check_p3.py
import fourd
import ptd_ttl

lib = ptd_ttl.LIBRARY
sch, site, life, cfg = fourd.load_project("project")

rep = fourd.closed_loop_demo(sch, site, life, cfg, lib,
                             days=200, mc_runs=1, seed=0, max_steps=150)

if "chosen_alternative" not in rep:
    print("note:", rep.get("note"))
else:
    print("최고위험 인스턴스:", rep["top_instance"], "(", rep["top_hazard"], ")  "
          "λ=%.3e" % rep["top_lambda_base"])
    print("적용가능 대안(HoC 순):")
    for aid, hoc in rep["applicable_alternatives"]:
        mark = "  <== 선택" if aid == rep["chosen_alternative"] else ""
        print(f"   - {aid:22} ({hoc}){mark}")
    print("전체 λ  base=%.4e  after=%.4e  Δ=%.4e  (%.1f%% 감소)" % (
        rep["base_total"], rep["after_total"], rep["delta"], rep["reduction_pct"]))
