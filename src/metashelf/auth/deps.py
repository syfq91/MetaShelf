"""Database session and request dependencies (no built-in auth; use reverse proxy if needed)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async DB session."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def require_auth() -> None:
    """No-op dependency kept for route compatibility (local LAN / reverse-proxy auth)."""
    return None


CurrentUser = Annotated[None, Depends(require_auth)]


async def require_csrf() -> None:
    """No-op dependency kept for route compatibility."""
    return None
