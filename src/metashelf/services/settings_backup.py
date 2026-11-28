"""Export and import of MetaShelf settings and library definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import Library, Setting
from metashelf.domain.models import LibraryType


async def export_settings_bundle(session: AsyncSession) -> dict[str, Any]:
    """Export all settings and library definitions as a JSON-serializable dict."""
    settings_rows = list((await session.scalars(select(Setting).order_by(Setting.key))).all())
    settings_map: dict[str, Any] = {}
    for row in settings_rows:
        try:
            settings_map[row.key] = json.loads(row.value_json)
        except Exception:
            settings_map[row.key] = row.value_json

    libraries = list((await session.scalars(select(Library).order_by(Library.id))).all())
    lib_list = [
        {
            "name": lib.name,
            "type": lib.type,
            "root_path": lib.root_path,
            "enabled": lib.enabled,
            "scan_cron": lib.scan_cron,
        }
        for lib in libraries
    ]
    return {
        "version": 1,
        "settings": settings_map,
        "libraries": lib_list,
    }


async def import_settings_bundle(
    session: AsyncSession,
    bundle: dict[str, Any],
) -> tuple[int, int]:
    """Validate and import a settings/libraries bundle."""
    if not isinstance(bundle, dict):
        raise ValueError("Settings bundle must be a JSON object.")

    raw_libs = bundle.get("libraries", [])
    if not isinstance(raw_libs, list):
        raise ValueError("'libraries' must be a list.")

    # Validate all library paths first before mutating DB
    validated_libs: list[tuple[str, LibraryType, Path, bool, str | None]] = []
    for entry in raw_libs:
        if not isinstance(entry, dict):
            raise ValueError("Each library entry must be an object.")
        lib_type = LibraryType(str(entry["type"]))
        raw_root = str(entry["root_path"]).strip()
        if not raw_root:
            raise ValueError("Library 'root_path' must not be empty.")
        resolved = Path(raw_root).resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Directory does not exist: {resolved}")
        name = str(entry.get("name") or resolved.name).strip() or resolved.name
        enabled = bool(entry.get("enabled", True))
        raw_cron = entry.get("scan_cron")
        scan_cron = str(raw_cron).strip() or None if raw_cron is not None else None
        validated_libs.append((name, lib_type, resolved, enabled, scan_cron))

    imported_libs = 0
    for name, lib_type, resolved, enabled, scan_cron in validated_libs:
        existing = await session.scalar(
            select(Library).where(Library.root_path == str(resolved))
        )
        if existing is None:
            session.add(
                Library(
                    name=name,
                    type=lib_type.value,
                    root_path=str(resolved),
                    enabled=enabled,
                    scan_cron=scan_cron,
                )
            )
        else:
            existing.name = name
            existing.type = lib_type.value
            existing.enabled = enabled
            existing.scan_cron = scan_cron
        imported_libs += 1

    raw_settings = bundle.get("settings", {})
    if not isinstance(raw_settings, dict):
        raise ValueError("'settings' must be an object.")

    imported_settings = 0
    for key, val in raw_settings.items():
        key_str = str(key).strip()
        if not key_str:
            continue
        encoded = json.dumps(val)
        row = await session.get(Setting, key_str)
        if row is None:
            session.add(Setting(key=key_str, value_json=encoded))
        else:
            row.value_json = encoded
        imported_settings += 1

    await session.commit()
    return imported_libs, imported_settings
