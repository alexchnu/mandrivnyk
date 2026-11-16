"""Relational model of the service."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Area(Base):
    """A circular region whose points of interest are loaded into ``poi``."""

    __tablename__ = "area"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    centre_lat: Mapped[float] = mapped_column(Float)  # density centre used by the relevance model
    centre_lon: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))  # "overpass" | "import"
    poi_count: Mapped[int] = mapped_column(Integer, default=0)
    wiki_status: Mapped[str] = mapped_column(String(16), default="none")  # none | pending | done
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Poi(Base):
    __tablename__ = "poi"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # "n123", "w45", "r6"
    name: Mapped[str] = mapped_column(String(300))
    name_en: Mapped[str | None] = mapped_column(String(300))
    name_uk: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=False)
    category: Mapped[str] = mapped_column(String(24), index=True)
    subtype: Mapped[str] = mapped_column(String(40))
    visit_minutes: Mapped[int] = mapped_column(SmallInteger)
    n_tags: Mapped[int] = mapped_column(SmallInteger, default=0)
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    opening_hours: Mapped[str | None] = mapped_column(Text)
    wikidata: Mapped[str | None] = mapped_column(String(20), index=True)
    sitelinks: Mapped[int] = mapped_column(Integer, default=0)
    pageviews: Mapped[int] = mapped_column(BigInteger, default=0)
    wiki_known: Mapped[bool] = mapped_column(Boolean, default=False)  # sitelinks/pageviews are filled
    relevance: Mapped[float] = mapped_column(Float, default=0.0)  # model output in [0, 1]
    relevance_model: Mapped[str] = mapped_column(String(16), default="")
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)  # {lang: {extract, image, url}}
    area_id: Mapped[int | None] = mapped_column(ForeignKey("area.id", ondelete="SET NULL"), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_poi_geom", "geom", postgresql_using="gist"),)


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trips: Mapped[list[Trip]] = relationship(back_populates="owner")


class Trip(Base):
    __tablename__ = "trip"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)  # anonymous browser id
    title: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(160), default="")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    start_date: Mapped[date | None] = mapped_column(Date)
    n_days: Mapped[int] = mapped_column(SmallInteger, default=1)
    day_start_min: Mapped[int] = mapped_column(SmallInteger, default=9 * 60)
    day_end_min: Mapped[int] = mapped_column(SmallInteger, default=19 * 60)
    share_slug: Mapped[str | None] = mapped_column(String(16), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User | None] = relationship(back_populates="trips")
    stops: Mapped[list[TripStop]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="(TripStop.day_index, TripStop.position)",
    )


class TripStop(Base):
    __tablename__ = "trip_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trip.id", ondelete="CASCADE"), index=True)
    poi_id: Mapped[str] = mapped_column(ForeignKey("poi.id", ondelete="RESTRICT"))
    day_index: Mapped[int] = mapped_column(SmallInteger, default=0)
    position: Mapped[int] = mapped_column(SmallInteger)
    visit_minutes: Mapped[int | None] = mapped_column(SmallInteger)  # user override
    note: Mapped[str] = mapped_column(String(500), default="")

    trip: Mapped[Trip] = relationship(back_populates="stops")
    poi: Mapped[Poi] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("trip_id", "poi_id", name="uq_trip_stop_poi"),)


class Feedback(Base):
    """Implicit feedback: which suggestions were added or dismissed (for future retraining)."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    poi_id: Mapped[str] = mapped_column(ForeignKey("poi.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(16))  # shown | added | removed | dismissed
    rank: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WalkLeg(Base):
    """Cache of pedestrian travel between two points (rounded to ~1 m)."""

    __tablename__ = "walk_leg"

    from_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    to_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    duration_s: Mapped[float] = mapped_column(Float)
    distance_m: Mapped[float] = mapped_column(Float)
    routed: Mapped[bool] = mapped_column(Boolean, default=True)  # False = straight-line estimate
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HttpCache(Base):
    """Generic cache of external lookups (geocoding, route geometry)."""

    __tablename__ = "http_cache"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
