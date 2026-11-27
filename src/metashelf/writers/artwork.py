"""Artwork downloader with SSRF, content-type, size, and Pillow validation."""

import ipaddress
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from metashelf.writers.atomic import atomic_write_bytes

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_ARTWORK_BYTES = 20 * 1024 * 1024  # 20 MiB


class ArtworkDownloadError(RuntimeError):
    """Raised when downloading or validating artwork fails."""


@dataclass
class DownloadedArtwork:
    """Metadata about a validated, saved artwork file."""

    path: Path
    width: int
    height: int


def validate_artwork_url(url: str) -> None:
    """Ensure artwork URL uses http(s) and does not target local/private hosts."""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ArtworkDownloadError(f"Unsupported artwork URL: {url}")

    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ArtworkDownloadError(f"Refused local artwork host: {host}")

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ArtworkDownloadError(f"Refused non-public artwork IP: {host}")
    except ValueError:
        pass


async def download_artwork(
    http_client: httpx.AsyncClient,
    url: str,
    target: Path,
) -> DownloadedArtwork:
    """Download, validate, and atomically save artwork to target."""
    validate_artwork_url(url)

    try:
        resp = await http_client.get(url, timeout=30.0, follow_redirects=False)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ArtworkDownloadError(f"Failed to download artwork from {url}: {exc}") from exc

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise ArtworkDownloadError(f"Invalid image content-type '{content_type}' from {url}")

    data = resp.content
    if len(data) > MAX_ARTWORK_BYTES:
        raise ArtworkDownloadError(f"Artwork exceeds {MAX_ARTWORK_BYTES} bytes limit")

    try:
        with Image.open(BytesIO(data)) as img:
            img.verify()
        with Image.open(BytesIO(data)) as img2:
            width, height = img2.size
    except (UnidentifiedImageError, OSError) as exc:
        raise ArtworkDownloadError(f"Invalid image payload from {url}: {exc}") from exc

    atomic_write_bytes(target, data)
    return DownloadedArtwork(path=target, width=width, height=height)
