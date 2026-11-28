"""MetaShelf CLI entrypoint (`metashelf rebuild-index`)."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import delete, func, select

from metashelf.config import Settings, get_settings
from metashelf.db.models import Artwork, Item, Library, SidecarFile
from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.domain.models import LibraryType
from metashelf.scanner.comic import scan_comic_library
from metashelf.scanner.ebook import scan_ebook_library
from metashelf.scanner.movie import scan_movie_library
from metashelf.scanner.music import scan_music_library
from metashelf.scanner.tv import scan_tv_library


async def rebuild_index(settings: Settings) -> int:
    """Clear indexed items/sidecars/artwork and rebuild them from the filesystem."""
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.resolved_database_url)
    engine = create_async_engine_with_wal(settings.resolved_database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await session.execute(delete(Artwork))
            await session.execute(delete(SidecarFile))
            await session.execute(delete(Item))
            await session.commit()

            libraries = list(
                (await session.scalars(select(Library).where(Library.enabled.is_(True)))).all()
            )
            for lib in libraries:
                if lib.type == LibraryType.MOVIE.value:
                    await scan_movie_library(session, lib)
                elif lib.type == LibraryType.TV.value:
                    await scan_tv_library(session, lib)
                elif lib.type == LibraryType.MUSIC.value:
                    await scan_music_library(session, lib)
                elif lib.type == LibraryType.EBOOK.value:
                    await scan_ebook_library(session, lib)
                elif lib.type == LibraryType.COMIC.value:
                    await scan_comic_library(session, lib)

            total = await session.scalar(select(func.count()).select_from(Item))
            return int(total or 0)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """Run MetaShelf CLI commands."""
    parser = argparse.ArgumentParser(prog="metashelf", description="MetaShelf CLI utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rebuild_parser = subparsers.add_parser(
        "rebuild-index",
        help="Drop cached item index and rebuild from filesystem sidecars",
    )
    rebuild_parser.add_argument("--config-dir", type=Path, default=None)
    rebuild_parser.add_argument("--database-url", type=str, default=None)

    args = parser.parse_args(argv)
    if args.command == "rebuild-index":
        base = get_settings()
        updates: dict[str, object] = {}
        if args.config_dir is not None:
            updates["config_dir"] = args.config_dir
        if args.database_url is not None:
            updates["database_url"] = args.database_url
        effective = base.model_copy(update=updates) if updates else base
        count = asyncio.run(rebuild_index(effective))
        print(f"Rebuilt index: {count} item(s).")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
