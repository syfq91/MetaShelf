# ADR 0003: NormalizedMetadata Union for Multi-Kind Providers

## Status
Accepted

## Context
In Phase 1, `Provider.fetch(self, kind: str, provider_id: str, lang: str)` in `src/metashelf/providers/base.py` was typed to return `MovieMetadata`. Phase 2 introduces TV shows (`ShowMetadata`) and episodes (`EpisodeMetadata`), and later phases introduce music, ebooks, and comics.

## Decision
- Define `NormalizedMetadata = MovieMetadata | ShowMetadata | EpisodeMetadata` in `src/metashelf/domain/models.py` (and expand this union in later phases).
- Update `Provider.fetch(...) -> NormalizedMetadata` in `src/metashelf/providers/base.py`.
- Keep `search(kind, query)` and `artwork(kind, provider_id)` unchanged.
- Existing movie callers can narrow with `isinstance(meta, MovieMetadata)` or `assert isinstance(...)`, preserving full `mypy --strict` safety without duplicating the `Provider` protocol.
