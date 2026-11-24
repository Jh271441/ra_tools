"""Cross-process advisory locks: PostgreSQL pg_advisory_lock with SQLite fallback.

PostgreSQL advisory locks are held on a dedicated pooled connection outside any
request/worker ORM Session so rollbacks cannot silently drop the lock, and a
crashed worker automatically releases all locks when its TCP/Unix socket closes.
Never hold an advisory lock across long external subprocess calls.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import struct
import threading
from collections.abc import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import engine as default_engine

_local_guard = threading.Lock()
_local_locks: dict[str, threading.RLock] = {}
_local_holders: dict[str, int] = {}


class LockBusyError(ValueError):
    """Raised when a non-blocking advisory lock is already held."""


def _lock_key_int64(name: str) -> int:
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return struct.unpack(">q", digest)[0]


def _local_lock_for(name: str) -> threading.RLock:
    with _local_guard:
        lock = _local_locks.get(name)
        if lock is None:
            lock = threading.RLock()
            _local_locks[name] = lock
        return lock


@contextmanager
def advisory_lock(
    name: str,
    *,
    blocking: bool = False,
    engine: Engine | None = None,
    busy_message: str = "busy",
) -> Iterator[None]:
    """Acquire a named advisory lock across processes (PG) or threads (SQLite)."""
    bind = engine or default_engine
    if bind.dialect.name == "postgresql":
        key = _lock_key_int64(name)
        conn = bind.connect()
        acquired = False
        try:
            if blocking:
                conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
                acquired = True
            else:
                acquired = bool(
                    conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
                )
            if not acquired:
                raise LockBusyError(busy_message)
            yield
        finally:
            try:
                if acquired:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            finally:
                conn.close()
        return

    # SQLite / in-process fallback (non-reentrant across distinct callers on busy)
    tid = threading.get_ident()
    with _local_guard:
        holder = _local_holders.get(name)
        if not blocking and holder is not None and holder != tid:
            raise LockBusyError(busy_message)
    lock = _local_lock_for(name)
    acquired = lock.acquire(blocking=blocking)
    if not acquired:
        raise LockBusyError(busy_message)
    with _local_guard:
        prev_holder = _local_holders.get(name)
        _local_holders[name] = tid
    try:
        yield
    finally:
        with _local_guard:
            if prev_holder is None:
                _local_holders.pop(name, None)
            else:
                _local_holders[name] = prev_holder
        lock.release()
