"""Atomic file writer with one-generation .bak backup."""

import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write data to target atomically, keeping a .bak of any existing file."""
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        if target.exists():
            bak_path = Path(f"{target}.bak")
            shutil.copy2(target, bak_path)

        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
