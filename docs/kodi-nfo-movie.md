# Kodi Movie NFO Format Notes

Source: Official Kodi Wiki (`NFO files/Movies`), verified 2026-11-27.

## Naming & Location
- `<VideoFileName>.nfo` (recommended, e.g. `Inception (2010).mkv` -> `Inception (2010).nfo`).
- `movie.nfo` when the movie lives in its own dedicated folder.
- UTF-8 encoding (`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`).

## Root Element & Supported Tags
Root element: `<movie>`

- `<title>`, `<originaltitle>`, `<sorttitle>`
- `<ratings><rating name="tmdb" max="10" default="true"><value>...</value><votes>...</votes></rating></ratings>`
- `<year>`, `<premiered>` (`YYYY-MM-DD`)
- `<outline>`, `<plot>`, `<tagline>`, `<runtime>` (minutes), `<mpaa>`
- `<uniqueid type="tmdb" default="true">...</uniqueid>`, `<uniqueid type="imdb" default="false">...</uniqueid>`
- `<genre>` (repeatable), `<country>` (repeatable), `<studio>` (repeatable), `<tag>` (repeatable)
- `<director>` (repeatable), `<credits>` (repeatable, writers)
- `<set><name>...</name><overview>...</overview></set>` (collection)
- `<trailer>`
- `<actor><name>...</name><role>...</role><order>...</order><thumb>...</thumb></actor>`

## Interoperability & Preservation
- Older NFOs may have `<set>Collection Name</set>` as plain text instead of `<set><name>...</name></set>`. Reader supports both; writer outputs `<set><name>...</name></set>`.
- Unknown XML elements (e.g. `<fileinfo>`, `<playcount>`, `<dateadded>`) present in an existing NFO must be preserved when re-saving.
