# EPUB & OPF Sidecar Format Notes

Source: W3C EPUB 3.3 Specification (`w3.org/TR/epub-33/`), verified 2026-11-27.

## Container & Embedded OPF
- Every `.epub` is a ZIP archive containing `META-INF/container.xml`.
- `META-INF/container.xml` points to the OPF package document via `<rootfile full-path="..." media-type="application/oebps-package+xml"/>`.
- Sidecar files written next to `<ebook>.epub`:
  - `<ebook>.opf` (OPF XML metadata)
  - `<ebook>.jpg` (cover image)
- The `.epub` archive itself is **never modified**.

## OPF Package Metadata (`<package>` / `<metadata>`)
- Namespaces: `xmlns="http://www.idpf.org/2007/opf"`, `xmlns:dc="http://purl.org/dc/elements/1.1/"`.
- Core Dublin Core elements:
  - `<dc:title>`
  - `<dc:creator id="creator01">...</dc:creator>` (repeatable for multiple authors)
  - `<dc:identifier id="pub-id" opf:scheme="ISBN">...</dc:identifier>` (or EPUB 3 `<dc:identifier>` with ISBN-10/ISBN-13)
  - `<dc:publisher>`, `<dc:date>`, `<dc:language>`, `<dc:description>`, `<dc:subject>` (repeatable tags/genres)
- Series metadata:
  - **EPUB 3.3**: `<meta property="belongs-to-collection" id="coll01">Series Name</meta>`, `<meta refines="#coll01" property="collection-type">series</meta>`, `<meta refines="#coll01" property="group-position">1</meta>`
  - **EPUB 2 / Calibre compatibility**: `<meta name="calibre:series" content="Series Name"/>`, `<meta name="calibre:series_index" content="1"/>`
  - Reader supports both; writer emits EPUB 3.3 `belongs-to-collection` / `group-position` (and preserves unknown elements in `<metadata>`).
