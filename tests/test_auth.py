"""Tests for first-run setup, login, logout, CSRF protection, and rate limiting."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


def _extract_csrf(html: str) -> str:
    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', html)
    assert match is not None, "CSRF token not found in HTML"
    return match.group(1)


def test_auth_lifecycle_and_csrf(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config", media_roots=str(tmp_path / "media"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        # 1. Unauthenticated -> redirects to setup
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].endswith("/auth/setup")

        # 2. Setup creates admin and logs in
        r = client.post(
            "/auth/setup",
            data={
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        csrf = _extract_csrf(r.text)

        # 3. Logout without CSRF fails with 403
        r_bad = client.post("/auth/logout", follow_redirects=False)
        assert r_bad.status_code == 403

        # 4. Logout with CSRF succeeds
        r_out = client.post(
            "/auth/logout",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert r_out.status_code == 303
        assert r_out.headers["location"].endswith("/auth/login")

        # 5. Unauthenticated now redirects to /auth/login
        r_home = client.get("/", follow_redirects=False)
        assert r_home.status_code == 303
        assert r_home.headers["location"].endswith("/auth/login")

        # 6. Login with valid password succeeds
        r_in = client.post(
            "/auth/login",
            data={"password": "password123"},
            follow_redirects=True,
        )
        assert r_in.status_code == 200
        assert "Welcome to MetaShelf" in r_in.text


def test_login_rate_limiting(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config", media_roots=str(tmp_path / "media"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        client.post(
            "/auth/setup",
            data={
                "password": "password123",
                "password_confirm": "password123",
            },
        )
        client.cookies.clear()

        for _ in range(5):
            resp = client.post(
                "/auth/login",
                data={"password": "wrong"},
            )
            assert resp.status_code == 401

        blocked = client.post(
            "/auth/login",
            data={"password": "password123"},
        )
        assert blocked.status_code == 429
