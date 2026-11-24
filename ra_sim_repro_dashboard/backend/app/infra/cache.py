"""Resilient Redis cache & token-safe distributed lock with automatic reconnect."""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

import redis

from app.infra.settings import settings

logger = logging.getLogger(__name__)

_UNLOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisCache:
    """Resilient Redis cache & token-safe distributed lock with automatic reconnect."""

    def __init__(self, reconnect_backoff_seconds: float = 15.0) -> None:
        self._client: redis.Redis | None = None
        self._last_failed_at: float = 0.0
        self._reconnect_backoff = reconnect_backoff_seconds
        self._lock_tokens: dict[str, str] = {}
        self._connect()

    def _connect(self) -> redis.Redis | None:
        if self._client is not None:
            return self._client
        now = time.monotonic()
        if self._last_failed_at and (now - self._last_failed_at) < self._reconnect_backoff:
            return None
        try:
            client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            client.ping()
            self._client = client
            self._last_failed_at = 0.0
            return self._client
        except Exception:
            self._client = None
            self._last_failed_at = now
            return None

    def _handle_failure(self, exc: Exception) -> None:
        logger.debug("Redis operation failed; falling back to DB/in-process cache: %s", exc)
        self._client = None
        self._last_failed_at = time.monotonic()

    @property
    def enabled(self) -> bool:
        return self._connect() is not None

    def get_json(self, key: str) -> Any | None:
        client = self._connect()
        if not client:
            return None
        try:
            value = client.get(key)
            if not value:
                return None
            return json.loads(value)
        except Exception as exc:
            self._handle_failure(exc)
            return None

    def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        client = self._connect()
        if not client:
            return
        try:
            client.setex(
                key, ttl or settings.cache_ttl_seconds, json.dumps(value, ensure_ascii=False)
            )
        except Exception as exc:
            self._handle_failure(exc)

    def delete_prefix(self, prefix: str) -> None:
        client = self._connect()
        if not client:
            return
        try:
            batch: list[str] = []
            for key in client.scan_iter(f"{prefix}*", count=200):
                batch.append(key)
                if len(batch) >= 200:
                    client.delete(*batch)
                    batch.clear()
            if batch:
                client.delete(*batch)
        except Exception as exc:
            self._handle_failure(exc)

    def lock(self, key: str, ttl: int = 600) -> bool:
        client = self._connect()
        if not client:
            return True
        token = secrets.token_hex(16)
        try:
            acquired = bool(client.set(key, token, ex=ttl, nx=True))
            if acquired:
                self._lock_tokens[key] = token
            return acquired
        except Exception as exc:
            self._handle_failure(exc)
            return True

    def unlock(self, key: str, token: str | None = None) -> None:
        client = self._connect()
        expected = token or self._lock_tokens.pop(key, None)
        if not client:
            return
        try:
            if expected:
                client.eval(_UNLOCK_LUA, 1, key, expected)
            else:
                client.delete(key)
        except Exception as exc:
            self._handle_failure(exc)


cache = RedisCache()
