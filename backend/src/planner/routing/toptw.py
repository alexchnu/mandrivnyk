"""Multi-day trip planning: team orienteering problem with time windows (TOPTW).

Given candidate stops with a profit (relevance), a visit duration and opening
intervals for each day, choose which stops to visit on which day and in which
order so that total profit is maximal and every day fits its time budget.

Two solvers share one interface: a greedy insertion heuristic (fast baseline)
and an OR-Tools routing model with optional (prize-collecting) nodes.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .order import two_opt

Interval = tuple[int, int]
PROFIT_UNIT = 100_000  # solver cost of skipping the most valuable stop


@dataclass(slots=True)
class Stop:
    """A candidate stop. ``windows[d]`` are opening intervals (minutes) on trip day d;
    ``None`` means "unknown, assume open", an empty list means closed that day."""

    profit: float
    visit_min: int
    windows: list[list[Interval] | None]
    mandatory: bool = False


@dataclass(slots=True)
class Visit:
    stop: int
    arrive: int  # minutes from midnight
    start: int  # service start (after waiting for opening)
    leave: int


@dataclass(slots=True)
class Plan:
    days: list[list[Visit]]
    skipped: list[int] = field(default_factory=list)

    @property
    def visited(self) -> list[int]:
        return [v.stop for day in self.days for v in day]

    def profit(self, stops: list[Stop]) -> float:
        return float(sum(stops[i].profit for i in self.visited))

    def travel_min(self, travel: np.ndarray, depot: int | None = None) -> float:
        total = 0.0
        for day in self.days:
            seq = [v.stop for v in day]
            if depot is not None and seq:
                total += travel[depot, seq[0]]
            total += sum(travel[a, b] for a, b in itertools.pairwise(seq))
        return float(total)


def _feasible_start(arrive: int, visit: int, windows: list[Interval] | None, day_end: int) -> int | None:
    """Earliest service start not before ``arrive`` that fits an opening interval."""
    if windows is None:
        return arrive if arrive + visit <= day_end else None
    for open_, close in windows:
        start = max(arrive, open_)
        if start + visit <= min(close, day_end):
            return start
    return None


def schedule_day(
    order: list[int],
    stops: list[Stop],
    travel: np.ndarray,
    day: int,
    day_start: int,
    day_end: int,
    depot: int | None = None,
) -> list[Visit] | None:
    """Simulate a day for a fixed order; ``None`` when some stop cannot be served."""
    visits: list[Visit] = []
    clock, prev = day_start, depot
    for i in order:
        arrive = clock + (round(travel[prev, i]) if prev is not None else 0)
        start = _feasible_start(arrive, stops[i].visit_min, stops[i].windows[day], day_end)
        if start is None:
            return None
        leave = start + stops[i].visit_min
        visits.append(Visit(i, arrive, start, leave))
        clock, prev = leave, i
    return visits


def _day_duration(visits: list[Visit], day_start: int) -> int:
    return visits[-1].leave - day_start if visits else 0


def greedy_plan(
    stops: list[Stop],
    travel: np.ndarray,
    n_days: int,
    day_start: int = 9 * 60,
    day_end: int = 19 * 60,
    depot: int | None = None,
    initial: list[list[int]] | None = None,
) -> Plan:
    """Cheapest-insertion heuristic: repeatedly add the stop with the best
    profit per extra minute, mandatory stops first.

    ``initial`` are feasible day orders to extend instead of starting from empty days."""
    orders: list[list[int]] = [list(o) for o in initial] if initial else [[] for _ in range(n_days)]
    scheds: list[list[Visit]] = [
        schedule_day(o, stops, travel, d, day_start, day_end, depot) or [] for d, o in enumerate(orders)
    ]
    orders = [[v.stop for v in day] for day in scheds]
    remaining = set(range(len(stops))) - ({depot} if depot is not None else set())
    remaining -= {i for o in orders for i in o}
    while remaining:
        best = None  # (key, stop, day, position, schedule)
        for i in remaining:
            for d in range(n_days):
                if stops[i].windows[d] == []:
                    continue
                base = _day_duration(scheds[d], day_start)
                for pos in range(len(orders[d]) + 1):
                    cand = [*orders[d][:pos], i, *orders[d][pos:]]
                    sched = schedule_day(cand, stops, travel, d, day_start, day_end, depot)
                    if sched is None:
                        continue
                    extra = max(_day_duration(sched, day_start) - base, 1)
                    key = (stops[i].mandatory, stops[i].profit / extra)
                    if best is None or key > best[0]:
                        best = (key, i, d, pos, sched)
        if best is None:
            break
        _, i, d, pos, sched = best
        orders[d].insert(pos, i)
        scheds[d] = sched
        remaining.remove(i)
    return Plan(scheds, sorted(remaining))


def ils_plan(
    stops: list[Stop],
    travel: np.ndarray,
    n_days: int,
    day_start: int = 9 * 60,
    day_end: int = 19 * 60,
    depot: int | None = None,
    time_limit_s: float = 1.0,
    seed: int = 0,
) -> Plan:
    """Iterated local search for the TOPTW in the spirit of Vansteenwegen et al. (2009).

    Starting from the greedy plan, every iteration removes a run of consecutive
    stops from each day ("shake"), re-optimises the visiting order of what is left
    and refills the days by greedy insertion. A plan that is not worse replaces
    the current one; the best plan seen is returned.
    """
    rng = np.random.default_rng(seed)
    args = (stops, travel, n_days, day_start, day_end, depot)
    best = current = greedy_plan(*args)
    best_obj = current_obj = _objective(best, stops, travel, depot)
    deadline = time.perf_counter() + time_limit_s
    length, stale = 1, 0
    while time.perf_counter() < deadline:
        orders = []
        for d, day in enumerate(current.days):
            seq = [v.stop for v in day]
            if seq:
                start = int(rng.integers(len(seq)))
                drop = {seq[(start + k) % len(seq)] for k in range(min(length, len(seq)))}
                seq = [i for i in seq if i not in drop or stops[i].mandatory]
            if len(seq) > 2:
                tour = two_opt(travel, seq)
                if schedule_day(tour, stops, travel, d, day_start, day_end, depot) is not None:
                    seq = tour
            orders.append(seq)
        cand = greedy_plan(*args, initial=orders)
        obj = _objective(cand, stops, travel, depot)
        if obj >= current_obj:
            current, current_obj = cand, obj
        if obj > best_obj:
            best, best_obj, length, stale = cand, obj, 1, 0
        else:
            stale += 1
            length = length % max(max((len(d) for d in current.days), default=1), 1) + 1
            if stale > 60:  # restart from the best plan
                current, current_obj, stale = best, best_obj, 0
    return best


def ortools_plan(
    stops: list[Stop],
    travel: np.ndarray,
    n_days: int,
    day_start: int = 9 * 60,
    day_end: int = 19 * 60,
    depot: int | None = None,
    time_limit_s: float = 2.0,
    warm_start: bool = True,
    lns: bool = True,
    initial: Plan | None = None,
) -> Plan:
    """Prize-collecting vehicle routing model: one vehicle per day.

    Every stop is copied once per day on which it is open; the copies form a
    disjunction (at most one is visited) whose penalty is the stop's profit scaled
    to ``PROFIT_UNIT``, while an arc costs its travel minutes. A whole day of
    walking is thus worth under 1 % of the best stop: the model maximises
    collected profit and uses travel time only as a tie-breaker. Time windows are enforced on a time
    dimension that accumulates travel, waiting and visit durations.

    Left to its own first-solution strategy the solver fills the days with the
    most valuable stops and then stalls: replacing one long visit by two short
    ones is not a single local-search move, and guided local search penalises
    arcs, whose cost is negligible next to the profits. Therefore the search
    starts from a known plan (``initial``, by default the greedy one when
    ``warm_start`` is set), large-neighbourhood operators are enabled (``lns``),
    and the starting plan is returned whenever the solver fails to improve on
    it - the result is never worse than the baseline.
    """
    baseline = initial
    if baseline is None and warm_start:
        baseline = greedy_plan(stops, travel, n_days, day_start, day_end, depot)
    real = [i for i in range(len(stops)) if i != depot]
    if not real:
        return Plan([[] for _ in range(n_days)])
    max_profit = max(max(stops[i].profit for i in real), 1e-9)
    unit = PROFIT_UNIT

    # node 0 is a virtual start/end of every day
    node_stop: list[int] = [-1]
    node_day: list[int] = [-1]
    node_windows: list[list[Interval]] = [[]]  # admissible service-start intervals
    copies: dict[int, list[int]] = {i: [] for i in real}
    for i in real:
        for d in range(n_days):
            windows = stops[i].windows[d]
            if windows is None:
                windows = [(day_start, day_end)]
            usable = [(max(a, day_start), min(b, day_end) - stops[i].visit_min) for a, b in windows]
            usable = [(a, b) for a, b in usable if a <= b]
            if not usable:
                continue  # closed, or the visit does not fit: no copy for this day
            copies[i].append(len(node_stop))
            node_stop.append(i)
            node_day.append(d)
            node_windows.append(usable)

    manager = pywrapcp.RoutingIndexManager(len(node_stop), n_days, 0)
    routing = pywrapcp.RoutingModel(manager)

    def travel_between(a: int, b: int) -> int:
        if b == 0:
            return 0  # the day ends at the last stop
        if a == 0:
            return round(travel[depot, node_stop[b]]) if depot is not None else 0
        return round(travel[node_stop[a], node_stop[b]])

    def time_cb(i: int, j: int) -> int:
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        service = stops[node_stop[a]].visit_min if a != 0 else 0
        return service + travel_between(a, b)

    def cost_cb(i: int, j: int) -> int:
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return travel_between(a, b)

    time_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(cost_cb))
    routing.AddDimension(time_idx, day_end - day_start, day_end, False, "time")
    time_dim = routing.GetDimensionOrDie("time")

    for node in range(1, len(node_stop)):
        index = manager.NodeToIndex(node)
        routing.VehicleVar(index).SetValues([-1, node_day[node]])  # -1 = not visited
        cumul = time_dim.CumulVar(index)
        usable = node_windows[node]
        cumul.SetRange(usable[0][0], usable[-1][1])
        for (_, prev_end), (next_start, _) in itertools.pairwise(usable):
            if next_start - 1 >= prev_end + 1:
                cumul.RemoveInterval(prev_end + 1, next_start - 1)

    for d in range(n_days):
        time_dim.CumulVar(routing.Start(d)).SetRange(day_start, day_end)
        time_dim.CumulVar(routing.End(d)).SetRange(day_start, day_end)

    for i in real:
        if not copies[i]:
            continue
        penalty = round(unit * stops[i].profit / max_profit) + 1
        if stops[i].mandatory:
            penalty = int(unit * 100)
        routing.AddDisjunction([manager.NodeToIndex(n) for n in copies[i]], penalty, 1)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    if lns:
        on = pywrapcp.BOOL_TRUE
        ops = params.local_search_operators
        ops.use_path_lns = on
        ops.use_inactive_lns = on
        ops.use_global_cheapest_insertion_path_lns = on
        ops.use_global_cheapest_insertion_expensive_chain_lns = on
        ops.use_relocate_and_make_active = on
        ops.use_exchange_and_make_active = on
        ops.use_extended_swap_active = on

    solution = None
    if baseline is not None:
        node_of = {(node_stop[n], node_day[n]): n for n in range(1, len(node_stop))}
        routes = [[node_of[v.stop, d] for v in day] for d, day in enumerate(baseline.days)]
        routing.CloseModelWithParameters(params)
        initial = routing.ReadAssignmentFromRoutes(routes, True)
        if initial is not None:
            solution = routing.SolveFromAssignmentWithParameters(initial, params)
    if solution is None:
        solution = routing.SolveWithParameters(params)
    if solution is None:
        return baseline or greedy_plan(stops, travel, n_days, day_start, day_end, depot)

    days: list[list[Visit]] = []
    for d in range(n_days):
        order, index = [], routing.Start(d)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                order.append(node_stop[node])
            index = solution.Value(routing.NextVar(index))
        sched = schedule_day(order, stops, travel, d, day_start, day_end, depot)
        days.append(sched if sched is not None else [])
    plan = Plan(days)
    plan.skipped = sorted(set(real) - set(plan.visited))
    if baseline is not None and _objective(baseline, stops, travel, depot) > _objective(
        plan, stops, travel, depot
    ):
        return baseline
    return plan


def hybrid_plan(
    stops: list[Stop],
    travel: np.ndarray,
    n_days: int,
    day_start: int = 9 * 60,
    day_end: int = 19 * 60,
    depot: int | None = None,
    time_limit_s: float = 1.0,
) -> Plan:
    """The planner used by the service: iterated local search, then OR-Tools
    started from its result. Each stage can only keep or improve the plan."""
    args = (stops, travel, n_days, day_start, day_end, depot)
    plan = ils_plan(*args, time_limit_s=time_limit_s / 2)
    return ortools_plan(*args, time_limit_s=time_limit_s / 2, initial=plan)


def profit_upper_bound(
    stops: list[Stop], travel: np.ndarray, n_days: int, day_start: int = 9 * 60, day_end: int = 19 * 60
) -> float:
    """Upper bound on collectable profit: fractional knapsack relaxation.

    Each stop costs at least its visit time plus the walk from its nearest
    neighbour (the first stop of a day is reached for free, hence the credit of
    one longest "nearest" walk per day); the capacity is the total length of the days.
    """
    n = len(stops)
    if n == 0:
        return 0.0
    masked = travel + np.diag(np.full(n, np.inf))
    nearest = masked.min(axis=0) if n > 1 else np.zeros(1)
    weight = np.array([s.visit_min for s in stops]) + nearest
    capacity = n_days * (day_end - day_start) + n_days * float(nearest.max())
    profit = np.array([s.profit for s in stops])
    total = 0.0
    for i in np.argsort(-profit / np.maximum(weight, 1e-9)):
        if all(w == [] for w in stops[i].windows):
            continue
        take = min(1.0, capacity / weight[i]) if weight[i] > 0 else 1.0
        total += take * profit[i]
        capacity -= take * weight[i]
        if capacity <= 0:
            break
    return float(total)


def _objective(plan: Plan, stops: list[Stop], travel: np.ndarray, depot: int | None) -> tuple:
    """What the planners maximise: mandatory stops, then profit, then little walking."""
    mandatory = sum(stops[i].mandatory for i in plan.visited)
    return mandatory, round(plan.profit(stops), 9), -plan.travel_min(travel, depot)


def simulate_day(
    order: list[int],
    stops: list[Stop],
    travel: np.ndarray,
    day: int,
    day_start: int,
    day_end: int,
    depot: int | None = None,
) -> list[tuple[Visit, str | None]]:
    """Follow a fixed order even when it is infeasible and report what goes wrong.

    Unlike :func:`schedule_day` this never gives up: a stop that is closed on that
    day gets the issue ``"closed"``, a stop reached after closing time or after
    the end of the day gets ``"late"``; the walk continues regardless, so the
    user sees the consequences of their own order.
    """
    out: list[tuple[Visit, str | None]] = []
    clock, prev = day_start, depot
    for i in order:
        arrive = clock + (round(travel[prev, i]) if prev is not None else 0)
        windows = stops[i].windows[day]
        issue: str | None = None
        start = arrive
        if windows == []:
            issue = "closed"
        elif windows is not None:
            fitting = [max(arrive, a) for a, b in windows if max(arrive, a) + stops[i].visit_min <= b]
            if fitting:
                start = fitting[0]
            else:
                issue = "late"
        leave = start + stops[i].visit_min
        if issue is None and leave > day_end:
            issue = "late"
        out.append((Visit(i, arrive, start, leave), issue))
        clock, prev = leave, i
    return out
