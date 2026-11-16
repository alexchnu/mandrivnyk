"""Ordering of already chosen stops: an open-path travelling salesman problem.

The traveller starts at a fixed stop (index ``start``) and may finish anywhere,
or at a fixed ``end``. ``cost`` is a square matrix of travel costs (seconds or
metres), not necessarily symmetric.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2


def path_cost(cost: np.ndarray, order: list[int]) -> float:
    return float(sum(cost[a, b] for a, b in zip(order[:-1], order[1:])))


def nearest_neighbour(cost: np.ndarray, start: int = 0, end: int | None = None) -> list[int]:
    n = len(cost)
    todo = set(range(n)) - {start} - ({end} if end is not None else set())
    order = [start]
    while todo:
        nxt = min(todo, key=lambda j: (cost[order[-1], j], j))
        order.append(nxt)
        todo.remove(nxt)
    if end is not None and end != start:
        order.append(end)
    return order


def two_opt(cost: np.ndarray, order: list[int], fixed_end: bool = False, max_rounds: int = 100) -> list[int]:
    """2-opt local search on an open path; the first stop stays in place."""
    order = list(order)
    n = len(order)
    last = n - 1 if fixed_end else n
    symmetric = np.allclose(cost, cost.T)
    for _ in range(max_rounds):
        improved = False
        for i in range(1, last - 1):
            for j in range(i + 1, last):
                if symmetric:
                    a, b = order[i - 1], order[i]
                    c = order[j]
                    d = order[j + 1] if j + 1 < n else None
                    delta = cost[a, c] - cost[a, b]
                    if d is not None:
                        delta += cost[b, d] - cost[c, d]
                else:
                    candidate = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                    delta = path_cost(cost, candidate) - path_cost(cost, order)
                if delta < -1e-9:
                    order[i : j + 1] = order[i : j + 1][::-1]
                    improved = True
        if not improved:
            break
    return order


def held_karp(cost: np.ndarray, start: int = 0, end: int | None = None) -> list[int]:
    """Exact dynamic programming, O(n^2 * 2^n); practical up to ~15 stops."""
    n = len(cost)
    others = [i for i in range(n) if i != start]
    if not others:
        return [start]
    best: dict[tuple[int, int], tuple[float, int]] = {}
    for j in others:
        best[(1 << j, j)] = (cost[start, j], start)
    for size in range(2, len(others) + 1):
        for subset in combinations(others, size):
            mask = sum(1 << j for j in subset)
            for j in subset:
                prev_mask = mask ^ (1 << j)
                best[(mask, j)] = min((best[(prev_mask, k)][0] + cost[k, j], k) for k in subset if k != j)
    full = sum(1 << j for j in others)
    last = end if end is not None and end != start else min(others, key=lambda j: best[(full, j)][0])
    order, mask = [], full
    while last != start:
        order.append(last)
        prev = best[(mask, last)][1]
        mask ^= 1 << last
        last = prev
    return [start, *reversed(order)]


def ortools_path(cost: np.ndarray, start: int = 0, end: int | None = None, time_limit_s: float = 1.0) -> list[int]:
    """Open-path TSP with OR-Tools (guided local search metaheuristic)."""
    n = len(cost)
    if n <= 2:
        return nearest_neighbour(cost, start, end)
    scale = 10.0 if float(np.max(cost)) < 1e7 else 1.0  # the solver needs integer costs
    free_end = end is None
    size = n + 1 if free_end else n
    finish = n if free_end else end
    manager = pywrapcp.RoutingIndexManager(size, 1, [start], [finish])
    routing = pywrapcp.RoutingModel(manager)

    def transit(i: int, j: int) -> int:
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        if a >= n or b >= n:  # dummy finish node: leaving the path costs nothing
            return 0
        return int(round(cost[a, b] * scale))

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(transit))
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    solution = routing.SolveWithParameters(params)
    if solution is None:
        return two_opt(cost, nearest_neighbour(cost, start, end), fixed_end=end is not None)
    order, index = [], routing.Start(0)
    while not routing.IsEnd(index):
        order.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    if not free_end:
        order.append(end)
    return order


def optimise_order(cost: np.ndarray, start: int = 0, end: int | None = None, time_limit_s: float = 1.0) -> list[int]:
    """Production entry point: exact for small trips, OR-Tools otherwise."""
    if len(cost) <= 10:
        return held_karp(cost, start, end)
    return ortools_path(cost, start, end, time_limit_s)
