"""Registration and sign-in. Anonymous trips of the browser are attached to the account."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..deps import CallerDep, CurrentUser, Session, client_ip
from ..models import Trip, User
from ..schemas import AuthOut, LoginIn, RegisterIn, UserOut
from ..security import RateLimiter, create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = RateLimiter(limit=10, window_s=300)
_DUMMY_HASH = hash_password("timing-equaliser")


async def _claim_trips(session: Session, user: User, client_id: str | None) -> int:
    if not client_id:
        return 0
    result = await session.execute(
        update(Trip).where(Trip.client_id == client_id, Trip.owner_id.is_(None)).values(owner_id=user.id)
    )
    return result.rowcount or 0


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, request: Request, session: Session, caller: CallerDep) -> AuthOut:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
    user = User(
        email=data.email.lower(), display_name=data.display_name, password_hash=hash_password(data.password)
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This email is already registered") from exc
    claimed = await _claim_trips(session, user, caller.client_id)
    await session.commit()
    return AuthOut(token=create_token(user.id), user=UserOut.model_validate(user), claimed_trips=claimed)


@router.post("/login", response_model=AuthOut)
async def login(data: LoginIn, request: Request, session: Session, caller: CallerDep) -> AuthOut:
    if not limiter.allow(client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again later")
    user = await session.scalar(select(User).where(User.email == data.email.lower()))
    # verify against a dummy hash when the user is unknown: equal work, no account enumeration by timing
    valid = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    claimed = await _claim_trips(session, user, caller.client_id)
    await session.commit()
    return AuthOut(token=create_token(user.id), user=UserOut.model_validate(user), claimed_trips=claimed)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
