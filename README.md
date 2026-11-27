# MetaShelf

Self-hosted metadata manager for movies, TV shows, music, ebooks (EPUB) and comics (CBZ).
Runs headless in Docker on Linux and saves sidecar metadata, artwork, subtitles and lyrics next to your media files.

## Quick Start

```bash
cp .env.example .env
# Edit .env and set METASHELF_SECRET_KEY
docker compose up --build
```
