"""Tests for movie library scanner and NFO adoption (written before implementation)."""

from pathlib import Path

from sqlalchemy import select

from metashelf.db.models import Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.scanner.movie import scan_movie_library

SAMPLE_NFO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>Inception</title>
  <originaltitle>Inception</originaltitle>
  <year>2010</year>
  <plot>A thief who steals corporate secrets through dream-sharing technology.</plot>
  <uniqueid type="tmdb" default="true">27205</uniqueid>
  <uniqueid type="imdb" default="false">tt1375666</uniqueid>
  <genre>Action</genre>
  <genre>Sci-Fi</genre>
</movie>
"""


async def test_scan_movie_library_and_adopt_nfo(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    lib_root = tmp_path / "movies"
    m1_dir = lib_root / "Inception (2010)"
    m1_dir.mkdir(parents=True)
    (m1_dir / "Inception (2010).mkv").write_bytes(b"fake-video-1")
    (m1_dir / "Inception (2010).nfo").write_text(SAMPLE_NFO, encoding="utf-8")
    (m1_dir / "Inception (2010)-poster.jpg").write_bytes(b"fake-poster")

    m2_dir = lib_root / "The Matrix (1999)"
    m2_dir.mkdir(parents=True)
    (m2_dir / "The.Matrix.1999.1080p.mkv").write_bytes(b"fake-video-2")

    # Ignored non-video or sample files
    (m2_dir / "sample.mkv").write_bytes(b"sample")

    try:
        async with session_factory() as session:
            lib = Library(name="Movies", type="movie", root_path=str(lib_root))
            session.add(lib)
            await session.commit()

            stats = await scan_movie_library(session, lib)
            assert stats.added == 2
            assert stats.updated == 0

            items = (
                await session.execute(select(Item).order_by(Item.rel_path))
            ).scalars().all()
            assert len(items) == 2

            inception = items[0]
            assert inception.title == "Inception"
            assert inception.year == 2010
            assert inception.state == "complete"
            assert '"tmdb": "27205"' in inception.provider_ids_json

            matrix = items[1]
            assert matrix.title == "The Matrix"
            assert matrix.year == 1999
            assert matrix.state == "unmatched"

            # Re-scan without changes -> incremental skip
            stats2 = await scan_movie_library(session, lib)
            assert stats2.added == 0
            assert stats2.updated == 0
            assert stats2.skipped == 2
    finally:
        await engine.dispose()
