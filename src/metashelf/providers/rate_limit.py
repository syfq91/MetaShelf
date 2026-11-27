"""Async per-provider rate limiter."""

import asyncio
import time


class AsyncRateLimiter:
    """Enforces a minimum interval between consecutive requests."""

    def __init__(self, calls_per_second: float = 3.0) -> None:
        self._interval = 1.0 / max(calls_per_second, 0.1)
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
