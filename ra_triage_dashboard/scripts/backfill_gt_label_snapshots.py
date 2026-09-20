#!/usr/bin/env python3
"""Create cutover GT snapshots from the current local overlay.

Dry-run is genuinely read-only: it never calls Database.init() or applies
PostgreSQL/SQLite schema. ``--apply`` requires the 043-compatible schema and
is the only mode that creates or activates snapshots.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database, LABELS
from app.db_parts.snapshots import _snapshot_membership_sha
from app.runtime import baseline_registry
from app.settings import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DASHBOARD_DATABASE_URL", ""))
    parser.add_argument("--scope", action="append", dest="scopes", default=[])
    parser.add_argument("--apply", action="store_true", help="write/activate snapshots")
    parser.add_argument("--created-by", default="snapshot-backfill")
    parser.add_argument("--created-by-source", default="migration")
    return parser.parse_args()


def configured_scopes() -> dict[str, Any]:
    return {entry.scope: entry for entry in baseline_registry.entries}


@contextmanager
def read_connection(database: Database) -> Iterator[Any]:
    """Open a no-write reader for dry-run, including SQLite mode=ro."""

    if database.backend == "sqlite":
        path = database.path
        if path is None or not path.exists():
            raise RuntimeError("dry-run requires an existing SQLite database; it will not create one")
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()
        return
    with database.connect() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        yield connection


def read_scope_rows(connection: Any, scope: str) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT issue_id, gt_label, gt_source
        FROM issues WHERE baseline_scope = ? ORDER BY issue_id
        """,
        (scope,),
    ).fetchall()
    return [
        {
            "issue_id": str(row["issue_id"] or ""),
            "gt_label": str(row["gt_label"] or ""),
            "gt_source": str(row["gt_source"] or ""),
        }
        for row in rows
    ]


def read_state(connection: Any, scope: str) -> dict[str, Any]:
    try:
        row = connection.execute(
            "SELECT * FROM gt_sync_state WHERE baseline_scope = ?", (scope,)
        ).fetchone()
    except Exception as exc:
        if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
            raise RuntimeError(
                "snapshot schema is not installed; deploy migration 043 before backfill"
            ) from exc
        raise
    if row is None:
        return {"status": "not_started", "source_sha256": "", "source_name": "Trail", "source_view_id": 1000, "source_field": "ra_merge_result"}
    return {key: row[key] for key in row.keys()}


