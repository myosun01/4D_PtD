"""P2-2 — site_model.py 검증: 다층 격자 로드, VerticalLink 그래프, 다층 경로계획
(층별 A* + 링크), availableFromActivity 게이팅, capacity(LinkOccupancy)."""
import random

import config as C
from site_model import SiteModel, VerticalLink, LinkOccupancy


def test_load_counts(site_model):
    assert len(site_model.levels) == 8
    assert len(site_model.links) == 16
    assert site_model.level_order == [f"L{i}" for i in range(1, 9)]


def test_level_grids(site_model):
    for lid, lv in site_model.levels.items():
        assert lv.grid.shape == (69, 93)
        used = set(int(x) for x in lv.grid.flatten())
        assert used <= {0, 1, 2, 4, 5, 6, 7}       # §2 어휘


def test_below_above(site_model):
    assert site_model.below("L3") == "L2"
    assert site_model.above("L3") == "L4"
    assert site_model.below("L1") is None
    assert site_model.above("L8") is None


def test_adjacency_is_stair_chain(site_model):
    adj = site_model.level_adjacency()
    assert sorted(adj["L1"]) == ["L2"]
    assert sorted(adj["L4"]) == ["L3", "L5"]
    assert sorted(adj["L8"]) == ["L7"]


def test_main_component_is_dominant(site_model):
    comp = site_model.level("L1").main_component()
    walkable = len(site_model.level("L1").walkable_cells())
    assert 0 < len(comp) <= walkable
    assert len(comp) >= 0.8 * walkable              # 지배적 컴포넌트


def test_plan_path_within_level(site_model):
    lv = site_model.level("L2")
    comp = lv.main_component()
    rng = random.Random(0)
    a, b = comp[0], comp[len(comp) // 2]
    seg, cost = site_model.plan_path(("L2", a), ("L2", b), rho=0.5, rng=rng)
    assert seg is not None and cost < float("inf")
    assert seg[0][0] == "move" and seg[0][1] == "L2"


def test_plan_path_cross_level_uses_links(site_model):
    rng = random.Random(1)
    a = site_model.level("L1").main_component()[0]
    b = site_model.level("L3").main_component()[0]
    seg, cost = site_model.plan_path(("L1", a), ("L3", b), rho=0.5, rng=rng)
    assert seg is not None
    links = [s for s in seg if s[0] == "link"]
    assert len(links) == 2                          # L1→L2, L2→L3
    # 비용에 링크 traversal_steps 가 포함됨
    assert cost >= sum(s[3] for s in links)


def test_link_available_gating():
    lk = VerticalLink("X", "stair", [("L1", (0, 0)), ("L2", (0, 0))],
                      capacity=1, traversal_steps=10, available_from_activity="A-99")
    assert lk.is_available(frozenset()) is False
    assert lk.is_available(frozenset({"A-99"})) is True
    lk2 = VerticalLink("Y", "stair", [("L1", (0, 0)), ("L2", (0, 0))])
    assert lk2.is_available() is True               # None → 상시 가용


def test_link_capacity(site_model):
    occ = LinkOccupancy(site_model)
    link = site_model.links[0]
    cap = link.capacity
    entered = [occ.try_enter(link.link_id) for _ in range(cap + 2)]
    assert entered[:cap] == [True] * cap
    assert entered[cap] is False                    # capacity 초과 → 대기
    occ.leave(link.link_id)
    assert occ.try_enter(link.link_id) is True      # 한 명 나가면 다시 가능
