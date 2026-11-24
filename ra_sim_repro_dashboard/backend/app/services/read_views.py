"""Fine-grained versioned cache for page reads; operational decisions stay uncached."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

from app.config import CONFIG_DIR, settings
from app.database import engine as default_engine
from app.domain.cycle import TZ
from app.infra.cache import cache as redis_cache
from app.repositories import read_models_repo, state_store  # noqa: F401 (registers Session hooks)

_lock = RLock()
_values: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
_fills: dict[Any, list[Any]] = {}
_read_db: ContextVar[Any] = ContextVar("read_view_session", default=None)
_read_memos: ContextVar[Any] = ContextVar("read_view_memos", default=None)
_MAX_ENTRIES = 128


def _file_revision(path):
    path = Path(path)
    try:
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
    except FileNotFoundError:
        return str(path), None


def revision(db, *, scope_releases: list[str] | None = None):
    """Lightweight version token using `release_data_versions` (1 tiny index scan, zero JSON).

    Previously scanned and sorted all 4 core tables (~10,000 rows) on every single GET.
    """
    versions = read_models_repo.get_version_signature(db, releases=scope_releases)
    return (
        db.get_bind(),
        versions,
        tuple(
            _file_revision(path)
            for path in [
                settings.versions_config,
                CONFIG_DIR / "versions.example.yaml",
                os.getenv("RELEASE_CYCLES_CONFIG", str(CONFIG_DIR / "release-cycles.default")),
            ]
        ),
        os.getenv("RELEASE_DRIVER_COMMAND_JSON"),
        os.getenv("RELEASE_WORKFLOW_ENABLED"),
        os.getenv("EVALUATION_WORKER_ENABLED", "1"),
        os.getenv("EVALUATION_CRON_ENABLED"),
        datetime.now(TZ).date(),
    )


def _redis_cache_key(token, name) -> str | None:
    try:
        # Exclude engine object (index 0); only cache for primary configured DB engine.
        serializable = [token[1:], name]
        raw = json.dumps(serializable, default=str, sort_keys=True, ensure_ascii=False)
    except Exception:
        return None
    return "ra_sim:view:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _is_json_primitive_tree(value: Any) -> bool:
    return isinstance(value, (dict, list))


def read_view(
    db,
    name,
    load,
    *,
    max_age=300,
    scope_releases: list[str] | None = None,
    model_cls: Any = None,
):
    # Never cache uncommitted state or a failed computation. Callers of this
    # helper are GET handlers, not the scheduler, publication, or submit paths.
    if db.new or db.dirty or db.deleted:
        return load()
    token = revision(db, scope_releases=scope_releases)
    key = (token, name)
    use_redis = db.get_bind() is default_engine and redis_cache.enabled
    redis_key = _redis_cache_key(token, name) if use_redis else None

    # Only requests for the same revision and view share a fill lock. A slow
    # board must not block unrelated pages or cache hits while holding the DB.
    with _lock:
        existing = _values.get(key)
        if existing and monotonic() - existing[0] < max_age:
            _values.move_to_end(key)
            return deepcopy(existing[1])
        fill = _fills.setdefault(key, [RLock(), 0])
        fill[1] += 1
    try:
        with fill[0]:
            with _lock:
                existing = _values.get(key)
                if existing and monotonic() - existing[0] < max_age:
                    _values.move_to_end(key)
                    return deepcopy(existing[1])
            if redis_key:
                from_redis = redis_cache.get_json(redis_key)
                if from_redis is not None:
                    if model_cls is not None and hasattr(model_cls, "validate_python"):
                        hydrated = model_cls.validate_python(from_redis)
                    elif model_cls is not None:
                        hydrated = model_cls.model_validate(from_redis)
                    else:
                        hydrated = from_redis
                    with _lock:
                        _values[key] = (monotonic(), deepcopy(hydrated))
                        _values.move_to_end(key)
                        while len(_values) > _MAX_ENTRIES:
                            _values.popitem(last=False)
                    return hydrated

            scope = _read_db.set(db)
            # Retain large immutable audit receipts only for this GET. Nested
            # public projections may reuse them, but another request (including
            # one using the same Session) must read and audit its own receipts.
            memos = _read_memos.set({} if scope.old_value is not db else _read_memos.get())
            try:
                value = load()
            finally:
                _read_memos.reset(memos)
                _read_db.reset(scope)
            cached = deepcopy(value)
            with _lock:
                _values[key] = (monotonic(), cached)
                _values.move_to_end(key)
                while len(_values) > _MAX_ENTRIES:
                    _values.popitem(last=False)
            if redis_key:
                if model_cls is not None and hasattr(model_cls, "dump_python"):
                    wire = model_cls.dump_python(cached, mode="json")
                elif model_cls is not None and hasattr(cached, "model_dump"):
                    wire = cached.model_dump(mode="json")
                elif _is_json_primitive_tree(cached):
                    wire = cached
                else:
                    wire = None
                if wire is not None:
                    try:
                        redis_cache.set_json(redis_key, wire, ttl=max(1, int(max_age)))
                    except TypeError:
                        pass
            return value
    finally:
        with _lock:
            fill[1] -= 1
            if not fill[1]:
                del _fills[key]


def read_projection(db, name, load, *, max_age=300, scope_releases: list[str] | None = None):
    """Reuse public subviews only inside a cached GET, never in worker decisions."""
    active = _read_db.get()
    if active is None or active is not db:
        return load()
    return read_view(db, name, load, max_age=max_age, scope_releases=scope_releases)


def read_memo(db, name, load):
    """Request-local immutable intermediates, never operational/cross-GET state."""
    values = _read_memos.get()
    if _read_db.get() is not db or values is None or db.new or db.dirty or db.deleted:
        return load()
    if name not in values:
        values[name] = load()
    return values[name]
