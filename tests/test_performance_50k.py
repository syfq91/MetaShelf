"""Performance test for paginated and indexed queries over 50,000 synthetic items."""

import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import insert, text

from metashelf.config import Settings
from metashelf.db.models import Item, Library
from metashelf.domain.models import ItemKind, ItemState
from metashelf.main import create_app
from metashelf.web.routers.movies import PAGE_SIZE, _build_movie_query


async def test_50k_synthetic_library_paginated_and_indexed(tmp_path: Path) -> None:
    media_root = tmp_path / "movies"
    media_root.mkdir()
    app_settings = Settings(config_dir=tmp_path / "config", media_roots=str(media_root))
    app = create_app(settings=app_settings)

    with TestClient(app):
        async with app.state.session_factory() as session:
            lib = Library(name="PerfMovies", type="movie", root_path=str(media_root))
            session.add(lib)
            await session.commit()
            lib_id = lib.id

            # Bulk insert 50,000 synthetic items
            batch_size = 5000
            for start in range(0, 50_000, batch_size):
                rows = [
                    {
                        "library_id": lib_id,
                        "kind": ItemKind.MOVIE.value,
                        "rel_path": f"Movie {i:05d}/Movie {i:05d}.mkv",
                        "title": f"Movie {i:05d}",
                        "year": 1980 + (i % 45),
                        "state": (
                            ItemState.DIRTY.value if i % 100 == 0 else ItemState.COMPLETE.value
                        ),
                        "provider_ids_json": "{}",
                        "metadata_json": "{}",
                    }
                    for i in range(start, start + batch_size)
                ]
                await session.execute(insert(Item), rows)
            await session.commit()

            # Verify indexes exist on `item`
            idx_rows = (await session.execute(text("PRAGMA index_list('item')"))).all()
            idx_names = {row[1] for row in idx_rows}
            assert "ix_item_title" in idx_names
            assert "ix_item_state" in idx_names
            assert "ix_item_library_kind" in idx_names

            # Page 1 query
            t0 = time.perf_counter()
            page1 = list(
                (
                    await session.scalars(
                        _build_movie_query(sort="title").limit(PAGE_SIZE).offset(0)
                    )
                ).all()
            )
            t_page1 = time.perf_counter() - t0
            assert len(page1) == PAGE_SIZE
            assert t_page1 < 1.0

            # Deep page query (page 500)
            t1 = time.perf_counter()
            page500 = list(
                (
                    await session.scalars(
                        _build_movie_query(sort="title").limit(PAGE_SIZE).offset(25_000)
                    )
                ).all()
            )
            t_page500 = time.perf_counter() - t1
            assert len(page500) == PAGE_SIZE
            assert t_page500 < 1.0

            # Filtered query (dirty)
            t2 = time.perf_counter()
            dirty_page = list(
                (
                    await session.scalars(
                        _build_movie_query(flt="dirty", sort="title").limit(PAGE_SIZE)
                    )
                ).all()
            )
            t_dirty = time.perf_counter() - t2
            assert len(dirty_page) == PAGE_SIZE
            assert t_dirty < 1.0
