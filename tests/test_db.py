"""Tests for SQLAlchemy models, WAL mode, and Alembic migrations."""

from pathlib import Path

from sqlalchemy import select, text

from metashelf.db.models import Item, Library
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)


async def test_migrations_and_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            result = await session.execute(text("PRAGMA journal_mode"))
            mode = result.scalar_one()
            assert mode.lower() == "wal"

            lib = Library(name="Movies", type="movie", root_path="/media/movies")
            session.add(lib)
            await session.flush()

            item = Item(
                library_id=lib.id,
                kind="movie",
                rel_path="Inception (2010)/Inception (2010).mkv",
                title="Inception",
                year=2010,
                state="unmatched",
            )
            session.add(item)
            await session.commit()

        async with session_factory() as session:
            row = (await session.execute(select(Item))).scalar_one()
            assert row.title == "Inception"
            assert row.year == 2010
    finally:
        await engine.dispose()
