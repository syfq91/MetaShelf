# ADR 0006: Comic Domain Model and Cover Source Preference

## Status
Accepted

## Context
Phase 5 adds `.cbz` comic books with `ComicInfo.xml` sidecars (`<comic>.xml`) and `<comic>.jpg` covers. Covers can come either from Comic Vine or from the first image page inside the `.cbz` archive.

## Decision
- Add `ComicMetadata` to `NormalizedMetadata` in `src/metashelf/domain/models.py`.
- Support configurable `comic_cover_source` setting (`"provider"` or `"archive"`):
  - `"provider"` (default): download cover from Comic Vine if available, falling back to extracting the first image page from the `.cbz`.
  - `"archive"`: extract and validate the first image page from the `.cbz` using Pillow (without modifying the `.cbz`).
