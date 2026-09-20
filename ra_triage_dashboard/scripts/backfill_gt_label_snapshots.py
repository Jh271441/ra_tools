#!/usr/bin/env python3
"""Create cutover GT snapshots from the current local overlay.

Dry-run is genuinely read-only: it never calls Database.init() or applies
PostgreSQL/SQLite schema. ``--apply`` requires the 043-compatible schema and
is the only mode that creates or activates snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.baseline import load_baseline_entry
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


def inspect_scope(
    connection: Any,
    entry: Any,
    state: dict[str, Any],
    *,
    action: str,
) -> dict[str, Any]:
    """Check source bytes and authoritative Issue membership independently."""

    scope = str(entry.scope)
    configured_source_sha = str(entry.members_sha256 or "").strip().lower()
    actual_source_sha = ""
    source_file_error = ""
    try:
        source_bytes = entry.xlsx.read_bytes()
        actual_source_sha = hashlib.sha256(source_bytes).hexdigest()
    except OSError as exc:
        source_file_error = type(exc).__name__
    source_file_sha_matches = bool(actual_source_sha) and (
        not configured_source_sha or actual_source_sha == configured_source_sha
    )

    loaded = None
    loader_error = ""
    try:
        loaded = load_baseline_entry(
            loader=str(entry.loader),
            path=Path(entry.xlsx),
            dataset=str(entry.dataset or ""),
        )
    except Exception as exc:
        loader_error = type(exc).__name__

    loader_rows = list(loaded.rows) if loaded is not None else []
    loader_ids = [str(row.get("issue_id") or "").strip() for row in loader_rows]
    loader_empty_issue_ids = sum(not issue_id for issue_id in loader_ids)
    nonempty_loader_ids = [issue_id for issue_id in loader_ids if issue_id]
    loader_duplicate_count = len(nonempty_loader_ids) - len(set(nonempty_loader_ids))
    expected_issue_ids = sorted(set(nonempty_loader_ids))
    expected_membership_sha = _snapshot_membership_sha(expected_issue_ids)
    loader_source_rows = int(loaded.source_rows) if loaded is not None else 0
    loader_skipped_rows = int(loaded.skipped_rows) if loaded is not None else 0
    loader_member_count = len(loader_rows)
    expected_count = entry.expected_count
    loader_count_matches = (
        expected_count is None
        or (
            loader_source_rows == int(expected_count)
            and loader_member_count == int(expected_count)
        )
    )
    loader_complete = bool(
        loaded is not None
        and loader_source_rows == loader_member_count
        and loader_skipped_rows == 0
        and loader_empty_issue_ids == 0
        and loader_duplicate_count == 0
    )

    database_rows = read_scope_rows(connection, scope)
    database_ids = [str(row["issue_id"] or "").strip() for row in database_rows]
    database_empty_issue_ids = sum(not issue_id for issue_id in database_ids)
    nonempty_database_ids = [issue_id for issue_id in database_ids if issue_id]
    database_duplicate_count = len(nonempty_database_ids) - len(set(nonempty_database_ids))
    actual_membership_sha = _snapshot_membership_sha(
        sorted(set(nonempty_database_ids))
    )
    expected_id_set = set(expected_issue_ids)
    database_id_set = set(nonempty_database_ids)
    missing_ids = sorted(expected_id_set - database_id_set)
    extra_ids = sorted(database_id_set - expected_id_set)
    database_count_matches = len(database_rows) == len(expected_issue_ids)
    membership_matches = bool(
        loader_complete
        and not database_empty_issue_ids
        and not database_duplicate_count
        and not missing_ids
        and not extra_ids
        and actual_membership_sha == expected_membership_sha
    )

    valid_label_count = sum(row["gt_label"] in LABELS for row in database_rows)
    empty_label_count = sum(not row["gt_label"] for row in database_rows)
    noncanonical_label_count = sum(
        bool(row["gt_label"]) and row["gt_label"] not in LABELS
        for row in database_rows
    )
    sync_status = str(state.get("status") or "not_started")
    source_sha = str(state.get("source_sha256") or "")
    errors = []
    if source_file_error:
        errors.append(f"source baseline file unavailable ({source_file_error})")
    if not source_file_sha_matches:
        errors.append("source baseline file SHA does not match registry")
    if loader_error:
        errors.append(f"baseline loader failed ({loader_error})")
    if loaded is None:
        errors.append("baseline loader returned no result")
    elif not loader_count_matches or not loader_complete:
        errors.append("baseline loader membership/count is incomplete or invalid")
    if not database_count_matches or not membership_matches:
        errors.append("database Issue membership does not match baseline loader membership")
    if not database_rows:
        errors.append("baseline scope has no database members")
    if sync_status != "ready" or not source_sha:
        errors.append("GT sync is not ready with a source hash")
    if noncanonical_label_count:
        errors.append("current GT contains noncanonical labels")
    if entry.gt_mode == "strict" and valid_label_count != len(database_rows):
        errors.append("strict scope contains empty/noncanonical current GT")

    return {
        "baseline_scope": scope,
        "gt_mode": str(entry.gt_mode),
        "configured_source_file_sha256": configured_source_sha,
        "actual_source_file_sha256": actual_source_sha,
        "source_file_sha_configured": bool(configured_source_sha),
        "source_file_sha_matches": source_file_sha_matches,
        "loader_source_row_count": loader_source_rows,
        "loader_member_count": loader_member_count,
        "loader_skipped_row_count": loader_skipped_rows,
        "loader_empty_issue_id_count": loader_empty_issue_ids,
        "loader_duplicate_issue_id_count": loader_duplicate_count,
        "loader_count_matches": loader_count_matches,
        "expected_count": expected_count,
        "expected_membership_sha256": expected_membership_sha,
        "actual_membership_sha256": actual_membership_sha,
        "membership_matches": membership_matches,
        "database_member_count": len(database_rows),
        "database_empty_issue_id_count": database_empty_issue_ids,
        "database_duplicate_issue_id_count": database_duplicate_count,
        "database_count_matches": database_count_matches,
        "missing_issue_count": len(missing_ids),
        "extra_issue_count": len(extra_ids),
        "missing_issue_ids_sample": missing_ids[:5],
        "extra_issue_ids_sample": extra_ids[:5],
        "valid_label_count": valid_label_count,
        "empty_label_count": empty_label_count,
        "noncanonical_label_count": noncanonical_label_count,
        "gt_sync_status": sync_status,
        "source_sha256": source_sha,
        "schema_mode": "read_only" if action == "dry_run" else "existing_043_schema",
        "action": action,
        "errors": errors,
        **({"error": errors[0]} if errors else {}),
        "_expected_issue_ids": expected_issue_ids,
    }


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

        action = "apply" if args.apply else "dry_run"
        plans: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
        with read_connection(database) as connection:
            require_snapshot_schema(connection)
            for scope in scopes:
                entry = registry[scope]
                state = read_state(connection, scope)
                report = inspect_scope(connection, entry, state, action=action)
                plans.append((entry, state, report))

        def public_report(report: dict[str, Any]) -> dict[str, Any]:
            return {key: value for key, value in report.items() if not key.startswith("_")}

        reports = [public_report(report) for _entry, _state, report in plans]
        errors = [report for report in reports if report.get("errors")]
        if errors:
            print(json.dumps({"apply": bool(args.apply), "scopes": reports}, ensure_ascii=False, indent=2))
            return 2

        if not args.apply:
            print(json.dumps({"apply": False, "scopes": reports}, ensure_ascii=False, indent=2))
            return 0

        # Recheck source bytes for every scope before the first snapshot write.
        for entry, _state, report in plans:
            try:
                current_source_sha = hashlib.sha256(entry.xlsx.read_bytes()).hexdigest()
            except OSError:
                current_source_sha = ""
            if current_source_sha != report["actual_source_file_sha256"]:
                report["errors"].append("source baseline file changed after preflight")
        if any(report["errors"] for _entry, _state, report in plans):
            print(json.dumps(
                {"apply": True, "scopes": [public_report(report) for _entry, _state, report in plans]},
                ensure_ascii=False,
                indent=2,
            ))
            return 2

        applied_reports = []
        for entry, _state, report in plans:
            snapshot = database.create_gt_snapshot_from_current(
                scope=entry.scope,
                gt_mode=entry.gt_mode,
                created_by=args.created_by,
                created_by_source=args.created_by_source,
                created_by_verified=False,
                activation_reason="cutover_current",
                expected_member_count=report["loader_member_count"],
                expected_membership_sha256=report["expected_membership_sha256"],
            )
            observation = snapshot.get("observation") or {}
            applied_reports.append({
                "baseline_scope": entry.scope,
                "action": "apply",
                "gt_mode": str(snapshot.get("gt_mode") or entry.gt_mode),
                "snapshot_id": str(snapshot.get("id") or ""),
                "content_sha256": str(snapshot.get("content_sha256") or ""),
                "membership_sha256": str(snapshot.get("membership_sha256") or ""),
                "member_count": int(snapshot.get("member_count") or 0),
                "valid_label_count": int(snapshot.get("valid_label_count") or 0),
                "empty_label_count": int(snapshot.get("member_count") or 0)
                    - int(snapshot.get("valid_label_count") or 0),
                "active": bool(snapshot.get("active")),
                "observation_last_checked_at": str(observation.get("last_checked_at") or ""),
                "observation_source_sha256": str(observation.get("source_sha256") or ""),
            })
        print(json.dumps({"apply": True, "scopes": applied_reports}, ensure_ascii=False, indent=2))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
