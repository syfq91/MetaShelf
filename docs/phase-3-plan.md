# Phase 3 Implementation Plan: Music

## Tasks

1. **Artist, album and track scanner using folder structure plus `mutagen` tags**
   - Dependency: add `mutagen>=1.47.0` to `pyproject.toml`.
   - Domain models: `ArtistMetadata`, `AlbumMetadata`, `TrackMetadata`, `TrackInfo` in `src/metashelf/domain/models.py`.
   - Scanner: `src/metashelf/scanner/music.py` (`scan_music_library` walking `Artist/Album/Track` or flat `Album/Track` using `mutagen` tags for title, artist, album, albumartist, tracknumber, discnumber, date, duration, and adopting existing `artist.nfo`, `album.nfo`, `folder.jpg`/`cover.jpg`).
   - Tests (first): `tests/test_music_scanner.py` (creates real tiny MP3/FLAC/OGG or tagged test files using `mutagen` / minimal valid frames, tests hierarchy, incremental skip, and NFO adoption).

2. **MusicBrainz provider (strict rate limiting, User-Agent) and Cover Art Archive**
   - `src/metashelf/providers/musicbrainz.py`: `MusicBrainzProvider` (`id="musicbrainz"`, `media_kinds={"artist", "album"}`, `needs_api_key=False`, `AsyncRateLimiter(calls_per_second=1.0)`, descriptive `User-Agent`, `search`, `fetch`, `fetch_release_tracks`).
   - `src/metashelf/providers/coverart.py`: `CoverArtArchiveProvider` (`id="coverart"`, `artwork("album", release_mbid)`, fallback to release-group).
   - Update `src/metashelf/writers/artwork.py`: support `allow_redirects: bool = False` with post-redirect URL SSRF validation (ADR 0004).
   - Tests (first): `tests/test_musicbrainz_provider.py`, `tests/test_coverart_provider.py` + `tests/fixtures/musicbrainz/*.json`, `tests/fixtures/coverart/*.json`.

3. **`artist.nfo`, `album.nfo`, `folder.jpg` writers and readers**
   - Readers: `src/metashelf/readers/kodi_nfo_music.py` (`read_artist_nfo`, `read_album_nfo`).
   - Writers: `src/metashelf/writers/kodi_nfo_music.py` (`write_artist_nfo`, `write_album_nfo`, atomic + `.bak`, preserving unknown XML elements).
   - Golden fixtures: `tests/fixtures/nfo/artist_golden.nfo`, `tests/fixtures/nfo/album_golden.nfo`.
   - Tests (first): `tests/test_kodi_nfo_music.py` (golden round-trip, unknown tag preservation, `.bak`).

4. **Album match using track count and track titles to disambiguate releases (+ Music UI & E2E)**
   - Matcher: `src/metashelf/matching/music.py` (`score_album_release` scoring title, artist, year, track count exact/diff, and track title similarity; `match_artist_and_albums` service).
   - Service & Job: `src/metashelf/services/music_save.py`, `scan_library` (`lib.type == "music"`), and `auto_match_music` job handler.
   - Router & Templates: `src/metashelf/web/routers/music.py` and `src/metashelf/web/templates/music/` (Artist -> Album -> Track tree, edit/save/scrape).
   - Tests (first): `tests/test_music_matcher.py` (disambiguating two releases of the same album by track count & track titles), `tests/test_phase3_e2e.py` (artist folder with two albums gets correct `artist.nfo`, `album.nfo`, and `folder.jpg` using recorded fixtures).
