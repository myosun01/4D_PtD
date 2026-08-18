import random

import numpy as np

import config as C
from movement import _grid_line, theta_route


def test_theta_open_grid_uses_direct_line_of_sight():
    grid = np.zeros((12, 12), dtype=np.int8)
    start, goal = (1, 1), (8, 5)
    route = theta_route(grid, start, goal, 0.5, random.Random(7))
    assert route == _grid_line(start, goal)[1:]


def test_theta_does_not_cross_wall_or_cut_blocked_corner():
    grid = np.zeros((12, 12), dtype=np.int8)
    grid[4, 3] = C.WALL
    start, goal = (1, 1), (8, 5)
    route = theta_route(grid, start, goal, 0.5, random.Random(7))
    assert route
    assert (4, 3) not in route
    prev = start
    for cur in route:
        assert grid[cur] != C.WALL
        if prev[0] != cur[0] and prev[1] != cur[1]:
            assert grid[prev[0], cur[1]] != C.WALL
            assert grid[cur[0], prev[1]] != C.WALL
        prev = cur


def test_theta_same_seed_is_reproducible():
    grid = np.zeros((12, 12), dtype=np.int8)
    grid[3:9, 5] = C.MATERIAL
    a = theta_route(grid, (1, 1), (10, 10), 0.35, random.Random(99))
    b = theta_route(grid, (1, 1), (10, 10), 0.35, random.Random(99))
    assert a == b
