"""Tests for TV Shows UI tree navigation, edit, and save."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from metashelf.config import Settings
from metashelf.db.models import Item, Library
from metashelf.main import create_app
from metashelf.scanner.tv import scan_tv_library


def _setup_and_login(_client: TestClient) -> str:
    return ""


async def test_tv_tree_navigation_and_save(tmp_path: Path) -> None:
    tv_root = tmp_path / "tv"
    s1_dir = tv_root / "Breaking Bad (2008)" / "Season 01"
    s1_dir.mkdir(parents=True)
    (s1_dir / "Breaking.Bad.S01E01.mkv").write_bytes(b"ep1")

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(tv_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        async with app.state.session_factory() as session:
            lib = Library(name="TV", type="tv", root_path=str(tv_root))
            session.add(lib)
            await session.commit()
            await scan_tv_library(session, lib)
            show = (
                await session.execute(select(Item).where(Item.kind == "show"))
            ).scalar_one()
            ep = (
                await session.execute(select(Item).where(Item.kind == "episode"))
            ).scalar_one()
            show_id, ep_id = show.id, ep.id

        r = client.get("/tv")
        assert r.status_code == 200
        assert "Breaking Bad" in r.text
        assert "Season 01" in r.text
        assert f'id="tv-show-children-{show_id}"' in r.text
        assert f'hx-get="/tv/{ep_id}"' in r.text
        assert "S01E01" in r.text

        # Navigate to episode in tree
        r_ep = client.get(f"/tv/{ep_id}")
        assert r_ep.status_code == 200
        assert "S01E01" in r_ep.text

        # Save tvshow.nfo
        r_save = client.post(f"/tv/{show_id}/save", headers=headers)
        assert r_save.status_code == 200
        assert (tv_root / "Breaking Bad (2008)" / "tvshow.nfo").is_file()
