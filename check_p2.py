# check_p2.py — Phase 2 스모크 (4D 일 루프 + λ CSV 산출)
# 실행: python check_p2.py
from collections import Counter

import fourd

sch, site, life, crews_cfg = fourd.load_project("project")
print("levels:", len(site.levels), "| links:", len(site.links), "| duration:", sch.duration)

# 전체 공기(409일) MC 1회, 축약 horizon (스모크/산출용). 정밀 λ는 max_steps 상향.
res = fourd.run_project(sch, site, life, crews_cfg,
                        days=None, mc_runs=1, seed=0, max_steps=200)

by_ch = Counter()
for (lv, r, c, d, ch), v in res.lam.items():
    by_ch[ch] += v
print("lambda nonzero cells:", len(res.lam))
print("lambda by channel:", {k: f"{v:.3e}" for k, v in by_ch.items()})

# 공종 투입 곡선(crew) == schedule.crewsOnSite 정합 확인
mism = 0
for d in range(sch.duration):
    for tr, crew in sch.crewsOnSite(d).items():
        rec = res.exposure_by_trade.get((d, tr))
        if rec is None or rec["crew"] != crew:
            mism += 1
print("crew-curve mismatches vs schedule:", mism)          # 0 이어야 함

lam_path, exp_path = fourd.write_outputs(res)
print("wrote:", lam_path)
print("wrote:", exp_path)
