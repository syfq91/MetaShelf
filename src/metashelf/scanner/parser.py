"""Filename parsing using guessit."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guessit import guessit


@dataclass
class ParsedMovieName:
    """Parsed movie title and year from filename/folder."""

    title: str
    year: int | None = None


def parse_movie_filename(rel_path: str) -> ParsedMovieName:
    """Parse a movie relative path into title and optional year using guessit."""
    p = Path(rel_path)
    result: dict[str, Any] = dict(guessit(p.name, {"type": "movie"}))
    raw_title = result.get("title")
    raw_year = result.get("year")

    # Fallback to parent folder if filename didn't yield a title or year
    if (not raw_title or not raw_year) and p.parent.name:
        folder_result: dict[str, Any] = dict(guessit(p.parent.name, {"type": "movie"}))
        if not raw_title:
            raw_title = folder_result.get("title")
        if not raw_year:
            raw_year = folder_result.get("year")

    title = str(raw_title).strip() if raw_title else p.stem
    year = int(raw_year) if isinstance(raw_year, int) else None
    return ParsedMovieName(title=title, year=year)
