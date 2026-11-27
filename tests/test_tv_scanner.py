"""Tests for TV show, season, and episode scanner (written before implementation)."""

from pathlib import Path

from sqlalchemy import select

from metashelf.db.models import Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.scanner.tv import scan_tv_library


async def test_scan_tv_library_hierarchy_specials_and_multiepisode(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    tv_root = tmp_path / "tv"
    show_dir = tv_root / "Breaking Bad (2008)"
    s0_dir = show_dir / "Specials"
    s1_dir = show_dir / "Season 01"
    s2_dir = show_dir / "Season 02"
    s0_dir.mkdir(parents=True)
    s1_dir.mkdir(parents=True)
    s2_dir.mkdir(parents=True)

    (s0_dir / "Breaking.Bad.S00E01.mkv").write_bytes(b"special-1")
    (s1_dir / "Breaking.Bad.S01E01.mkv").write_bytes(b"s1e1")
    (s1_dir / "Breaking.Bad.S01E02E03.mkv").write_bytes(b"s1e2e3")
    (s2_dir / "Breaking.Bad.S02E01.mkv").write_bytes(b"s2e1")
    (show_dir / "poster.jpg").write_bytes(b"show-poster")
    (show_dir / "season01-poster.jpg").write_bytes(b"s1-poster")

    try:
        async with session_factory() as session:
            lib = Library(name="TV Shows", type="tv", root_path=str(tv_root))
            session.add(lib)
            await session.commit()

            stats = await scan_tv_library(session, lib)
            assert stats.added == 4  # 4 episode video files

            shows = (
                await session.execute(select(Item).where(Item.kind == "show"))
            ).scalars().all()
            assert len(shows) == 1
            assert shows[0].title == "Breaking Bad"
            assert shows[0].year == 2008

            seasons = (
                await session.execute(
                    select(Item).where(Item.kind == "season").order_by(Item.rel_path)
                )
            ).scalars().all()
            assert len(seasons) == 3  # Season 0, 1, 2
            assert all(s.parent_id == shows[0].id for s in seasons)

            episodes = (
                await session.execute(
                    select(Item).where(Item.kind == "episode").order_by(Item.rel_path)
                )
            ).scalars().all()
            assert len(episodes) == 4
            assert '"episodes":[2,3]' in episodes[1].metadata_json

            # Incremental re-scan skips unchanged episodes
            stats2 = await scan_tv_library(session, lib)
            assert stats2.added == 0
            assert stats2.skipped == 4
    finally:
        await engine.dispose()
