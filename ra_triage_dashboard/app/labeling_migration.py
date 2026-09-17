"""Idempotent legacy Review-to-Case-labeling migration helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from .db_parts.shared import _json_load
from .review_workflow import effective_expected_output


DEFAULT_LABEL_DATASETS = ("0522", "0626", "0821")
DEFAULT_POLICY_VERSION = "case-labeling-v1"


def legacy_labeling_inventory(
    database: Any,
    *,
    scopes: Sequence[str],
) -> dict[str, Any]:
    normalized = [str(value or "").strip() for value in scopes if str(value or "").strip()]
    if not normalized:
        return {"datasets": [], "annotation_versions": 0, "tasks": []}
    placeholders = ", ".join("?" for _ in normalized)
    with database.connect() as conn:
        dataset_rows = conn.execute(
            f"""
            SELECT baseline_scope, COUNT(*) AS issue_count,
                   SUM(CASE WHEN COALESCE(gt_label, '') <> '' THEN 1 ELSE 0 END) AS gt_count
            FROM issues WHERE baseline_scope IN ({placeholders})
            GROUP BY baseline_scope ORDER BY baseline_scope
            """,
            normalized,
        ).fetchall()
        annotation_rows = conn.execute(
            f"""
            SELECT i.baseline_scope, COUNT(*) AS version_count,
                   COUNT(DISTINCT a.issue_id) AS issue_count,
                   SUM(CASE WHEN a.work_split_id <> '' THEN 1 ELSE 0 END) AS task_version_count
            FROM annotations a JOIN issues i ON i.issue_id = a.issue_id
            WHERE i.baseline_scope IN ({placeholders})
            GROUP BY i.baseline_scope ORDER BY i.baseline_scope
            """,
            normalized,
        ).fetchall()
        task_rows = conn.execute(
            f"""
            SELECT split.id, split.created_by, split.created_at, split.model_run_id,
                   split.filter_json, split.assignees_json,
                   COUNT(DISTINCT assignment.issue_id) AS issue_count
            FROM issue_work_splits split
            JOIN review_work_assignments assignment ON assignment.split_id = split.id
            JOIN issues issue ON issue.issue_id = assignment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            GROUP BY split.id ORDER BY split.created_at
            """,
            normalized,
        ).fetchall()
    annotations = {
        str(row["baseline_scope"]): {
            "version_count": int(row["version_count"] or 0),
            "issue_count": int(row["issue_count"] or 0),
            "task_version_count": int(row["task_version_count"] or 0),
        }
        for row in annotation_rows
    }
    return {
        "datasets": [
            {
                "baseline_scope": str(row["baseline_scope"]),
                "issue_count": int(row["issue_count"] or 0),
                "gt_count": int(row["gt_count"] or 0),
                **annotations.get(str(row["baseline_scope"]), {
                    "version_count": 0,
                    "task_version_count": 0,
                }),
            }
            for row in dataset_rows
        ],
        "annotation_versions": sum(int(row["version_count"] or 0) for row in annotation_rows),
        "tasks": [
            {
                "id": str(row["id"]),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
                "model_run_id": str(row["model_run_id"] or ""),
                "issue_count": int(row["issue_count"] or 0),
                "filter": _json_load(row["filter_json"], {}),
                "assignments": _json_load(row["assignees_json"], []),
            }
            for row in task_rows
        ],
    }


def _snapshot_issue_ids(assignments: Any) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for member in assignments if isinstance(assignments, list) else []:
        source = member.get("items") if isinstance(member, dict) else None
        if isinstance(source, list):
            candidates = [item.get("issue_id") for item in source if isinstance(item, dict)]
        else:
            candidates = member.get("issue_ids") if isinstance(member, dict) else []
        for value in candidates or []:
            issue_id = str(value or "").strip()
            if issue_id and issue_id not in seen:
                seen.add(issue_id)
                ordered.append(issue_id)
    return ordered


def migrate_legacy_labeling(
    database: Any,
    *,
    scopes: Sequence[str],
    tag_catalog: Sequence[dict[str, Any]],
    policy_version: str = DEFAULT_POLICY_VERSION,
) -> dict[str, Any]:
    """Backfill explicit Label records without changing legacy Review rows."""

    inventory = legacy_labeling_inventory(database, scopes=scopes)
    task_ids: set[str] = set()
    created_worksets: list[str] = []
    for task in inventory["tasks"]:
        issue_ids = _snapshot_issue_ids(task["assignments"])
        if not issue_ids:
            with database.connect() as conn:
                rows = conn.execute(
                    "SELECT issue_id FROM review_work_assignments WHERE split_id = ? ORDER BY ordinal, issue_id",
                    (task["id"],),
                ).fetchall()
            issue_ids = list(dict.fromkeys(str(row["issue_id"]) for row in rows))
        if not issue_ids:
            continue
        with database.connect() as conn:
            scope_rows = conn.execute(
                f"SELECT DISTINCT baseline_scope FROM issues WHERE issue_id IN ({', '.join('?' for _ in issue_ids)})",
                issue_ids,
            ).fetchall()
        task_scopes = [str(row["baseline_scope"] or "") for row in scope_rows]
        if len(task_scopes) != 1 or task_scopes[0] not in scopes:
            continue
        workset = database.create_review_workset(
            baseline_scope=task_scopes[0],
            issue_ids=issue_ids,
            name=f"历史标注任务 {len(issue_ids)}",
            selection_source_run_id=task["model_run_id"],
            source_filter=task["filter"],
            created_by=task["created_by"],
            created_by_source="legacy_migration",
            created_by_verified=False,
        )
        database.bind_labeling_task(task_id=task["id"], workset_id=workset["id"])
        database.record_label_migration_map(
            source_table="issue_work_splits",
            source_id=task["id"],
            target_table="review_worksets",
            target_id=workset["id"],
            policy_version=policy_version,
        )
        task_ids.add(task["id"])
        created_worksets.append(workset["id"])

    normalized_scopes = [str(value) for value in scopes]
    placeholders = ", ".join("?" for _ in normalized_scopes)
    with database.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT annotation.*, issue.baseline_scope, issue.gt_label, issue.gt_source
            FROM annotations annotation
            JOIN issues issue ON issue.issue_id = annotation.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY annotation.id
            """,
            normalized_scopes,
        ).fetchall()
    migrated_by_scope: dict[str, int] = defaultdict(int)
    label_case_ids: set[str] = set()
    for row in rows:
        split_id = str(row["work_split_id"] or "")
        task_id = split_id if split_id in task_ids else ""
        source_run_id = str(row["model_run_id"] or "")
        label_case = database.ensure_label_case(
            issue_id=str(row["issue_id"]),
            task_id=task_id,
            source_run_id=source_run_id,
            created_at=str(row["created_at"] or ""),
        )
        annotation = {
            "label": str(row["label"] or ""),
            "tags": _json_load(row["tags_json"], []),
        }
        output, _ = effective_expected_output(annotation, tag_catalog)
        database.migrate_legacy_label_revision(
            label_case_id=label_case["id"],
            source_annotation_id=int(row["id"]),
            expected_output=output,
            tags=_json_load(row["tags_json"], []),
            evidence_gaps=_json_load(row["missing_evidence_json"], []),
            rationale=str(row["note"] or ""),
            is_excluded=bool(row["is_excluded"]),
            author=str(row["author"] or ""),
            author_source=str(row["author_source"] or "legacy"),
            author_verified=bool(row["author_verified"]),
            supersedes_source_annotation_id=(
                int(row["supersedes_id"])
                if row["supersedes_id"] not in (None, "")
                else None
            ),
            created_at=str(row["created_at"] or ""),
            policy_version=policy_version,
        )
        label_case_ids.add(label_case["id"])
        migrated_by_scope[str(row["baseline_scope"] or "")] += 1
    with database.connect() as conn:
        task_context_rows = conn.execute(
            """
            SELECT split.id, split.selection_source_run_id, item.issue_id
            FROM issue_work_splits split
            JOIN review_workset_items item ON item.workset_id = split.workset_id
            WHERE split.task_kind = 'labeling'
            ORDER BY split.id, item.ordinal
            """
        ).fetchall()
        comment_rows = conn.execute(
            f"""
            SELECT comment.id, comment.issue_id, comment.model_run_id
            FROM review_comments comment
            JOIN issues issue ON issue.issue_id = comment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY comment.id
            """,
            normalized_scopes,
        ).fetchall()
    contexts_by_issue: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in task_context_rows:
        contexts_by_issue[str(row["issue_id"])].append(
            (str(row["id"]), str(row["selection_source_run_id"] or ""))
        )
    linked_comments = 0
    ambiguous_comments = 0
    for row in comment_rows:
        issue_id = str(row["issue_id"])
        source_run = str(row["model_run_id"] or "")
        candidates = [
            task_id
            for task_id, task_run in contexts_by_issue.get(issue_id, [])
            if task_run == source_run
        ]
        task_id = candidates[0] if len(candidates) == 1 else ""
        if len(candidates) > 1:
            ambiguous_comments += 1
        database.link_label_comment(
            comment_id=int(row["id"]),
            task_id=task_id,
            source_run_id=source_run,
            policy_version=policy_version,
        )
        linked_comments += 1
    return {
        "policy_version": policy_version,
        "worksets": sorted(set(created_worksets)),
        "task_count": len(task_ids),
        "label_case_count": len(label_case_ids),
        "revision_count": sum(migrated_by_scope.values()),
        "revisions_by_scope": dict(sorted(migrated_by_scope.items())),
        "linked_comment_count": linked_comments,
        "ambiguous_comment_count": ambiguous_comments,
    }
