"""SQLite-backed provider response cache."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from metashelf.db.models import ProviderCache


class ProviderResponseCache:
    """Caches raw provider JSON responses in the provider_cache table."""

    def __init__(self, session: AsyncSession, default_ttl: int = 86400) -> None:
        self._session = session
        self._default_ttl = default_ttl

    async def get(self, key: str) -> dict[str, Any] | None:
        row = await self._session.get(ProviderCache, key)
        if row is None:
            return None
        fetched = row.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        if datetime.now(UTC) > fetched + timedelta(seconds=row.ttl):
            return None
        data = json.loads(row.response_json)
        return data if isinstance(data, dict) else None

    async def set(self, key: str, data: dict[str, Any], ttl: int | None = None) -> None:
        now = datetime.now(UTC)
        encoded = json.dumps(data)
        row = await self._session.get(ProviderCache, key)
        effective_ttl = ttl if ttl is not None else self._default_ttl
        if row is None:
            self._session.add(
                ProviderCache(
                    key=key,
                    response_json=encoded,
                    fetched_at=now,
                    ttl=effective_ttl,
                )
            )
        else:
            row.response_json = encoded
            row.fetched_at = now
            row.ttl = effective_ttl
        await self._session.flush()
