"""Tests for accessibility attributes, keyboard shortcuts, empty states, and error toasts."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


def _setup_and_login(client: TestClient) -> None:
    resp = client.post(
        "/auth/setup",
        data={
            "username": "admin",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=True,
    )
    assert re.search(r'"X-CSRF-Token":\s*"([^"]+)"', resp.text) is not None


def test_accessibility_shortcuts_empty_states_and_error_toasts(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        _setup_and_login(client)

        r = client.get("/movies")
        assert r.status_code == 200
        # Accessibility & ARIA
        assert 'aria-live="polite"' in r.text
        assert 'role="listbox"' in r.text
        assert "Skip to main content" in r.text
        # Empty state
        assert "No movies found" in r.text
        # Keyboard shortcuts & HTMX error toast listener
        assert "ArrowDown" in r.text
        assert "ArrowUp" in r.text
        assert "htmx:responseError" in r.text
        assert 'e.key.toLowerCase() === "s"' in r.text
