"""Batch operations with dry-run and unified diff preview."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Item, Library
from metashelf.domain.models import ItemState, MovieMetadata
from metashelf.matching.movie import auto_match_movie_item
from metashelf.providers.base import MissingApiKeyError
from metashelf.providers.tmdb import TMDBProvider
from metashelf.readers.kodi_nfo_movie import read_movie_nfo
from metashelf.scanner.movie import find_movie_nfo
from metashelf.services.movie_save import resolve_movie_nfo_target, save_movie_to_disk
from metashelf.services.paths import PathTraversalError, resolve_within_root
from metashelf.writers.kodi_nfo_movie import render_movie_nfo


@dataclass
class BatchItemPreview:
    """Preview of a single item in a batch operation."""

    item_id: int
    title: str
    target_path: str
    diff_text: str
    has_changes: bool
    status: str


@dataclass
class BatchResult:
    """Result of a batch preview or execution."""

    action: str
    dry_run: bool
    previews: list[BatchItemPreview] = field(default_factory=list)
    applied_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


def _compute_movie_nfo_diff(
    item: Item,
    library: Library,
    naming_scheme: str = "file",
) -> BatchItemPreview:
    root = Path(library.root_path)
    video_path = resolve_within_root(Path(item.rel_path), root)
    existing_nfo = find_movie_nfo(video_path)
    target_nfo = existing_nfo or resolve_movie_nfo_target(video_path, naming_scheme=naming_scheme)

    old_lines: list[str] = []
    unknown_elements = None
    if target_nfo.exists():
        old_text = target_nfo.read_text(encoding="utf-8", errors="replace")
        old_lines = old_text.splitlines(keepends=True)
        try:
            parsed = read_movie_nfo(target_nfo)
            unknown_elements = parsed.unknown_elements
        except Exception:
            unknown_elements = None

    meta = MovieMetadata.model_validate_json(item.metadata_json)
    new_bytes = render_movie_nfo(meta, unknown_elements=unknown_elements)
    new_text = new_bytes.decode("utf-8")
    new_lines = new_text.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{target_nfo.name}",
            tofile=f"b/{target_nfo.name}",
            n=2,
        )
    )
    diff_text = "".join(diff_lines)
    has_changes = bool(diff_lines)
    return BatchItemPreview(
        item_id=item.id,
        title=item.title or item.rel_path,
        target_path=str(target_nfo),
        diff_text=diff_text if has_changes else "(no changes)",
        has_changes=has_changes,
        status="changed" if has_changes else "unchanged",
    )


async def preview_batch_diff(
    session: AsyncSession,
    item_ids: list[int],
    action: str = "save",
    naming_scheme: str = "file",
) -> BatchResult:
    """Compute a dry-run diff preview for the selected items without modifying disk or DB."""
    result = BatchResult(action=action, dry_run=True)
    if not item_ids:
        return result

    items = list(
        (await session.scalars(select(Item).where(Item.id.in_(item_ids)).order_by(Item.id))).all()
    )
    lib_ids = {it.library_id for it in items}
    libs_by_id: dict[int, Library] = {}
    if lib_ids:
        libs = list((await session.scalars(select(Library).where(Library.id.in_(lib_ids)))).all())
        libs_by_id = {lib.id: lib for lib in libs}

    for item in items:
        lib = libs_by_id.get(item.library_id)
        if lib is None:
            result.errors.append(f"Item {item.id}: missing library")
            continue
        if action == "save":
            try:
                preview = _compute_movie_nfo_diff(item, lib, naming_scheme=naming_scheme)
                result.previews.append(preview)
            except (PathTraversalError, Exception) as exc:
                result.errors.append(f"{item.title or item.id}: {exc}")
        elif action == "auto_match":
            will_match = item.state == ItemState.UNMATCHED.value
            msg = (
                f"Would auto-match '{item.title or item.rel_path}' ({item.year or 'unknown year'})"
                if will_match
                else f"Already matched ({item.state}); would skip"
            )
            result.previews.append(
                BatchItemPreview(
                    item_id=item.id,
                    title=item.title or item.rel_path,
                    target_path=item.rel_path,
                    diff_text=msg,
                    has_changes=will_match,
                    status="will_match" if will_match else "skip",
                )
            )
        else:
            result.errors.append(f"Unknown batch action: {action}")
    return result


async def execute_batch_action(
    session: AsyncSession,
    item_ids: list[int],
    action: str,
    dry_run: bool = True,
    naming_scheme: str = "file",
    tmdb_api_key: str = "",
    lang: str = "en-US",
    http_client: httpx.AsyncClient | None = None,
) -> BatchResult:
    """Preview or execute a batch action (`save` or `auto_match`) over selected movie items."""
    if dry_run:
        return await preview_batch_diff(
            session, item_ids, action=action, naming_scheme=naming_scheme
        )

    result = BatchResult(action=action, dry_run=False)
    if not item_ids:
        return result

    items = list(
        (await session.scalars(select(Item).where(Item.id.in_(item_ids)).order_by(Item.id))).all()
    )
    lib_ids = {it.library_id for it in items}
    libs_by_id: dict[int, Library] = {}
    if lib_ids:
        libs = list((await session.scalars(select(Library).where(Library.id.in_(lib_ids)))).all())
        libs_by_id = {lib.id: lib for lib in libs}

    if action == "save":
        for item in items:
            lib = libs_by_id.get(item.library_id)
            if lib is None:
                result.errors.append(f"Item {item.id}: missing library")
                continue
            try:
                target = await save_movie_to_disk(session, item, lib, naming_scheme=naming_scheme)
                result.applied_count += 1
                result.previews.append(
                    BatchItemPreview(
                        item_id=item.id,
                        title=item.title or item.rel_path,
                        target_path=str(target),
                        diff_text="Saved NFO to disk",
                        has_changes=True,
                        status="saved",
                    )
                )
            except Exception as exc:
                result.errors.append(f"{item.title or item.id}: {exc}")
    elif action == "auto_match":
        if not tmdb_api_key:
            result.errors.append("TMDB API key is required for auto-match.")
            return result
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=15.0)
        try:
            provider = TMDBProvider(api_key=tmdb_api_key, http_client=client)
            for item in items:
                lib = libs_by_id.get(item.library_id)
                if lib is None:
                    result.errors.append(f"Item {item.id}: missing library")
                    continue
                try:
                    matched = await auto_match_movie_item(
                        session,
                        item,
                        lib,
                        provider,
                        client,
                        lang=lang,
                        naming_scheme=naming_scheme,
                    )
                    if matched:
                        result.applied_count += 1
                        status = "matched"
                    else:
                        result.skipped_count += 1
                        status = "skipped"
                    result.previews.append(
                        BatchItemPreview(
                            item_id=item.id,
                            title=item.title or item.rel_path,
                            target_path=item.rel_path,
                            diff_text="Matched via TMDB" if matched else "No match / skipped",
                            has_changes=matched,
                            status=status,
                        )
                    )
                except MissingApiKeyError as exc:
                    result.errors.append(str(exc))
                    break
                except Exception as exc:
                    result.errors.append(f"{item.title or item.id}: {exc}")
        finally:
            if owns_client:
                await client.aclose()
    else:
        result.errors.append(f"Unknown batch action: {action}")
    return result
