#!/usr/bin/env python3
"""Read-only S4 inventory and purpose-mapping dry-run for legacy work splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from app.db import Database  # noqa: E402

SAFE_DATABASE_RE = re.compile(r"^manual_s4_smoke(?:_[a-z0-9][a-z0-9_-]*)?$", re.IGNORECASE)
SAFE_HOSTS = {"", "127.0.0.1", "::1", "localhost"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_url_file(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("S4 inventory URL file must be an owned regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("S4 inventory URL file must be 0600")
        content = os.read(descriptor, 16 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(content) > 16 * 1024:
        raise RuntimeError("S4 inventory URL file is too large")
    value = content.decode("utf-8").strip()
    if not value:
        raise RuntimeError("S4 inventory URL file is empty")
    return value


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _snapshot_requirement_distribution(value: Any) -> dict[str, int]:
    per_issue: dict[str, set[str]] = defaultdict(set)
    for member in _json_list(value):
        if not isinstance(member, dict):
            continue
        reviewer = str(member.get("name") or "").strip().lower()
        if not reviewer:
            continue
        items = member.get("items")
        if isinstance(items, list):
            issue_ids = [
                str(item.get("issue_id") or "").strip()
                for item in items
                if isinstance(item, dict)
            ]
        else:
            issue_ids = [str(item or "").strip() for item in member.get("issue_ids") or []]
        for issue_id in set(issue_ids):
            if issue_id:
                per_issue[issue_id].add(reviewer)
    return dict(sorted(Counter(len(reviewers) for reviewers in per_issue.values()).items()))


def _required_submitter_distribution(rows: list[Any], *, split_id: str) -> dict[str, int]:
    counts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if str(row["split_id"]) == split_id:
            counts[str(row["issue_id"])].add(str(row["assignee"] or "").strip().lower())
    return dict(sorted(Counter(len({name for name in names if name}) for names in counts.values()).items()))


def _classify_purpose(split: dict[str, Any]) -> tuple[str | None, str, list[str]]:
    task_kind = str(split.get("task_kind") or "legacy").strip().lower()
    has_label_evidence = bool(
        str(split.get("workset_id") or "").strip()
        or int(split.get("label_case_count") or 0)
        or int(split.get("label_comment_link_count") or 0)
    )
    has_model_evidence = bool(
        task_kind == "model_review"
        or int(split.get("model_review_revision_count") or 0)
    )
    evidence: list[str] = []
    if task_kind == "labeling":
        evidence.append("legacy_task_kind_labeling")
        has_label_evidence = True
    elif task_kind == "model_review":
        evidence.append("legacy_task_kind_model_review")
    if str(split.get("workset_id") or "").strip():
        evidence.append("linked_review_workset")
    if int(split.get("label_case_count") or 0):
        evidence.append("linked_label_cases")
    if int(split.get("label_comment_link_count") or 0):
        evidence.append("linked_label_discussions")
    if int(split.get("model_review_revision_count") or 0):
        evidence.append("run_bound_model_review_revisions")
    if has_label_evidence and has_model_evidence:
        return None, "conflicting_evidence_read_only", evidence
    if has_label_evidence:
        return "labeling", "mapped_from_explicit_label_evidence", evidence
    if has_model_evidence:
        return "model_review", "mapped_from_explicit_model_review_evidence", evidence
    return None, "ambiguous_legacy_read_only", evidence


def collect_inventory(database: Database) -> dict[str, Any]:
    with database.connect() as connection:
        if database.backend == "postgresql":
            connection.execute("SET TRANSACTION READ ONLY")
        else:
            connection.execute("PRAGMA query_only = ON")
        identity = connection.execute(
            "SELECT current_database() AS name, COALESCE(inet_server_addr()::text, '') AS host"
        ).fetchone()
        db_name = str(identity["name"] or "")
        host = str(identity["host"] or "")
        if not SAFE_DATABASE_RE.fullmatch(db_name) or host not in SAFE_HOSTS:
            raise RuntimeError("S4 inventory refuses a non-smoke or non-local database")
        migration_count = int(
            connection.execute(
                "SELECT COUNT(*) AS n FROM dashboard_schema_migrations"
            ).fetchone()["n"]
        )
        task_kind_rows = connection.execute(
            "SELECT task_kind, COUNT(*) AS count FROM issue_work_splits GROUP BY task_kind ORDER BY task_kind"
        ).fetchall()
        split_rows = connection.execute(
            """
            SELECT split.id, split.task_kind, split.model_run_id,
                   split.workset_id, split.selection_source_run_id,
                   split.mode, split.reviewers_per_issue, split.overlap_ratio,
                   split.total_count, split.assignment_count, split.assignees_json,
                   split.created_at,
                   workset.baseline_scope AS workset_baseline_scope,
                   workset.member_count AS workset_member_count,
                   workset.members_sha256 AS workset_members_sha256,
                   workset.selection_source_run_id AS workset_selection_source_run_id,
                   COALESCE(assignments.assignment_rows, 0) AS current_assignment_rows,
                   COALESCE(assignments.issue_count, 0) AS current_assignment_issues,
                   COALESCE(assignments.assignee_count, 0) AS current_assignee_count,
                   COALESCE(changes.change_count, 0) AS assignment_change_count,
                   COALESCE(model_reviews.revision_count, 0) AS model_review_revision_count,
                   COALESCE(legacy_reviews.revision_count, 0) AS legacy_review_revision_count,
                   COALESCE(label_cases.case_count, 0) AS label_case_count,
                   COALESCE(label_revisions.revision_count, 0) AS label_revision_count,
                   COALESCE(label_comments.comment_count, 0) AS label_comment_link_count
            FROM issue_work_splits split
            LEFT JOIN review_worksets workset ON workset.id = split.workset_id
            LEFT JOIN (
                SELECT split_id, COUNT(*) AS assignment_rows,
                       COUNT(DISTINCT issue_id) AS issue_count,
                       COUNT(DISTINCT assignee) AS assignee_count
                FROM review_work_assignments GROUP BY split_id
            ) assignments ON assignments.split_id = split.id
            LEFT JOIN (
                SELECT split_id, COUNT(*) AS change_count
                FROM review_work_assignment_changes GROUP BY split_id
            ) changes ON changes.split_id = split.id
            LEFT JOIN (
                SELECT work_split_id, COUNT(*) AS revision_count
                FROM model_review_revisions
                WHERE work_split_id <> '' GROUP BY work_split_id
            ) model_reviews ON model_reviews.work_split_id = split.id
            LEFT JOIN (
                SELECT work_split_id, COUNT(*) AS revision_count
                FROM annotations
                WHERE work_split_id <> '' GROUP BY work_split_id
            ) legacy_reviews ON legacy_reviews.work_split_id = split.id
            LEFT JOIN (
                SELECT task_id, COUNT(*) AS case_count
                FROM label_cases WHERE task_id <> '' GROUP BY task_id
            ) label_cases ON label_cases.task_id = split.id
            LEFT JOIN (
                SELECT label_case.task_id, COUNT(*) AS revision_count
                FROM label_revisions revision
                JOIN label_cases label_case ON label_case.id = revision.label_case_id
                WHERE label_case.task_id <> '' GROUP BY label_case.task_id
            ) label_revisions ON label_revisions.task_id = split.id
            LEFT JOIN (
                SELECT task_id, COUNT(*) AS comment_count
                FROM label_comment_links WHERE task_id <> '' GROUP BY task_id
            ) label_comments ON label_comments.task_id = split.id
            ORDER BY split.created_at, split.id
            """
        ).fetchall()
        current_requirement_rows = connection.execute(
            """
            SELECT split_id, issue_id, COUNT(DISTINCT assignee) AS required_count
            FROM review_work_assignments
            GROUP BY split_id, issue_id
            ORDER BY split_id, issue_id
            """
        ).fetchall()
        channel_counts = {
            "unbound_review_comments": int(connection.execute(
                "SELECT COUNT(*) AS n FROM review_comments WHERE model_run_id = ''"
            ).fetchone()["n"]),
            "run_bound_review_comments": int(connection.execute(
                "SELECT COUNT(*) AS n FROM review_comments WHERE model_run_id <> ''"
            ).fetchone()["n"]),
            "label_comment_links": int(connection.execute(
                "SELECT COUNT(*) AS n FROM label_comment_links"
            ).fetchone()["n"]),
        }
        gt_snapshot_rows = connection.execute(
            """
            SELECT active.baseline_scope, active.snapshot_id, snapshot.gt_mode,
                   snapshot.member_count, snapshot.content_sha256
            FROM gt_snapshot_active active
            JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
            ORDER BY active.baseline_scope
            """
        ).fetchall()

    requirement_rows_by_split: dict[str, list[Any]] = defaultdict(list)
    for row in current_requirement_rows:
        requirement_rows_by_split[str(row["split_id"])].append(row)
    splits: list[dict[str, Any]] = []
    purpose_counts: Counter[str] = Counter()
    read_only_splits = 0
    for row in split_rows:
        split = {name: row[name] for name in row.keys()}
        split_id = str(split["id"])
        current_distribution = dict(sorted(Counter(
            int(item["required_count"] or 0)
            for item in requirement_rows_by_split.get(split_id, [])
        ).items()))
        snapshot_distribution = _snapshot_requirement_distribution(split["assignees_json"])
        purpose, mapping_status, evidence = _classify_purpose(split)
        if purpose is None:
            read_only_splits += 1
        else:
            purpose_counts[purpose] += 1
        selection_source = str(
            split.get("workset_selection_source_run_id")
            or split.get("selection_source_run_id")
            or ""
        )
        splits.append(
            {
                "legacy_split_id": split_id,
                "legacy_task_kind": str(split.get("task_kind") or "legacy"),
                "proposed_purpose": purpose,
                "mapping_status": mapping_status,
                "mapping_evidence": evidence,
                "read_only": purpose is None,
                "workset_linked": bool(str(split.get("workset_id") or "").strip()),
                "workset_baseline_scope": str(split.get("workset_baseline_scope") or ""),
                "workset_member_count": int(split.get("workset_member_count") or 0),
                "workset_members_sha256": str(split.get("workset_members_sha256") or ""),
                "selection_source_run_id_present": bool(selection_source),
                "legacy_model_run_id_present": bool(str(split.get("model_run_id") or "").strip()),
                "evaluation_run_id_candidate_present": (
                    purpose == "model_review"
                    and bool(str(split.get("model_run_id") or "").strip())
                ),
                "mode": str(split.get("mode") or "single"),
                "configured_reviewers_per_issue": int(split.get("reviewers_per_issue") or 1),
                "overlap_ratio": float(split.get("overlap_ratio") or 0),
                "snapshot_total_count": int(split.get("total_count") or 0),
                "snapshot_assignment_count": int(split.get("assignment_count") or 0),
                "current_assignment_rows": int(split.get("current_assignment_rows") or 0),
                "current_assignment_issues": int(split.get("current_assignment_issues") or 0),
                "current_assignee_count": int(split.get("current_assignee_count") or 0),
                "current_required_submitter_count_distribution": current_distribution,
                "snapshot_required_submitter_count_distribution": snapshot_distribution,
                "assignment_change_count": int(split.get("assignment_change_count") or 0),
                "model_review_revision_count": int(split.get("model_review_revision_count") or 0),
                "legacy_review_revision_count": int(split.get("legacy_review_revision_count") or 0),
                "label_case_count": int(split.get("label_case_count") or 0),
                "label_revision_count": int(split.get("label_revision_count") or 0),
                "label_comment_link_count": int(split.get("label_comment_link_count") or 0),
                "created_at": str(split.get("created_at") or ""),
            }
        )

    return {
        "schema": "manual-s4-campaign-inventory-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": db_name,
        "host": host or "local_socket",
        "migration_count": migration_count,
        "mode": "read_only_dry_run",
        "task_kind_counts": {
            str(row["task_kind"] or "legacy"): int(row["count"] or 0)
            for row in task_kind_rows
        },
        "proposed_purpose_counts": dict(sorted(purpose_counts.items())),
        "read_only_ambiguous_or_conflicting_split_count": read_only_splits,
        "split_count": len(splits),
        "discussion_channel_baseline_counts": channel_counts,
        "active_gt_reference_counts": [
            {
                "baseline_scope": str(row["baseline_scope"]),
                "gt_mode": str(row["gt_mode"]),
                "member_count": int(row["member_count"] or 0),
                "content_sha256": str(row["content_sha256"] or ""),
            }
            for row in gt_snapshot_rows
        ],
        "splits": splits,
    }


def main() -> int:
    args = parse_args()
    database = Database(
        read_url_file(Path(args.database_url_file)),
        postgres_migrations_dir=APP_ROOT / "migrations" / "postgres",
        pool_size=4,
    )
    try:
        report = collect_inventory(database)
    finally:
        database.close()
    output = Path(args.output).expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    os.chmod(output, 0o600)
    print(json.dumps({
        "status": "passed",
        "mode": report["mode"],
        "database": report["database"],
        "split_count": report["split_count"],
        "purpose_counts": report["proposed_purpose_counts"],
        "read_only_count": report["read_only_ambiguous_or_conflicting_split_count"],
        "output": str(output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
