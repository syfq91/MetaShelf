# ADR 0004: Music Domain Models and Redirect-Following Cover Art Downloads

## Status
Accepted

## Context
Phase 3 introduces `ArtistMetadata`, `AlbumMetadata`, and `TrackMetadata` alongside `MovieMetadata`, `ShowMetadata`, `SeasonMetadata`, and `EpisodeMetadata`. Additionally, Cover Art Archive (`coverartarchive.org`) responds with `307 Temporary Redirect` to `archive.org` storage nodes, whereas our Phase 1 `download_artwork` defaulted to `follow_redirects=False`.

## Decision
- Expand `NormalizedMetadata` in `src/metashelf/domain/models.py` to include `ArtistMetadata | AlbumMetadata | TrackMetadata`.
- Add an explicit opt-in `allow_redirects: bool = False` parameter to `download_artwork` (and validate the final redirected URL with `validate_artwork_url` before accepting it) so Cover Art Archive redirects work safely without weakening SSRF protection for other callers.
