"""Place search, categories, recommendations and feedback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ...taxonomy import CATEGORIES, RULES
from ..deps import CallerDep, Session, client_ip
from ..models import Feedback, HttpCache, Poi
from ..providers import photon
from ..providers.http import ProviderError
from ..recommend import recommend
from ..schemas import FeedbackIn, Lang, Place, RecommendRequest, RecommendResponse
from ..security import RateLimiter

router = APIRouter(tags=["discovery"])
_search_limiter = RateLimiter(limit=60, window_s=60)
_GEOCODE_TTL = timedelta(days=30)


@router.get("/categories")
async def categories() -> list[dict]:
    """Category taxonomy with the OSM tags behind every category."""
    return [
        {"id": cat, "subtypes": sorted({r.value for r in RULES if r.category == cat})} for cat in CATEGORIES
    ]


@router.get("/places", response_model=list[Place])
async def search_places(
    request: Request,
    session: Session,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    lang: Lang = "uk",
) -> list[dict]:
    """City search-as-you-type (cached server-side proxy for Photon)."""
    if not _search_limiter.allow(client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many search requests")
    key = f"place:{lang}:{q.strip().casefold()}"[:200]
    hit = await session.get(HttpCache, key)
    if hit is not None and hit.created_at > datetime.now(UTC) - _GEOCODE_TTL:
        return hit.payload["items"]
    try:
        items = await photon.search(q.strip(), "en" if lang == "en" else "default")
    except ProviderError as exc:
        if hit is not None:
            return hit.payload["items"]
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    stmt = insert(HttpCache).values(key=key, kind="place", payload={"items": items})
    stmt = stmt.on_conflict_do_update(
        index_elements=[HttpCache.key],
        set_={"payload": stmt.excluded.payload, "created_at": datetime.now(UTC)},
    )
    await session.execute(stmt)
    await session.commit()
    return items


@router.post("/recommendations", response_model=RecommendResponse)
async def recommendations(req: RecommendRequest, session: Session) -> RecommendResponse:
    """A diversified page of places around a point, aware of what is already in the trip."""
    try:
        return await recommend(session, req)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(items: list[FeedbackIn], session: Session, caller: CallerDep) -> None:
    """Implicit feedback (shown / added / removed / dismissed) for later model retraining."""
    if not items or len(items) > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "1..100 feedback items expected")
    known = set((await session.scalars(select(Poi.id).where(Poi.id.in_([i.poi_id for i in items])))).all())
    session.add_all(
        Feedback(
            client_id=caller.client_id,
            user_id=caller.user.id if caller.user else None,
            poi_id=i.poi_id,
            action=i.action,
            rank=i.rank,
        )  # fmt: skip
        for i in items
        if i.poi_id in known
    )
    await session.commit()
