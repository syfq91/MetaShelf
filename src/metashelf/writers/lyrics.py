"""Lyrics sidecar writer (.lrc for synced, .txt for plain) with no-overwrite safety."""

from pathlib import Path

from metashelf.writers.atomic import atomic_write_bytes


class LyricsExistsError(FileExistsError):
    """Raised when attempting to overwrite an existing lyrics file with overwrite=False."""


def lyrics_target_path(audio_path: Path, *, synced: bool) -> Path:
    """Return <track_stem>.lrc (synced) or <track_stem>.txt (plain)."""
    ext = ".lrc" if synced else ".txt"
    return audio_path.with_suffix(ext)


def find_existing_lyrics(audio_path: Path) -> Path | None:
    """Return existing .lrc or .txt sidecar next to audio_path, if any."""
    for ext in (".lrc", ".txt"):
        p = audio_path.with_suffix(ext)
        if p.is_file():
            return p
    return None


def write_lyrics_file(
    audio_path: Path,
    text: str,
    *,
    synced: bool,
    overwrite: bool = False,
) -> Path:
    """Write lyrics text in UTF-8 next to audio_path (keeping .bak on forced overwrite)."""
    target = lyrics_target_path(audio_path, synced=synced)
    if target.exists() and not overwrite:
        raise LyricsExistsError(f"Lyrics file already exists: {target}")

    atomic_write_bytes(target, text.encode("utf-8"))
    return target
