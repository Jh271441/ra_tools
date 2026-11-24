"""Compatibility re-export of `app.infra.cache`."""

from __future__ import annotations

from app.infra.cache import RedisCache, _UNLOCK_LUA, cache

__all__ = ["RedisCache", "_UNLOCK_LUA", "cache"]
