"""Application configuration loaded from environment variables and config dir."""

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {
    "",
    "dev-insecure-secret-change-me",
    "change-me-to-a-long-random-string",
}


class Settings(BaseSettings):
    """MetaShelf runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="METASHELF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = ""
    config_dir: Path = Path("/config")
    media_roots: str = "/media"
    base_url: str = ""
    log_level: str = "INFO"
    log_format: str = "json"
    tmdb_api_key: str = ""
    tvdb_api_key: str = ""
    fanart_api_key: str = ""
    google_books_api_key: str = ""
    comicvine_api_key: str = ""
    opensubtitles_api_key: str = ""
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""
    watch_enabled: bool = False
    database_url: str | None = Field(default=None)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.config_dir / "metashelf.db"
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def media_root_paths(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self.media_roots.split(","):
            cleaned = raw.strip()
            if cleaned:
                roots.append(Path(cleaned).resolve())
        return roots

    @property
    def thumbnails_dir(self) -> Path:
        return self.config_dir / "thumbnails"

    def ensure_secret_key(self) -> str:
        """Return configured secret key, or auto-generate and persist one in config_dir."""
        cleaned = self.secret_key.strip()
        if cleaned not in _PLACEHOLDER_SECRETS:
            return cleaned

        key_file = self.config_dir / ".secret_key"
        if key_file.exists():
            stored = key_file.read_text(encoding="utf-8").strip()
            if stored:
                self.secret_key = stored
                return stored

        self.config_dir.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated, encoding="utf-8")
        os.chmod(key_file, 0o600)
        self.secret_key = generated
        return generated


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
