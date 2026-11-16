"""Saved trips: owned by an account or by an anonymous browser id; shareable by link."""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from ..deps import Caller, CallerDep, KnownCaller, Session
from ..models import Poi, Trip, TripStop
from ..recommend import poi_out
from ..schemas import Lang, TripIn, TripOut, TripStopOut, TripSummary

router = APIRouter(prefix="/trips", tags=["trips"])
MAX_TRIPS_PER_OWNER = 200


def _owned_by(caller: Caller):
    """SQL condition: the trip belongs to the caller."""
    conditions = []
    if caller.user is not None:
        conditions.append(Trip.owner_id == caller.user.id)
    if caller.client_id is not None:
        conditions.append((Trip.client_id == caller.client_id) & Trip.owner_id.is_(None))
    return or_(*conditions)


def _can_edit(trip: Trip, caller: Caller) -> bool:
    if trip.owner_id is not None:
        return caller.user is not None and caller.user.id == trip.owner_id
    return caller.client_id is not None and caller.client_id == trip.client_id


def _trip_out(trip: Trip, lang: str, editable: bool) -> TripOut:
    stops = [
        TripStopOut(
            poi=poi_out(s.poi, lang),
            day_index=s.day_index,
            position=s.position,
            visit_minutes=s.visit_minutes,
            note=s.note,
        )  # fmt: skip
        for s in trip.stops
    ]
    cover = next(
        (
            s.poi.summary.get(lang, {}).get("image")
            for s in trip.stops
            if s.poi.summary.get(lang, {}).get("image")
        ),
        None,
    )
    return TripOut(
        id=trip.id, title=trip.title, city=trip.city, lat=trip.lat, lon=trip.lon, start_date=trip.start_date,
        n_days=trip.n_days, share_slug=trip.share_slug, updated_at=trip.updated_at, stop_count=len(stops),
        cover=cover, day_start_min=trip.day_start_min, day_end_min=trip.day_end_min, stops=stops, editable=editable,
    )  # fmt: skip


async def _apply(session: Session, trip: Trip, data: TripIn) -> None:
    if data.day_end_min - data.day_start_min < 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The day must last at least one hour")
    ids = [s.poi_id for s in data.stops]
    known = set((await session.scalars(select(Poi.id).where(Poi.id.in_(ids)))).all()) if ids else set()
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown places: {', '.join(unknown)}")
    for field in ("title", "city", "lat", "lon", "start_date", "n_days", "day_start_min", "day_end_min"):
        setattr(trip, field, getattr(data, field))
    trip.title = trip.title.strip()
    trip.stops.clear()
    await session.flush()
    position: dict[int, int] = {}
    for stop in data.stops:
        day = min(stop.day_index, data.n_days - 1)
        trip.stops.append(
            TripStop(
                poi_id=stop.poi_id,
                day_index=day,
                position=position.get(day, 0),
                visit_minutes=stop.visit_minutes,
                note=stop.note,
            )  # fmt: skip
        )
        position[day] = position.get(day, 0) + 1


async def _load(session: Session, trip_id: uuid.UUID) -> Trip:
    trip = await session.scalar(select(Trip).where(Trip.id == trip_id).options(selectinload(Trip.stops)))
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return trip


@router.get("", response_model=list[TripSummary])
async def list_trips(session: Session, caller: KnownCaller, lang: Lang = "uk") -> list[TripSummary]:
    trips = (
        await session.scalars(
            select(Trip)
            .where(_owned_by(caller))
            .options(selectinload(Trip.stops))
            .order_by(Trip.updated_at.desc())
        )
    ).all()
    out = []
    for trip in trips:
        full = _trip_out(trip, lang, True)
        out.append(TripSummary(**full.model_dump(include=set(TripSummary.model_fields))))
    return out


@router.post("", response_model=TripOut, status_code=status.HTTP_201_CREATED)
async def create_trip(data: TripIn, session: Session, caller: KnownCaller, lang: Lang = "uk") -> TripOut:
    count = await session.scalar(select(func.count()).select_from(Trip).where(_owned_by(caller)))
    if (count or 0) >= MAX_TRIPS_PER_OWNER:
        raise HTTPException(status.HTTP_409_CONFLICT, "Trip limit reached")
    trip = Trip(
        owner_id=caller.user.id if caller.user else None,
        client_id=None if caller.user else caller.client_id,
        title=data.title, lat=data.lat, lon=data.lon,
    )  # fmt: skip
    trip.stops = []
    session.add(trip)
    await _apply(session, trip, data)
    await session.commit()
    return _trip_out(await _load(session, trip.id), lang, True)


@router.get("/shared/{slug}", response_model=TripOut)
async def shared_trip(slug: str, session: Session, caller: CallerDep, lang: Lang = "uk") -> TripOut:
    trip = await session.scalar(select(Trip).where(Trip.share_slug == slug).options(selectinload(Trip.stops)))
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return _trip_out(trip, lang, _can_edit(trip, caller))


@router.get("/{trip_id}", response_model=TripOut)
async def get_trip(trip_id: uuid.UUID, session: Session, caller: CallerDep, lang: Lang = "uk") -> TripOut:
    trip = await _load(session, trip_id)
    if not _can_edit(trip, caller):
        # private trips are indistinguishable from missing ones
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return _trip_out(trip, lang, True)


@router.put("/{trip_id}", response_model=TripOut)
async def update_trip(
    trip_id: uuid.UUID, data: TripIn, session: Session, caller: CallerDep, lang: Lang = "uk"
) -> TripOut:
    trip = await _load(session, trip_id)
    if not _can_edit(trip, caller):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    await _apply(session, trip, data)
    trip.updated_at = func.now()
    await session.commit()
    session.expire_all()
    return _trip_out(await _load(session, trip_id), lang, True)


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(trip_id: uuid.UUID, session: Session, caller: CallerDep) -> None:
    trip = await _load(session, trip_id)
    if not _can_edit(trip, caller):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    await session.delete(trip)
    await session.commit()


@router.post("/{trip_id}/share", response_model=TripOut)
async def share_trip(trip_id: uuid.UUID, session: Session, caller: CallerDep, lang: Lang = "uk") -> TripOut:
    """Create (or return) a public read-only link."""
    trip = await _load(session, trip_id)
    if not _can_edit(trip, caller):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    if trip.share_slug is None:
        trip.share_slug = secrets.token_urlsafe(8)[:11]
        await session.commit()
    return _trip_out(await _load(session, trip_id), lang, True)


@router.delete("/{trip_id}/share", response_model=TripOut)
async def unshare_trip(trip_id: uuid.UUID, session: Session, caller: CallerDep, lang: Lang = "uk") -> TripOut:
    trip = await _load(session, trip_id)
    if not _can_edit(trip, caller):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    trip.share_slug = None
    await session.commit()
    return _trip_out(await _load(session, trip_id), lang, True)
