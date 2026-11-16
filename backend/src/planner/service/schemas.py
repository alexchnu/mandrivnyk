"""Request and response models of the public API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ..taxonomy import CATEGORIES

Lang = Literal["uk", "en"]
Lat = Annotated[float, Field(ge=-90, le=90)]
Lon = Annotated[float, Field(ge=-180, le=180)]
PoiId = Annotated[str, Field(pattern=r"^[nwr]\d{1,19}$")]


class LatLon(BaseModel):
    lat: Lat
    lon: Lon


class Place(BaseModel):
    name: str
    label: str
    country: str
    country_code: str
    kind: str
    lat: float
    lon: float
    bbox: list[float] | None = None


class Summary(BaseModel):
    title: str
    extract: str
    image: str | None = None
    url: str | None = None
    lang: str


class Reason(BaseModel):
    code: Literal[
        "wiki_languages", "has_article", "close", "new_category", "open_now", "top_rated", "preference"
    ]
    value: float | None = None


class PoiOut(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    category: str
    subtype: str
    visit_minutes: int
    opening_hours: str | None = None
    is_open: bool | None = None
    website: str | None = None
    wikidata: str | None = None
    sitelinks: int = 0
    score: float | None = None
    distance_m: float | None = None
    reasons: list[Reason] = []
    summary: Summary | None = None


class RecommendRequest(BaseModel):
    lat: Lat
    lon: Lon
    radius_km: float = Field(3.0, ge=0.3, le=10.0)
    anchor: LatLon | None = Field(None, description="Current stop; closeness is measured from it")
    categories: list[str] = Field(default_factory=list, description="Empty = all categories")
    preferences: dict[str, float] = Field(default_factory=dict, description="Category weight in [-1, 2]")
    exclude_ids: list[PoiId] = Field(default_factory=list, max_length=500)
    selected_ids: list[PoiId] = Field(default_factory=list, max_length=100)
    limit: int = Field(12, ge=1, le=30)
    lang: Lang = "uk"
    open_only: bool = False
    method: Literal["xquad", "round_robin", "mmr", "top_k"] = "xquad"

    @field_validator("categories")
    @classmethod
    def _known_categories(cls, value: list[str]) -> list[str]:
        unknown = set(value) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"unknown categories: {sorted(unknown)}")
        return value

    @field_validator("preferences")
    @classmethod
    def _bounded_preferences(cls, value: dict[str, float]) -> dict[str, float]:
        return {k: max(-1.0, min(2.0, float(v))) for k, v in value.items() if k in CATEGORIES}


class RecommendResponse(BaseModel):
    items: list[PoiOut]
    total_candidates: int
    model: str
    data_status: Literal["fresh", "stale"]
    enrichment: Literal["none", "pending", "done"]


class PlanStop(BaseModel):
    poi_id: PoiId
    visit_minutes: int | None = Field(None, ge=5, le=600)
    day: int | None = Field(None, ge=0, le=13, description="Pin the stop to a day (keep_order mode)")


class PlanRequest(BaseModel):
    stops: list[PlanStop] = Field(min_length=1, max_length=60)
    optional_ids: list[PoiId] = Field(
        default_factory=list, max_length=40, description="May be added if time allows"
    )
    start: LatLon | None = Field(None, description="Where every day starts (e.g. the hotel)")
    days: int = Field(1, ge=1, le=14)
    start_date: date | None = None
    day_start: str = Field("09:00", pattern=r"^\d{2}:\d{2}$")
    day_end: str = Field("19:00", pattern=r"^\d{2}:\d{2}$")
    mode: Literal["keep_order", "optimize"] = "optimize"

    @field_validator("day_end")
    @classmethod
    def _day_window(cls, value: str, info) -> str:
        start = info.data.get("day_start", "09:00")
        if minutes(value) - minutes(start) < 60:
            raise ValueError("the day must last at least one hour")
        return value


def minutes(clock: str) -> int:
    hours, mins = clock.split(":")
    total = int(hours) * 60 + int(mins)
    if not (0 <= int(hours) <= 24 and 0 <= int(mins) < 60 and total <= 1440):
        raise ValueError(f"invalid time {clock}")
    return total


class Warning_(BaseModel):
    code: Literal["closed", "late", "waits", "unscheduled", "estimated_walk", "added"]
    poi_id: str | None = None
    day: int | None = None
    minutes: int | None = None


class VisitOut(BaseModel):
    poi: PoiOut
    arrive: int
    start: int
    leave: int
    walk_minutes: float
    walk_meters: float
    optional: bool = False


class DayOut(BaseModel):
    index: int
    date: date | None
    visits: list[VisitOut]
    walk_minutes: float
    walk_meters: float
    visit_minutes: int
    geometry: list[list[float]]


class PlanResponse(BaseModel):
    days: list[DayOut]
    warnings: list[Warning_]
    unscheduled: list[str]
    total_walk_minutes: float
    saved_walk_minutes: float | None = Field(None, description="Compared with the order given by the user")
    routed: bool


class TripStopIn(BaseModel):
    poi_id: PoiId
    day_index: int = Field(0, ge=0, le=13)
    visit_minutes: int | None = Field(None, ge=5, le=600)
    note: str = Field("", max_length=500)


class TripIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    city: str = Field("", max_length=160)
    lat: Lat
    lon: Lon
    start_date: date | None = None
    n_days: int = Field(1, ge=1, le=14)
    day_start_min: int = Field(540, ge=0, le=1380)
    day_end_min: int = Field(1140, ge=60, le=1440)
    stops: list[TripStopIn] = Field(default_factory=list, max_length=60)

    @field_validator("stops")
    @classmethod
    def _unique_stops(cls, value: list[TripStopIn]) -> list[TripStopIn]:
        ids = [s.poi_id for s in value]
        if len(ids) != len(set(ids)):
            raise ValueError("a place can be added to a trip only once")
        return value


class TripStopOut(BaseModel):
    poi: PoiOut
    day_index: int
    position: int
    visit_minutes: int | None
    note: str


class TripSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    city: str
    lat: float
    lon: float
    start_date: date | None
    n_days: int
    share_slug: str | None
    updated_at: datetime
    stop_count: int = 0
    cover: str | None = None


class TripOut(TripSummary):
    day_start_min: int
    day_end_min: int
    stops: list[TripStopOut]
    editable: bool = True


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def _stripped(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str


class AuthOut(BaseModel):
    token: str
    user: UserOut
    claimed_trips: int = 0


class FeedbackIn(BaseModel):
    poi_id: PoiId
    action: Literal["shown", "added", "removed", "dismissed"]
    rank: int | None = Field(None, ge=0, le=100)
