"""Idempotent legacy Review-to-Case-labeling migration helpers."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any, Sequence

from .db_parts.shared import _json_load
from .review_workflow import effective_expected_output


DEFAULT_LABEL_DATASETS = ("0522", "0626", "0821")
DEFAULT_POLICY_VERSION = "case-labeling-v1"


def _normalized_scopes(scopes: Sequence[str]) -> list[str]:
    return sorted(
        {
            str(value or "").strip()
            for value in scopes
            if str(value or "").strip()
        }
    )


def labeling_inventory_fingerprint(database: Any, *, scopes: Sequence[str]) -> str:
    normalized = _normalized_scopes(scopes)
    if not normalized:
        return hashlib.sha256(b"").hexdigest()
    placeholders = ", ".join("?" for _ in normalized)
    with database.connect() as conn:
        issues = conn.execute(
            f"SELECT issue_id, baseline_scope, COALESCE(gt_label, '') AS gt_label, COALESCE(gt_source, '') AS gt_source FROM issues WHERE baseline_scope IN ({placeholders}) ORDER BY baseline_scope, issue_id",
            normalized,
        ).fetchall()
        annotations = conn.execute(
            f"""
            SELECT annotation.id, annotation.issue_id, annotation.model_run_id,
                   annotation.work_split_id, COALESCE(annotation.label, '') AS label,
                   annotation.tags_json, annotation.missing_evidence_json,
                   annotation.note, annotation.author, annotation.author_source,
                   annotation.author_verified, annotation.supersedes_id,
                   annotation.created_at
            FROM annotations annotation
            JOIN issues issue ON issue.issue_id = annotation.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY annotation.id
            """,
            normalized,
        ).fetchall()
        comments = conn.execute(
            f"""
            SELECT comment.id, comment.issue_id, comment.model_run_id,
                   comment.body, comment.author, comment.reply_to_id, comment.created_at
            FROM review_comments comment
            JOIN issues issue ON issue.issue_id = comment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY comment.id
            """,
            normalized,
        ).fetchall()
        tasks = conn.execute(
            f"""
            SELECT DISTINCT split.id, split.filter_json, split.assignees_json,
                   split.model_run_id, split.assignment_count, split.created_at
            FROM issue_work_splits split
            JOIN review_work_assignments assignment ON assignment.split_id = split.id
            JOIN issues issue ON issue.issue_id = assignment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY split.id
            """,
            normalized,
        ).fetchall()
    def plain(rows: Sequence[Any]) -> list[list[str]]:
        return [
            [str(row[key] if row[key] is not None else "") for key in row.keys()]
            for row in rows
        ]
    payload = {
        "scopes": sorted(normalized),
        "issues": plain(issues),
        "annotations": plain(annotations),
        "comments": plain(comments),
        "tasks": plain(tasks),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def labeling_inventory_fingerprints(
    database: Any, *, scopes: Sequence[str]
) -> dict[str, str]:
    """Return independently activatable source hashes for each dataset scope."""

    return {
        scope: labeling_inventory_fingerprint(database, scopes=[scope])
        for scope in _normalized_scopes(scopes)
    }


def legacy_labeling_inventory(
    database: Any,
    *,
    scopes: Sequence[str],
) -> dict[str, Any]:
    normalized = _normalized_scopes(scopes)
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
    migrated_by: str = "migration",
) -> dict[str, Any]:
    """Backfill explicit Label records without changing legacy Review rows."""

    normalized_scopes = _normalized_scopes(scopes)
    source_fingerprints = labeling_inventory_fingerprints(
        database, scopes=normalized_scopes
    )
    existing_states = {
        item["baseline_scope"]: item
        for item in database.labeling_scope_states(normalized_scopes)
    }
    drifted_active = [
        scope
        for scope, state in existing_states.items()
        if state["status"] == "active"
        and (
            state["policy_version"] != policy_version
            or state["source_inventory_sha256"] != source_fingerprints[scope]
        )
    ]
    if drifted_active:
        raise ValueError(
            "已激活的数据集源清单发生变化，不能直接重新回填："
            + "、".join(drifted_active)
            + "。请先暂停并建立新的迁移批次。"
        )

    inventory = legacy_labeling_inventory(database, scopes=normalized_scopes)
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
        if len(task_scopes) != 1 or task_scopes[0] not in normalized_scopes:
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
    source_fingerprints = labeling_inventory_fingerprints(
        database, scopes=normalized_scopes
    )
    scope_states = []
    for scope in normalized_scopes:
        existing = existing_states.get(scope)
        keep_active = bool(
            existing
            and existing["status"] == "active"
            and existing["policy_version"] == policy_version
            and existing["source_inventory_sha256"] == source_fingerprints[scope]
        )
        scope_states.append(
            database.set_labeling_scope_state(
                baseline_scope=scope,
                status="active" if keep_active else "shadow",
                policy_version=policy_version,
                source_inventory_sha256=source_fingerprints[scope],
                updated_by=migrated_by,
                expected_epoch=existing["epoch"] if existing else None,
            )
        )
    return {
        "policy_version": policy_version,
        "worksets": sorted(set(created_worksets)),
        "task_count": len(task_ids),
        "label_case_count": len(label_case_ids),
        "revision_count": sum(migrated_by_scope.values()),
        "revisions_by_scope": dict(sorted(migrated_by_scope.items())),
        "linked_comment_count": linked_comments,
        "ambiguous_comment_count": ambiguous_comments,
        "source_inventory_sha256": labeling_inventory_fingerprint(
            database, scopes=normalized_scopes
        ),
        "source_inventory_sha256_by_scope": source_fingerprints,
        "scope_states": scope_states,
    }


def reconcile_legacy_labeling(
    database: Any,
    *,
    scopes: Sequence[str],
    policy_version: str = DEFAULT_POLICY_VERSION,
) -> dict[str, Any]:
    normalized = _normalized_scopes(scopes)
    placeholders = ", ".join("?" for _ in normalized)
    if not normalized:
        return {"passed": False, "errors": ["没有数据集范围。"]}
    with database.connect() as conn:
        source_annotations = conn.execute(
            f"""
            SELECT annotation.id FROM annotations annotation
            JOIN issues issue ON issue.issue_id = annotation.issue_id
            WHERE issue.baseline_scope IN ({placeholders}) ORDER BY annotation.id
            """,
            normalized,
        ).fetchall()
        mapped_annotations = conn.execute(
            f"""
            SELECT mapping.source_id
            FROM label_migration_map mapping
            JOIN label_revisions revision
              ON CAST(revision.id AS TEXT) = mapping.target_id
            JOIN label_cases label_case ON label_case.id = revision.label_case_id
            WHERE mapping.source_table = 'annotations'
              AND mapping.target_table = 'label_revisions'
              AND mapping.policy_version = ?
              AND label_case.baseline_scope IN ({placeholders})
            """,
            (policy_version, *normalized),
        ).fetchall()
        source_comments = conn.execute(
            f"""
            SELECT comment.id FROM review_comments comment
            JOIN issues issue ON issue.issue_id = comment.issue_id
            WHERE issue.baseline_scope IN ({placeholders}) ORDER BY comment.id
            """,
            normalized,
        ).fetchall()
        mapped_comments = conn.execute(
            f"""
            SELECT link.comment_id FROM label_comment_links link
            JOIN issues issue ON issue.issue_id = link.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
              AND link.policy_version = ?
            ORDER BY link.comment_id
            """,
            (*normalized, policy_version),
        ).fetchall()
        source_tasks = conn.execute(
            f"""
            SELECT DISTINCT split.id FROM issue_work_splits split
            JOIN review_work_assignments assignment ON assignment.split_id = split.id
            JOIN issues issue ON issue.issue_id = assignment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY split.id
            """,
            normalized,
        ).fetchall()
        mapped_tasks = conn.execute(
            f"""
            SELECT mapping.source_id
            FROM label_migration_map mapping
            JOIN review_worksets workset ON workset.id = mapping.target_id
            WHERE mapping.source_table = 'issue_work_splits'
              AND mapping.target_table = 'review_worksets'
              AND mapping.policy_version = ?
              AND workset.baseline_scope IN ({placeholders})
            """,
            (policy_version, *normalized),
        ).fetchall()
    source_annotation_ids = {str(row["id"]) for row in source_annotations}
    mapped_annotation_ids = {str(row["source_id"]) for row in mapped_annotations}
    source_comment_ids = {str(row["id"]) for row in source_comments}
    mapped_comment_ids = {str(row["comment_id"]) for row in mapped_comments}
    source_task_ids = {str(row["id"]) for row in source_tasks}
    mapped_task_ids = {str(row["source_id"]) for row in mapped_tasks}
    errors: list[str] = []
    missing_annotations = sorted(source_annotation_ids - mapped_annotation_ids)
    extra_annotations = sorted(mapped_annotation_ids - source_annotation_ids)
    missing_comments = sorted(source_comment_ids - mapped_comment_ids)
    extra_comments = sorted(mapped_comment_ids - source_comment_ids)
    missing_tasks = sorted(source_task_ids - mapped_task_ids)
    extra_tasks = sorted(mapped_task_ids - source_task_ids)
    if missing_annotations:
        errors.append(f"缺少 annotation 映射 {len(missing_annotations)} 条。")
    if extra_annotations:
        errors.append(f"存在范围外 annotation 映射 {len(extra_annotations)} 条。")
    if missing_comments:
        errors.append(f"缺少 comment 链接 {len(missing_comments)} 条。")
    if extra_comments:
        errors.append(f"存在范围外 comment 链接 {len(extra_comments)} 条。")
    if missing_tasks:
        errors.append(f"缺少任务映射 {len(missing_tasks)} 条。")
    if extra_tasks:
        errors.append(f"存在范围外任务映射 {len(extra_tasks)} 条。")
    current_fingerprint = labeling_inventory_fingerprint(database, scopes=normalized)
    current_fingerprints = labeling_inventory_fingerprints(
        database, scopes=normalized
    )
    states = database.labeling_scope_states(normalized)
    states_by_scope = {item["baseline_scope"]: item for item in states}
    stale_states = [
        scope
        for scope in normalized
        if scope in states_by_scope
        and (
            states_by_scope[scope]["policy_version"] != policy_version
            or states_by_scope[scope]["source_inventory_sha256"]
            != current_fingerprints[scope]
        )
    ]
    if len(states) != len(normalized):
        errors.append("部分数据集缺少迁移状态。")
    if stale_states:
        errors.append("源数据在回填后发生变化：" + "、".join(stale_states))
    return {
        "passed": not errors,
        "policy_version": policy_version,
        "source_inventory_sha256": current_fingerprint,
        "source_inventory_sha256_by_scope": current_fingerprints,
        "source_annotation_count": len(source_annotation_ids),
        "mapped_annotation_count": len(mapped_annotation_ids & source_annotation_ids),
        "source_comment_count": len(source_comment_ids),
        "mapped_comment_count": len(mapped_comment_ids & source_comment_ids),
        "source_task_count": len(source_task_ids),
        "mapped_task_count": len(mapped_task_ids & source_task_ids),
        "missing_annotation_ids": missing_annotations[:100],
        "missing_comment_ids": missing_comments[:100],
        "missing_task_ids": missing_tasks[:100],
        "errors": errors,
        "scope_states": states,
    }
