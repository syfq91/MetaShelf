"""SQLAlchemy 2.0 ORM models."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarative class."""


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Library(Base):
    __tablename__ = "library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    root_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scan_cron: Mapped[str | None] = mapped_column(String(128), nullable=True)

    items: Mapped[list["Item"]] = relationship(
        back_populates="library",
        cascade="all, delete-orphan",
    )


class Item(Base):
    __tablename__ = "item"
    __table_args__ = (
        UniqueConstraint("library_id", "rel_path", name="uq_item_library_rel_path"),
        Index("ix_item_library_kind", "library_id", "kind"),
        Index("ix_item_state", "state"),
        Index("ix_item_title", "title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(
        ForeignKey("library.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("item.id", ondelete="CASCADE"),
        nullable=True,
    )
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="unmatched")
    provider_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    sidecar_mtime: Mapped[float | None] = mapped_column(nullable=True)
    media_mtime: Mapped[float | None] = mapped_column(nullable=True)
    media_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    library: Mapped["Library"] = relationship(back_populates="items")
    artworks: Mapped[list["Artwork"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
    )
    sidecar_files: Mapped[list["SidecarFile"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
    )


class SidecarFile(Base):
    __tablename__ = "sidecar_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("item.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    item: Mapped["Item"] = relationship(back_populates="sidecar_files")


class Artwork(Base):
    __tablename__ = "artwork"
    __table_args__ = (
        UniqueConstraint("item_id", "type", name="uq_artwork_item_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("item.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    item: Mapped["Item"] = relationship(back_populates="artworks")


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (Index("ix_job_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderCache(Base):
    __tablename__ = "provider_cache"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ttl: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
