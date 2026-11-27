"""Tests for the base HTML layout shell."""

from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.main import create_app


def test_base_shell_renders(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config", media_roots=str(tmp_path / "media"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "MetaShelf" in resp.text
    assert "toggleTheme()" in resp.text
