#!/usr/bin/env python3
"""One-shot, verified SQLite -> PostgreSQL cutover copy.

The source SQLite database is never modified.  The target must contain no
dashboard data, and every logical table is compared after the transactional
copy before commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TABLES = (
    "issues",
    "annotations",
    "review_attachments",
    "model_runs",
    "model_predictions",
    "inference_jobs",
    "batch_prediction_jobs",
    "batch_prediction_items",
)
JSON_COLUMNS = {
    "issues": {"extra_json"},
    "annotations": {"tags_json", "missing_evidence_json"},
    "model_runs": {"metadata_json"},
    "model_predictions": {"model_extra_json", "raw_json"},
    "inference_jobs": {"config_json", "result_json"},
    "batch_prediction_jobs": {"input_config_json", "summary_json"},
    "batch_prediction_items": {"result_json"},
}
BOOLEAN_COLUMNS = {
    "annotations": {"author_verified"},
    "model_runs": {"is_default", "created_by_verified"},
    "inference_jobs": {"requested_by_verified"},
    "batch_prediction_jobs": {"requested_by_verified"},
}
PRIMARY_KEYS = {
    "issues": ("issue_id",),
    "annotations": ("id",),
    "review_attachments": ("id",),
    "model_runs": ("id",),
    "model_predictions": ("id",),
    "inference_jobs": ("id",),
    "batch_prediction_jobs": ("id",),
    "batch_prediction_items": ("job_id", "issue_id"),
}


def read_secret_file(path: Path) -> str:
    target = path.expanduser().absolute()
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("target URL file must be a regular file")
        if metadata.st_uid != os.getuid():
            raise RuntimeError("target URL file must belong to the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise RuntimeError("target URL file permissions must be 0600")
        content = os.read(descriptor, 16 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(content) > 16 * 1024:
        raise RuntimeError("target URL file is too large")
    value = content.decode("utf-8").strip()
    if not value.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("target URL must use postgresql://")
    return value


def normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (dict, list)):
        return value
    return value


def normalize_timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def canonical_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column, value in row.items():
        if column in JSON_COLUMNS.get(table, set()):
            if isinstance(value, str):
                value = json.loads(value or "{}")
            result[column] = value
        elif column in BOOLEAN_COLUMNS.get(table, set()):
            result[column] = bool(value)
        elif column.endswith("_at"):
            result[column] = normalize_timestamp(value)
        else:
            result[column] = normalize(value)
    return result


def digest_rows(table: str, rows: list[dict[str, Any]]) -> str:
    ordered = sorted(
        (canonical_row(table, row) for row in rows),
        key=lambda row: tuple(str(row[key]) for key in PRIMARY_KEYS[table]),
    )
    payload = json.dumps(
        ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sqlite_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid ASC')
    ]


def backup_sqlite(source: sqlite3.Connection, destination: Path) -> None:
    destination = destination.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"backup already exists: {destination}")
    backup = sqlite3.connect(destination)
    try:
        source.backup(backup)
    finally:
        backup.close()
    os.chmod(destination, 0o600)


def apply_migrations(database_url: str, migrations_dir: Path) -> None:
    from ra_triage_dashboard.app.db import Database

    database = Database(
        database_url,
        postgres_migrations_dir=migrations_dir,
        pool_size=2,
    )
    database._apply_postgres_migrations()


def migrate(
    source_path: Path,
    backup_path: Path,
    database_url: str,
    migrations_dir: Path,
) -> dict[str, Any]:
    try:
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("install psycopg[binary] before migration") from exc

    source = sqlite3.connect(
        f"file:{source_path.expanduser().absolute()}?mode=ro", uri=True
    )
    source.row_factory = sqlite3.Row
    try:
        source.execute("BEGIN")
        backup_sqlite(source, backup_path)
        source_data = {table: sqlite_rows(source, table) for table in TABLES}
        revision_row = source.execute(
            "SELECT revision, updated_at FROM dashboard_change_revision WHERE id = 1"
        ).fetchone()

        apply_migrations(database_url, migrations_dir)
        with psycopg.connect(database_url, row_factory=dict_row) as target:
            with target.transaction():
                counts = {
                    table: int(
                        target.execute(
                            sql.SQL("SELECT COUNT(*) AS count FROM {}")
                            .format(sql.Identifier(table))
                        ).fetchone()["count"]
                    )
                    for table in TABLES
                }
                occupied = {table: count for table, count in counts.items() if count}
                if occupied:
                    raise RuntimeError(f"PostgreSQL target is not empty: {occupied}")

                for table in TABLES:
                    rows = source_data[table]
                    if not rows:
                        continue
                    columns = tuple(rows[0].keys())
                    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                    )
                    values: list[tuple[Any, ...]] = []
                    for row in rows:
                        item: list[Any] = []
                        for column in columns:
                            value = row[column]
                            if column in JSON_COLUMNS.get(table, set()):
                                value = Jsonb(json.loads(value or "{}"))
                            elif column in BOOLEAN_COLUMNS.get(table, set()):
                                value = bool(value)
                            item.append(value)
                        values.append(tuple(item))
                    cursor = target.cursor()
                    cursor.executemany(statement, values)

                for table in ("annotations", "model_predictions"):
                    target.execute(
                        sql.SQL(
                            "SELECT setval(pg_get_serial_sequence({}, 'id'), "
                            "COALESCE((SELECT MAX(id) FROM {}), 1), "
                            "EXISTS (SELECT 1 FROM {}))"
                        ).format(
                            sql.Literal(table),
                            sql.Identifier(table),
                            sql.Identifier(table),
                        )
                    )

                target.execute(
                    "UPDATE dashboard_change_revision "
                    "SET revision = %s, updated_at = %s WHERE id = 1",
                    (
                        int(revision_row["revision"] if revision_row else 0),
                        str(revision_row["updated_at"] if revision_row else "")
                        or datetime.now(timezone.utc).isoformat(),
                    ),
                )

                verification: dict[str, Any] = {}
                for table in TABLES:
                    source_columns = tuple(source_data[table][0].keys()) if source_data[table] else ()
                    target_rows = (
                        target.execute(
                            sql.SQL("SELECT {} FROM {}").format(
                                sql.SQL(", ").join(map(sql.Identifier, source_columns)),
                                sql.Identifier(table),
                            )
                        ).fetchall()
                        if source_columns
                        else []
                    )
                    source_digest = digest_rows(table, source_data[table])
                    target_digest = digest_rows(table, list(target_rows))
                    if len(source_data[table]) != len(target_rows):
                        raise RuntimeError(f"row count mismatch for {table}")
                    if source_digest != target_digest:
                        raise RuntimeError(f"content digest mismatch for {table}")
                    verification[table] = {
                        "rows": len(target_rows),
                        "sha256": target_digest,
                    }
        source.execute("ROLLBACK")
    finally:
        source.close()
    return {
        "ok": True,
        "source": str(source_path.expanduser().absolute()),
        "backup": str(backup_path.expanduser().absolute()),
        "tables": verification,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--target-url-file", type=Path, required=True)
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "migrations" / "postgres",
    )
    args = parser.parse_args()
    try:
        result = migrate(
            args.source,
            args.backup,
            read_secret_file(args.target_url_file),
            args.migrations_dir,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
