"""Request-scoped dependencies: database session, caller identity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import User
from .security import read_token

Session = Annotated[AsyncSession, Depends(get_session)]
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@dataclass(slots=True)
class Caller:
    """Who makes the request: a signed-in user and/or an anonymous browser id."""

    user: User | None
    client_id: str | None

    @property
    def known(self) -> bool:
        return self.user is not None or self.client_id is not None


async def get_caller(
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
    x_client_id: Annotated[str | None, Header()] = None,
) -> Caller:
    user: User | None = None
    if authorization:
        scheme, _, token = authorization.partition(" ")
        user_id = read_token(token) if scheme.lower() == "bearer" else None
        user = await session.get(User, user_id) if user_id else None
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    client_id = x_client_id if x_client_id and _CLIENT_ID.match(x_client_id) else None
    return Caller(user, client_id)


async def require_user(caller: Annotated[Caller, Depends(get_caller)]) -> User:
    if caller.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return caller.user


async def require_caller(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    if not caller.known:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Client-Id header or sign-in required")
    return caller


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )


CallerDep = Annotated[Caller, Depends(get_caller)]
KnownCaller = Annotated[Caller, Depends(require_caller)]
CurrentUser = Annotated[User, Depends(require_user)]
