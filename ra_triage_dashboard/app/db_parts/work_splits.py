"""Work split, reviewer assignment, and multi-review query repository (Phase 2B)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from typing import Any, Iterable, Iterator, Sequence

from ..work_split import normalize_overlap_ratio
from ..gt_observations import TRAIL_GT_RAW_VALUES
from .task_lifecycle import task_lifecycle_where, task_reviewable
from .labeling_shared import matches_issue_label_states
from .assignment_rules import (
    ASSIGNMENT_SUBMITTED_SQL,
    MODEL_ASSIGNMENT_SCOPE_SQL,
    MODEL_SUBMISSION_SQL,
    legacy_batch_source,
    assignment_snapshot_members,
    pending_assignment_issue_ids,
)
from .model_reviews import MODEL_REVIEW_STATUSES, MODEL_REVIEW_PUBLIC_ID_OFFSET
from .shared import (
    COMPARISON_STATUSES,
    LABELS,
    MODEL_LABELS,
    _json,
    _json_load,
    model_label_matches_gt,
    model_prediction_match_sql,
    model_prediction_mismatch_sql,
    model_prediction_no_gt_sql,
    model_prediction_none_sql,
    utc_now,
)




class DatabaseWorkSplitsMixin:
    def _historical_overlap_conflicts(self, conn, campaign_ids):
        conflicts = {cid: [] for cid in campaign_ids}
        if not campaign_ids:
            return conflicts
        marks = ",".join("?" for _ in campaign_ids)
        candidates = conn.execute(f"""
            SELECT p.campaign_id, p.issue_id, m.baseline_scope
            FROM combined_review_progress p
            JOIN campaign_issue_members m ON m.campaign_id=p.campaign_id AND m.issue_id=p.issue_id
            JOIN review_work_assignments a ON a.split_id=p.campaign_id AND a.issue_id=p.issue_id
                 AND lower(a.assignee)=lower(p.reviewer)
            JOIN label_revisions r ON r.id=p.case_label_revision_id AND lower(r.author)=lower(p.reviewer)
            JOIN label_cases lc ON lc.id=r.label_case_id AND lc.issue_id=p.issue_id AND lc.baseline_scope=m.baseline_scope
            WHERE p.campaign_id IN ({marks}) AND p.model_review_submitted AND p.case_label_acknowledged
              AND NOT EXISTS (SELECT 1 FROM label_import_suppressed_revisions s WHERE s.revision_id=r.id)
            GROUP BY p.campaign_id, p.issue_id, m.baseline_scope
            HAVING COUNT(DISTINCT lower(p.reviewer)) > 1 AND COUNT(DISTINCT r.expected_output) > 1
            ORDER BY p.issue_id
        """, campaign_ids).fetchall()
        by_scope = defaultdict(list)
        for case in candidates:
            by_scope[case["baseline_scope"]].append(case)
        for scope, cases in by_scope.items():
            # The Review gallery includes stale decisions and honors the original label Case's adjudication.
            states = self.project_issue_label_states(scope, sorted({r["issue_id"] for r in cases}),
                                                     include_sources=False, connection=conn)
            for r in cases:
                if matches_issue_label_states(states.get(r["issue_id"], {}), ("conflict",)):
                    conflicts[r["campaign_id"]].append(r["issue_id"])
        return conflicts

    def list_work_assignees(
        self, *, issue_ids: Sequence[str] | None = None, model_run_id: str = ""
    ) -> list[dict[str, Any]]:
        """Distinct assignees, optionally scoped to an exact Review queue."""

        cleaned_ids = (
            list(
                dict.fromkeys(
                    str(issue_id or "").strip()
                    for issue_id in issue_ids
                    if str(issue_id or "").strip()
                )
            )
            if issue_ids is not None
            else None
        )
        if cleaned_ids == []:
            return []

        counts: dict[str, int] = {}
        with self.connect() as conn:
            if cleaned_ids is None:
                batches: list[list[str] | None] = [None]
            else:
                # Stay below conservative SQLite variable limits while using
                # the same query path through the PostgreSQL compatibility adapter.
                batches = [
                    cleaned_ids[offset : offset + 500]
                    for offset in range(0, len(cleaned_ids), 500)
                ]
            for batch in batches:
                issue_clause = ""
                params: list[Any] = []
                if batch is not None:
                    issue_clause = (
                        f"AND assignment.issue_id IN ({', '.join('?' for _ in batch)})"
                    )
                    params.extend(batch)
                rows = conn.execute(
                    f"""
                    SELECT assignment.assignee, COUNT(*) AS issue_count
                    FROM review_work_assignments assignment
                    JOIN issue_work_splits split ON split.id = assignment.split_id
                    WHERE assignment.assignee <> '' AND split.model_run_id = ?
                    {issue_clause}
                    GROUP BY assignment.assignee
                    ORDER BY assignment.assignee ASC
                    """,
                    (str(model_run_id or "").strip(), *params),
                ).fetchall()
                for row in rows:
                    username = str(row["assignee"] or "").strip()
                    if username:
                        counts[username] = counts.get(username, 0) + int(
                            row["issue_count"] or 0
                        )
        return [
            {"username": username, "issue_count": counts[username]}
            for username in sorted(counts)
        ]

    _work_split_snapshot_members = staticmethod(assignment_snapshot_members)

    def list_review_work_splits(
        self, *, limit: int = 50, model_run_id: str = "", assignee: str = "",
        lifecycle: str = "current", split_id: str = "",
        issue_ids: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        """Return assignment batches with current completion statistics."""

        safe_limit = max(1, min(int(limit or 50), 100))
        run_id = str(model_run_id or "").strip()
        lifecycle_clause, parameters = task_lifecycle_where(lifecycle, include_archived=bool(split_id))
        where = "WHERE split.task_kind != 'labeling' AND " + lifecycle_clause
        if split_id:
            where += " AND split.id = ?"
            parameters.append(str(split_id).strip())
        if assignee:
            where += " AND EXISTS (SELECT 1 FROM review_work_assignments mine WHERE mine.split_id=split.id AND lower(mine.assignee)=lower(?))"
            parameters.append(str(assignee).strip())
        if run_id:
            where += " AND split.model_run_id = ?"
            parameters.append(run_id)
        if issue_ids:
            where += " AND EXISTS (SELECT 1 FROM review_work_assignments selected "
            where += "WHERE selected.split_id=split.id AND selected.issue_id IN (" + ",".join("?" for _ in issue_ids) + "))"
            parameters.extend(issue_ids)
        with self.connect() as conn:
            split_rows = conn.execute(
                f"""
                SELECT split.*,
                       COALESCE(current.assignment_count, 0) AS current_assignment_count,
                       COALESCE(current.issue_count, 0) AS current_issue_count
                FROM issue_work_splits split
                LEFT JOIN (
                    SELECT split_id,
                           COUNT(*) AS assignment_count,
                           COUNT(DISTINCT issue_id) AS issue_count
                    FROM review_work_assignments
                    GROUP BY split_id
                ) current ON current.split_id = split.id
                {where}
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT ?
                """,
                (*parameters, safe_limit),
            ).fetchall()
            if not split_rows:
                return []

            # Migrated campaigns retain their creation audit; display the original
            # batch's timestamp, creator and frozen selection through provenance.
            source_ids = {
                str(_json_load(row["filter_json"], {}).get("source_legacy_split_id") or "")
                for row in split_rows
            } - {""}
            source_rows = conn.execute(
                f"SELECT * FROM issue_work_splits WHERE id IN ({', '.join('?' for _ in source_ids)})",
                sorted(source_ids),
            ).fetchall() if source_ids else []
            sources_by_id = {str(source["id"]): dict(source) for source in source_rows}
            historical_conflicts = self._historical_overlap_conflicts(conn, [
                row["id"] for row in split_rows if row["workflow_mode"] == "model_review_and_case_label"
                and task_reviewable(row) and (
                    legacy_batch_source(row, sources_by_id)
                    or _json_load(row["filter_json"], {}).get("merged_review_sources")
                )
            ])
            historical_pending = pending_assignment_issue_ids(conn, list(historical_conflicts))
            split_ids = [str(row["id"]) for row in split_rows]
            filters_by_split = {
                str(row["id"]): _json_load(row["filter_json"], {}) for row in split_rows
            }
            grouped_split_ids = [
                split_id for split_id, filters in filters_by_split.items()
                if isinstance(filters, dict) and (filters.get("task_allocation") or {}).get("groups")
            ]
            placeholders = ", ".join("?" for _ in split_ids)
            scope_rows = conn.execute(
                f"""SELECT DISTINCT assignment.split_id, issue.baseline_scope
                    FROM review_work_assignments assignment
                    JOIN issues issue ON issue.issue_id = assignment.issue_id
                    WHERE assignment.split_id IN ({placeholders})
                    ORDER BY assignment.split_id, issue.baseline_scope""",
                split_ids,
            ).fetchall()
            scopes_by_split: dict[str, list[str]] = {}
            for scope_row in scope_rows:
                if scope_row["baseline_scope"]:
                    scopes_by_split.setdefault(str(scope_row["split_id"]), []).append(str(scope_row["baseline_scope"]))
            progress_rows = conn.execute(
                f"""
                SELECT assignment.split_id,
                       assignment.assignee,
                       COUNT(*) AS assigned_count,
                       SUM(CASE WHEN {ASSIGNMENT_SUBMITTED_SQL} THEN 1 ELSE 0 END) AS completed_count
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                WHERE assignment.split_id IN ({placeholders})
                GROUP BY assignment.split_id, assignment.assignee
                ORDER BY assignment.split_id, assignment.assignee
                """,
                split_ids,
            ).fetchall()
            completed_group_slots = defaultdict(set)
            if grouped_split_ids:
                grouped_marks = ", ".join("?" for _ in grouped_split_ids)
                for slot in conn.execute(
                    f"""
                    SELECT assignment.split_id, assignment.issue_id, assignment.assignee
                    FROM review_work_assignments assignment
                    JOIN issue_work_splits split ON split.id = assignment.split_id
                    WHERE assignment.split_id IN ({grouped_marks}) AND ({ASSIGNMENT_SUBMITTED_SQL})
                    """,
                    grouped_split_ids,
                ).fetchall():
                    completed_group_slots[slot["split_id"]].add((slot["issue_id"], slot["assignee"]))
            change_rows = conn.execute(
                f"""
                SELECT split_id, COUNT(*) AS change_count
                FROM review_work_assignment_changes
                WHERE split_id IN ({placeholders})
                GROUP BY split_id
                """,
                split_ids,
            ).fetchall()
            historical_progress: dict[str, list[dict[str, Any]]] = {}
            for split in split_rows:
                if int(split["current_assignment_count"] or 0) > 0:
                    continue
                split_id = str(split["id"])
                snapshot_members = self._work_split_snapshot_members(
                    split["assignees_json"]
                )
                for member in snapshot_members:
                    issue_ids = list(
                        dict.fromkeys(
                            str(item["issue_id"])
                            for item in member.get("items") or []
                            if str(item.get("issue_id") or "").strip()
                        )
                    )
                    completed_ids: set[str] = set()
                    for offset in range(0, len(issue_ids), 500):
                        batch = issue_ids[offset : offset + 500]
                        if not batch:
                            continue
                        batch_placeholders = ", ".join("?" for _ in batch)
                        work_split_clause = (
                            "annotation.work_split_id = ?"
                            if str(split["mode"] or "") == "blind"
                            else "annotation.work_split_id = ''"
                        )
                        query_parameters: list[Any] = [
                            str(split["model_run_id"] or ""),
                            str(member["name"]),
                        ]
                        if str(split["mode"] or "") == "blind":
                            query_parameters.append(split_id)
                        query_parameters.extend(batch)
                        rows = conn.execute(
                            f"""
                            SELECT DISTINCT head.issue_id
                            FROM model_review_heads head
                            JOIN model_review_revisions revision ON revision.id = head.revision_id
                            WHERE head.model_run_id = ?
                              AND lower(head.reviewer) = lower(?)
                              AND {MODEL_SUBMISSION_SQL}
                              AND {work_split_clause.replace('annotation.work_split_id', 'revision.work_split_id')}
                              AND head.issue_id IN ({batch_placeholders})
                            """,
                            query_parameters,
                        ).fetchall()
                        completed_ids.update(str(item["issue_id"]) for item in rows)
                    historical_progress.setdefault(split_id, []).append(
                        {
                            "username": str(member["name"]),
                            "assigned_count": len(issue_ids),
                            "completed_count": len(completed_ids),
                        }
                    )

        progress_by_split: dict[str, list[dict[str, Any]]] = {}
        for row in progress_rows:
            split_id = str(row["split_id"])
            progress_by_split.setdefault(split_id, []).append(
                {
                    "username": str(row["assignee"] or ""),
                    "assigned_count": int(row["assigned_count"] or 0),
                    "completed_count": int(row["completed_count"] or 0),
                }
            )
        changes_by_split = {
            str(row["split_id"]): int(row["change_count"] or 0)
            for row in change_rows
        }
        result: list[dict[str, Any]] = []
        for row in split_rows:
            split_id = str(row["id"])
            source = legacy_batch_source(row, sources_by_id)
            snapshot_members = self._work_split_snapshot_members(
                source.get("assignees_json") or row["assignees_json"]
            )
            snapshot_by_name = {
                str(item["name"]): item for item in snapshot_members
            }
            current_members = progress_by_split.get(split_id, [])
            if not current_members:
                current_members = historical_progress.get(split_id, [])
            current_by_name = {item["username"]: item for item in current_members}
            member_names = [item["name"] for item in snapshot_members]
            member_names.extend(
                item["username"]
                for item in current_members
                if item["username"] not in member_names
            )
            members: list[dict[str, Any]] = []
            for name in member_names:
                current = current_by_name.get(name, {})
                snapshot = snapshot_by_name.get(name, {})
                assigned_count = int(
                    current.get("assigned_count")
                    or snapshot.get("count")
                    or 0
                )
                completed_count = int(current.get("completed_count") or 0)
                members.append(
                    {
                        "username": name,
                        "assigned_count": assigned_count,
                        "completed_count": completed_count,
                        "pending_count": max(0, assigned_count - completed_count),
                        "requested_count": snapshot.get("requested_count"),
                        "completion_ratio": (
                            round(completed_count / assigned_count, 4)
                            if assigned_count
                            else 0.0
                        ),
                    }
                )
            current_assignment_count = int(row["current_assignment_count"] or 0)
            current_issue_count = int(row["current_issue_count"] or 0)
            assignment_count = int(row["assignment_count"] or 0) or current_assignment_count
            total_count = int(row["total_count"] or 0) or current_issue_count
            completed_count = sum(item["completed_count"] for item in members)
            filter_snapshot = filters_by_split[split_id]
            alloc_groups = ((filter_snapshot.get("task_allocation") or {}).get("groups") or []) if isinstance(filter_snapshot, dict) else []
            if alloc_groups:
                active_slots = [
                    (issue_id, owner) for grp in alloc_groups
                    for issue_id, owner in (grp.get("assignments") or {}).items() if owner
                ]
                active_by_person = Counter(owner for _, owner in active_slots)
                if active_by_person:
                    submitted = completed_group_slots[split_id]
                    active_completed = Counter(owner for issue_id, owner in active_slots if (issue_id, owner) in submitted)
                    norm_members = []
                    for item in members:
                        uname = item["username"]
                        act = active_by_person.get(uname, 0)
                        comp = item["completed_count"]
                        if act == 0 and comp == 0:
                            continue
                        done = active_completed[uname]
                        norm_members.append({
                            **item,
                            "assigned_count": act,
                            "pending_count": act - done,
                            "extra_completed_count": max(0, comp - done),
                            "completion_ratio": round(done / act, 4) if act else 0.0,
                        })
                    members = norm_members
                    assignment_count = total_count if len(alloc_groups) == 1 else sum(active_by_person.values())
                    completed_count = min(
                        assignment_count,
                        sum(active_completed.values()) + (
                            max(0, total_count - sum(active_by_person.values())) if len(alloc_groups) == 1 else 0
                        ),
                    )
            result.append(
                {
                    "split_id": split_id,
                    "created_by": str(row["created_by"] or ""),
                    **({"conflict_count": len(historical_conflicts[split_id]),
                        "pending_issue_ids": historical_pending[split_id],
                        "conflict_issue_ids": historical_conflicts[split_id]} if split_id in historical_conflicts else {}),
                    "created_at": str(row["created_at"] or ""),
                    "campaign_name": str(row["campaign_name"] or ""),
                    "legacy_read_only": bool(row["legacy_read_only"]),
                    "purpose": str(row["purpose"] or ""),
                    "lifecycle": str(row["lifecycle"] or ""),
                    "source_split_id": str(source.get("id") or ""),
                    "source_created_at": str(source.get("created_at") or ""),
                    "source_created_by": str(source.get("created_by") or ""),
                    "source_filter_snapshot": _json_load(source.get("filter_json"), {}) if source else None,
                    "seed": row["seed"],
                    "total_count": total_count,
                    "assignment_count": assignment_count,
                    **(dict(allocation_group_count=len(alloc_groups)) if alloc_groups else {}),
                    "mode": str(row["mode"] or "single"),
                    "reviewers_per_issue": int(row["reviewers_per_issue"] or 1),
                    "model_run_id": str(row["model_run_id"] or ""),
                    "workflow_mode": str(row["workflow_mode"] or "model_review_only"),
                    "overlap_ratio": float(row["overlap_ratio"] or 0),
                    "filter_snapshot": filter_snapshot,
                    "baseline_scopes": scopes_by_split.get(split_id, []),
                    "members": members,
                    "completed_count": completed_count,
                    "pending_count": max(0, assignment_count - completed_count),
                    "completion_ratio": (
                        round(completed_count / assignment_count, 4)
                        if assignment_count
                        else 0.0
                    ),
                    "change_count": changes_by_split.get(split_id, 0),
                    "is_current": current_assignment_count > 0 and task_reviewable(row),
                }
            )
        return result

    def get_review_work_split(
        self,
        split_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        assignee: str = "",
        status: str = "all",
        query: str = "",
    ) -> dict[str, Any] | None:
        """Return one split and a paginated task/progress detail."""

        normalized_split_id = self.resolve_version_campaign(str(split_id or "").strip())
        if not normalized_split_id:
            return None
        normalized_status = str(status or "all").strip().lower()
        if normalized_status not in {"all", "completed", "pending"}:
            raise ValueError("任务状态筛选不合法。")
        safe_page = max(1, int(page or 1))
        safe_page_size = max(10, min(int(page_size or 50), 100))
        normalized_assignee = str(assignee or "").strip().lower()
        normalized_query = str(query or "").strip()[:128]
        submitted_condition = ASSIGNMENT_SUBMITTED_SQL
        conditions = ["assignment.split_id = ?"]
        parameters: list[Any] = [normalized_split_id]
        if normalized_assignee:
            conditions.append("assignment.assignee = ?")
            parameters.append(normalized_assignee)
        if normalized_query:
            like = f"%{normalized_query}%"
            conditions.append("(assignment.issue_id LIKE ? OR issue.title LIKE ? OR issue.scenario LIKE ?)")
            parameters.extend([like, like, like])
        if normalized_status == "completed":
            conditions.append(submitted_condition)
        elif normalized_status == "pending":
            conditions.append(f"NOT ({submitted_condition})")
        where = " AND ".join(conditions)
        with self.connect() as conn:
            split = conn.execute(
                "SELECT * FROM issue_work_splits WHERE id = ?",
                (normalized_split_id,),
            ).fetchone()
            if split is None:
                return None
            from_sql = """
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                JOIN issues issue ON issue.issue_id = assignment.issue_id
            """
            total_row = conn.execute(
                f"SELECT COUNT(*) AS count {from_sql} WHERE {where}",
                parameters,
            ).fetchone()
            offset = (safe_page - 1) * safe_page_size
            item_rows = conn.execute(
                f"""
                SELECT assignment.issue_id,
                       assignment.assignee,
                       assignment.assignment_kind,
                       assignment.ordinal,
                       COALESCE((
                           SELECT progress.model_review_submitted
                           FROM combined_review_progress progress
                           WHERE progress.campaign_id=assignment.split_id
                             AND progress.issue_id=assignment.issue_id
                             AND lower(progress.reviewer)=lower(assignment.assignee)
                       ), false) AS model_review_submitted,
                       COALESCE((
                           SELECT progress.case_label_acknowledged
                           FROM combined_review_progress progress
                           WHERE progress.campaign_id=assignment.split_id
                             AND progress.issue_id=assignment.issue_id
                             AND lower(progress.reviewer)=lower(assignment.assignee)
                       ), false) AS case_label_acknowledged,
                       assignment.assigned_by,
                       assignment.assigned_at,
                       issue.title,
                       issue.scenario,
                       issue.gt_label,
                       issue.baseline_scope,
                       COALESCE((
                           SELECT progress.model_review_submitted
                           FROM combined_review_progress progress
                           WHERE progress.campaign_id=split.id
                             AND progress.issue_id=assignment.issue_id
                             AND lower(progress.reviewer)=lower(assignment.assignee)
                       ), false) AS model_review_submitted,
                       COALESCE((
                           SELECT progress.case_label_acknowledged
                           FROM combined_review_progress progress
                           WHERE progress.campaign_id=split.id
                             AND progress.issue_id=assignment.issue_id
                             AND lower(progress.reviewer)=lower(assignment.assignee)
                       ), false) AS case_label_acknowledged,
                       CASE WHEN {submitted_condition} THEN 1 ELSE 0 END AS submitted,
                       (
                           SELECT revision.created_at
                           FROM model_review_heads head
                           JOIN model_review_revisions revision ON revision.id = head.revision_id
                           WHERE head.issue_id = assignment.issue_id
                             AND head.model_run_id = split.model_run_id
                             AND lower(head.reviewer) = lower(assignment.assignee)
                             AND {MODEL_SUBMISSION_SQL}
                             AND {MODEL_ASSIGNMENT_SCOPE_SQL}
                           ORDER BY revision.id DESC LIMIT 1
                       ) AS submitted_at,
                       (
                       SELECT annotation.review_status
                           FROM review_records annotation
                           WHERE annotation.issue_id = assignment.issue_id
                             AND annotation.model_run_id = split.model_run_id
                             AND annotation.author = assignment.assignee
                             AND (
                               (split.mode = 'blind' AND annotation.work_split_id = assignment.split_id)
                               OR (split.mode <> 'blind' AND annotation.work_split_id = '')
                             )
                           ORDER BY annotation.id DESC
                           LIMIT 1
                       ) AS review_status,
                       (
                           SELECT revision.status
                           FROM model_review_heads head
                           JOIN model_review_revisions revision ON revision.id = head.revision_id
                           WHERE head.issue_id = assignment.issue_id
                             AND head.model_run_id = split.model_run_id
                             AND lower(head.reviewer) = lower(assignment.assignee)
                             AND {MODEL_ASSIGNMENT_SCOPE_SQL}
                           ORDER BY revision.id DESC LIMIT 1
                       ) AS model_review_status
                {from_sql}
                WHERE {where}
                ORDER BY assignment.assignee ASC, assignment.ordinal ASC, assignment.issue_id ASC
                LIMIT ? OFFSET ?
                """,
                (*parameters, safe_page_size, offset),
            ).fetchall()
            change_rows = conn.execute(
                """
                SELECT id, issue_id, from_assignee, to_assignee, changed_by, changed_at
                FROM review_work_assignment_changes
                WHERE split_id = ?
                ORDER BY changed_at DESC, id DESC
                LIMIT 100
                """,
                (normalized_split_id,),
            ).fetchall()
        total = int(total_row["count"] or 0)
        items = [
            {
                "issue_id": str(row["issue_id"]),
                "assignee": str(row["assignee"]),
                "assignment_kind": str(row["assignment_kind"] or "base"),
                "ordinal": int(row["ordinal"] or 1),
                "assigned_by": str(row["assigned_by"] or ""),
                "assigned_at": str(row["assigned_at"] or ""),
                "title": str(row["title"] or ""),
                "scenario": str(row["scenario"] or ""),
                "gt_label": str(row["gt_label"] or ""),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "submitted": bool(row["submitted"]),
                "submitted_at": str(row["submitted_at"] or ""),
                "review_status": str(row["review_status"] or ""),
                "model_review_status": str(row["model_review_status"] or ""),
                "model_review_submitted": bool(row["model_review_submitted"]),
                "case_label_acknowledged": bool(row["case_label_acknowledged"]),
            }
            for row in item_rows
        ]
        changes = [
            {
                "id": int(row["id"]),
                "issue_id": str(row["issue_id"]),
                "from_assignee": str(row["from_assignee"]),
                "to_assignee": str(row["to_assignee"]),
                "changed_by": str(row["changed_by"]),
                "changed_at": str(row["changed_at"]),
            }
            for row in change_rows
        ]
        snapshot_members = self._work_split_snapshot_members(split["assignees_json"])
        current_assignment_count = 0
        current_issue_count = 0
        with self.connect() as conn:
            current = conn.execute(
                """
                SELECT COUNT(*) AS assignment_count, COUNT(DISTINCT issue_id) AS issue_count
                FROM review_work_assignments
                WHERE split_id = ?
                """,
                (normalized_split_id,),
            ).fetchone()
            if current:
                current_assignment_count = int(current["assignment_count"] or 0)
                current_issue_count = int(current["issue_count"] or 0)
        if not item_rows and current_assignment_count == 0 and snapshot_members:
            snapshot_issue_ids = list(
                dict.fromkeys(
                    str(assignment["issue_id"])
                    for member in snapshot_members
                    for assignment in member.get("items") or []
                    if str(assignment.get("issue_id") or "").strip()
                )
            )
            issue_by_id: dict[str, dict[str, Any]] = {}
            annotation_by_key: dict[tuple[str, str], dict[str, Any]] = {}
            with self.connect() as conn:
                for offset in range(0, len(snapshot_issue_ids), 500):
                    batch = snapshot_issue_ids[offset : offset + 500]
                    if not batch:
                        continue
                    batch_placeholders = ", ".join("?" for _ in batch)
                    issue_rows = conn.execute(
                        f"""
                        SELECT issue_id, title, scenario, gt_label, baseline_scope
                        FROM issues
                        WHERE issue_id IN ({batch_placeholders})
                        """,
                        batch,
                    ).fetchall()
                    for row in issue_rows:
                        issue_by_id[str(row["issue_id"])] = {
                            "title": str(row["title"] or ""),
                            "scenario": str(row["scenario"] or ""),
                            "gt_label": str(row["gt_label"] or ""),
                            "baseline_scope": str(row["baseline_scope"] or ""),
                        }
                    annotation_work_split = (
                        "annotation.work_split_id = ?"
                        if str(split["mode"] or "") == "blind"
                        else "annotation.work_split_id = ''"
                    )
                    annotation_parameters: list[Any] = [
                        str(split["model_run_id"] or "")
                    ]
                    if str(split["mode"] or "") == "blind":
                        annotation_parameters.append(normalized_split_id)
                    annotation_parameters.extend(batch)
                    annotation_rows = conn.execute(
                        f"""
                        SELECT annotation.issue_id, annotation.author, annotation.id,
                               annotation.created_at, annotation.review_status,
                               annotation.review_domain, annotation.model_review_status,
                               EXISTS (SELECT 1 FROM model_review_revisions migrated
                                       WHERE migrated.id = annotation.id - {MODEL_REVIEW_PUBLIC_ID_OFFSET}
                                         AND migrated.legacy_annotation_id IS NOT NULL) AS legacy_submitted
                        FROM review_records annotation
                        WHERE annotation.model_run_id = ?
                          AND {annotation_work_split}
                          AND annotation.issue_id IN ({batch_placeholders})
                        ORDER BY annotation.id DESC
                        """,
                        annotation_parameters,
                    ).fetchall()
                    for row in annotation_rows:
                        key = (str(row["issue_id"]), str(row["author"] or ""))
                        annotation_by_key.setdefault(
                            key,
                            {
                                "created_at": str(row["created_at"] or ""),
                                "review_status": str(row["review_status"] or ""),
                                "review_domain": str(row["review_domain"] or "legacy"),
                                "model_review_status": str(row["model_review_status"] or ""),
                                "legacy_submitted": bool(row["legacy_submitted"]),
                            },
                        )
            snapshot_rows: list[dict[str, Any]] = []
            for member in snapshot_members:
                member_name = str(member["name"])
                for assignment in member.get("items") or []:
                    assignment_issue_id = str(assignment["issue_id"])
                    issue = issue_by_id.get(assignment_issue_id, {})
                    annotation = annotation_by_key.get((assignment_issue_id, member_name))
                    completed = bool(
                        annotation
                        and annotation.get("review_domain") == "model_review"
                        and (annotation.get("model_review_status") == "completed" or annotation.get("legacy_submitted"))
                    )
                    row = {
                        "issue_id": assignment_issue_id,
                        "assignee": member_name,
                        "assignment_kind": str(
                            assignment.get("assignment_kind") or "base"
                        ),
                        "ordinal": int(assignment.get("ordinal") or 1),
                        "assigned_by": str(split["created_by"] or ""),
                        "assigned_at": str(split["created_at"] or ""),
                        "title": str(issue.get("title") or ""),
                        "scenario": str(issue.get("scenario") or ""),
                        "gt_label": str(issue.get("gt_label") or ""),
                        "baseline_scope": str(issue.get("baseline_scope") or ""),
                        "submitted": completed,
                        "submitted_at": str((annotation or {}).get("created_at") or "") if completed else "",
                        "review_status": str((annotation or {}).get("review_status") or ""),
                        "model_review_status": str((annotation or {}).get("model_review_status") or ""),
                    }
                    if normalized_assignee and member_name.lower() != normalized_assignee:
                        continue
                    if normalized_query:
                        haystack = " ".join(
                            [assignment_issue_id, row["title"], row["scenario"]]
                        ).casefold()
                        if normalized_query.casefold() not in haystack:
                            continue
                    if normalized_status == "completed" and not row["submitted"]:
                        continue
                    if normalized_status == "pending" and row["submitted"]:
                        continue
                    snapshot_rows.append(row)
            snapshot_rows.sort(
                key=lambda item: (
                    item["assignee"],
                    item["ordinal"],
                    item["issue_id"],
                )
            )
            total = len(snapshot_rows)
            items = snapshot_rows[offset : offset + safe_page_size]
        summary = next(
            (
                item
                for item in self.list_review_work_splits(limit=1, lifecycle="all", split_id=normalized_split_id)
                if item["split_id"] == normalized_split_id
            ),
            None,
        )
        if summary is None:
            summary = {
                "members": [
                    {
                        "username": str(item["name"]),
                        "assigned_count": int(item.get("count") or 0),
                        "completed_count": 0,
                        "pending_count": int(item.get("count") or 0),
                        "requested_count": item.get("requested_count"),
                        "completion_ratio": 0.0,
                    }
                    for item in snapshot_members
                ],
                "completed_count": 0,
                "pending_count": int(split["assignment_count"] or 0),
                "completion_ratio": 0.0,
                "change_count": len(changes),
                "is_current": current_assignment_count > 0 and task_reviewable(split),
            }
        return {
            "split_id": normalized_split_id,
            "lifecycle": str(split["lifecycle"] or "active"),
            "campaign_name": str(split["campaign_name"] or ""),
            "legacy_read_only": bool(split["legacy_read_only"]),
            "created_by": str(split["created_by"] or ""),
            "created_at": str(split["created_at"] or ""),
            "seed": split["seed"],
            "total_count": int(split["total_count"] or 0) or current_issue_count,
            "assignment_count": int(split["assignment_count"] or 0) or current_assignment_count,
            "mode": str(split["mode"] or "single"),
            "reviewers_per_issue": int(split["reviewers_per_issue"] or 1),
            "model_run_id": str(split["model_run_id"] or ""),
            "workflow_mode": str(split["workflow_mode"] or "model_review_only"),
            "purpose": str(split["purpose"] or ""),
            "overlap_ratio": float(split["overlap_ratio"] or 0),
            "filter_snapshot": _json_load(split["filter_json"], {}),
            "baseline_scopes": summary.get("baseline_scopes", []),
            "members": summary.get("members", []),
            "completed_count": int(summary.get("completed_count") or 0),
            "pending_count": int(summary.get("pending_count") or 0),
            "completion_ratio": float(summary.get("completion_ratio") or 0),
            "change_count": int(summary.get("change_count") or len(changes)),
            "is_current": bool(summary.get("is_current")),
            "changes": changes,
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "page_count": max(1, (total + safe_page_size - 1) // safe_page_size),
            "filters": {
                "assignee": normalized_assignee,
                "status": normalized_status,
                "q": normalized_query,
            },
        }

    def reassign_review_work_assignment(
        self,
        *,
        split_id: str,
        issue_id: str,
        assignee: str,
        changed_by: str,
    ) -> dict[str, Any]:
        """Transfer one unfinished task and retain a change audit row."""

        normalized_split_id = str(split_id or "").strip()
        normalized_issue_id = str(issue_id or "").strip()
        normalized_assignee = str(assignee or "").strip().lower()
        actor = str(changed_by or "").strip()
        if not normalized_split_id or not normalized_issue_id:
            raise ValueError("任务分配标识不能为空。")
        if not normalized_assignee:
            raise ValueError("新负责人不能为空。")
        if not actor:
            raise ValueError("任务调整人不能为空。")
        # Canonical tasks use the same saved-work guard and audit as the editor.
        with self.connect() as conn:
            canonical = conn.execute("SELECT purpose,config_revision FROM issue_work_splits WHERE id=?",
                                     (normalized_split_id,)).fetchone()
            source = conn.execute("SELECT assignee,assignment_kind FROM review_work_assignments "
                                  "WHERE split_id=? AND issue_id=? ORDER BY ordinal,assignee LIMIT 1",
                                  (normalized_split_id, normalized_issue_id)).fetchone()
        if canonical and canonical["purpose"] and source:
            if source["assignee"] == normalized_assignee:
                return dict(split_id=normalized_split_id, issue_id=normalized_issue_id, changed=False)
            result = self.update_campaign_assignment(
                campaign_id=normalized_split_id, issue_id=normalized_issue_id, action="reassign",
                from_assignee=source["assignee"], assignee=normalized_assignee,
                assignment_kind=source["assignment_kind"], actor=actor,
                expected_revision=canonical["config_revision"],
                idempotency_key=f"legacy-reassign-{uuid.uuid4().hex}",
            )
            return {**result, "split_id": normalized_split_id,
                    "from_assignee": source["assignee"], "to_assignee": normalized_assignee}
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            split = conn.execute(
                "SELECT * FROM issue_work_splits WHERE id = ?",
                (normalized_split_id,),
            ).fetchone()
            if split is None:
                raise ValueError("分配批次不存在。")
            current = conn.execute(
                """
                SELECT assignee, assignment_kind, ordinal
                FROM review_work_assignments
                WHERE split_id = ? AND issue_id = ?
                ORDER BY ordinal ASC, assignee ASC
                LIMIT 1
                """,
                (normalized_split_id, normalized_issue_id),
            ).fetchone()
            if current is None:
                raise ValueError("当前分配批次中找不到这条任务；它可能已被后续分配覆盖。")
            old_assignee = str(current["assignee"] or "").strip().lower()
            if old_assignee == normalized_assignee:
                return {
                    "split_id": normalized_split_id,
                    "issue_id": normalized_issue_id,
                    "changed": False,
                }
            duplicate = conn.execute(
                """
                SELECT 1 FROM review_work_assignments
                WHERE split_id = ? AND issue_id = ? AND assignee = ?
                LIMIT 1
                """,
                (normalized_split_id, normalized_issue_id, normalized_assignee),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("该 Issue 已经分配给目标负责人。")
            submitted = conn.execute(
                """
                SELECT annotation.id
                FROM review_records annotation
                WHERE annotation.issue_id = ?
                  AND annotation.model_run_id = ?
                  AND annotation.author = ?
                  AND (
                    ( ? = 'blind' AND annotation.work_split_id = ? )
                    OR ( ? <> 'blind' AND annotation.work_split_id = '' )
                  )
                ORDER BY annotation.id DESC
                LIMIT 1
                """,
                (
                    normalized_issue_id,
                    str(split["model_run_id"] or ""),
                    old_assignee,
                    str(split["mode"] or "single"),
                    normalized_split_id,
                    str(split["mode"] or "single"),
                ),
            ).fetchone()
            if submitted is not None:
                raise ValueError("已提交的 Review 不能直接转派；请保留原记录后再新建分配。")
            next_ordinal = conn.execute(
                """
                SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal
                FROM review_work_assignments
                WHERE split_id = ? AND assignee = ?
                """,
                (normalized_split_id, normalized_assignee),
            ).fetchone()
            now = utc_now()
            conn.execute(
                """
                UPDATE review_work_assignments
                SET assignee = ?, ordinal = ?, assigned_by = ?, assigned_at = ?
                WHERE split_id = ? AND issue_id = ? AND assignee = ?
                """,
                (
                    normalized_assignee,
                    int(next_ordinal["ordinal"] or 1),
                    actor,
                    now,
                    normalized_split_id,
                    normalized_issue_id,
                    old_assignee,
                ),
            )
            conn.execute(
                """
                INSERT INTO review_work_assignment_changes (
                    split_id, issue_id, from_assignee, to_assignee, changed_by, changed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_split_id,
                    normalized_issue_id,
                    old_assignee,
                    normalized_assignee,
                    actor,
                    now,
                ),
            )
            rows = conn.execute(
                """
                SELECT assignee, assignment_kind, ordinal, issue_id
                FROM review_work_assignments
                WHERE split_id = ?
                ORDER BY assignee ASC, ordinal ASC, issue_id ASC
                """,
                (normalized_split_id,),
            ).fetchall()
            previous = {
                str(item["name"]): item
                for item in self._work_split_snapshot_members(split["assignees_json"])
            }
            groups: dict[str, dict[str, Any]] = {}
            order: list[str] = []
            for row in rows:
                name = str(row["assignee"] or "").strip()
                if not name:
                    continue
                if name not in groups:
                    old = previous.get(name, {})
                    groups[name] = {
                        "name": name,
                        "count": 0,
                        "requested_count": old.get("requested_count"),
                        "mode": old.get("mode") or (
                            "blind" if str(split["mode"] or "") == "blind" else "share"
                        ),
                        "issue_ids": [],
                        "items": [],
                    }
                    order.append(name)
                group = groups[name]
                item = {
                    "issue_id": str(row["issue_id"]),
                    "assignment_kind": str(row["assignment_kind"] or "base"),
                    "ordinal": int(row["ordinal"] or 1),
                }
                group["items"].append(item)
                group["issue_ids"].append(item["issue_id"])
                group["count"] += 1
            snapshot = [groups[name] for name in order]
            conn.execute(
                """
                UPDATE issue_work_splits
                SET assignees_json = ?, total_count = ?, assignment_count = ?
                WHERE id = ?
                """,
                (
                    _json(snapshot),
                    len({str(row["issue_id"]) for row in rows}),
                    len(rows),
                    normalized_split_id,
                ),
            )
        return {
            "split_id": normalized_split_id,
            "issue_id": normalized_issue_id,
            "from_assignee": old_assignee,
            "to_assignee": normalized_assignee,
            "changed": True,
        }

    def review_assignment_context(
        self,
        issue_id: str,
        *,
        model_run_id: str = "",
        username: str = "",
        work_split_id: str = "",
    ) -> dict[str, Any] | None:
        """Return the current assignment snapshot for one Issue/Run."""

        work_split_id=self.resolve_version_campaign(work_split_id)
        with self.connect() as conn:
            normalized_split_id = str(work_split_id or "").strip()
            split_condition = "AND split.id = ?" if normalized_split_id else ""
            split_parameters: tuple[Any, ...] = (
                (str(issue_id or "").strip(), str(model_run_id or "").strip(), normalized_split_id)
                if normalized_split_id
                else (str(issue_id or "").strip(), str(model_run_id or "").strip())
            )
            split = conn.execute(
                f"""
                SELECT split.*
                FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                WHERE assignment.issue_id = ? AND split.model_run_id = ?
                  {split_condition}
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT 1
                """,
                split_parameters,
            ).fetchone()
            if split is None:
                return None
            rows = conn.execute(
                f"""
                SELECT assignment.assignee, assignment.assignment_kind,
                       assignment.ordinal,
                       COALESCE((
                           SELECT progress.model_review_submitted
                           FROM combined_review_progress progress
                           WHERE progress.campaign_id=assignment.split_id
                             AND progress.issue_id=assignment.issue_id
                             AND lower(progress.reviewer)=lower(assignment.assignee)
                       ), false) AS model_review_submitted,
                       COALESCE((
                           SELECT progress.case_label_acknowledged
                           FROM combined_review_progress progress
                           WHERE progress.campaign_id=assignment.split_id
                             AND progress.issue_id=assignment.issue_id
                             AND lower(progress.reviewer)=lower(assignment.assignee)
                       ), false) AS case_label_acknowledged,
                       (
                           SELECT revision.id FROM model_review_heads head
                           JOIN model_review_revisions revision ON revision.id = head.revision_id
                           WHERE head.issue_id = assignment.issue_id
                             AND head.model_run_id = ?
                             AND revision.work_split_id = assignment.split_id
                             AND lower(head.reviewer) = lower(assignment.assignee)
                             AND {MODEL_SUBMISSION_SQL}
                           ORDER BY revision.id DESC LIMIT 1
                       ) AS annotation_id
                FROM review_work_assignments assignment
                WHERE assignment.issue_id = ? AND assignment.split_id = ?
                ORDER BY assignment.assignee ASC
                """,
                (str(model_run_id or "").strip(), issue_id, split["id"]),
            ).fetchall()
        current = str(username or "").strip().lower()
        members = [
            {
                "username": str(row["assignee"]),
                "assignment_kind": str(row["assignment_kind"]),
                "ordinal": int(row["ordinal"]),
                "model_review_submitted": bool(row["model_review_submitted"]),
                "case_label_acknowledged": bool(row["case_label_acknowledged"]),
                "submitted": (
                    bool(row["model_review_submitted"] and row["case_label_acknowledged"])
                    if str(split["workflow_mode"] or "model_review_only") == "model_review_and_case_label"
                    else row["annotation_id"] is not None
                ),
            }
            for row in rows
        ]
        own = next(
            (item for item in members if item["username"].lower() == current),
            None,
        )
        reviewer_count = int(split["reviewers_per_issue"] or 1)
        return {
            "split_id": str(split["id"]),
            "config_revision": int(split["config_revision"] or 1),
            "purpose": str(split["purpose"] or ""),
            "mode": str(split["mode"] or "single"),
            "model_run_id": str(split["model_run_id"] or ""),
            "workflow_mode": str(split["workflow_mode"] or "model_review_only"),
            "reviewers_per_issue": reviewer_count,
            "overlap_ratio": (
                float(split["overlap_ratio"] or 0)
                if reviewer_count > 1
                else 0.0
            ),
            "assigned_count": len(members),
            "submitted_count": sum(bool(item["submitted"]) for item in members),
            "assigned": own is not None,
            "own_assignment": own,
            "members": members,
        }

    def review_task_context(
        self, *, split_id: str, username: str, is_admin: bool = False,
        allow_supplemental: bool = False,
    ) -> dict[str, Any] | None:
        normalized = str(split_id or "").strip()
        actor = str(username or "").strip().lower()
        if not normalized:
            return None
        normalized=self.resolve_version_campaign(normalized)
        with self.connect() as conn:
            split = conn.execute(
                "SELECT * FROM issue_work_splits WHERE id=?", (normalized,)
            ).fetchone()
            if split is None:
                return None
            if not task_reviewable(split):
                raise PermissionError("该任务已替代、取消、关闭或只读，不能继续复核；请从历史任务查看记录。")
            member = conn.execute(
                "SELECT 1 FROM review_work_assignments WHERE split_id=? AND lower(assignee)=lower(?) LIMIT 1",
                (normalized, actor),
            ).fetchone() if actor else None
            if not is_admin and not allow_supplemental and member is None:
                raise PermissionError("当前账号不是该任务成员。")
            scope_rows = conn.execute(
                """
                SELECT DISTINCT issue.baseline_scope
                FROM review_work_assignments assignment
                JOIN issues issue ON issue.issue_id=assignment.issue_id
                WHERE assignment.split_id=?
                ORDER BY issue.baseline_scope
                """,
                (normalized,),
            ).fetchall()
            issue_count = int(conn.execute(
                "SELECT COUNT(DISTINCT issue_id) n FROM review_work_assignments WHERE split_id=?",
                (normalized,),
            ).fetchone()["n"] or 0)
        snapshot = _json_load(split["filter_json"], {})
        scopes = [str(row["baseline_scope"] or "") for row in scope_rows if str(row["baseline_scope"] or "")]
        if not scopes:
            raw = snapshot.get("baseline_scopes") or snapshot.get("baselines") or []
            scopes = [str(value or "").strip() for value in (raw if isinstance(raw, list) else str(raw).split(",")) if str(value or "").strip()]
        run_id = str(split["evaluation_run_id"] or split["model_run_id"] or "")
        created_at = str(split["created_at"] or "")
        name = str(split["campaign_name"] or "").strip()
        if not name:
            name = f"历史任务 · {created_at[:10]}" if created_at else f"历史任务 · {normalized[:12]}"
        return {
            "id": normalized,
            "name": name,
            "purpose": str(split["purpose"] or "") or None,
            "workflow_mode": str(split["workflow_mode"] or "model_review_only"),
            "lifecycle": str(split["lifecycle"] or "active"),
            "legacy_read_only": bool(split["legacy_read_only"]),
            "baseline_scopes": list(dict.fromkeys(scopes)),
            "model_run_id": run_id,
            "issue_count": issue_count or int(split["total_count"] or 0),
            "current_user_is_member": member is not None,
            "supplemental_only": member is None,
            "legacy_no_run": not run_id,
            "mode": str(split["mode"] or "single"),
            "created_by": str(split["created_by"] or ""),
            "created_at": created_at,
        }

    def review_multi_rows(
        self,
        *,
        baseline_scopes: Sequence[str],
        model_run_id: str = "",
        work_split_id: str = "",
        issue_ids: Sequence[str] | None = None,
        include_single_campaigns: bool = False,
    ) -> list[dict[str, Any]]:
        """Return one row per current blind assignment member for aggregation."""

        scopes = self._normalize_baseline_scopes(baseline_scopes)
        if not scopes:
            return []
        scope_clause, scope_params = self._scope_in_sql(scopes)
        selected_issue_ids = tuple(
            dict.fromkeys(
                str(issue_id or "").strip()
                for issue_id in (issue_ids or ())
                if str(issue_id or "").strip()
            )
        )
        issue_clause = ""
        selected_run_id = str(model_run_id or "").strip()
        selected_work_split_id = str(work_split_id or "").strip()
        def eligible(alias):
            legacy = f"{alias}.mode = 'blind'"
            if not include_single_campaigns:
                return legacy
            return (f"({legacy} OR ({alias}.purpose = 'model_review' "
                    f"AND {alias}.lifecycle = 'active' AND {alias}.legacy_read_only = false "
                    f"AND EXISTS (SELECT 1 FROM model_review_heads submitted_head "
                    f"WHERE submitted_head.campaign_id={alias}.id "
                    f"AND submitted_head.issue_id=assignment.issue_id)))")

        if selected_work_split_id:
            split_filter = "split.id = ?"
            split_params = [selected_work_split_id]
            if selected_run_id:
                split_filter += " AND split.model_run_id = ?"
                split_params.append(selected_run_id)
            prediction_run_id = selected_run_id
        elif selected_run_id:
            split_filter = f"""
                split.model_run_id = ?
                AND split.id = (
                    SELECT latest_split.id
                    FROM issue_work_splits latest_split
                    JOIN review_work_assignments latest_assignment
                      ON latest_assignment.split_id = latest_split.id
                    WHERE latest_assignment.issue_id = assignment.issue_id
                      AND latest_split.model_run_id = ?
                      AND {eligible("latest_split")}
                    ORDER BY latest_split.created_at DESC, latest_split.id DESC
                    LIMIT 1
                )
            """
            split_params = [selected_run_id, selected_run_id]
            prediction_run_id = selected_run_id
        else:
            # No model overlay is a global human-Review view, not the legacy
            # empty-Run namespace. Pick the newest blind split for each Issue
            # across Runs so current cross-validation evidence remains visible
            # without duplicating an Issue from historical assignments.
            split_filter = f"""
                split.id = (
                    SELECT latest_split.id
                    FROM issue_work_splits latest_split
                    JOIN review_work_assignments latest_assignment
                      ON latest_assignment.split_id = latest_split.id
                    WHERE latest_assignment.issue_id = assignment.issue_id
                      AND {eligible("latest_split")}
                    ORDER BY latest_split.created_at DESC, latest_split.id DESC
                    LIMIT 1
                )
            """
            split_params = []
            # A no-overlay response must not silently attach the split's model
            # prediction. The Review retains its own immutable Run binding.
            prediction_run_id = ""
        mode_filter = "TRUE" if selected_work_split_id else eligible("split")
        query = f"""
            SELECT i.issue_id, i.title, i.scenario, i.summary, i.gt_label,
                   i.baseline_scope, assignment.split_id, assignment.assignee,
                   split.mode AS split_mode,
                   split.model_run_id AS split_model_run_id,
                   annotation.id AS annotation_id,
                   annotation.label AS annotation_label,
                   annotation.review_status AS annotation_review_status,
                   annotation.is_excluded AS annotation_is_excluded,
                   annotation.tags_json AS annotation_tags_json,
                   annotation.missing_evidence_json AS annotation_missing_evidence_json,
                   annotation.note AS annotation_note,
                   annotation.author AS annotation_author,
                   annotation.author_source AS annotation_author_source,
                   annotation.author_verified AS annotation_author_verified,
                   annotation.created_at AS annotation_created_at,
                   annotation.review_domain AS annotation_review_domain,
                   annotation.model_review_status AS annotation_model_review_status,
                   annotation.campaign_id AS annotation_campaign_id,
                   annotation.reference_id AS annotation_reference_id,
                   annotation.work_split_id AS annotation_work_split_id,
                   prediction.model_run_id, prediction.model_label,
                   prediction.model_reason, prediction.model_confidence
            FROM review_work_assignments assignment
            JOIN issue_work_splits split ON split.id = assignment.split_id
            JOIN issues i ON i.issue_id = assignment.issue_id
            LEFT JOIN review_records annotation
              ON annotation.issue_id = assignment.issue_id AND annotation.id = (
                SELECT candidate.id FROM review_records candidate
                WHERE candidate.issue_id = assignment.issue_id
                  AND candidate.model_run_id = split.model_run_id
                  AND (
                    (split.purpose = 'model_review'
                     AND candidate.campaign_id = split.id
                     AND candidate.reference_id = split.reference_id
                     AND candidate.review_domain = 'model_review'
                     AND EXISTS (
                         SELECT 1 FROM model_review_heads current_head
                         WHERE current_head.revision_id = candidate.storage_id
                           AND current_head.campaign_id = split.id
                           AND current_head.reference_id = split.reference_id
                     ))
                    OR (COALESCE(split.purpose, '') <> 'model_review' AND (
                        (split.mode = 'blind' AND candidate.work_split_id = assignment.split_id)
                        OR (split.mode <> 'blind' AND candidate.work_split_id = '')
                    ))
                  )
                  AND lower(candidate.author) = lower(assignment.assignee)
                ORDER BY candidate.id DESC LIMIT 1
            )
            LEFT JOIN model_predictions prediction
              ON prediction.issue_id = i.issue_id
             AND prediction.model_run_id = ?
            WHERE {mode_filter} AND {split_filter}
              AND {scope_clause}
              {{issue_clause}}
            ORDER BY i.issue_id ASC, assignment.assignee ASC
        """
        with self.connect() as conn:
            rows: list[Any] = []
            if selected_issue_ids:
                for offset in range(0, len(selected_issue_ids), 400):
                    batch = selected_issue_ids[offset : offset + 400]
                    issue_clause = (
                        "AND assignment.issue_id IN "
                        f"({', '.join('?' for _ in batch)})"
                    )
                    chunk_query = query.replace("{issue_clause}", issue_clause)
                    rows.extend(
                        conn.execute(
                            chunk_query,
                            (prediction_run_id, *split_params, *scope_params, *batch),
                        ).fetchall()
                    )
            else:
                rows = conn.execute(
                    query.replace("{issue_clause}", ""),
                    (prediction_run_id, *split_params, *scope_params),
                ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            annotation = None
            if row["annotation_id"] is not None:
                annotation = {
                    "id": int(row["annotation_id"]),
                    "review_domain": str(row["annotation_review_domain"] or "legacy"),
                    "model_review_status": str(row["annotation_model_review_status"] or ""),
                    "campaign_id": str(row["annotation_campaign_id"] or ""),
                    "reference_id": str(row["annotation_reference_id"] or ""),
                    "model_run_id": str(row["split_model_run_id"] or ""),
                    "work_split_id": str(row["annotation_work_split_id"] or ""),
                    "label": str(row["annotation_label"] or ""),
                    "review_status": str(row["annotation_review_status"] or "pending"),
                    "is_excluded": bool(row["annotation_is_excluded"]),
                    "tags": _json_load(row["annotation_tags_json"], []),
                    "missing_evidence": _json_load(
                        row["annotation_missing_evidence_json"], []
                    ),
                    "note": str(row["annotation_note"] or ""),
                    "author": str(row["annotation_author"] or row["assignee"]),
                    "author_source": str(row["annotation_author_source"] or "legacy"),
                    "author_verified": bool(row["annotation_author_verified"]),
                    "created_at": str(row["annotation_created_at"] or ""),
                }
            results.append(
                {
                    "issue_id": str(row["issue_id"]),
                    "baseline_scope": str(row["baseline_scope"] or ""),
                    "title": str(row["title"] or ""),
                    "scenario": str(row["scenario"] or ""),
                    "summary": str(row["summary"] or ""),
                    "gt_label": str(row["gt_label"] or ""),
                    "split_id": str(row["split_id"]),
                    "split_model_run_id": str(row["split_model_run_id"] or ""),
                    "assignee": str(row["assignee"]),
                    "annotation": annotation,
                    "prediction": {
                        "model_run_id": str(row["model_run_id"] or ""),
                        "label": str(row["model_label"] or ""),
                        "reason": str(row["model_reason"] or ""),
                        "confidence": row["model_confidence"],
                    },
                }
            )
        return results

    def apply_work_split(
        self,
        *,
        assignments: list[dict[str, Any]],
        created_by: str,
        seed: int | None = None,
        filter_snapshot: dict[str, Any] | None = None,
        reviewers_per_issue: int = 1,
        overlap_ratio: float | None = None,
        model_run_id: str = "",
    ) -> dict[str, Any]:
        """Persist a work-split batch and overwrite assignments for its issues."""

        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("均分操作人不能为空。")
        if not assignments:
            raise ValueError("分配结果为空。")
        try:
            reviewer_count = int(reviewers_per_issue or 1)
        except (TypeError, ValueError) as exc:
            raise ValueError("每个 Issue 的复核人数必须是整数。") from exc
        if reviewer_count < 1:
            raise ValueError("每个 Issue 的复核人数至少为 1。")
        resolved_overlap_ratio = normalize_overlap_ratio(
            overlap_ratio,
            reviewers_per_issue=reviewer_count,
        )
        split_id = f"split-{uuid.uuid4().hex}"
        now = utc_now()
        rows: list[tuple[str, str, str, int, str, str]] = []
        for item in assignments:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            assignment_items = item.get("items") or [
                {
                    "issue_id": issue_id,
                    "assignment_kind": "base",
                    "ordinal": ordinal,
                }
                for ordinal, issue_id in enumerate(item.get("issue_ids") or [], 1)
            ]
            for assignment in assignment_items:
                cleaned = str(assignment.get("issue_id") or "").strip()
                if not cleaned:
                    continue
                rows.append(
                    (
                        cleaned,
                        name,
                        str(assignment.get("assignment_kind") or "base"),
                        int(assignment.get("ordinal") or 1),
                        actor,
                        now,
                    )
                )
        if not rows:
            raise ValueError("没有可写入的 Issue 分配。")
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            conn.execute(
                """
                INSERT INTO issue_work_splits (
                    id, created_by, created_at, seed, total_count, filter_json,
                    assignees_json, mode, reviewers_per_issue, model_run_id,
                    overlap_ratio, assignment_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    split_id,
                    actor,
                    now,
                    seed,
                    len({row[0] for row in rows}),
                    json.dumps(filter_snapshot or {}, ensure_ascii=False),
                    json.dumps(assignments, ensure_ascii=False),
                    "blind" if reviewer_count > 1 else "single",
                    reviewer_count,
                    str(model_run_id or "").strip(),
                    resolved_overlap_ratio,
                    len(rows),
                ),
            )
            issue_ids = sorted({row[0] for row in rows})
            for offset in range(0, len(issue_ids), 500):
                batch = issue_ids[offset : offset + 500]
                conn.execute(
                    "DELETE FROM review_work_assignments WHERE split_id IN "
                    "(SELECT id FROM issue_work_splits WHERE model_run_id = ? AND COALESCE(purpose, '') = '') "
                    f"AND issue_id IN ({', '.join('?' for _ in batch)})",
                    (str(model_run_id or "").strip(), *batch),
                )
            for issue_id, assignee, kind, ordinal, assigned_by, assigned_at in rows:
                conn.execute(
                    """
                    INSERT INTO review_work_assignments (
                        split_id, issue_id, assignee, assignment_kind, ordinal,
                        assigned_by, assigned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (split_id, issue_id, assignee, kind, ordinal, assigned_by, assigned_at),
                )
        return {
            "split_id": split_id,
            "created_by": actor,
            "created_at": now,
            "seed": seed,
            "total": len({row[0] for row in rows}),
            "assignment_count": len(rows),
            "reviewers_per_issue": reviewer_count,
            "overlap_ratio": resolved_overlap_ratio,
            "assignments": assignments,
        }
