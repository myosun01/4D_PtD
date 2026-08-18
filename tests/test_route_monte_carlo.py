import math
import random

import numpy as np
import pytest

import config as C
import movement
from fourd_workers import (RouteAudit, freeze_worker_assignments,
                           workers_from_assignments)
from monte_carlo import (convergence_trace, paired_differences, quantile,
                         summarize)
from movement import theta_route
from random_streams import stable_seed, stable_uniform


def test_keyed_random_stream_is_stable_and_key_sensitive():
    assert stable_seed("x", 1, (2, 3)) == stable_seed("x", 1, (2, 3))
    assert stable_seed("x", 1) != stable_seed("x", 2)
    assert stable_uniform("x", "cell", 4, 5) == stable_uniform("x", "cell", 4, 5)
    assert 0.0 <= stable_uniform("x") < 1.0


def test_theta_keyed_noise_ignores_rng_consumption_order():
    grid = np.zeros((15, 21), dtype=np.int8)
    grid[2:13, 10] = C.WALL
    grid[4, 10] = C.WALKABLE
    grid[10, 10] = C.WALKABLE
    a = theta_route(grid, (7, 2), (7, 18), 0.5, random.Random(1),
                    noise_seed=("rep", 7))
    rng = random.Random(999)
    for _ in range(100):
        rng.random()
    b = theta_route(grid, (7, 2), (7, 18), 0.5, rng,
                    noise_seed=("rep", 7))
    assert a == b


def test_theta_replicates_have_route_diversity(monkeypatch):
    monkeypatch.setattr(C, "PATH_NOISE", 2.0)
    grid = np.zeros((15, 21), dtype=np.int8)
    grid[2:13, 10] = C.WALL
    grid[4, 10] = C.WALKABLE
    grid[10, 10] = C.WALKABLE
    routes = {
        tuple(theta_route(grid, (7, 2), (7, 18), 0.5, random.Random(0),
                          noise_seed=("rep", rep)))
        for rep in range(40)
    }
    assert len(routes) >= 2


class _Locations:
    def targets_on_grid(self, activity_id, grid):
        return [(2, 2), (7, 7)]


def test_frozen_worker_assignments_clone_without_redrawing():
    grid = np.full((10, 10), C.WALKABLE, dtype=np.int8)
    comp = [(r, c) for r in range(10) for c in range(10)]
    specs = [("A1", "rebar", 5)]
    a, stats_a = freeze_worker_assignments(
        specs, _Locations(), grid, comp, {}, random.Random(42),
        stagger_steps=10)
    b, stats_b = freeze_worker_assignments(
        specs, _Locations(), grid, comp, {}, random.Random(42),
        stagger_steps=10)
    assert a == b and stats_a == stats_b
    first = workers_from_assignments(a)
    second = workers_from_assignments(a)
    assert [(w.wid, w.rho, w.pos, w.targets, w.depart) for w in first] == [
        (w.wid, w.rho, w.pos, w.targets, w.depart) for w in second]
    assert all(len(w.targets) == 1 for w in first)
    first[0].pos = (9, 9)
    assert second[0].pos == a[0].start


def test_route_audit_detects_same_and_different_realisations():
    def digest(route):
        audit = RouteAudit()
        audit.add("work", 1, "L1", 3, 0, (0, 0), (2, 2), route)
        return audit.summary()

    a = digest([(1, 1), (2, 2)])
    b = digest([(1, 1), (2, 2)])
    c = digest([(0, 1), (1, 2), (2, 2)])
    assert a == b
    assert a["route_digest"] != c["route_digest"]


def test_monte_carlo_summary_quantiles_and_paired_difference():
    row = summarize([1, 2, 3, 4])
    assert row["mean"] == pytest.approx(2.5)
    assert row["stdev"] == pytest.approx(math.sqrt(5.0 / 3.0))
    assert row["p05"] == pytest.approx(1.15)
    assert row["p50"] == pytest.approx(2.5)
    assert row["p95"] == pytest.approx(3.85)
    assert quantile([0, 10], 0.25) == pytest.approx(2.5)
    base = [{"replicate": i, "x": x} for i, x in enumerate((1, 2, 4))]
    alt = [{"replicate": i, "x": x} for i, x in enumerate((2, 4, 7))]
    paired = paired_differences(base, alt, "x")
    assert paired["mean"] == pytest.approx(2.0)
    assert paired["replicate_ids"] == [0, 1, 2]
    assert convergence_trace([1, 2, 3, 4], every=2, minimum=2)[-1]["n"] == 4


def test_route_only_project_run_is_reproducible_and_batch_invariant():
    import fourd_workers as fw

    sch, site, life, cfg, wl = fw.load_project_v2()

    def run(count, start=0):
        movement._CTX.clear()
        return fw.run_project_workers(
            sch, site, life, cfg, wl, days=1, mc_runs=count,
            seed="route-only-test", max_steps=20,
            variation_scope="route_only", record_replicates=True,
            replicate_start=start, collect_cell_maps=False)

    full = run(2)
    repeated = run(2)
    second_only = run(1, start=1)
    assert full["assignment_digest"] == repeated["assignment_digest"]
    assert full["replicates"] == repeated["replicates"]
    assert second_only["assignment_digest"] == full["assignment_digest"]
    assert second_only["replicates"][0] == full["replicates"][1]
    placements = [row["placement"] for row in full["replicates"]]
    assert placements[0] == placements[1]
