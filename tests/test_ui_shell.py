"""Tests for the base HTML layout shell."""

from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


def test_base_shell_renders_directly(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 200
        assert "MetaShelf" in resp.text
        assert "toggleTheme()" in resp.text
        assert "Movies" in resp.text
        assert "Settings" in resp.text
        assert "Logout" not in resp.text
