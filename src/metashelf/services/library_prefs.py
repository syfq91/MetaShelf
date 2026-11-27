"""Per-library preferences stored in the `setting` table (ADR 0008)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Setting


class LibraryPreferences(BaseModel):
    """Per-library naming, language, and artwork limit preferences."""

    naming_scheme: Literal["file", "movie_nfo"] = "file"
    language: str = "en-US"
    max_posters: int = Field(default=3, ge=1, le=50)
    max_fanart: int = Field(default=3, ge=1, le=50)


def library_prefs_key(library_id: int) -> str:
    """Return the `setting.key` used for a library's preferences."""
    return f"library_prefs:{library_id}"


async def get_library_prefs(session: AsyncSession, library_id: int) -> LibraryPreferences:
    """Load per-library preferences, falling back to global defaults when unset."""
    row = await session.get(Setting, library_prefs_key(library_id))
    if row is not None:
        try:
            return LibraryPreferences.model_validate_json(row.value_json)
        except Exception:
            pass

    lang_row = await session.get(Setting, "metadata_language")
    naming_row = await session.get(Setting, "movie_naming_scheme")
    language = "en-US"
    naming_scheme: Literal["file", "movie_nfo"] = "file"
    if lang_row is not None:
        try:
            import json

            val = json.loads(lang_row.value_json)
            if isinstance(val, str) and val.strip():
                language = val.strip()
        except Exception:
            pass
    if naming_row is not None:
        try:
            import json

            val = json.loads(naming_row.value_json)
            if val in ("file", "movie_nfo"):
                naming_scheme = val
        except Exception:
            pass
    return LibraryPreferences(naming_scheme=naming_scheme, language=language)


async def set_library_prefs(
    session: AsyncSession,
    library_id: int,
    prefs: LibraryPreferences,
) -> LibraryPreferences:
    """Persist per-library preferences in the `setting` table."""
    key = library_prefs_key(library_id)
    row = await session.get(Setting, key)
    payload = prefs.model_dump_json()
    if row is None:
        session.add(Setting(key=key, value_json=payload))
    else:
        row.value_json = payload
    await session.commit()
    return prefs