def require_snapshot_schema(connection: Any) -> None:
    for table in ("gt_snapshots", "gt_snapshot_items", "gt_snapshot_active", "gt_sync_state"):
        try:
            connection.execute(f"SELECT 1 FROM {table} LIMIT 0").fetchone()
        except Exception as exc:
            if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
                raise RuntimeError(
                    "snapshot schema is not installed; deploy migration 043 before backfill"
                ) from exc
            raise


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    database_url = args.database_url or settings.database_url
    database = Database(
        database_url,
        postgres_migrations_dir=settings.postgres_migrations_dir,
        pool_size=2,
    )
    registry = configured_scopes()
    try:
        requested = list(dict.fromkeys(str(item).strip() for item in args.scopes if str(item).strip()))
        scopes = requested or list(registry)
        unknown = [scope for scope in scopes if scope not in registry]
        if unknown:
            print(json.dumps({"error": "unknown baseline scope", "scopes": unknown}, ensure_ascii=False, indent=2))
            return 2
        if not scopes:
            print(json.dumps({"error": "configured baseline registry is empty"}, ensure_ascii=False, indent=2))
            return 2

        if not args.apply:
            # No init: only read existing schema and data.
            with read_connection(database) as connection:
                require_snapshot_schema(connection)
                reports: list[dict[str, Any]] = []
                for scope in scopes:
                    rows = read_scope_rows(connection, scope)
                    state = read_state(connection, scope)
                    entry = registry[scope]
                    actual_sha = _snapshot_membership_sha([row["issue_id"] for row in rows])
                    valid = sum(row["gt_label"] in LABELS for row in rows)
                    noncanonical = sum(
                        bool(row["gt_label"]) and row["gt_label"] not in LABELS
                        for row in rows
                    )
                    expected_count = entry.expected_count
                    configured_sha = entry.members_sha256
                    report = {
                        "baseline_scope": scope,
                        "gt_mode": entry.gt_mode,
                        "member_count": len(rows),
                        "valid_label_count": valid,
                        "empty_label_count": len(rows) - valid,
                        "noncanonical_label_count": noncanonical,
                        "expected_count": expected_count,
                        "membership_sha256": actual_sha,
                        "configured_membership_sha256": configured_sha,
                        "count_matches": expected_count in (None, len(rows)),
                        "sha_matches": not configured_sha or configured_sha == actual_sha,
                        "gt_sync_status": str(state.get("status") or "not_started"),
                        "source_sha256": str(state.get("source_sha256") or ""),
                        "schema_mode": "read_only",
                        "action": "dry_run",
                    }
                    if not report["count_matches"] or not report["sha_matches"]:
                        report["error"] = "baseline membership count/hash does not match registry"
                    elif str(state.get("status") or "") != "ready" or not str(state.get("source_sha256") or ""):
                        report["error"] = "GT sync is not ready with a source hash; run a complete sync first"
                    elif not rows:
                        report["error"] = "baseline scope has no members"
                    elif noncanonical:
                        report["error"] = "current GT contains noncanonical labels"
                    elif entry.gt_mode == "strict" and valid != len(rows):
                        report["error"] = "strict scope contains empty/noncanonical current GT"
                    reports.append(report)
            print(json.dumps({"apply": False, "scopes": reports}, ensure_ascii=False, indent=2))
            return 0 if not any(report.get("error") for report in reports) else 2

        # Apply mode may write snapshots only into an already upgraded schema.
        # It must never apply DDL or otherwise initialize a database.
        with read_connection(database) as connection:
            require_snapshot_schema(connection)
        plans: list[tuple[Any, dict[str, Any], list[dict[str, str]]]] = []
        for scope in scopes:
            entry = registry[scope]
            state = database.gt_sync_status(scope)
            with database.connect() as connection:
                rows = read_scope_rows(connection, scope)
            actual_sha = _snapshot_membership_sha([row["issue_id"] for row in rows])
            if str(state.get("status") or "") != "ready" or not str(state.get("source_sha256") or ""):
                raise RuntimeError(f"{scope}: GT sync is not ready with a source hash")
            if not rows:
                raise RuntimeError(f"{scope}: baseline scope has no members")
            if entry.expected_count not in (None, len(rows)):
                raise RuntimeError(f"{scope}: membership count mismatch")
            if entry.members_sha256 and entry.members_sha256 != actual_sha:
                raise RuntimeError(f"{scope}: membership SHA mismatch")
            noncanonical = [
                row["issue_id"]
                for row in rows
                if row["gt_label"] and row["gt_label"] not in LABELS
            ]
            if noncanonical:
                raise RuntimeError(f"{scope}: current GT contains noncanonical labels")
            if entry.gt_mode == "strict" and any(row["gt_label"] not in LABELS for row in rows):
                raise RuntimeError(
                    f"{scope}: strict scope contains empty/noncanonical current GT"
                )
            plans.append((entry, state, rows))

        reports = []
        for entry, state, _rows in plans:
            scope = entry.scope
            snapshot = database.create_gt_snapshot_from_current(
                scope=scope,
                gt_mode=entry.gt_mode,
                source_name=str(state.get("source_name") or "Trail"),
                source_view_id=int(state.get("source_view_id") or 1000),
                source_field=str(state.get("source_field") or "ra_merge_result"),
                created_by=args.created_by,
                created_by_source=args.created_by_source,
                created_by_verified=False,
                activation_reason="cutover_current",
            )
            reports.append({"baseline_scope": scope, "action": "apply", "snapshot": snapshot})
        print(json.dumps({"apply": True, "scopes": reports}, ensure_ascii=False, indent=2))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
