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


def _inventory_fingerprint_on_connection(
    conn: Any, *, scopes: Sequence[str]
) -> str:
    normalized = _normalized_scopes(scopes)
    if not normalized:
        return hashlib.sha256(b"").hexdigest()
    placeholders = ", ".join("?" for _ in normalized)
    issues = conn.execute(
        f"SELECT issue_id, baseline_scope, COALESCE(gt_label, '') AS gt_label, COALESCE(gt_source, '') AS gt_source FROM issues WHERE baseline_scope IN ({placeholders}) ORDER BY baseline_scope, issue_id",
        normalized,
    ).fetchall()
    annotations = conn.execute(
        f"""
        SELECT annotation.*
        FROM annotations annotation
        JOIN issues issue ON issue.issue_id = annotation.issue_id
        WHERE issue.baseline_scope IN ({placeholders})
        ORDER BY annotation.id
        """,
        normalized,
    ).fetchall()
    comments = conn.execute(
        f"""
        SELECT comment.*
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
               split.model_run_id, split.assignment_count, split.created_at,
               split.created_by, split.seed, split.total_count, split.mode,
               split.reviewers_per_issue, split.overlap_ratio
        FROM issue_work_splits split
        JOIN review_work_assignments assignment ON assignment.split_id = split.id
        JOIN issues issue ON issue.issue_id = assignment.issue_id
        WHERE issue.baseline_scope IN ({placeholders})
        ORDER BY split.id
        """,
        normalized,
    ).fetchall()
    review_attachments = conn.execute(
        f"""
        SELECT attachment.* FROM review_attachments attachment
        JOIN annotations annotation ON annotation.id = attachment.annotation_id
        JOIN issues issue ON issue.issue_id = annotation.issue_id
        WHERE issue.baseline_scope IN ({placeholders}) ORDER BY attachment.id
        """, normalized,
    ).fetchall()
    comment_attachments = conn.execute(
        f"""
        SELECT attachment.* FROM comment_attachments attachment
        JOIN review_comments comment ON comment.id = attachment.comment_id
        JOIN issues issue ON issue.issue_id = comment.issue_id
        WHERE issue.baseline_scope IN ({placeholders}) ORDER BY attachment.id
        """, normalized,
    ).fetchall()
    assignments = conn.execute(
        f"""
        SELECT assignment.* FROM review_work_assignments assignment
        JOIN issues issue ON issue.issue_id = assignment.issue_id
        WHERE issue.baseline_scope IN ({placeholders})
        ORDER BY assignment.split_id, assignment.issue_id, assignment.assignee
        """, normalized,
    ).fetchall()
    assignment_changes = conn.execute(
        f"""
        SELECT change.* FROM review_work_assignment_changes change
        JOIN issues issue ON issue.issue_id = change.issue_id
        WHERE issue.baseline_scope IN ({placeholders}) ORDER BY change.id
        """, normalized,
    ).fetchall()
    tag_catalog = conn.execute(
        "SELECT * FROM review_tag_catalog ORDER BY key"
    ).fetchall()

    def plain(rows: Sequence[Any]) -> list[dict[str, Any]]:
        # Preserve NULL distinctly, name columns, and canonicalize JSONB/text
        # equally rather than relying on the database's JSON rendering order.
        return [
            {
                key: (
                    _json_load(row[key], None) if key.endswith("_json")
                    else None if row[key] is None else str(row[key])
                )
                for key in row.keys()
            }
            for row in rows
        ]
    payload = {
        "fingerprint_version": 2,
        "scopes": sorted(normalized),
        "issues": plain(issues),
        "annotations": plain(annotations),
        "comments": plain(comments),
        "tasks": plain(tasks),
        "review_attachments": plain(review_attachments),
        "comment_attachments": plain(comment_attachments),
        "assignments": plain(assignments),
        "assignment_changes": plain(assignment_changes),
        "tag_catalog": plain(tag_catalog),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def labeling_inventory_fingerprint(database: Any, *, scopes: Sequence[str]) -> str:
    with database.connect() as conn:
        return _inventory_fingerprint_on_connection(conn, scopes=scopes)


def scope_inventory_verifier(
    scopes: Sequence[str],
) -> Any:
    """Build a connection-scoped fingerprint check for atomic activation."""

    def verify(conn: Any) -> str:
        return _inventory_fingerprint_on_connection(conn, scopes=scopes)

    return verify


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
            "annotated_issue_count": int(row["issue_count"] or 0),
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
                    "annotated_issue_count": 0,
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
            # Legacy annotations may reference a source Run that was never
            # imported or has since been deleted; the id stays as context.
            allow_missing_source_run=True,
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
    final_fingerprints = labeling_inventory_fingerprints(
        database, scopes=normalized_scopes
    )
    if final_fingerprints != source_fingerprints:
        raise ValueError("回填期间源数据发生变化；本次回填不能作为激活依据，请重新对账。")
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
    tag_catalog: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    normalized = _normalized_scopes(scopes)
    placeholders = ", ".join("?" for _ in normalized)
    if not normalized:
        return {"passed": False, "errors": ["没有数据集范围。"]}
    with database.connect() as conn:
        source_annotations = conn.execute(
            f"""
            SELECT annotation.*, issue.baseline_scope,
                   issue.gt_label AS source_gt_label, issue.gt_source AS source_gt_source
            FROM annotations annotation
            JOIN issues issue ON issue.issue_id = annotation.issue_id
            WHERE issue.baseline_scope IN ({placeholders}) ORDER BY annotation.id
            """,
            normalized,
        ).fetchall()
        mapped_annotations = conn.execute(
            f"""
            SELECT mapping.source_id, revision.*,
                   label_case.baseline_scope AS target_scope,
                   label_case.issue_id AS target_issue_id,
                   label_case.task_id AS target_task_id,
                   label_case.source_run_id AS target_run_id,
                   label_case.seen_gt_label, label_case.seen_gt_source
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
            SELECT comment.*, issue.baseline_scope FROM review_comments comment
            JOIN issues issue ON issue.issue_id = comment.issue_id
            WHERE issue.baseline_scope IN ({placeholders}) ORDER BY comment.id
            """,
            normalized,
        ).fetchall()
        mapped_comments = conn.execute(
            f"""
            SELECT link.* FROM label_comment_links link
            JOIN issues issue ON issue.issue_id = link.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
              AND link.policy_version = ?
            ORDER BY link.comment_id
            """,
            (*normalized, policy_version),
        ).fetchall()
        source_tasks = conn.execute(
            f"""
            SELECT DISTINCT split.* FROM issue_work_splits split
            JOIN review_work_assignments assignment ON assignment.split_id = split.id
            JOIN issues issue ON issue.issue_id = assignment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY split.id
            """,
            normalized,
        ).fetchall()
        mapped_tasks = conn.execute(
            f"""
            SELECT mapping.source_id, workset.*
            FROM label_migration_map mapping
            JOIN review_worksets workset ON workset.id = mapping.target_id
            WHERE mapping.source_table = 'issue_work_splits'
              AND mapping.target_table = 'review_worksets'
              AND mapping.policy_version = ?
              AND workset.baseline_scope IN ({placeholders})
            """,
            (policy_version, *normalized),
        ).fetchall()
        source_attachments = conn.execute(
            f"""
            SELECT attachment.* FROM review_attachments attachment
            JOIN annotations annotation ON annotation.id = attachment.annotation_id
            JOIN issues issue ON issue.issue_id = annotation.issue_id
            WHERE issue.baseline_scope IN ({placeholders}) ORDER BY attachment.id
            """, normalized,
        ).fetchall()
        target_attachments = conn.execute(
            f"""
            SELECT attachment.* FROM label_attachments attachment
            JOIN label_revisions revision ON revision.id = attachment.revision_id
            JOIN label_cases label_case ON label_case.id = revision.label_case_id
            WHERE label_case.baseline_scope IN ({placeholders})
              AND revision.source_annotation_id IS NOT NULL
            ORDER BY attachment.id
            """, normalized,
        ).fetchall()
        assignment_rows = conn.execute(
            f"""
            SELECT assignment.* FROM review_work_assignments assignment
            JOIN issues issue ON issue.issue_id = assignment.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY assignment.ordinal, assignment.issue_id, assignment.assignee
            """, normalized,
        ).fetchall()
        workset_items = conn.execute(
            f"""
            SELECT item.* FROM review_workset_items item
            JOIN review_worksets workset ON workset.id = item.workset_id
            WHERE workset.baseline_scope IN ({placeholders})
            ORDER BY item.workset_id, item.ordinal
            """, normalized,
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
    # IDs alone cannot prove a migration: an existing source revision is never
    # rewritten by backfill. Validate content and ownership before activation.
    mismatches: list[dict[str, Any]] = []

    def mismatch(kind: str, source_id: Any, fields: Sequence[str]) -> None:
        if fields:
            mismatches.append({
                "kind": kind, "source_id": str(source_id), "fields": list(fields),
            })

    def text_value(value: Any) -> str:
        return str(value if value is not None else "")

    revisions_by_source = {str(row["source_id"]): row for row in mapped_annotations}
    task_by_source = {str(row["source_id"]): row for row in mapped_tasks}
    for source in source_annotations:
        source_id = str(source["id"])
        target = revisions_by_source.get(source_id)
        if target is None:
            continue
        source_tags = _json_load(source["tags_json"], [])
        expected_output, _ = effective_expected_output(
            {"label": source["label"], "tags": source_tags}, tag_catalog
        )
        split_id = text_value(source["work_split_id"])
        expected_task = split_id if split_id in task_by_source else ""
        expected_run = text_value(source["model_run_id"])
        if not expected_run and expected_task:
            expected_run = text_value(task_by_source[expected_task]["selection_source_run_id"])
        predecessor = revisions_by_source.get(text_value(source["supersedes_id"]))
        fields = []
        expected_fields = {
            "source_annotation_id": source_id,
            "expected_output": expected_output,
            "rationale": text_value(source["note"]),
            "author": text_value(source["author"]),
            "author_source": text_value(source["author_source"]) or "legacy",
            "created_at": text_value(source["created_at"]),
            "revision_kind": "legacy",
            "target_scope": text_value(source["baseline_scope"]),
            "target_issue_id": text_value(source["issue_id"]),
            "target_task_id": expected_task,
            "target_run_id": expected_run,
            "seen_gt_label": text_value(source["source_gt_label"]),
            "seen_gt_source": text_value(source["source_gt_source"]),
            "supersedes_id": text_value(predecessor["id"]) if predecessor else "",
        }
        for key, expected in expected_fields.items():
            if text_value(target[key]) != expected:
                fields.append(key)
        if source["supersedes_id"] is not None and predecessor is None:
            fields.append("unmapped_source_predecessor")
        for key in ("is_excluded", "author_verified"):
            if bool(target[key]) != bool(source[key]):
                fields.append(key)
        for target_key, values in (
            ("tags_json", source_tags),
            ("evidence_gaps_json", _json_load(source["missing_evidence_json"], [])),
        ):
            if _json_load(target[target_key], []) != _normalized_scopes(values):
                fields.append(target_key)
        mismatch("annotation", source_id, fields)

    source_attachment_ids = {str(row["id"]) for row in source_attachments}
    target_attachments_by_source = {
        text_value(row["source_review_attachment_id"]): row for row in target_attachments
    }
    missing_attachments = sorted(source_attachment_ids - set(target_attachments_by_source))
    extra_attachments = sorted(set(target_attachments_by_source) - source_attachment_ids)
    if missing_attachments:
        errors.append(f"缺少 Review 附件映射 {len(missing_attachments)} 条。")
    if extra_attachments:
        errors.append(f"存在范围外 Review 附件映射 {len(extra_attachments)} 条。")
    for source in source_attachments:
        source_id = str(source["id"])
        target = target_attachments_by_source.get(source_id)
        if target is None:
            continue
        fields = [
            key for key in (
                "id", "original_name", "stored_name", "media_type", "size_bytes",
                "width", "height", "sha256", "created_at",
            ) if text_value(source[key]) != text_value(target[key])
        ]
        revision = revisions_by_source.get(str(source["annotation_id"]))
        if revision is None or int(target["revision_id"]) != int(revision["id"]):
            fields.append("revision_id")
        mismatch("attachment", source_id, fields)

    items_by_workset: dict[str, list[Any]] = defaultdict(list)
    for row in workset_items:
        items_by_workset[str(row["workset_id"])].append(row)
    assignments_by_task: dict[str, list[str]] = defaultdict(list)
    for row in assignment_rows:
        assignments_by_task[str(row["split_id"])].append(str(row["issue_id"]))
    contexts_by_issue: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for source in source_tasks:
        source_id = str(source["id"])
        target = task_by_source.get(source_id)
        if target is None:
            continue
        issue_ids = _snapshot_issue_ids(_json_load(source["assignees_json"], []))
        if not issue_ids:
            issue_ids = list(dict.fromkeys(assignments_by_task[source_id]))
        items = items_by_workset[str(target["id"])]
        actual_ids = [str(item["issue_id"]) for item in items]
        fields = []
        if actual_ids != issue_ids:
            fields.append("members")
        if [int(item["ordinal"]) for item in items] != list(range(1, len(issue_ids) + 1)):
            fields.append("ordinals")
        if int(target["member_count"]) != len(issue_ids):
            fields.append("member_count")
        digest = hashlib.sha256("\n".join(issue_ids).encode("utf-8")).hexdigest()
        if str(target["members_sha256"]) != digest:
            fields.append("members_sha256")
        if str(source["workset_id"]) != str(target["id"]):
            fields.append("workset_id")
        if str(source["task_kind"]) != "labeling":
            fields.append("task_kind")
        for key in ("model_run_id", "selection_source_run_id"):
            if text_value(source[key]) != text_value(target["selection_source_run_id"]):
                fields.append(key)
        if _json_load(source["filter_json"], {}) != _json_load(target["source_filter_json"], {}):
            fields.append("source_filter_json")
        mismatch("task", source_id, fields)
        for issue_id in issue_ids:
            contexts_by_issue[issue_id].append((source_id, text_value(source["model_run_id"])))

    links_by_comment = {str(row["comment_id"]): row for row in mapped_comments}
    for source in source_comments:
        source_id = str(source["id"])
        target = links_by_comment.get(source_id)
        if target is None:
            continue
        source_run = text_value(source["model_run_id"])
        candidates = [
            task for task, run in contexts_by_issue[text_value(source["issue_id"])]
            if run == source_run
        ]
        expected_fields = {
            "issue_id": text_value(source["issue_id"]),
            "baseline_scope": text_value(source["baseline_scope"]),
            "source_run_id": source_run,
            "task_id": candidates[0] if len(candidates) == 1 else "",
        }
        fields = [
            key for key, expected in expected_fields.items()
            if text_value(target[key]) != expected
        ]
        if source["reply_to_id"] is not None:
            parent = links_by_comment.get(str(source["reply_to_id"]))
            if parent is None or any(
                text_value(parent[key]) != text_value(target[key])
                for key in ("issue_id", "task_id", "source_run_id")
            ):
                fields.append("reply_context")
        mismatch("comment", source_id, fields)
    if mismatches:
        errors.append(f"源/目标内容或归属不一致 {len(mismatches)} 条。")
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
        "source_attachment_count": len(source_attachment_ids),
        "mapped_attachment_count": len(source_attachment_ids & set(target_attachments_by_source)),
        "missing_attachment_ids": missing_attachments[:100],
        "content_mismatch_count": len(mismatches),
        "content_mismatches": mismatches[:100],
        "attachment_file_verification": "not_performed",
        "errors": errors,
        "scope_states": states,
    }


def activate_legacy_labeling(
    database: Any,
    *,
    scopes: Sequence[str],
    policy_version: str = DEFAULT_POLICY_VERSION,
    tag_catalog: Sequence[dict[str, Any]] = (),
    expected_epoch: int,
    updated_by: str = "migration",
) -> dict[str, Any]:
    """Activate one dataset scope atomically and verify the cutover afterwards."""

    normalized = _normalized_scopes(scopes)
    if len(normalized) != 1:
        raise ValueError("activate 每次只能处理一个数据集。")
    scope = normalized[0]
    reconciliation = reconcile_legacy_labeling(
        database,
        scopes=[scope],
        policy_version=policy_version,
        tag_catalog=tag_catalog,
    )
    result: dict[str, Any] = {
        "passed": False,
        "policy_version": policy_version,
        "baseline_scope": scope,
        "reconciliation": reconciliation,
        "activation": None,
        "post_reconciliation": None,
        "paused_state": None,
    }
    if not reconciliation["passed"]:
        return result
    expected_fingerprint = reconciliation["source_inventory_sha256_by_scope"][scope]
    state = next(
        (
            item for item in reconciliation["scope_states"]
            if item["baseline_scope"] == scope
        ),
        None,
    )
    if state is None or state["policy_version"] != policy_version:
        result["errors"] = ["该数据集缺少当前 policy 的回填状态；请先 backfill。"]
        return result
    if state["source_inventory_sha256"] != expected_fingerprint:
        result["errors"] = ["回填状态与对账指纹不一致；请重新 backfill。"]
        return result
    activation = database.activate_labeling_scope(
        baseline_scope=scope,
        policy_version=policy_version,
        source_inventory_sha256=expected_fingerprint,
        updated_by=updated_by,
        expected_epoch=expected_epoch,
        verify_inventory=scope_inventory_verifier([scope]),
    )
    result["activation"] = activation
    post = reconcile_legacy_labeling(
        database,
        scopes=[scope],
        policy_version=policy_version,
        tag_catalog=tag_catalog,
    )
    result["post_reconciliation"] = post
    if not post["passed"]:
        # A write slipped into the activation window: pause the scope so the
        # old entry stays closed while the drift is re-audited.
        result["paused_state"] = database.set_labeling_scope_state(
            baseline_scope=scope,
            status="paused",
            policy_version=policy_version,
            source_inventory_sha256=post["source_inventory_sha256_by_scope"][scope],
            updated_by=updated_by,
            expected_epoch=activation["epoch"],
        )
        result["errors"] = [
            "激活后源数据校验失败，该数据集已暂停；请重新对账后再激活。"
        ]
        return result
    result["passed"] = True
    return result
