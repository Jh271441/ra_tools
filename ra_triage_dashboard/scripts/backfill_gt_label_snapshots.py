#!/usr/bin/env python3
"""Create cutover GT snapshots from the current local overlay.

Dry-run is the default. ``--apply`` is required to create/activate snapshots.
This tool is intentionally explicit about the cutover source: it records the
current overlay as an observed migration-time reference and never reconstructs
older GT history.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

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


def scope_rows(database: Database, scope: str) -> list[dict[str, str]]:
    with database.connect() as conn:
        rows = conn.execute(
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


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    database_url = args.database_url or settings.database_url
    database = Database(
        database_url,
        postgres_migrations_dir=settings.postgres_migrations_dir,
        pool_size=2,
    )
    database.init()
    try:
        scopes = list(dict.fromkeys(str(item).strip() for item in args.scopes if str(item).strip()))
        if not scopes:
            with database.connect() as conn:
                scopes = [
                    str(row["baseline_scope"] or "")
                    for row in conn.execute(
                        "SELECT DISTINCT baseline_scope FROM issues WHERE baseline_scope <> '' ORDER BY baseline_scope"
                    ).fetchall()
                ]
        reports: list[dict[str, Any]] = []
        for scope in scopes:
            rows = scope_rows(database, scope)
            entry = baseline_registry.by_scope(scope)
            gt_mode = entry.gt_mode if entry is not None else "strict"
            status = database.gt_sync_status(scope)
            valid = sum(str(row["gt_label"] or "") in LABELS for row in rows)
            empty = len(rows) - valid
            actual_membership_sha = _snapshot_membership_sha(
                [str(row["issue_id"] or "") for row in rows]
            )
            expected_count = entry.expected_count if entry is not None else None
            configured_membership_sha = entry.members_sha256 if entry is not None else ""
            report: dict[str, Any] = {
                "baseline_scope": scope,
                "gt_mode": gt_mode,
                "member_count": len(rows),
                "valid_label_count": valid,
                "empty_label_count": empty,
                "expected_count": expected_count,
                "membership_sha256": actual_membership_sha,
                "configured_membership_sha256": configured_membership_sha,
                "count_matches": expected_count in (None, len(rows)),
                "sha_matches": not configured_membership_sha or configured_membership_sha == actual_membership_sha,
                "gt_sync_status": status.get("status", "not_started"),
                "source_name": status.get("source_name", "Trail"),
                "source_view_id": int(status.get("source_view_id") or 1000),
                "source_field": status.get("source_field", "ra_merge_result"),
                "active_snapshot_id": (database.get_active_gt_snapshot(scope) or {}).get("id", ""),
                "action": "apply" if args.apply else "dry_run",
            }
            if not report["count_matches"]:
                report["error"] = f"membership count mismatch: expected {expected_count}, got {len(rows)}"
            elif not report["sha_matches"]:
                report["error"] = "membership SHA does not match the configured frozen registry"
            if report.get("error"):
                reports.append(report)
                continue
            if gt_mode == "strict" and empty:
                report["error"] = "strict scope contains empty/noncanonical current GT"
                reports.append(report)
                continue
            if args.apply:
                snapshot = database.create_gt_snapshot_from_current(
                    scope=scope,
                    gt_mode=gt_mode,
                    source_name=str(status.get("source_name") or "Trail"),
                    source_view_id=int(status.get("source_view_id") or 1000),
                    source_field=str(status.get("source_field") or "ra_merge_result"),
                    created_by=args.created_by,
                    created_by_source=args.created_by_source,
                    created_by_verified=False,
                    activation_reason="cutover_current",
                )
                report["snapshot"] = snapshot
            reports.append(report)
        print(json.dumps({"apply": bool(args.apply), "scopes": reports}, ensure_ascii=False, indent=2))
        return 0 if not any(item.get("error") for item in reports) else 2
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
