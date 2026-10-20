"""Read-only task projection of the exact Case votes acknowledged by Review."""
from collections import defaultdict


def is_combined_task(conn, task_id):
    return bool(task_id and conn.execute(
        "SELECT 1 FROM issue_work_splits WHERE id=? AND purpose='model_review' "
        "AND workflow_mode='model_review_and_case_label'", (task_id,),
    ).fetchone())


def combined_label_cases(database, conn, issue_ids, task_id):
    """Do not import free votes or a later, unacknowledged revision into a task."""
    result = {}
    for offset in range(0, len(issue_ids), 400):
        batch = issue_ids[offset:offset + 400]
        placeholders = ", ".join("?" for _ in batch)
        members = conn.execute(
            f"""SELECT member.issue_id, member.baseline_scope, issue.gt_label, issue.gt_source,
                       campaign.created_at
                FROM campaign_issue_members member
                JOIN issues issue ON issue.issue_id=member.issue_id
                JOIN issue_work_splits campaign ON campaign.id=member.campaign_id
                WHERE member.campaign_id=? AND member.issue_id IN ({placeholders})""",
            [task_id, *batch],
        ).fetchall()
        assignments = conn.execute(
            f"""SELECT issue_id, assignee FROM review_work_assignments
                WHERE split_id=? AND issue_id IN ({placeholders})""",
            [task_id, *batch],
        ).fetchall()
        rows = conn.execute(
            f"""SELECT revision.*, progress.issue_id, progress.submission_group_id
                FROM combined_review_progress progress
                JOIN review_work_assignments assignment
                  ON assignment.split_id=progress.campaign_id
                 AND assignment.issue_id=progress.issue_id
                 AND lower(assignment.assignee)=lower(progress.reviewer)
                JOIN label_revisions revision ON revision.id=progress.case_label_revision_id
                JOIN label_cases label_case ON label_case.id=revision.label_case_id
                WHERE progress.campaign_id=? AND progress.issue_id IN ({placeholders})
                  AND progress.model_review_submitted AND progress.case_label_acknowledged
                  AND lower(revision.author)=lower(progress.reviewer)
                  AND label_case.issue_id=progress.issue_id
                  AND NOT EXISTS (SELECT 1 FROM label_import_suppressed_revisions s
                                  WHERE s.revision_id=revision.id)""",
            [task_id, *batch],
        ).fetchall()
        assigned = defaultdict(list)
        heads = defaultdict(list)
        for row in assignments:
            assigned[str(row["issue_id"])].append(str(row["assignee"]).lower())
        for row in rows:
            vote = database._label_revision_dict(row)
            vote["submission_group_id"] = str(row["submission_group_id"])
            heads[str(row["issue_id"])].append(vote)
        for row in members:
            issue = str(row["issue_id"])
            result[issue] = [{
                "id": f"combined:{task_id}:{issue}",
                "baseline_scope": str(row["baseline_scope"]),
                "issue_id": issue, "task_id": task_id, "source_run_id": "",
                "seen_gt_label": str(row["gt_label"] or ""),
                "seen_gt_source": str(row["gt_source"] or ""),
                "created_at": str(row["created_at"]), "read_only": True,
                "resolution": database._resolve_loaded_label_case(
                    heads=heads[issue], assigned_authors=assigned[issue],
                    latest_resolution=None, result_revision=None,
                ),
            }]
    return result
