"""Tests for FastAPI app factory, config loading, and /healthz."""

from pathlib import Path

from fastapi.testclient import TestClient

from metashelf import __version__
from metashelf.config import Settings
from metashelf.main import create_app


def test_healthz_returns_ok(tmp_path: Path) -> None:
    settings = Settings(config_dir=tmp_path / "config", media_roots=str(tmp_path / "media"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}


def test_settings_env_override(monkeypatch: object, tmp_path: Path) -> None:
    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setenv("METASHELF_TMDB_API_KEY", "test-key")
    settings = Settings(config_dir=tmp_path)
    assert settings.tmdb_api_key == "test-key"
    assert settings.resolved_database_url == f"sqlite+aiosqlite:///{tmp_path / 'metashelf.db'}"
