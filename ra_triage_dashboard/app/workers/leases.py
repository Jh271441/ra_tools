"""Database-backed distributed lease manager for single-leader background tasks.

Guarantees that across multi-worker uvicorn deployments or separate web + worker
daemons, external side-effect loops (DChat notifications, Trail writes, GT sync,
human-label publication) execute under strictly one active lease holder at a time.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os
import socket
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger("ra_triage_dashboard.workers")


def make_worker_owner_id(prefix: str = "worker") -> str:
    host = socket.gethostname() or "localhost"
    return f"{prefix}:{host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _utc_iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).isoformat()


class WorkerLeaseManager:
    """Atomic DB-backed lease table helper supporting PostgreSQL and SQLite."""

    def __init__(self, database: Any, owner_id: str | None = None) -> None:
        self._database = database
        self.owner_id = owner_id or make_worker_owner_id()
        self._host_name = socket.gethostname() or "localhost"
        self._pid = os.getpid()

    def try_acquire_or_renew(
        self,
        lease_key: str,
        *,
        ttl_seconds: float = 60.0,
        now: dt.datetime | None = None,
    ) -> bool:
        """Acquire an expired/free lease or renew an existing lease held by self."""
        key = str(lease_key or "").strip()
        if not key:
            raise ValueError("lease_key is required")
        ttl = max(1.0, float(ttl_seconds))
        current = now or dt.datetime.now(dt.timezone.utc)
        expires = current + dt.timedelta(seconds=ttl)

        with self._database.connect() as conn:
            if getattr(self._database, "backend", "sqlite") == "postgresql":
                row = conn.execute(
                    """
                    INSERT INTO worker_leases (
                        lease_key, owner_id, host_name, pid,
                        acquired_at, renewed_at, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (lease_key) DO UPDATE SET
                        owner_id = EXCLUDED.owner_id,
                        host_name = EXCLUDED.host_name,
                        pid = EXCLUDED.pid,
                        acquired_at = CASE
                            WHEN worker_leases.owner_id = EXCLUDED.owner_id
                            THEN worker_leases.acquired_at
                            ELSE EXCLUDED.acquired_at
                        END,
                        renewed_at = EXCLUDED.renewed_at,
                        expires_at = EXCLUDED.expires_at
                    WHERE worker_leases.owner_id = EXCLUDED.owner_id
                       OR worker_leases.expires_at <= %s
                    RETURNING lease_key
                    """,
                    (
                        key,
                        self.owner_id,
                        self._host_name,
                        self._pid,
                        current,
                        current,
                        expires,
                        current,
                    ),
                ).fetchone()
                return row is not None

            now_iso = _utc_iso(current)
            exp_iso = _utc_iso(expires)
            with self._database._write_lock:
                existing = conn.execute(
                    "SELECT owner_id, expires_at FROM worker_leases WHERE lease_key = ?",
                    (key,),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO worker_leases (
                            lease_key, owner_id, host_name, pid,
                            acquired_at, renewed_at, expires_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (key, self.owner_id, self._host_name, self._pid, now_iso, now_iso, exp_iso),
                    )
                    return True
                holder = str(existing["owner_id"])
                exp_val = str(existing["expires_at"])
                if holder == self.owner_id or exp_val <= now_iso:
                    conn.execute(
                        """
                        UPDATE worker_leases
                        SET owner_id = ?,
                            host_name = ?,
                            pid = ?,
                            acquired_at = CASE WHEN owner_id = ? THEN acquired_at ELSE ? END,
                            renewed_at = ?,
                            expires_at = ?
                        WHERE lease_key = ?
                        """,
                        (
                            self.owner_id,
                            self._host_name,
                            self._pid,
                            self.owner_id,
                            now_iso,
                            now_iso,
                            exp_iso,
                            key,
                        ),
                    )
                    return True
                return False

    def release(self, lease_key: str) -> bool:
        """Release a lease if currently owned by this worker."""
        key = str(lease_key or "").strip()
        if not key:
            return False
        with self._database.connect() as conn:
            if getattr(self._database, "backend", "sqlite") == "postgresql":
                cur = conn.execute(
                    "DELETE FROM worker_leases WHERE lease_key = %s AND owner_id = %s",
                    (key, self.owner_id),
                )
                return bool(cur.rowcount)
            with self._database._write_lock:
                cur = conn.execute(
                    "DELETE FROM worker_leases WHERE lease_key = ? AND owner_id = ?",
                    (key, self.owner_id),
                )
                return bool(cur.rowcount)

    def list_active_leases(self, *, now: dt.datetime | None = None) -> list[dict[str, Any]]:
        """Return currently unexpired leases for status and Prometheus metrics."""
        current = now or dt.datetime.now(dt.timezone.utc)
        try:
            with self._database.connect() as conn:
                if getattr(self._database, "backend", "sqlite") == "postgresql":
                    rows = conn.execute(
                        """
                        SELECT lease_key, owner_id, host_name, pid, acquired_at, renewed_at, expires_at
                        FROM worker_leases
                        WHERE expires_at > %s
                        ORDER BY lease_key ASC
                        """,
                        (current,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT lease_key, owner_id, host_name, pid, acquired_at, renewed_at, expires_at
                        FROM worker_leases
                        WHERE expires_at > ?
                        ORDER BY lease_key ASC
                        """,
                        (_utc_iso(current),),
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


async def run_with_lease(
    lease_manager: WorkerLeaseManager,
    lease_key: str,
    coro_factory: Callable[[], Awaitable[None]],
    *,
    ttl_seconds: float = 90.0,
    retry_seconds: float = 15.0,
) -> None:
    """Keep a long-running coroutine active strictly while holding its DB lease."""
    renew_interval = max(5.0, ttl_seconds / 3.0)
    while True:
        acquired = False
        try:
            acquired = await asyncio.to_thread(
                lease_manager.try_acquire_or_renew,
                lease_key,
                ttl_seconds=ttl_seconds,
            )
        except Exception:
            logger.exception("worker_lease_acquire_error lease=%s", lease_key)

        if not acquired:
            await asyncio.sleep(retry_seconds)
            continue

        logger.info("worker_lease_acquired lease=%s owner=%s", lease_key, lease_manager.owner_id)
        inner_task = asyncio.create_task(coro_factory(), name=f"leased:{lease_key}")
        try:
            while not inner_task.done():
                await asyncio.sleep(renew_interval)
                if inner_task.done():
                    break
                still_held = await asyncio.to_thread(
                    lease_manager.try_acquire_or_renew,
                    lease_key,
                    ttl_seconds=ttl_seconds,
                )
                if not still_held:
                    logger.warning("worker_lease_lost lease=%s owner=%s", lease_key, lease_manager.owner_id)
                    inner_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await inner_task
                    break
            if inner_task.done() and not inner_task.cancelled():
                exc = inner_task.exception()
                if exc is not None:
                    logger.error("worker_task_failed lease=%s error=%r", lease_key, exc)
                    await asyncio.sleep(retry_seconds)
                else:
                    # One-shot startup tasks (like trail-sync-startup) exit cleanly.
                    return
        except asyncio.CancelledError:
            inner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await inner_task
            with contextlib.suppress(Exception):
                await asyncio.to_thread(lease_manager.release, lease_key)
            raise
