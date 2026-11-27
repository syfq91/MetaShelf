"""Tests for Open Library and Google Books providers (written before implementation)."""

from pathlib import Path

import httpx
import respx

from metashelf.domain.models import EbookMetadata
from metashelf.providers.base import SearchQuery
from metashelf.providers.googlebooks import GoogleBooksProvider
from metashelf.providers.openlibrary import OpenLibraryProvider

OL_FIX = Path(__file__).parent / "fixtures" / "openlibrary"
GB_FIX = Path(__file__).parent / "fixtures" / "googlebooks"


@respx.mock
async def test_openlibrary_isbn_search_fetch_and_artwork() -> None:
    respx.get("https://openlibrary.org/search.json").mock(
        return_value=httpx.Response(
            200, text=(OL_FIX / "search_dune.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://openlibrary.org/isbn/9780441172719.json").mock(
        return_value=httpx.Response(
            200, text=(OL_FIX / "isbn_9780441172719.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://openlibrary.org/works/OL893415W.json").mock(
        return_value=httpx.Response(
            200, text=(OL_FIX / "work_OL893415W.json").read_text(encoding="utf-8")
        )
    )

    async with httpx.AsyncClient() as client:
        ol = OpenLibraryProvider(http_client=client)
        cands = await ol.search(
            "ebook",
            SearchQuery(title="Dune", author="Frank Herbert", isbn="9780441172719"),
        )
        assert len(cands) == 1
        assert cands[0].provider_id == "9780441172719"

        meta = await ol.fetch("ebook", "9780441172719", "en")
        assert isinstance(meta, EbookMetadata)
        assert meta.title == "Dune"
        assert meta.isbn == "9780441172719"
        assert "desert planet Arrakis" in meta.description

        arts = await ol.artwork("ebook", "9780441172719")
        assert len(arts) >= 1
        assert arts[0].type == "cover"


@respx.mock
async def test_google_books_search_and_https_cover_upgrade() -> None:
    respx.get("https://www.googleapis.com/books/v1/volumes").mock(
        return_value=httpx.Response(
            200, text=(GB_FIX / "volumes_dune.json").read_text(encoding="utf-8")
        )
    )
    respx.get("https://www.googleapis.com/books/v1/volumes/B1h0AAAAYAAJ").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "B1h0AAAAYAAJ",
                "volumeInfo": {
                    "title": "Dune",
                    "authors": ["Frank Herbert", "Brian Herbert"],
                    "publisher": "Ace",
                    "publishedDate": "1990-09-01",
                    "description": "Classic science fiction novel.",
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780441172719"}],
                    "categories": ["Fiction / Science Fiction"],
                    "language": "en",
                    "imageLinks": {
                        "thumbnail": "http://books.google.com/books/content?id=B1h0AAAAYAAJ&img=1"
                    },
                },
            },
        )
    )

    async with httpx.AsyncClient() as client:
        gb = GoogleBooksProvider(http_client=client)
        cands = await gb.search("ebook", SearchQuery(title="Dune", isbn="9780441172719"))
        assert len(cands) == 1
        assert cands[0].provider_id == "B1h0AAAAYAAJ"

        meta = await gb.fetch("ebook", "B1h0AAAAYAAJ", "en")
        assert isinstance(meta, EbookMetadata)
        assert meta.authors == ["Frank Herbert", "Brian Herbert"]
        assert meta.isbn == "9780441172719"

        arts = await gb.artwork("ebook", "B1h0AAAAYAAJ")
        assert len(arts) == 1
        assert arts[0].url.startswith("https://")
