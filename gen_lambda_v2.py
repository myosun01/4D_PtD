"""v2 데이터로 lambda_daily.csv 재생성 (heatmap self-test용).
전체 공기(409일) MC 1회. 산출: output/lambda_daily.csv, exposure_by_trade.csv."""
import sys
import fourd

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sch, site, life, cfg = fourd.load_project("project")
print(f"공기 {sch.duration}일, 인스턴스 {len(life.instances)} — run_project 시작")
res = fourd.run_project(sch, site, life, cfg, mc_runs=1, seed="v2-lambda", max_steps=80)
lam, exp = fourd.write_outputs(res)
print(f"저장: {lam}, {exp}  (λ 항목 {len(res.lam)})")
