"""Tests for TMDB provider using respx-mocked recorded fixtures (written before implementation)."""

from pathlib import Path

import httpx
import pytest
import respx

from metashelf.db.session import (
    create_async_engine_with_wal,
    create_session_factory,
    run_migrations,
)
from metashelf.providers.base import MissingApiKeyError, SearchQuery
from metashelf.providers.cache import ProviderResponseCache
from metashelf.providers.tmdb import TMDBProvider

FIXTURES = Path(__file__).parent / "fixtures" / "tmdb"


async def test_tmdb_missing_key_raises() -> None:
    async with httpx.AsyncClient() as client:
        provider = TMDBProvider(api_key="", http_client=client)
        with pytest.raises(MissingApiKeyError):
            await provider.search("movie", SearchQuery(title="Inception", year=2010))


@respx.mock
async def test_tmdb_search_fetch_artwork_and_cache(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    run_migrations(db_url)
    engine = create_async_engine_with_wal(db_url)
    session_factory = create_session_factory(engine)

    search_route = respx.get("https://api.themoviedb.org/3/search/movie").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "search_inception.json").read_text(encoding="utf-8")
        )
    )
    details_route = respx.get("https://api.themoviedb.org/3/movie/27205").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "movie_27205.json").read_text(encoding="utf-8")
        )
    )
    images_route = respx.get("https://api.themoviedb.org/3/movie/27205/images").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "images_27205.json").read_text(encoding="utf-8")
        )
    )

    try:
        async with session_factory() as session:
            cache = ProviderResponseCache(session)
            async with httpx.AsyncClient() as client:
                provider = TMDBProvider(api_key="dummy-key", http_client=client, cache=cache)

                candidates = await provider.search(
                    "movie", SearchQuery(title="Inception", year=2010)
                )
                assert len(candidates) == 2
                assert candidates[0].provider_id == "27205"
                assert candidates[0].title == "Inception"
                assert candidates[0].year == 2010
                assert candidates[0].poster_url is not None
                assert "image.tmdb.org" in candidates[0].poster_url

                # Second search hits cache, not HTTP
                candidates_cached = await provider.search(
                    "movie", SearchQuery(title="Inception", year=2010)
                )
                assert len(candidates_cached) == 2
                assert search_route.call_count == 1

                meta = await provider.fetch("movie", "27205", "en-US")
                assert meta.title == "Inception"
                assert meta.imdb_id == "tt1375666"
                assert meta.tmdb_id == "27205"
                assert meta.runtime == 148
                assert meta.mpaa == "PG-13"
                assert "Christopher Nolan" in meta.directors
                assert len(meta.actors) == 2
                assert meta.actors[0].name == "Leonardo DiCaprio"
                assert details_route.call_count == 1

                artworks = await provider.artwork("movie", "27205")
                assert len(artworks) == 2
                types = {a.type for a in artworks}
                assert types == {"poster", "fanart"}
                assert images_route.call_count == 1
    finally:
        await engine.dispose()
