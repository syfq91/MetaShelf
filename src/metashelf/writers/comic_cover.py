"""Extract the first image page from a CBZ archive as a JPEG cover."""

import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from metashelf.writers.artwork import DownloadedArtwork
from metashelf.writers.atomic import atomic_write_bytes

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def extract_cbz_first_page_cover(cbz_path: Path, target: Path) -> DownloadedArtwork | None:
    """Read the first sorted image from cbz_path and save it as JPEG without modifying the CBZ."""
    with zipfile.ZipFile(cbz_path, "r") as zf:
        image_names = sorted(
            name
            for name in zf.namelist()
            if not name.endswith("/")
            and not Path(name).name.startswith(".")
            and Path(name).suffix.lower() in IMAGE_EXTS
        )
        if not image_names:
            return None
        raw = zf.read(image_names[0])

    try:
        with Image.open(BytesIO(raw)) as img:
            rgb = img.convert("RGB")
            width, height = rgb.size
            buf = BytesIO()
            rgb.save(buf, format="JPEG", quality=90)
    except (UnidentifiedImageError, OSError):
        return None

    atomic_write_bytes(target, buf.getvalue())
    return DownloadedArtwork(path=target, width=width, height=height)
