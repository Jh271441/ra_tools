from __future__ import annotations

import json
from typing import Any

import redis

from app.config import settings


class RedisCache:
    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        try:
            self._client = redis.from_url(settings.redis_url, decode_responses=True)
            self._client.ping()
        except Exception:
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def get_json(self, key: str) -> Any | None:
        if not self._client:
            return None
        value = self._client.get(key)
        if not value:
            return None
        return json.loads(value)

    def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        if not self._client:
            return
        self._client.setex(key, ttl or settings.cache_ttl_seconds, json.dumps(value, ensure_ascii=False))

    def delete_prefix(self, prefix: str) -> None:
        if not self._client:
            return
        for key in self._client.scan_iter(f"{prefix}*"):
            self._client.delete(key)

    def lock(self, key: str, ttl: int = 600) -> bool:
        if not self._client:
            return True
        return bool(self._client.set(key, "1", ex=ttl, nx=True))

    def unlock(self, key: str) -> None:
        if self._client:
            self._client.delete(key)


cache = RedisCache()
