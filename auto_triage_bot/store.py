from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .events import IncomingEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS bot_events (
                    event_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    question TEXT NOT NULL,
                    chat_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    answer TEXT NOT NULL DEFAULT '',
                    delivery_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bot_events_queue
                ON bot_events(status, next_attempt_at, created_at);
                """
            )
            conn.execute(
                "UPDATE bot_events SET status='queued', updated_at=? WHERE status='running'",
                (_now(),),
            )

    def enqueue(self, event: IncomingEvent) -> bool:
        now = _now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO bot_events (
                    event_id, sender, question, chat_id, next_attempt_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event.event_id, event.sender, event.text, event.chat_id, now, now, now),
            )
        return cursor.rowcount == 1

    def claim_next(self) -> dict[str, Any] | None:
        now = _now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM bot_events
                WHERE status='queued' AND next_attempt_at <= ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                """
                UPDATE bot_events
                SET status='running', attempt_count=attempt_count+1, updated_at=?
                WHERE event_id=?
                """,
                (now, row["event_id"]),
            )
            conn.execute("COMMIT")
        result = dict(row)
        result["attempt_count"] = int(result["attempt_count"]) + 1
        return result

    def complete(self, event_id: str, *, answer: str, delivery_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE bot_events
                SET status='completed', answer=?, delivery_id=?, error='', updated_at=?
                WHERE event_id=?
                """,
                (answer, delivery_id, _now(), event_id),
            )

    def fail(
        self, event_id: str, *, error: str, attempts: int, terminal: bool = False
    ) -> None:
        terminal = terminal or attempts >= 5
        next_at = datetime.now(timezone.utc) + timedelta(
            seconds=min(300, 2 ** min(attempts, 8))
        )
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE bot_events
                SET status=?, next_attempt_at=?, error=?, updated_at=?
                WHERE event_id=?
                """,
                (
                    "failed" if terminal else "queued",
                    next_at.isoformat(timespec="seconds"),
                    str(error)[:500],
                    _now(),
                    event_id,
                ),
            )

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bot_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return dict(row) if row else None
