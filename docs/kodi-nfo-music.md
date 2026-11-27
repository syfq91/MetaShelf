# Kodi Music NFO Format Notes (`artist.nfo` and `album.nfo`)

Source: Official Kodi Wiki (`NFO files/Artists`, `NFO files/Albums`), verified 2026-11-27.

## Naming & Location
- **Artist folder**: `artist.nfo`, `folder.jpg`, `fanart.jpg`
- **Album folder**: `album.nfo`, `folder.jpg` (or `cover.jpg` adopted on scan)

## `artist.nfo` (`<artist>`)
- `<name>`, `<sortname>`
- `<musicbrainzartistid>`
- `<type>` (`Group`, `Person`, `Orchestra`, etc.)
- `<gender>`, `<disambiguation>`
- `<born>`, `<formed>`, `<died>`, `<disbanded>`, `<yearsactive>`
- `<biography>`
- `<genre>` (repeatable), `<style>` (repeatable), `<mood>` (repeatable)
- Unknown XML elements are preserved on re-save.

## `album.nfo` (`<album>`)
- `<title>`
- `<musicbrainzalbumid>` (MusicBrainz Release MBID)
- `<musicbrainzreleasegroupid>` (MusicBrainz Release Group MBID)
- `<albumArtistCredits><artist>...</artist><musicBrainzArtistID>...</musicBrainzArtistID></albumArtistCredits>`
- `<year>`, `<releasedate>` (`YYYY-MM-DD`), `<label>`, `<type>` (`Album`, `Single`, `EP`), `<compilation>` (`true`/`false`), `<boxset>` (`true`/`false`)
- `<review>`, `<rating max="10">...</rating>`
- `<genre>`, `<style>`, `<mood>`, `<theme>` (all repeatable)
- `<track><position>...</position><title>...</title><duration>...</duration></track>` (optional track listing)
- Unknown XML elements are preserved on re-save.
