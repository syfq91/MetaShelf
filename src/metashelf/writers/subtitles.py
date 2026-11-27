"""Subtitle sidecar writer: Kodi/Jellyfin naming, UTF-8 conversion, and no-overwrite safety."""

from pathlib import Path

from metashelf.writers.atomic import atomic_write_bytes


class SubtitleExistsError(FileExistsError):
    """Raised when attempting to overwrite an existing subtitle with overwrite=False."""


def subtitle_target_path(
    video_path: Path,
    lang: str,
    *,
    forced: bool = False,
    hearing_impaired: bool = False,
    fmt: str = "srt",
) -> Path:
    """Build <video_stem>.<lang>[.forced][.sdh].<fmt> next to the video file."""
    parts = [video_path.stem, lang.strip().lower()]
    if forced:
        parts.append("forced")
    if hearing_impaired:
        parts.append("sdh")
    parts.append(fmt.lstrip("."))
    return video_path.parent / ".".join(parts)


def find_existing_subtitles(video_path: Path) -> list[Path]:
    """Find all existing .srt/.vtt/.ass sidecar files belonging to video_path."""
    prefix = f"{video_path.stem}."
    exts = {".srt", ".vtt", ".ass", ".sub"}
    if not video_path.parent.is_dir():
        return []
    return sorted(
        p
        for p in video_path.parent.iterdir()
        if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() in exts
    )


def normalize_subtitle_to_utf8(raw_bytes: bytes) -> bytes:
    """Decode subtitle bytes (UTF-8-SIG, UTF-8, CP1252, Latin-1) and re-encode as UTF-8."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            return text.encode("utf-8")
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace").encode("utf-8")


def write_subtitle_file(
    video_path: Path,
    lang: str,
    raw_bytes: bytes,
    *,
    forced: bool = False,
    hearing_impaired: bool = False,
    fmt: str = "srt",
    overwrite: bool = False,
) -> Path:
    """Convert subtitle bytes to UTF-8 and write atomically (keeping .bak on overwrite)."""
    target = subtitle_target_path(
        video_path,
        lang,
        forced=forced,
        hearing_impaired=hearing_impaired,
        fmt=fmt,
    )
    if target.exists() and not overwrite:
        raise SubtitleExistsError(f"Subtitle already exists: {target}")

    utf8_bytes = normalize_subtitle_to_utf8(raw_bytes)
    atomic_write_bytes(target, utf8_bytes)
    return target
