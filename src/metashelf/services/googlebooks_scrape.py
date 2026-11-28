"""Shared helpers for manual Google Books search & metadata apply (ebooks and comics)."""

from pathlib import Path

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Artwork, Item
from metashelf.domain.models import ArtworkType
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.googlebooks import GoogleBooksProvider
from metashelf.writers.artwork import ArtworkDownloadError, download_artwork


def get_google_books_provider(request: Request, session: AsyncSession) -> GoogleBooksProvider:
    """Build a GoogleBooksProvider using app HTTP client, API key, and DB response cache."""
    http_client: httpx.AsyncClient = request.app.state.http_client
    api_key: str = request.app.state.settings.google_books_api_key
    return GoogleBooksProvider(
        http_client=http_client,
        api_key=api_key,
        cache=ProviderResponseCache(session),
    )


async def save_googlebooks_cover(
    session: AsyncSession,
    http_client: httpx.AsyncClient,
    provider: GoogleBooksProvider,
    item: Item,
    kind: str,
    provider_id: str,
    cover_path: Path,
    root: Path,
) -> None:
    """Download and upsert cover artwork from Google Books if available."""
    arts = await provider.artwork(kind, provider_id)
    if not arts:
        return
    try:
        dl = await download_artwork(http_client, arts[0].url, cover_path)
    except ArtworkDownloadError:
        return

    rel_art = str(cover_path.resolve().relative_to(root.resolve()))
    existing = (
        await session.execute(
            select(Artwork).where(
                Artwork.item_id == item.id,
                Artwork.type == ArtworkType.COVER.value,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Artwork(
                item_id=item.id,
                type=ArtworkType.COVER.value,
                rel_path=rel_art,
                source_url=arts[0].url,
                width=dl.width,
                height=dl.height,
            )
        )
    else:
        existing.rel_path = rel_art
        existing.source_url = arts[0].url
        existing.width = dl.width
        existing.height = dl.height
