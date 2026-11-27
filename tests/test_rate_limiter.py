"""Tests for async per-provider rate limiter (written before implementation)."""

import time

from metashelf.providers.rate_limit import AsyncRateLimiter


async def test_rate_limiter_enforces_interval() -> None:
    limiter = AsyncRateLimiter(calls_per_second=20.0)  # 50ms interval
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08
