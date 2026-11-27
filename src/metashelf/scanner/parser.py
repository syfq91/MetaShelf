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


@dataclass
class ParsedEpisodeName:
    """Parsed TV episode metadata from filename and folder structure."""

    show_title: str
    season: int
    episodes: list[int]
    year: int | None = None


def parse_show_folder_name(folder_name: str) -> ParsedMovieName:
    """Parse a TV show folder name (e.g. 'Breaking Bad (2008)') into title and year."""
    result: dict[str, Any] = dict(guessit(folder_name, {"type": "episode"}))
    raw_title = result.get("title")
    raw_year = result.get("year")
    title = str(raw_title).strip() if raw_title else folder_name.strip()
    year = int(raw_year) if isinstance(raw_year, int) else None
    return ParsedMovieName(title=title, year=year)


def parse_tv_episode_filename(rel_path: str) -> ParsedEpisodeName:
    """Parse a TV episode relative path into show title, season, and episode numbers."""
    p = Path(rel_path)
    result: dict[str, Any] = dict(guessit(rel_path, {"type": "episode"}))

    # Show title: prefer top-level folder in rel_path if present, else guessit title
    parts = p.parts
    raw_title = result.get("title")
    raw_year = result.get("year")
    if len(parts) >= 2:
        folder_parsed = parse_show_folder_name(parts[0])
        show_title = folder_parsed.title
        if raw_year is None:
            raw_year = folder_parsed.year
        # If guessit found a more specific title (e.g. "The Office US"), keep if folder is generic
        if raw_title and str(raw_title).strip().lower().startswith(show_title.lower()):
            show_title = str(raw_title).strip()
    else:
        show_title = str(raw_title).strip() if raw_title else p.stem

    raw_season = result.get("season")
    if isinstance(raw_season, int):
        season = raw_season
    elif any("special" in part.lower() for part in parts[:-1]):
        season = 0
    else:
        season = 1

    raw_ep = result.get("episode")
    if isinstance(raw_ep, list):
        episodes = [int(e) for e in raw_ep if isinstance(e, int)]
    elif isinstance(raw_ep, int):
        episodes = [raw_ep]
    else:
        episodes = [1]

    if not episodes:
        episodes = [1]

    year = int(raw_year) if isinstance(raw_year, int) else None
    return ParsedEpisodeName(
        show_title=show_title,
        season=season,
        episodes=sorted(episodes),
        year=year,
    )
