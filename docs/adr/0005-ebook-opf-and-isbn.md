# ADR 0005: Ebook Domain Model, ISBN SearchQuery, and OPF Series Mapping

## Status
Accepted

## Context
Phase 4 introduces `.epub` ebooks with ISBN-first matching, multiple authors (`dc:creator`), and series metadata (`belongs-to-collection` in EPUB 3.3 and `calibre:series` in EPUB 2).

## Decision
- Add `EbookMetadata` to `NormalizedMetadata` in `src/metashelf/domain/models.py`.
- Add optional `isbn: str | None = None` and `author: str | None = None` fields to `SearchQuery` in `src/metashelf/providers/base.py` (defaulting to `None` so all existing callers remain unchanged).
- Support reading both EPUB 3.3 (`belongs-to-collection` + `group-position`) and Calibre (`calibre:series` + `calibre:series_index`) in `read_opf_bytes`/`read_opf_file`, while writing EPUB 3.3 `belongs-to-collection` + `group-position` in `write_opf`.
