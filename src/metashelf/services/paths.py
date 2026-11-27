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


def resolve_within_roots(raw_path: str | Path, roots: list[Path]) -> Path:
    """Resolve raw_path and ensure it lies inside at least one allowed root."""
    if not roots:
        raise PathTraversalError("No media roots configured.")
    candidate = Path(raw_path).resolve()
    for root in roots:
        if is_within(candidate, root):
            return candidate
    raise PathTraversalError(f"Path '{raw_path}' is outside configured media roots.")


def resolve_within_root(rel_path: str | Path, root: Path) -> Path:
    """Resolve rel_path relative to root and ensure it does not escape root."""
    resolved_root = root.resolve()
    candidate = (resolved_root / rel_path).resolve()
    if not is_within(candidate, resolved_root):
        raise PathTraversalError(f"Relative path '{rel_path}' escapes root '{root}'.")
    return candidate


def list_allowed_directories(
    raw_path: str | None,
    roots: list[Path],
) -> tuple[str | None, str | None, list[dict[str, str]]]:
    """Return (current_path, parent_path, child_dirs) strictly within roots."""
    resolved_roots = [r.resolve() for r in roots]
    if not raw_path:
        entries = [
            {"name": str(r), "path": str(r)}
            for r in resolved_roots
            if r.exists() and r.is_dir()
        ]
        return None, None, entries

    current = resolve_within_roots(raw_path, resolved_roots)
    if not current.exists() or not current.is_dir():
        raise PathTraversalError(f"Directory '{current}' does not exist.")

    parent: str | None = None
    if current not in resolved_roots:
        candidate_parent = current.parent
        for r in resolved_roots:
            if is_within(candidate_parent, r):
                parent = str(candidate_parent)
                break

    children: list[dict[str, str]] = []
    for child in sorted(current.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir() and not child.name.startswith("."):
            children.append({"name": child.name, "path": str(child)})
    return str(current), parent, children
