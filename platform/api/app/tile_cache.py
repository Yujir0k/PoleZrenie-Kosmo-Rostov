from __future__ import annotations

import json
import time
from typing import Any

from redis.asyncio import Redis


class TileDescriptorCache:
    """Caches temporary map IDs without ever replacing their real GEE data."""

    def __init__(self, url: str, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._redis = Redis.from_url(url, decode_responses=True)
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        current = self._memory.get(key)
        if current and current[0] > time.monotonic():
            return current[1].copy()
        if current:
            self._memory.pop(key, None)
        try:
            payload = await self._redis.get(key)
        except Exception:
            return None
        if not payload:
            return None
        value = json.loads(payload)
        self._memory[key] = (time.monotonic() + self.ttl_seconds, value)
        return value.copy()

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self._memory[key] = (time.monotonic() + self.ttl_seconds, value.copy())
        try:
            await self._redis.set(key, json.dumps(value, ensure_ascii=False), ex=self.ttl_seconds)
        except Exception:
            pass

    async def close(self) -> None:
        await self._redis.aclose()
