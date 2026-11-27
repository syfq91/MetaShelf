# Kodi TV Show & Episode NFO Format Notes

Source: Official Kodi Wiki (`NFO files/TV shows`, `NFO files/Episodes`), verified 2026-11-27.

## Naming & Location
- **Show folder**: `tvshow.nfo`, `poster.jpg`, `fanart.jpg`, `banner.jpg`, `seasonNN-poster.jpg` (e.g. `season01-poster.jpg`, `season00-poster.jpg` for specials).
- **Episode**: `<episode filename>.nfo` and `<episode filename>-thumb.jpg` next to the video file.

## `tvshow.nfo` (`<tvshow>`)
- `<title>`, `<originaltitle>`, `<sorttitle>`
- `<ratings><rating name="tmdb" max="10" default="true"><value>...</value><votes>...</votes></rating></ratings>`
- `<year>`, `<premiered>` (`YYYY-MM-DD`), `<status>` (`Continuing`, `Ended`)
- `<plot>`, `<outline>`, `<tagline>`, `<mpaa>`
- `<uniqueid type="tmdb" default="true">...</uniqueid>`, `<uniqueid type="tvdb" default="false">...</uniqueid>`, `<uniqueid type="imdb" default="false">...</uniqueid>`
- `<genre>` (repeatable), `<studio>` (repeatable), `<tag>` (repeatable)
- `<actor><name>...</name><role>...</role><order>...</order><thumb>...</thumb></actor>`
- Unknown XML elements (e.g. `<episodeguide>`, `<dateadded>`) are preserved when re-saving.

## Episode NFO (`<episodedetails>`)
- `<title>`, `<showtitle>`
- `<season>` (integer, `0` for specials), `<episode>` (integer)
- `<aired>` (`YYYY-MM-DD`), `<plot>`, `<runtime>` (minutes)
- `<ratings><rating ...><value>...</value><votes>...</votes></rating></ratings>`
- `<uniqueid type="tmdb|tvdb|imdb">...</uniqueid>`
- `<director>` (repeatable), `<credits>` (repeatable, writers)
- `<actor>...</actor>`

### Multi-Episode Files (e.g. `Show.S01E01E02.mkv`)
- For Kodi v21 compatibility, a multi-episode NFO stacks sequential `<episodedetails>` root blocks in the same `.nfo` file, each with mandatory `<season>` and `<episode>`.
- Reader parses all `<episodedetails>` elements in the file; writer emits one `<episodedetails>` per episode (stacked when a file represents multiple episodes).
