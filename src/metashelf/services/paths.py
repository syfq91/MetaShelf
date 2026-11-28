"""Path resolution and confinement helpers."""

from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a path escapes configured library or media roots."""


def is_within(path: Path, root: Path) -> bool:
    """Return True if resolved path is equal to or inside resolved root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_within_root(rel_path: str | Path, root: Path) -> Path:
    """Resolve rel_path relative to root and ensure it does not escape root."""
    resolved_root = root.resolve()
    candidate = (resolved_root / rel_path).resolve()
    if not is_within(candidate, resolved_root):
        raise PathTraversalError(f"Relative path '{rel_path}' escapes root '{root}'.")
    return candidate


def list_directories(
    raw_path: str | None,
) -> tuple[str, str | None, list[dict[str, str]]]:
    """Return (current_path, parent_path, child_dirs) for the UI folder picker."""
    if raw_path and raw_path.strip():
        current = Path(raw_path.strip()).resolve()
    else:
        default_media = Path("/media")
        current = default_media.resolve() if default_media.is_dir() else Path("/").resolve()

    if not current.exists() or not current.is_dir():
        raise PathTraversalError(f"Directory '{current}' does not exist.")

    parent: str | None = str(current.parent) if current.parent != current else None

    children: list[dict[str, str]] = []
    try:
        entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise PathTraversalError(f"Cannot read directory '{current}': {exc}") from exc

    for child in entries:
        if child.is_dir() and not child.name.startswith("."):
            children.append({"name": child.name, "path": str(child)})
    return str(current), parent, children
