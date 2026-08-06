"""Shared storage primitives used by the database domain mixins.

The original MVP kept these helpers in ``app.db``.  Keeping them in a small
dependency-free module lets the domain mixins import the same objects without
depending on the aggregate ``Database`` class during module initialisation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from ..sanitization import redact_sensitive_fields


LABELS = ("误触发", "正确触发", "无需协助")
COMPARISON_STATUSES = ("all", "mismatch", "match", "none")
REVIEW_STATUSES = ("pending", "reviewed", "needs_gt_review")
BATCH_JOB_STATUSES = ("queued", "running", "succeeded", "partial", "failed")
BATCH_PUBLISH_STATUSES = (
    "not_requested",
    "running",
    "succeeded",
    "partial",
    "failed",
)
ACCESS_ROLES = ("writer", "admin")


class AnnotationConflictError(RuntimeError):
    """Raised when a Review save is based on a stale version."""


# ``None`` is a valid expected value (the editor saw no Review yet).  The
# sentinel keeps direct/legacy Database callers backwards compatible while the
# HTTP Review form always sends an explicit optimistic-lock value.
_EXPECTED_ANNOTATION_UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _postgres_sql(sql: str) -> str:
    """Translate the deliberately small SQLite query subset to psycopg."""

    output: list[str] = []
    quoted = False
    index = 0
    while index < len(sql):
        character = sql[index]
        if character == "'":
            output.append(character)
            if quoted and index + 1 < len(sql) and sql[index + 1] == "'":
                output.append("'")
                index += 2
                continue
            quoted = not quoted
        elif character == "?" and not quoted:
            output.append("%s")
        else:
            output.append(character)
        index += 1
    translated = "".join(output).replace(" COLLATE BINARY", "")
    translated = re.sub(
        r"\b(ann\.(?:tags_json|missing_evidence_json))\s+LIKE\s+",
        r"\1::text ILIKE ",
        translated,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+LIKE\s+", " ILIKE ", translated, flags=re.IGNORECASE)


class _CompatRow:
    """Expose psycopg mapping rows through sqlite3.Row's tiny used surface."""

    def __init__(self, values: dict[str, Any]):
        self._values = values
        self._keys = tuple(values.keys())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            key = self._keys[key]
        value = self._values[key]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return value

    def keys(self) -> tuple[str, ...]:
        return self._keys


class _PostgresCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    @property
    def lastrowid(self) -> None:
        return None

    def fetchone(self) -> _CompatRow | None:
        row = self._cursor.fetchone()
        return _CompatRow(row) if row is not None else None

    def fetchall(self) -> list[_CompatRow]:
        return [_CompatRow(row) for row in self._cursor.fetchall()]


class _NoopCursor:
    rowcount = 0
    lastrowid = None

    @staticmethod
    def fetchone() -> None:
        return None

    @staticmethod
    def fetchall() -> list[Any]:
        return []


class _PostgresConnection:
    def __init__(self, connection: Any):
        self._connection = connection

    def execute(
        self, sql: str, params: Iterable[Any] = ()
    ) -> _PostgresCursor | _NoopCursor:
        if sql.lstrip().upper().startswith("CREATE TRIGGER IF NOT EXISTS"):
            return _NoopCursor()
        return _PostgresCursor(
            self._connection.execute(_postgres_sql(sql), tuple(params))
        )

    def executemany(
        self, sql: str, params: Iterable[Iterable[Any]]
    ) -> _PostgresCursor:
        cursor = self._connection.cursor()
        cursor.executemany(
            _postgres_sql(sql), [tuple(values) for values in params]
        )
        return _PostgresCursor(cursor)

    @staticmethod
    def executescript(_: str) -> None:
        # PostgreSQL schema and revision triggers are applied by migrations.
        return None
