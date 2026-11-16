import numpy as np
import pytest

from planner.geo import distance_matrix_m
from planner.routing.toptw import (
    Stop,
    greedy_plan,
    hybrid_plan,
    ils_plan,
    ortools_plan,
    profit_upper_bound,
    schedule_day,
)

SOLVERS = (greedy_plan, ortools_plan, ils_plan, hybrid_plan)

WALK_M_PER_MIN = 75.0


def _instance(n, n_days, seed, windows=True):
    rng = np.random.default_rng(seed)
    travel = distance_matrix_m(48.29 + rng.random(n) * 0.03, 25.93 + rng.random(n) * 0.04) / WALK_M_PER_MIN
    stops = []
    for _ in range(n):
        if windows and rng.random() < 0.6:
            open_ = int(rng.choice([540, 600, 720]))
            w = [
                [(open_, open_ + int(rng.choice([240, 480])))] if rng.random() > 0.15 else []
                for _ in range(n_days)
            ]
        else:
            w = [None] * n_days
        stops.append(Stop(float(rng.random()), int(rng.choice([15, 30, 45, 60, 90])), w))
    return stops, travel


def _check(plan, stops, travel, n_days, day_start=540, day_end=1140):
    seen = plan.visited
    assert len(seen) == len(set(seen)), "a stop is visited twice"
    assert sorted(seen + plan.skipped) == list(range(len(stops)))
    for d, day in enumerate(plan.days):
        assert schedule_day([v.stop for v in day], stops, travel, d, day_start, day_end) is not None
        for v in day:
            assert day_start <= v.start and v.leave <= day_end
            w = stops[v.stop].windows[d]
            assert w is None or any(a <= v.start and v.leave <= b for a, b in w)


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("n_days", [1, 3])
def test_plans_are_feasible(seed, n_days):
    stops, travel = _instance(25, n_days, seed)
    for solver in SOLVERS:
        _check(solver(stops, travel, n_days), stops, travel, n_days)


def test_ortools_not_worse_than_greedy_on_average():
    gains = []
    for seed in range(6):
        stops, travel = _instance(30, 2, 100 + seed)
        g = greedy_plan(stops, travel, 2).profit(stops)
        o = ortools_plan(stops, travel, 2, time_limit_s=1.0).profit(stops)
        gains.append(o / g)
    assert np.mean(gains) >= 0.99


def test_improvers_never_lose_to_greedy_and_respect_the_bound():
    """Many short cheap visits against a few long valuable ones: the case in which a
    cold-started routing solver stalls far below the greedy plan."""
    for seed in range(4):
        rng = np.random.default_rng(seed)
        stops, travel = _instance(40, 2, 200 + seed, windows=False)
        for s in stops:
            s.visit_min = int(rng.choice([15, 20, 20, 45, 120]))
            s.profit = 0.4 + 0.6 * rng.random() + s.visit_min / 400
        g = greedy_plan(stops, travel, 2).profit(stops)
        bound = profit_upper_bound(stops, travel, 2)
        for solver in (ortools_plan, ils_plan, hybrid_plan):
            plan = solver(stops, travel, 2, time_limit_s=0.6)
            _check(plan, stops, travel, 2)
            assert g - 1e-9 <= plan.profit(stops) <= bound + 1e-9


def test_everything_fits_when_budget_is_large():
    stops, travel = _instance(6, 1, 3, windows=False)
    for solver in SOLVERS:
        assert solver(stops, travel, 1, day_start=0, day_end=1440).skipped == []


def test_closed_day_and_mandatory():
    travel = np.full((3, 3), 10.0)
    np.fill_diagonal(travel, 0)
    stops = [
        Stop(1.0, 60, [[], [(600, 720)]]),  # closed on day 0
        Stop(0.1, 500, [None, None], mandatory=True),  # long but mandatory
        Stop(0.9, 500, [None, None]),
    ]
    for solver in SOLVERS:
        plan = solver(stops, travel, 2)
        assert 0 in [v.stop for v in plan.days[1]]
        assert 1 in plan.visited
        _check(plan, stops, travel, 2)


def test_waiting_for_opening():
    travel = np.zeros((1, 1))
    visits = schedule_day([0], [Stop(1, 30, [[(600, 700)]])], travel, 0, 540, 1140)
    assert (visits[0].arrive, visits[0].start, visits[0].leave) == (540, 600, 630)
    assert schedule_day([0], [Stop(1, 120, [[(600, 700)]])], travel, 0, 540, 1140) is None
