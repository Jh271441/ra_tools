"""Assignment completion and migrated batch provenance.

SQL fragments use the fixed internal aliases split/assignment/head/revision.
No caller-provided identifiers or data are interpolated here. Completion means
an eligible current model head, or both explicit combined-workflow markers;
it does not mean the shared label is resolved.
"""
from typing import Any, Mapping

from .shared import _json_load

MODEL_SUBMISSION_SQL = """
(revision.status = 'completed' OR EXISTS (
    SELECT 1 FROM annotations legacy_submission
    WHERE legacy_submission.id = revision.legacy_annotation_id
      AND legacy_submission.issue_id = revision.issue_id
      AND legacy_submission.model_run_id = revision.model_run_id
      AND lower(legacy_submission.author) = lower(revision.reviewer)
))
"""

MODEL_ASSIGNMENT_SCOPE_SQL = """
(
    (split.purpose = 'model_review' AND head.campaign_id = split.id
     AND head.reference_id = split.reference_id)
    OR (COALESCE(split.purpose, '') <> 'model_review'
        AND split.mode = 'blind' AND revision.work_split_id = assignment.split_id)
    OR (COALESCE(split.purpose, '') <> 'model_review'
        AND split.mode <> 'blind' AND revision.work_split_id = '')
)
"""

ASSIGNMENT_SUBMITTED_SQL = f"""
(
    (split.workflow_mode = 'model_review_and_case_label' AND EXISTS (
        SELECT 1 FROM combined_review_progress progress
        WHERE progress.campaign_id = split.id
          AND progress.issue_id = assignment.issue_id
          AND lower(progress.reviewer) = lower(assignment.assignee)
          AND progress.model_review_submitted = true
          AND progress.case_label_acknowledged = true
    )) OR
    (split.workflow_mode <> 'model_review_and_case_label' AND EXISTS (
        SELECT 1 FROM model_review_heads head
        JOIN model_review_revisions revision ON revision.id = head.revision_id
        WHERE head.issue_id = assignment.issue_id
          AND head.model_run_id = split.model_run_id
          AND lower(head.reviewer) = lower(assignment.assignee)
          AND {MODEL_SUBMISSION_SQL}
          AND {MODEL_ASSIGNMENT_SCOPE_SQL}
    ))
)
"""


def combined_task_progress_ids(database, task_id, progress, assignees=()):
    """Read task delivery, never shared resolution or another author's head.

    With several selected owners, an Issue is complete only when all their
    assigned slots are complete. Pending and completed therefore partition it.
    """
    task_id = database.resolve_version_campaign(task_id)
    owners = sorted({str(owner).strip().lower() for owner in assignees if str(owner).strip()})
    with database.connect() as conn:
        task = conn.execute(
            "SELECT workflow_mode FROM issue_work_splits WHERE id=?", (task_id,)
        ).fetchone()
        if not task or task["workflow_mode"] != "model_review_and_case_label":
            raise ValueError("进度筛选仅支持联合复核任务 / Progress filtering requires a combined-review task")
        owner_where = ""
        args = [task_id]
        if owners:
            owner_where = " AND lower(assignment.assignee) IN (" + ",".join("?" for _ in owners) + ")"
            args.extend(owners)
        rows = conn.execute(
            "SELECT assignment.issue_id, "
            f"MIN(CASE WHEN {ASSIGNMENT_SUBMITTED_SQL} THEN 1 ELSE 0 END) AS submitted "
            "FROM review_work_assignments assignment "
            "JOIN issue_work_splits split ON split.id=assignment.split_id "
            "WHERE split.id=?" + owner_where + " GROUP BY assignment.issue_id",
            args,
        ).fetchall()
    return {row["issue_id"] for row in rows
            if ("completed" if row["submitted"] else "pending") in progress}


def legacy_batch_source(batch: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    """Use original display metadata only for a source from the same Run."""
    source_id = str(_json_load(batch["filter_json"], {}).get("source_legacy_split_id") or "")
    source = sources.get(source_id, {})
    if str(source.get("model_run_id") or "") != str(batch["model_run_id"] or ""):
        return {}
    return source


def assignment_snapshot_members(value: Any) -> list[dict[str, Any]]:
    """Normalize the original split payload for history/fallback views."""

    raw_members = _json_load(value, [])
    if not isinstance(raw_members, list):
        return []
    members: list[dict[str, Any]] = []
    for raw_member in raw_members:
        if not isinstance(raw_member, dict):
            continue
        name = str(raw_member.get("name") or "").strip()
        if not name:
            continue
        raw_items = raw_member.get("items")
        items: list[dict[str, Any]] = []
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                issue_id = str(raw_item.get("issue_id") or "").strip()
                if not issue_id:
                    continue
                items.append(
                    {
                        "issue_id": issue_id,
                        "assignment_kind": str(
                            raw_item.get("assignment_kind") or "base"
                        ),
                        "ordinal": int(raw_item.get("ordinal") or len(items) + 1),
                    }
                )
        if not items:
            items = [
                {
                    "issue_id": str(issue_id).strip(),
                    "assignment_kind": "base",
                    "ordinal": index,
                }
                for index, issue_id in enumerate(raw_member.get("issue_ids") or [], 1)
                if str(issue_id or "").strip()
            ]
        members.append(
            {
                "name": name,
                "count": len(items),
                "requested_count": raw_member.get("requested_count"),
                "mode": str(raw_member.get("mode") or "share"),
                "items": items,
            }
        )
    return members
