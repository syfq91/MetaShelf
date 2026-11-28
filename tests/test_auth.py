"""Tests for auth-free local LAN / reverse-proxy access."""

from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


def test_direct_access_without_login(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 200
        assert "Welcome to MetaShelf" in r.text
        assert "Logout" not in r.text

        assert client.get("/auth/setup", follow_redirects=False).status_code == 404
        assert client.get("/auth/login", follow_redirects=False).status_code == 404

        r_prefs = client.post(
            "/settings/preferences",
            data={"language": "en-US", "movie_naming": "file"},
        )
        assert r_prefs.status_code == 200
