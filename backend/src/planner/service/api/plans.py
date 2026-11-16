"""Route optimisation and day-by-day timetable."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import Session
from ..planning import UnknownPoi, build_plan
from ..schemas import Lang, PlanRequest, PlanResponse

router = APIRouter(tags=["planning"])


@router.post("/plans", response_model=PlanResponse)
async def make_plan(req: PlanRequest, session: Session, lang: Lang = "uk") -> PlanResponse:
    """Order the stops, split them into days and check opening hours.

    ``mode="keep_order"`` only simulates the user's own order and reports
    conflicts; ``mode="optimize"`` searches for the best order and day split.
    """
    try:
        return await build_plan(session, req, lang)
    except UnknownPoi as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown places: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
