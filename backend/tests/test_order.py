import numpy as np
import pytest

from planner.geo import distance_matrix_m
from planner.routing import order as od


def _instance(n, seed):
    rng = np.random.default_rng(seed)
    return distance_matrix_m(48.29 + rng.random(n) * 0.03, 25.93 + rng.random(n) * 0.04)


@pytest.mark.parametrize("n,seed", [(2, 0), (5, 1), (8, 2), (9, 3)])
def test_all_methods_return_permutations(n, seed):
    cost = _instance(n, seed)
    for fn in (od.nearest_neighbour, od.held_karp, od.ortools_path, od.optimise_order):
        order = fn(cost, 0)
        assert order[0] == 0 and sorted(order) == list(range(n))


@pytest.mark.parametrize("seed", range(5))
def test_exact_is_lower_bound_and_heuristics_close(seed):
    cost = _instance(9, seed)
    exact = od.path_cost(cost, od.held_karp(cost, 0))
    nn = od.nearest_neighbour(cost, 0)
    opt2 = od.two_opt(cost, nn)
    ort = od.ortools_path(cost, 0, time_limit_s=0.5)
    assert exact <= od.path_cost(cost, opt2) + 1e-6 <= od.path_cost(cost, nn) + 1e-6
    assert od.path_cost(cost, ort) <= exact * 1.01


def test_fixed_end_is_respected():
    cost = _instance(7, 11)
    for fn in (od.nearest_neighbour, od.held_karp, od.ortools_path):
        order = fn(cost, 0, 3)
        assert order[0] == 0 and order[-1] == 3 and sorted(order) == list(range(7))
    exact = od.path_cost(cost, od.held_karp(cost, 0, 3))
    assert od.path_cost(cost, od.ortools_path(cost, 0, 3, 0.5)) <= exact * 1.01
    improved = od.two_opt(cost, od.nearest_neighbour(cost, 0, 3), fixed_end=True)
    assert improved[-1] == 3


def test_asymmetric_costs():
    rng = np.random.default_rng(5)
    cost = rng.random((7, 7)) * 100
    np.fill_diagonal(cost, 0)
    exact = od.path_cost(cost, od.held_karp(cost, 0))
    assert od.path_cost(cost, od.two_opt(cost, od.nearest_neighbour(cost, 0))) >= exact - 1e-6
    assert od.path_cost(cost, od.ortools_path(cost, 0, time_limit_s=0.5)) <= exact * 1.02
