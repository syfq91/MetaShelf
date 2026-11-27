# Phase 4 Implementation Plan: Ebooks (EPUB)

## Tasks

1. **Ebook scanner for `.epub` files; read embedded OPF inside each EPUB to prefill fields**
   - Domain model: `EbookMetadata` in `src/metashelf/domain/models.py`.
   - OPF reader (shared for embedded EPUB & sidecar `.opf`): `src/metashelf/readers/opf_ebook.py` (`read_opf_bytes`, `read_opf_file`, `read_epub_embedded_opf`).
   - Scanner: `src/metashelf/scanner/ebook.py` (`scan_ebook_library` walking `.epub` files, adopting sidecar `<ebook>.opf` first if present, else reading embedded OPF inside the `.epub` via `zipfile`, plus adopting `<ebook>.jpg`).
   - Tests (first): `tests/test_ebook_scanner.py` (builds real minimal `.epub` ZIP fixtures with `container.xml` + `package.opf`, tests embedded prefill, sidecar priority, and incremental skip).

2. **Open Library and Google Books providers; ISBN-first matching**
   - Add optional `isbn` and `author` to `SearchQuery` in `src/metashelf/providers/base.py`.
   - Add `google_books_api_key: str = ""` to `src/metashelf/config.py`.
   - Implement `OpenLibraryProvider` in `src/metashelf/providers/openlibrary.py` and `GoogleBooksProvider` in `src/metashelf/providers/googlebooks.py`.
   - Tests (first): `tests/test_ebook_providers.py` + `tests/fixtures/openlibrary/*.json` + `tests/fixtures/googlebooks/*.json`.

3. **Writer and reader for `<ebook filename>.opf` and cover `<ebook filename>.jpg`; adopt existing sidecars**
   - Writer: `src/metashelf/writers/opf_ebook.py` (`write_opf`, atomic + `.bak`, preserving unknown XML elements in `<metadata>`, supporting multiple `<dc:creator>` authors and series/group-position).
   - Golden fixture: `tests/fixtures/opf/dune_golden.opf`.
   - Tests (first): `tests/test_opf_ebook.py` (golden round-trip, multiple authors, series/index, unknown tag preservation, `.bak`).

4. **Series, author and multiple-author fields (+ Ebooks UI, DB rebuild & E2E)**
   - Matcher: `src/metashelf/matching/ebook.py` (ISBN-first matching, title+author fallback, writes `<ebook>.opf` and downloads `<ebook>.jpg`).
   - Service & Job: `scan_library` (`lib.type == "ebook"`) and `auto_match` (`lib.type == "ebook"`) in `src/metashelf/jobs/handlers.py`.
   - Router & Templates: `src/metashelf/web/routers/ebooks.py` and `src/metashelf/web/templates/ebooks/` (`index.html`, `_detail.html` with series, series_index, multiple authors, ISBN, edit/save).
   - Tests: `tests/test_phase4_e2e.py` (folder of EPUBs gets `.opf` and `.jpg` beside each file, then wipe/recreate empty DB and rescan -> restores identical metadata).
