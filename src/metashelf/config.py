"""Application configuration loaded from environment variables and config dir."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MetaShelf runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="METASHELF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = "dev-insecure-secret-change-me"
    config_dir: Path = Path("/config")
    media_roots: str = "/media"
    base_url: str = ""
    log_level: str = "INFO"
    tmdb_api_key: str = ""
    tvdb_api_key: str = ""
    fanart_api_key: str = ""
    google_books_api_key: str = ""
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
