# ComicInfo.xml Schema Notes

Source: Anansi Project `ComicInfo.xml` specification (`anansi-project.github.io`), verified 2026-11-27.

## Sidecar vs Embedded Archive
- Sidecar files saved next to `<comic>.cbz`:
  - `<comic>.xml` (ComicInfo.xml schema)
  - `<comic>.jpg` (cover image)
- The `.cbz` archive itself is **never modified**.
- On scan: if `<comic>.xml` exists, it wins; otherwise, if `ComicInfo.xml` is embedded inside the `.cbz` ZIP archive, the scanner reads it to prefill fields.

## Root Element & Fields (`<ComicInfo>`)
- `<Title>` (`xs:string`) — issue title
- `<Series>` (`xs:string`) — series name
- `<Number>` (`xs:string`) — issue number (string, e.g. `"1"`, `"1.5"`, `"Annual 1"`)
- `<Volume>` (`xs:int`) — volume number or start year
- `<Summary>` (`xs:string`) — plain-text issue summary
- `<Year>`, `<Month>`, `<Day>` (`xs:int`) — publication date
- `<Publisher>` (`xs:string`)
- `<Genre>` (`xs:string`, comma-separated)
- `<Writer>`, `<Penciller>`, `<Inker>`, `<Colorist>`, `<Letterer>`, `<CoverArtist>`, `<Editor>` (`xs:string`, comma-separated when multiple)
- `<PageCount>` (`xs:int`)
- `<Web>` (`xs:string`, e.g. Comic Vine URL)
- Unknown XML elements are preserved when re-saving.
