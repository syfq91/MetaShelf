# ADR 0008: Per-Library Preferences and `metashelf` CLI Entrypoint

## Status
Accepted

## Context
Phase 7 adds per-library preferences (sidecar naming scheme, language, artwork limits, subtitle languages) and a `metashelf rebuild-index` CLI command.

## Decision
- **Per-library preferences**: Store a `LibraryPreferences` Pydantic model as JSON in the existing `setting` table keyed by `library_prefs:{library_id}` rather than altering the `library` table schema, keeping migrations backward-compatible and export/import trivial.
- **CLI entrypoint**: Register `metashelf = "metashelf.cli:main"` in `pyproject.toml` using stdlib `argparse` so `metashelf rebuild-index` works inside Docker and local virtualenvs without extra CLI dependencies.
