#!/usr/bin/env python3
"""Conservatively map determinate legacy Run reviews into the S3 domain.

Dry-run is the default. Only legacy rows with a non-empty Run, diagnostic
content, and no label/tag/exclusion payload are eligible. Mixed label/diagnosis
rows remain available through the legacy fallback and are never auto-split.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database
from app.settings import Settings


DEFAULT_SCOPES = (
    "release0508_1071_20260729",
    "release0206_1326_20260729",
)
SAFE_DATABASE_RE = re.compile(r"^manual_s3_smoke(?:_[a-z0-9][a-z0-9_-]*)?$", re.IGNORECASE)
SAFE_HOSTS = {"", "127.0.0.1", "::1", "localhost"}


def require_safe_target(database_name: str, host: str) -> None:
    if not SAFE_DATABASE_RE.fullmatch(str(database_name or "")):
        raise RuntimeError(f"refusing unsafe database name: {database_name}")
    if str(host or "") not in SAFE_HOSTS:
        raise RuntimeError(f"refusing non-local database host: {host}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", action="append", dest="scopes", default=[])
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    database = Database(
        settings.database_url,
        postgres_migrations_dir=settings.postgres_migrations_dir,
        pool_size=2,
    )
    scopes = tuple(dict.fromkeys(args.scopes or DEFAULT_SCOPES))
    report = {"apply": bool(args.apply), "scopes": list(scopes), "eligible": [], "skipped": {}}
    try:
        with database.connect() as connection:
            identity = connection.execute(
                "SELECT current_database() AS name, COALESCE(inet_server_addr()::text, '') AS host"
            ).fetchone()
        database_name = str(identity["name"] or "")
        host = str(identity["host"] or "")
        if args.apply:
            require_safe_target(database_name, host)
            database.init()
        with database.connect() as connection:
            clause, scope_params = database._scope_in_sql(scopes, "issue.baseline_scope")
            rows = connection.execute(
                f"""
                SELECT annotation.*, issue.baseline_scope
                FROM annotations annotation
                JOIN issues issue ON issue.issue_id = annotation.issue_id
                WHERE {clause} AND TRIM(annotation.model_run_id) != ''
                ORDER BY annotation.id
                """,
                scope_params,
            ).fetchall()
            migrated_rows = connection.execute(
                "SELECT legacy_annotation_id FROM model_review_revisions "
                "WHERE legacy_annotation_id IS NOT NULL"
            ).fetchall()
            migrated = {int(row["legacy_annotation_id"]) for row in migrated_rows}
        scope_issue_ids: dict[str, list[str]] = {}
        for row in rows:
            scope_issue_ids.setdefault(str(row["baseline_scope"] or ""), []).append(
                str(row["issue_id"] or "")
            )
        label_states_by_issue: dict[str, dict[str, Any]] = {}
        for scope, issue_ids in scope_issue_ids.items():
            label_states_by_issue.update(
                database.project_issue_label_states(
                    scope, issue_ids, include_sources=False
                )
            )
        for row in rows:
            annotation_id = int(row["id"])
            if annotation_id in migrated:
                report["skipped"][str(annotation_id)] = "already_migrated"
                continue
            reason = str(row["note"] or "").strip()
            evidence = json.loads(row["missing_evidence_json"] or "[]")
            tags = json.loads(row["tags_json"] or "[]")
            mixed = bool(str(row["label"] or "").strip() or tags or row["is_excluded"])
            if mixed:
                report["skipped"][str(annotation_id)] = "mixed_label_and_model_review"
                continue
            if not reason and not evidence:
                report["skipped"][str(annotation_id)] = "no_model_diagnostic_content"
                continue
            if not str(row["author"] or "").strip():
                report["skipped"][str(annotation_id)] = "missing_reviewer_identity"
                continue
            # Legacy review_status is derived from expected-output/GT
            # comparison. It cannot determine model-review progress. A
            # persisted diagnostic-only row maps to completed; only the current
            # shared Label projection can force blocked_by_label.
            label_state = label_states_by_issue.get(str(row["issue_id"]), {})
            status = (
                "blocked_by_label"
                if str(label_state.get("state") or "") in {"conflict", "stale"}
                else "completed"
            )
            item = {
                "legacy_annotation_id": annotation_id,
                "issue_id": str(row["issue_id"]),
                "model_run_id": str(row["model_run_id"]),
                "status": status,
                "reviewer": str(row["author"] or ""),
                "label_state": str(label_state.get("state") or "none"),
            }
            report["eligible"].append(item)
            if args.apply:
                database.create_model_review(
                    issue_id=item["issue_id"],
                    model_run_id=item["model_run_id"],
                    work_split_id=str(row["work_split_id"] or ""),
                    status=status,
                    reason=reason,
                    missing_evidence=evidence,
                    reviewer=item["reviewer"],
                    reviewer_source=str(row["author_source"] or "legacy"),
                    reviewer_verified=bool(row["author_verified"]),
                    label_state=label_state,
                    legacy_annotation_id=annotation_id,
                )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
