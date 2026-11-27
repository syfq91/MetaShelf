"""Tests for batch actions, dry-run, and diff preview."""

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from metashelf.config import Settings
from metashelf.db.models import Item, Library
from metashelf.domain.models import ItemState, MovieMetadata
from metashelf.main import create_app
from metashelf.scanner.movie import scan_movie_library
from metashelf.services.batch import execute_batch_action, preview_batch_diff


def _setup_and_login(client: TestClient) -> str:
    resp = client.post(
        "/auth/setup",
        data={
            "username": "admin",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=True,
    )
    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', resp.text)
    assert match is not None
    return match.group(1)


async def test_batch_dry_run_diff_preview_does_not_touch_disk(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    m1_dir = media_root / "Inception (2010)"
    m2_dir = media_root / "Matrix (1999)"
    m1_dir.mkdir(parents=True)
    m2_dir.mkdir(parents=True)
    (m1_dir / "Inception (2010).mkv").write_bytes(b"video1")
    (m2_dir / "Matrix (1999).mkv").write_bytes(b"video2")
    nfo1 = m1_dir / "Inception (2010).nfo"
    nfo1.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<movie><title>Inception</title><year>2010</year></movie>\n",
        encoding="utf-8",
    )

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app):
        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            await scan_movie_library(session, lib)

            from sqlalchemy import select

            items = list((await session.scalars(select(Item).order_by(Item.id))).all())
            assert len(items) == 2

            # Modify metadata in DB without saving
            meta1 = MovieMetadata.model_validate_json(items[0].metadata_json)
            meta1.title = "Inception Updated"
            meta1.plot = "A thief who steals corporate secrets."
            items[0].metadata_json = meta1.model_dump_json()
            items[0].title = meta1.title
            items[0].state = ItemState.DIRTY.value
            await session.commit()

            result = await preview_batch_diff(session, [items[0].id, items[1].id], action="save")
            assert result.dry_run is True
            assert len(result.previews) == 2
            assert result.previews[0].has_changes is True
            assert "Inception Updated" in result.previews[0].diff_text
            assert "+" in result.previews[0].diff_text
            # Disk must not be touched
            assert "Inception Updated" not in nfo1.read_text(encoding="utf-8")
            assert not (m2_dir / "Matrix (1999).nfo").exists()


async def test_batch_route_dry_run_and_live_save(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    m1_dir = media_root / "Inception (2010)"
    m2_dir = media_root / "Matrix (1999)"
    m1_dir.mkdir(parents=True)
    m2_dir.mkdir(parents=True)
    (m1_dir / "Inception (2010).mkv").write_bytes(b"video1")
    (m2_dir / "Matrix (1999).mkv").write_bytes(b"video2")

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app) as client:
        csrf = _setup_and_login(client)
        headers = {"X-CSRF-Token": csrf}

        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            await scan_movie_library(session, lib)

            from sqlalchemy import select

            items = list((await session.scalars(select(Item).order_by(Item.id))).all())
            for item in items:
                meta = MovieMetadata.model_validate_json(item.metadata_json)
                meta.plot = f"Plot for {meta.title}"
                item.metadata_json = meta.model_dump_json()
                item.state = ItemState.DIRTY.value
            await session.commit()
            ids = [str(item.id) for item in items]

        # Dry-run via route
        r_dry = client.post(
            "/movies/batch",
            headers=headers,
            data={"item_ids": ids, "action": "save", "dry_run": "true"},
        )
        assert r_dry.status_code == 200
        assert "Dry-run preview" in r_dry.text
        assert "Plot for Inception" in r_dry.text
        assert not (m1_dir / "Inception (2010).nfo").exists()

        # Live save via route
        r_live = client.post(
            "/movies/batch",
            headers=headers,
            data={"item_ids": ids, "action": "save", "dry_run": "false"},
        )
        assert r_live.status_code == 200
        assert "Applied to 2 item(s)" in r_live.text
        assert (m1_dir / "Inception (2010).nfo").exists()
        assert (m2_dir / "Matrix (1999).nfo").exists()
        assert "Plot for Inception" in (m1_dir / "Inception (2010).nfo").read_text(encoding="utf-8")

        # Verify states are no longer dirty
        async with app.state.session_factory() as session:
            from sqlalchemy import select

            updated = list((await session.scalars(select(Item).order_by(Item.id))).all())
            assert all(it.state != ItemState.DIRTY.value for it in updated)


async def test_batch_auto_match_dry_run(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    m1_dir = media_root / "Inception (2010)"
    m1_dir.mkdir(parents=True)
    (m1_dir / "Inception (2010).mkv").write_bytes(b"video1")

    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app):
        async with app.state.session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            await scan_movie_library(session, lib)

            from sqlalchemy import select

            item = await session.scalar(select(Item))
            assert item is not None
            res = await execute_batch_action(
                session,
                [item.id],
                action="auto_match",
                dry_run=True,
            )
            assert res.dry_run is True
            assert len(res.previews) == 1
            assert "Would auto-match" in res.previews[0].diff_text
            assert json.loads(item.provider_ids_json) == {}
