"""Tests for the base HTML layout shell."""

from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


def test_base_shell_renders_after_setup(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config", media_roots=str(tmp_path / "media"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/auth/setup")

        setup_resp = client.post(
            "/auth/setup",
            data={
                "username": "admin",
                "password": "supersecretpassword",
                "password_confirm": "supersecretpassword",
            },
            follow_redirects=True,
        )
        assert setup_resp.status_code == 200
        assert "MetaShelf" in setup_resp.text
        assert "toggleTheme()" in setup_resp.text
        assert "Movies" in setup_resp.text
        assert "Settings" in setup_resp.text
