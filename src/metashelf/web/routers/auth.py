"""Auth routes: first-run setup, login, logout."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from metashelf.auth.deps import DbSession, has_any_user, load_session_user, require_csrf
from metashelf.auth.security import (
    SESSION_COOKIE_NAME,
    create_session_cookie,
    hash_password,
    verify_password,
)
from metashelf.db.models import User
from metashelf.web.templating import render_template

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, session: DbSession) -> Response:
    """Render first-run admin account setup page."""
    base = request.app.state.settings.base_url.rstrip("/")
    if await has_any_user(session):
        return RedirectResponse(f"{base}/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    return render_template(request, "auth/setup.html")


@router.post("/setup", response_class=HTMLResponse)
async def setup_submit(
    request: Request,
    session: DbSession,
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
) -> Response:
    """Create the initial admin password."""
    base = request.app.state.settings.base_url.rstrip("/")
    if await has_any_user(session):
        return RedirectResponse(f"{base}/auth/login", status_code=status.HTTP_303_SEE_OTHER)

    if len(password) < 8:
        return render_template(
            request,
            "auth/setup.html",
            {"error": "Password must be at least 8 characters."},
            status_code=400,
        )
    if password != password_confirm:
        return render_template(
            request,
            "auth/setup.html",
            {"error": "Passwords do not match."},
            status_code=400,
        )

    user = User(username="admin", password_hash=hash_password(password))
    session.add(user)
    await session.commit()

    token = create_session_cookie(request.app.state.settings.secret_key, user.username)
    resp = RedirectResponse(f"{base}/", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return resp


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: DbSession) -> Response:
    """Render login page (or redirect to setup if no user exists)."""
    base = request.app.state.settings.base_url.rstrip("/")
    if not await has_any_user(session):
        return RedirectResponse(f"{base}/auth/setup", status_code=status.HTTP_303_SEE_OTHER)
    user = await load_session_user(request, session)
    if user is not None:
        return RedirectResponse(f"{base}/", status_code=status.HTTP_303_SEE_OTHER)
    return render_template(request, "auth/login.html")


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    session: DbSession,
    password: Annotated[str, Form()],
) -> Response:
    """Authenticate with the configured access password."""
    base = request.app.state.settings.base_url.rstrip("/")
    if not await has_any_user(session):
        return RedirectResponse(f"{base}/auth/setup", status_code=status.HTTP_303_SEE_OTHER)

    limiter = request.app.state.login_limiter
    client_ip = request.client.host if request.client else "unknown"
    if limiter.is_limited(client_ip):
        return render_template(
            request,
            "auth/login.html",
            {"error": "Too many failed login attempts. Please wait a minute."},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = (
        await session.execute(select(User).order_by(User.id).limit(1))
    ).scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        limiter.record_failure(client_ip)
        return render_template(
            request,
            "auth/login.html",
            {"error": "Invalid password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    limiter.reset(client_ip)
    token = create_session_cookie(request.app.state.settings.secret_key, user.username)
    resp = RedirectResponse(f"{base}/", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/logout")
async def logout(request: Request, session: DbSession) -> Response:
    """Clear the session cookie."""
    user = await load_session_user(request, session)
    if user is not None:
        await require_csrf(request, user)
    base = request.app.state.settings.base_url.rstrip("/")
    resp = RedirectResponse(f"{base}/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp
