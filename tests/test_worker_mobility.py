import random

from site_model import SiteModel
from worker_mobility import LinkReservationTable, boundary_entrance, plan_commute


def test_l1_to_l8_uses_connected_stairs_only():
    site = SiteModel.load("project/site.json")
    start = ("L1", boundary_entrance(site, "L1"))
    goal = ("L8", site.level("L8").main_component()[0])
    plan = plan_commute(site, start, goal, 0.4, random.Random(7))
    assert plan is not None
    assert plan.arrival_level == "L8"
    assert len(plan.links_used) == 7
    assert all(p.state in ("commute", "stair_wait", "stair") for p in plan.points)
    assert sum(p.state == "stair" for p in plan.points) >= 7 * 40


def test_stair_capacity_creates_queue():
    site = SiteModel.load("project/site.json")
    table = LinkReservationTable(site)
    # ST3 capacity=2, traversal=40: 세 번째 작업자는 앞 두 명 뒤에 들어가야 한다.
    assert table.reserve("ST3", 10, 40) == 10
    assert table.reserve("ST3", 10, 40) == 10
    assert table.reserve("ST3", 10, 40) == 50


def test_same_seed_same_commute_trace():
    site = SiteModel.load("project/site.json")
    start = ("L1", boundary_entrance(site, "L1"))
    goal = ("L6", site.level("L6").main_component()[10])
    a = plan_commute(site, start, goal, 0.55, random.Random(99))
    b = plan_commute(site, start, goal, 0.55, random.Random(99))
    assert a == b


def test_real_worker_loop_reports_stair_use(tmp_path):
    import fourd_workers as fw
    sch, site, life, cfg, wl = fw.load_project_v2()
    out = tmp_path / "trajectory.csv"
    res = fw.run_project_workers(
        sch, site, life, cfg, wl, days=350, day_start=340, mc_runs=1,
        seed="stair-integration", max_steps=480, trajectory_path=str(out),
        trajectory_every=20, social_on=False)
    assert res["placement"]["commute_ok"] > 0
    assert res["placement"]["stair_traversals"] > 0
    text = out.read_text(encoding="utf-8")
    assert ",stair," in text
