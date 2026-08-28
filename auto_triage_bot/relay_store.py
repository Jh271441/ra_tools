from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .events import IncomingEvent


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now_dt()).isoformat(timespec="seconds")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RelayStore:
    """Durable relay queue with expiring worker leases.

    Only normalized DChat event fields are persisted. Raw callbacks and secrets
    never enter the queue database.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS relay_events (
                    event_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    question TEXT NOT NULL,
                    chat_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    lease_token_hash TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    leased_by TEXT NOT NULL DEFAULT '',
                    delivery_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_relay_events_queue
                ON relay_events(status, next_attempt_at, created_at);
                """
            )

    def enqueue(self, event: IncomingEvent) -> bool:
        now = _timestamp()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO relay_events (
                    event_id, sender, question, chat_id, next_attempt_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event.event_id, event.sender, event.text, event.chat_id, now, now, now),
            )
        return cursor.rowcount == 1

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM relay_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return dict(row) if row else None

    def counts(self) -> dict[str, int]:
        result = {"queued": 0, "leased": 0, "completed": 0, "failed": 0}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, count(*) AS total FROM relay_events GROUP BY status"
            ).fetchall()
        for row in rows:
            status = str(row["status"])
            if status in result:
                result[status] = int(row["total"])
        return result

    def claim_next(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> dict[str, Any] | None:
        now_dt = _now_dt()
        now = _timestamp(now_dt)
        lease_expires = _timestamp(now_dt + timedelta(seconds=lease_seconds))
        lease_token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE relay_events
                SET status=CASE WHEN attempt_count >= ? THEN 'failed' ELSE 'queued' END,
                    next_attempt_at=?, lease_token_hash='', lease_expires_at='',
                    leased_by='', error=CASE WHEN attempt_count >= ?
                        THEN 'Worker lease expired after maximum attempts.' ELSE error END,
                    updated_at=?
                WHERE status='leased' AND lease_expires_at <= ?
                """,
                (max_attempts, now, max_attempts, now, now),
            )
            row = conn.execute(
                """
                SELECT * FROM relay_events
                WHERE status='queued' AND next_attempt_at <= ? AND attempt_count < ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (now, max_attempts),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            updated = conn.execute(
                """
                UPDATE relay_events
                SET status='leased', attempt_count=attempt_count+1,
                    lease_token_hash=?, lease_expires_at=?, leased_by=?, updated_at=?
                WHERE event_id=? AND status='queued'
                """,
                (
                    _token_hash(lease_token),
                    lease_expires,
                    worker_id,
                    now,
                    row["event_id"],
                ),
            )
            if updated.rowcount != 1:
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
        result = {
            "event_id": str(row["event_id"]),
            "sender": str(row["sender"]),
            "question": str(row["question"]),
            "chat_id": str(row["chat_id"]),
            "attempt_count": int(row["attempt_count"]) + 1,
            "lease_token": lease_token,
            "lease_expires_at": lease_expires,
        }
        return result

    def ack(self, *, event_id: str, lease_token: str, delivery_id: str) -> bool:
        delivery_id = delivery_id[:256]
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE relay_events
                SET status='completed', delivery_id=?, error='',
                    lease_token_hash='', lease_expires_at='', leased_by='', updated_at=?
                WHERE event_id=? AND status='leased' AND lease_token_hash=?
                """,
                (delivery_id, _timestamp(), event_id, _token_hash(lease_token)),
            )
            if cursor.rowcount == 1:
                return True
            # Make ACK safe to retry when the relay committed the first ACK but
            # its HTTP response was lost on the way back to the worker.
            row = conn.execute(
                "SELECT status, delivery_id FROM relay_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
        return bool(
            row
            and row["status"] == "completed"
            and str(row["delivery_id"]) == delivery_id
        )

    def nack(
        self,
        *,
        event_id: str,
        lease_token: str,
        error: str,
        terminal: bool,
        max_attempts: int,
    ) -> bool:
        now_dt = _now_dt()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT attempt_count FROM relay_events
                WHERE event_id=? AND status='leased' AND lease_token_hash=?
                """,
                (event_id, _token_hash(lease_token)),
            ).fetchone()
            if row is None:
                return False
            attempts = int(row["attempt_count"])
            final = terminal or attempts >= max_attempts
            next_at = now_dt + timedelta(seconds=min(300, 2 ** min(attempts, 8)))
            cursor = conn.execute(
                """
                UPDATE relay_events
                SET status=?, next_attempt_at=?, error=?, lease_token_hash='',
                    lease_expires_at='', leased_by='', updated_at=?
                WHERE event_id=? AND status='leased' AND lease_token_hash=?
                """,
                (
                    "failed" if final else "queued",
                    _timestamp(next_at),
                    str(error)[:500],
                    _timestamp(now_dt),
                    event_id,
                    _token_hash(lease_token),
                ),
            )
        return cursor.rowcount == 1
