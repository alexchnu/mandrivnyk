"""Trip planning use case: order of stops, day split, timetable and warnings."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import logging
from datetime import timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import hours
from ..geo import distance_matrix_m
from ..routing import order as ordering
from ..routing.toptw import Stop, Visit, hybrid_plan, simulate_day
from .config import get_settings
from .models import HttpCache, Poi, WalkLeg
from .providers import osrm
from .providers.http import ProviderError
from .recommend import local_now, poi_out
from .schemas import DayOut, PlanRequest, PlanResponse, VisitOut, Warning_, minutes

log = logging.getLogger(__name__)
Point = tuple[float, float]
MAX_ROUTED_POINTS = 80


class UnknownPoi(LookupError):
    pass


def _key(p: Point) -> str:
    return f"{p[0]:.5f},{p[1]:.5f}"


def estimate_matrix(points: list[Point]) -> tuple[np.ndarray, np.ndarray]:
    """Straight-line fallback: distance x detour factor at an average walking speed."""
    settings = get_settings()
    dist = distance_matrix_m([p[0] for p in points], [p[1] for p in points]) * settings.detour_factor
    return dist / settings.walk_speed_m_s, dist


async def travel_matrix(session: AsyncSession, points: list[Point]) -> tuple[np.ndarray, np.ndarray, bool]:
    """Walking duration (s) and distance (m) between all points; third value = really routed."""
    n = len(points)
    if n < 2:
        return np.zeros((n, n)), np.zeros((n, n)), True
    keys = [_key(p) for p in points]
    index = {k: i for i, k in enumerate(keys)}
    duration = np.full((n, n), np.nan)
    distance = np.full((n, n), np.nan)
    np.fill_diagonal(duration, 0.0)
    np.fill_diagonal(distance, 0.0)
    cached = await session.execute(
        select(WalkLeg.from_key, WalkLeg.to_key, WalkLeg.duration_s, WalkLeg.distance_m).where(
            WalkLeg.from_key.in_(keys), WalkLeg.to_key.in_(keys)
        )
    )
    for a, b, dur, dist in cached:
        duration[index[a], index[b]] = dur
        distance[index[a], index[b]] = dist
    for a in range(n):  # duplicate coordinates share a key
        for b in range(n):
            if keys[a] == keys[b]:
                duration[a, b] = distance[a, b] = 0.0
    if not np.isnan(duration).any():
        return duration, distance, True

    est_duration, est_distance = estimate_matrix(points)
    if n > MAX_ROUTED_POINTS:
        return est_duration, est_distance, False
    try:
        duration, distance = await osrm.table(points)
    except ProviderError as exc:
        log.warning("using straight-line estimates: %s", exc)
        return est_duration, est_distance, False
    unreachable = np.isnan(duration) | np.isnan(distance)
    duration[unreachable] = est_duration[unreachable]
    distance[unreachable] = est_distance[unreachable]
    rows = [
        {"from_key": keys[a], "to_key": keys[b], "duration_s": float(duration[a, b]),
         "distance_m": float(distance[a, b]), "routed": not bool(unreachable[a, b])}
        for a in range(n) for b in range(n) if keys[a] != keys[b]
    ]  # fmt: skip
    unique = {(r["from_key"], r["to_key"]): r for r in rows}
    payload = list(unique.values())
    for start in range(0, len(payload), 1000):
        await session.execute(insert(WalkLeg).values(payload[start : start + 1000]).on_conflict_do_nothing())
    await session.commit()
    return duration, distance, True


async def path_geometry(session: AsyncSession, points: list[Point]) -> list[list[float]]:
    """Street-level polyline through the points; straight segments when routing is down."""
    straight = [[lat, lon] for lat, lon in points]
    if len(points) < 2:
        return straight
    key = "route:" + hashlib.sha1("|".join(_key(p) for p in points).encode()).hexdigest()
    hit = await session.get(HttpCache, key)
    if hit is not None:
        return hit.payload["geometry"]
    try:
        data = await osrm.route(points)
    except ProviderError:
        return straight
    await session.execute(
        insert(HttpCache)
        .values(key=key, kind="route", payload={"geometry": data["geometry"]})
        .on_conflict_do_nothing()
    )
    await session.commit()
    return data["geometry"]


def _shortest_order(cost: np.ndarray, has_depot: bool) -> list[int]:
    """Shortest open path over all stops; without a depot the first stop is free too."""
    n = len(cost)
    if has_depot:
        return ordering.optimise_order(cost, 0)[1:]
    padded = np.zeros((n + 1, n + 1))
    padded[1:, 1:] = cost
    return [i - 1 for i in ordering.optimise_order(padded, 0)[1:]]


async def build_plan(session: AsyncSession, req: PlanRequest, lang: str = "uk") -> PlanResponse:
    ids = [s.poi_id for s in req.stops]
    optional_ids = [i for i in dict.fromkeys(req.optional_ids) if i not in set(ids)]
    found = {
        p.id: p for p in (await session.scalars(select(Poi).where(Poi.id.in_(ids + optional_ids)))).all()
    }
    missing = [i for i in ids + optional_ids if i not in found]
    if missing:
        raise UnknownPoi(", ".join(missing))
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate stops")

    pois = [found[i] for i in ids + optional_ids]
    n_user = len(ids)
    has_depot = req.start is not None
    points: list[Point] = ([(req.start.lat, req.start.lon)] if has_depot else []) + [
        (p.lat, p.lon) for p in pois
    ]
    duration_s, distance_m, routed = await travel_matrix(session, points)
    travel_min = duration_s / 60.0
    offset = 1 if has_depot else 0
    depot = 0 if has_depot else None

    day_start, day_end = minutes(req.day_start), minutes(req.day_end)
    first_day = req.start_date or local_now(pois[0].lat, pois[0].lon).date()
    weekdays = [(first_day + timedelta(days=d)).weekday() for d in range(req.days)]
    stops: list[Stop] = [Stop(0.0, 0, [None] * req.days)] if has_depot else []
    for k, poi in enumerate(pois):
        week = hours.parse(poi.opening_hours)
        windows = [hours.intervals_for_day(week, wd) for wd in weekdays]
        visit = (req.stops[k].visit_minutes if k < n_user else None) or poi.visit_minutes
        stops.append(
            Stop(profit=max(poi.relevance, 0.01), visit_min=int(visit), windows=windows, mandatory=k < n_user)
        )

    user_nodes = [offset + k for k in range(n_user)]

    def keep_order_days() -> list[list[int]]:
        days: list[list[int]] = [[] for _ in range(req.days)]
        for k, stop in enumerate(req.stops):
            days[min(stop.day or 0, req.days - 1)].append(offset + k)
        return days

    def walk_of(days: list[list[int]]) -> float:
        total = 0.0
        for seq in days:
            path = ([depot] if depot is not None else []) + seq
            total += sum(travel_min[a, b] for a, b in itertools.pairwise(path))
        return float(total)

    unscheduled: list[int] = []
    saved: float | None = None
    if req.mode == "keep_order":
        day_orders = keep_order_days()
    else:
        day_orders = []
        if req.days == 1 and not optional_ids:
            sub = travel_min[
                np.ix_(([0] if has_depot else []) + user_nodes, ([0] if has_depot else []) + user_nodes)
            ]
            best = [
                user_nodes[i - offset] if has_depot else user_nodes[i]
                for i in await asyncio.to_thread(_shortest_order, sub, has_depot)
            ]
            checked = simulate_day(best, stops, travel_min, 0, day_start, day_end, depot)
            if all(issue is None for _, issue in checked):
                day_orders = [best]
        if not day_orders:
            # the solvers are CPU-bound: a worker thread keeps the event loop free for other requests
            plan = await asyncio.to_thread(
                hybrid_plan, stops, travel_min, req.days, day_start, day_end, depot, time_limit_s=1.0
            )
            day_orders = [[v.stop for v in day] for day in plan.days]
            unscheduled = [i for i in plan.skipped if i in set(user_nodes)]
        if req.days == 1 and not unscheduled:
            saved = round(
                walk_of(keep_order_days()) - walk_of([[i for i in day_orders[0] if i in set(user_nodes)]]), 1
            )

    now = local_now(pois[0].lat, pois[0].lon)
    warnings: list[Warning_] = []
    days_out: list[DayOut] = []
    for d, seq in enumerate(day_orders):
        visits: list[VisitOut] = []
        prev = depot
        for visit, issue in simulate_day(seq, stops, travel_min, d, day_start, day_end, depot):
            poi = pois[visit.stop - offset]
            optional = visit.stop - offset >= n_user
            walk_m = float(distance_m[prev, visit.stop]) if prev is not None else 0.0
            walk_min = float(travel_min[prev, visit.stop]) if prev is not None else 0.0
            visits.append(
                VisitOut(
                    poi=poi_out(poi, lang, now),
                    arrive=visit.arrive,
                    start=visit.start,
                    leave=visit.leave,
                    walk_minutes=round(walk_min, 1),
                    walk_meters=round(walk_m),
                    optional=optional,
                )  # fmt: skip
            )
            if issue:
                warnings.append(Warning_(code=issue, poi_id=poi.id, day=d))  # type: ignore[arg-type]
            elif visit.start - visit.arrive >= 10:
                warnings.append(
                    Warning_(code="waits", poi_id=poi.id, day=d, minutes=visit.start - visit.arrive)
                )
            if optional:
                warnings.append(Warning_(code="added", poi_id=poi.id, day=d))
            prev = visit.stop
        path = ([points[0]] if has_depot else []) + [points[i] for i in seq]
        geometry = await path_geometry(session, path) if routed else [[lat, lon] for lat, lon in path]
        days_out.append(
            DayOut(
                index=d,
                date=first_day + timedelta(days=d) if req.start_date else None,
                visits=visits,
                walk_minutes=round(sum(v.walk_minutes for v in visits), 1),
                walk_meters=round(sum(v.walk_meters for v in visits)),
                visit_minutes=sum(v.leave - v.start for v in visits),
                geometry=geometry,
            )
        )
    for node in unscheduled:
        warnings.append(Warning_(code="unscheduled", poi_id=pois[node - offset].id))
    if not routed:
        warnings.append(Warning_(code="estimated_walk"))
    return PlanResponse(
        days=days_out,
        warnings=warnings,
        unscheduled=[pois[node - offset].id for node in unscheduled],
        total_walk_minutes=round(sum(d.walk_minutes for d in days_out), 1),
        saved_walk_minutes=saved,
        routed=routed,
    )


__all__ = ["UnknownPoi", "Visit", "build_plan", "estimate_matrix", "path_geometry", "travel_matrix"]
