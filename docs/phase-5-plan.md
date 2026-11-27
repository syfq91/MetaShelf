# Phase 5 Implementation Plan: Comics (CBZ)

## Tasks

1. **Comic scanner for `.cbz` files: series folders, issue number, volume & year parsing; read embedded `ComicInfo.xml`**
   - Domain model: `ComicMetadata` in `src/metashelf/domain/models.py`.
   - Parser: `parse_comic_filename` in `src/metashelf/scanner/parser.py` (series folder, issue `#001`/`001`, volume `v01`/`Vol. 2`, year `(2020)`).
   - Reader (shared for sidecar `<comic>.xml` & embedded `ComicInfo.xml`): `src/metashelf/readers/comicinfo_xml.py` (`read_comicinfo_bytes`, `read_comicinfo_file`, `read_cbz_embedded_comicinfo`).
   - Scanner: `src/metashelf/scanner/comic.py` (`scan_comic_library`, sidecar `<comic>.xml` wins over embedded `ComicInfo.xml`, archive untouched, incremental mtime/size).
   - Tests (first): `tests/test_comic_parser.py`, `tests/test_comic_scanner.py`.

2. **Comic Vine provider (volume search, then issue fetch)**
   - Config: add `comicvine_api_key: str = ""` to `src/metashelf/config.py`.
   - Provider: `src/metashelf/providers/comicvine.py` (`ComicVineProvider` with `needs_api_key=True`, descriptive `User-Agent`, `format=json`, `AsyncRateLimiter(calls_per_second=0.8)`, volume search, volume issues listing, issue fetch with `person_credits`, artwork).
   - Tests (first): `tests/test_comicvine_provider.py` + `tests/fixtures/comicvine/*.json`.

3. **Writer and reader for `<comic filename>.xml` (`ComicInfo.xml`) with golden-file tests & cover extraction/download**
   - Writer: `src/metashelf/writers/comicinfo_xml.py` (`write_comicinfo_xml`, atomic + `.bak`, preserving unknown XML elements).
   - Cover helper: `extract_cbz_first_page_cover` in `src/metashelf/writers/comic_cover.py` (validates with Pillow, writes `<comic>.jpg` atomically with `.bak`, never modifies `.cbz`).
   - Golden fixture: `tests/fixtures/comicinfo/batman_golden.xml`.
   - Tests (first): `tests/test_comicinfo_xml.py` (golden round-trip, unknown tag preservation, `.bak`, archive cover extraction).

4. **UI: series grouping in the list; fields for series, number, volume, year, publisher, writers, artists & summary (+ E2E)**
   - Matcher: `src/metashelf/matching/comic.py` (`auto_match_comic_library` matching series folder to Comic Vine volume, fetching issue details by issue number, writing `<comic>.xml` + `<comic>.jpg`).
   - Jobs: wire `lib.type == "comic"` in `scan_library` and `auto_match` in `src/metashelf/jobs/handlers.py`.
   - Router & Templates: `src/metashelf/web/routers/comics.py` and `src/metashelf/web/templates/comics/` (`index.html` with series-grouped list, `_detail.html` with series, number, volume, year, publisher, writers, artists, summary, edit/save).
   - Tests: `tests/test_comics_ui.py`, `tests/test_phase5_e2e.py` (folder of CBZs in series folders matched against recorded Comic Vine fixtures -> `.xml` and `.jpg` beside each file, archives untouched).
