"""Authentication and CSRF dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.auth.security import (
    SESSION_COOKIE_NAME,
    read_session_cookie,
    verify_csrf_token,
)
from metashelf.db.models import User


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async DB session."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def has_any_user(session: AsyncSession) -> bool:
    count = (await session.execute(select(func.count(User.id)))).scalar_one()
    return count > 0


async def load_session_user(request: Request, session: AsyncSession) -> User | None:
    """Populate request.state.user and request.state.csrf_token from cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        request.state.user = None
        request.state.csrf_token = ""
        return None
    data = read_session_cookie(request.app.state.settings.secret_key, token)
    if not data:
        request.state.user = None
        request.state.csrf_token = ""
        return None
    user = (
        await session.execute(select(User).where(User.username == data["u"]))
    ).scalar_one_or_none()
    if user is None:
        request.state.user = None
        request.state.csrf_token = ""
        return None
    request.state.user = user
    request.state.csrf_token = data["csrf"]
    return user


class AuthRedirectError(Exception):
    """Raised when an unauthenticated browser request should redirect to login/setup."""

    def __init__(self, location: str) -> None:
        self.location = location


async def require_auth(request: Request, session: DbSession) -> User:
    """Require an authenticated user, otherwise redirect to login or setup."""
    user = await load_session_user(request, session)
    if user is not None:
        return user
    base = request.app.state.settings.base_url.rstrip("/")
    if not await has_any_user(session):
        raise AuthRedirectError(f"{base}/auth/setup")
    raise AuthRedirectError(f"{base}/auth/login")


CurrentUser = Annotated[User, Depends(require_auth)]


async def require_csrf(request: Request, _user: CurrentUser) -> None:
    """Verify CSRF token from X-CSRF-Token header or form field."""
    expected = getattr(request.state, "csrf_token", "")
    provided = request.headers.get("X-CSRF-Token")
    if not provided and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        content_type = request.headers.get("content-type", "")
        is_form = (
            "application/x-www-form-urlencoded" in content_type
            or "multipart/form-data" in content_type
        )
        if is_form:
            form = await request.form()
            raw = form.get("csrf_token")
            if isinstance(raw, str):
                provided = raw
    if not verify_csrf_token(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )
