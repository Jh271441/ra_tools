"""Atomic combined model Review and shared Case-label submissions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence
from uuid import uuid4

from .model_reviews import MODEL_REVIEW_PUBLIC_ID_OFFSET, MODEL_REVIEW_WRITE_STATUSES, model_review_label_fingerprint
from .shared import LABELS, AnnotationConflictError, LabelAnnotationConflictError, _json, _json_load, utc_now


WORKFLOW_MODES = {"model_review_only", "model_review_and_case_label"}


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class DatabaseCombinedReviewMixin:
    def submit_review_case_label(
        self, *, issue_id: str, reviewer: str, reviewer_source: str,
        reviewer_verified: bool, expected_output: str, tags: Sequence[str],
        rationale: str, expected_case_revision_id: int | None,
        expected_label_state_fingerprint: str,
    ) -> dict[str, Any]:
        issue_key = str(issue_id or "").strip()
        actor = str(reviewer or "").strip().lower()
        output = str(expected_output or "").strip()
        if not reviewer_verified or not actor:
            raise PermissionError("Case 标注要求已验证账号。")
        if output not in LABELS:
            raise ValueError("必须明确选择 Case 标签。")
        clean_tags = sorted({str(value or "").strip() for value in tags if str(value or "").strip()})
        with self._write_lock, self.connect() as conn:
            issue = conn.execute(
                "SELECT issue_id, baseline_scope, gt_label, gt_source FROM issues WHERE issue_id=?",
                (issue_key,),
            ).fetchone()
            if issue is None:
                raise ValueError("Issue 不存在。")
            scope = str(issue["baseline_scope"] or "")
            active = conn.execute(
                "SELECT status FROM labeling_scope_state WHERE baseline_scope=?", (scope,)
            ).fetchone()
            if active is None or str(active["status"] or "") != "active":
                raise PermissionError("当前数据集尚未启用 Case 标注写入。")
            head = conn.execute(
                """
                SELECT revision.* FROM label_revisions revision
                JOIN label_cases label_case ON label_case.id=revision.label_case_id
                WHERE label_case.baseline_scope=? AND label_case.issue_id=?
                  AND lower(revision.author)=lower(?)
                  AND revision.revision_kind IN ('submission','legacy')
                  AND NOT EXISTS (SELECT 1 FROM label_import_suppressed_revisions s WHERE s.revision_id=revision.id)
                ORDER BY revision.id DESC LIMIT 1
                """,
                (scope, issue_key, actor),
            ).fetchone()
            current_id = int(head["id"]) if head is not None else None
            label_state = self.project_issue_label_states(
                scope, [issue_key], include_sources=True, connection=conn
            ).get(issue_key, {})
            if current_id != expected_case_revision_id:
                raise LabelAnnotationConflictError("Case 标签 vote 已变化，请刷新后重新确认。")
            if model_review_label_fingerprint(label_state) != str(expected_label_state_fingerprint or ""):
                raise LabelAnnotationConflictError("共享 Case 标签结论已变化，请刷新后重新确认。")
            if head is not None and str(head["expected_output"] or "") == output:
                return {
                    "case_action": "acknowledged", "case_revision": self._label_revision_dict(head),
                    "label_state": label_state,
                    "label_state_fingerprint": model_review_label_fingerprint(label_state),
                }
            now = utc_now()
            label_case_id = str(head["label_case_id"] or "") if head is not None else ""
            if not label_case_id:
                existing_case = conn.execute(
                    "SELECT id FROM label_cases WHERE baseline_scope=? AND issue_id=? AND task_id='' AND source_run_id=''",
                    (scope, issue_key),
                ).fetchone()
                label_case_id = str(existing_case["id"]) if existing_case is not None else f"label-{uuid4().hex}"
                if existing_case is None:
                    conn.execute(
                        """
                        INSERT INTO label_cases (id, baseline_scope, issue_id, task_id, source_run_id,
                                                 seen_gt_label, seen_gt_source, created_at)
                        VALUES (?, ?, ?, '', '', ?, ?, ?)
                        """,
                        (label_case_id, scope, issue_key, str(issue["gt_label"] or ""), str(issue["gt_source"] or ""), now),
                    )
            sql = """
                INSERT INTO label_revisions (
                    label_case_id, expected_output, tags_json, evidence_gaps_json,
                    rationale, is_excluded, author, author_source, author_verified,
                    revision_kind, supersedes_id, source_annotation_id, created_at
                ) VALUES (?, ?, ?, '[]', ?, false, ?, ?, true, 'submission', ?, NULL, ?)
            """
            if self.backend == "postgresql":
                sql += " RETURNING id"
            cursor = conn.execute(
                sql,
                (label_case_id, output, _json(clean_tags), str(rationale or ""), actor,
                 str(reviewer_source or "legacy"), current_id, now),
            )
            revision_id = int(cursor.fetchone()["id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
            row = conn.execute("SELECT * FROM label_revisions WHERE id=?", (revision_id,)).fetchone()
            state = self.project_issue_label_states(scope, [issue_key], include_sources=True, connection=conn).get(issue_key, {})
            self._mark_labeling_change(conn)
            return {
                "case_action": "submitted", "case_revision": self._label_revision_dict(row),
                "label_state": state,
                "label_state_fingerprint": model_review_label_fingerprint(state),
            }

    def _combined_context_on_connection(
        self, conn: Any, *, issue_id: str, campaign_id: str, reviewer: str,
        model_run_id: str = "",
    ) -> dict[str, Any]:
        campaign = conn.execute(
            """
            SELECT id, purpose, workflow_mode, lifecycle, legacy_read_only,
                   evaluation_run_id, reference_id, workset_id
            FROM issue_work_splits WHERE id = ?
            """,
            (campaign_id,),
        ).fetchone()
        if campaign is None and campaign_id:
            raise ValueError("联合复核任务不存在。")
        assignment = conn.execute(
            """
            SELECT assignment_kind FROM review_work_assignments
            WHERE split_id = ? AND issue_id = ? AND lower(assignee) = lower(?)
            """,
            (campaign_id, issue_id, reviewer),
        ).fetchone()
        member = conn.execute(
            "SELECT baseline_scope FROM campaign_issue_members WHERE campaign_id=? AND issue_id=?",
            (campaign_id, issue_id),
        ).fetchone()
        issue = conn.execute(
            "SELECT issue_id, baseline_scope, gt_label, gt_source FROM issues WHERE issue_id=?",
            (issue_id,),
        ).fetchone()
        if issue is None or (campaign_id and member is None):
            raise ValueError("Issue 不在联合复核任务中。")
        if campaign is None:
            run_id = str(model_run_id or "").strip()
            if run_id and conn.execute("SELECT 1 FROM model_runs WHERE id=?", (run_id,)).fetchone() is None:
                raise ValueError("联合浏览选择的 Model Run 无效。")
            campaign = {
                "id": "", "purpose": "model_review",
                "workflow_mode": "model_review_and_case_label",
                "lifecycle": "active", "legacy_read_only": False,
                "evaluation_run_id": run_id, "reference_id": "", "workset_id": "",
            }
        head = conn.execute(
            """
            SELECT revision.* FROM model_review_heads head
            JOIN model_review_revisions revision ON revision.id = head.revision_id
            WHERE head.model_run_id = ? AND head.issue_id = ?
              AND head.campaign_id = ? AND head.reference_id = ?
              AND lower(head.reviewer) = lower(?)
            """,
            (
                str(campaign["evaluation_run_id"] or ""), issue_id, campaign_id,
                str(campaign["reference_id"] or ""), reviewer,
            ),
        ).fetchone()
        label_head = conn.execute(
            """
            SELECT revision.*, label_case.baseline_scope, label_case.issue_id,
                   label_case.task_id, label_case.source_run_id,
                   label_case.seen_gt_label, label_case.seen_gt_source
            FROM label_revisions revision
            JOIN label_cases label_case ON label_case.id = revision.label_case_id
            WHERE label_case.baseline_scope = ? AND label_case.issue_id = ?
              AND lower(revision.author) = lower(?)
              AND revision.revision_kind IN ('submission', 'legacy')
              AND NOT EXISTS (
                  SELECT 1 FROM label_import_suppressed_revisions suppressed
                  WHERE suppressed.revision_id = revision.id
              )
              AND revision.id = (
                  SELECT MAX(candidate.id) FROM label_revisions candidate
                  WHERE candidate.label_case_id = revision.label_case_id
                    AND lower(candidate.author) = lower(revision.author)
                    AND candidate.revision_kind IN ('submission', 'legacy')
                    AND NOT EXISTS (
                        SELECT 1 FROM label_import_suppressed_revisions suppressed
                        WHERE suppressed.revision_id = candidate.id
                    )
              )
            ORDER BY revision.id DESC LIMIT 1
            """,
            (str(issue["baseline_scope"] or ""), issue_id, reviewer),
        ).fetchone()
        label_state = self.project_issue_label_states(
            str(issue["baseline_scope"] or ""), [issue_id],
            include_sources=True, connection=conn,
        ).get(issue_id, {})
        progress = conn.execute(
            """
            SELECT * FROM combined_review_progress
            WHERE campaign_id=? AND issue_id=? AND lower(reviewer)=lower(?)
            """,
            (campaign_id, issue_id, reviewer),
        ).fetchone()
        return {
            "campaign": {key: campaign[key] for key in campaign.keys()},
            "issue": {key: issue[key] for key in issue.keys()},
            "assigned": assignment is not None or not campaign_id,
            "model_review": self._model_review_dict(head) if head is not None else None,
            "model_review_storage_id": int(head["id"]) if head is not None else None,
            "case_revision": self._label_revision_dict(label_head) if label_head is not None else None,
            "case_revision_id": int(label_head["id"]) if label_head is not None else None,
            "label_case_id": str(label_head["label_case_id"] or "") if label_head is not None else "",
            "label_state": label_state,
            "label_state_fingerprint": model_review_label_fingerprint(label_state),
            "progress": (
                {key: progress[key] for key in progress.keys()} if progress is not None else {
                    "model_review_submitted": False,
                    "case_label_acknowledged": False,
                }
            ),
        }

    def combined_review_context(
        self, *, issue_id: str, campaign_id: str, reviewer: str,
        model_run_id: str = "",
    ) -> dict[str, Any]:
        with self.connect() as conn:
            return self._combined_context_on_connection(
                conn, issue_id=str(issue_id), campaign_id=str(campaign_id),
                reviewer=str(reviewer).strip().lower(), model_run_id=str(model_run_id),
            )

    def submit_combined_review(
        self,
        *,
        issue_id: str,
        campaign_id: str,
        model_run_id: str,
        reviewer: str,
        reviewer_source: str,
        reviewer_verified: bool,
        model_review_status: str,
        reason: str,
        missing_evidence: Sequence[str],
        expected_output: str,
        tags: Sequence[str],
        rationale: str,
        expected_model_review_storage_id: int | None,
        expected_case_revision_id: int | None,
        expected_label_state_fingerprint: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        issue_key = str(issue_id or "").strip()
        campaign_key = str(campaign_id or "").strip()
        run_key = str(model_run_id or "").strip()
        actor = str(reviewer or "").strip().lower()
        status = str(model_review_status or "pending").strip().lower()
        output = str(expected_output or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        if not reviewer_verified or not actor:
            raise PermissionError("联合复核要求已验证账号。")
        if status not in MODEL_REVIEW_WRITE_STATUSES:
            raise ValueError("模型判错复核状态仅支持待开始、复核中、已完成。")
        if output not in LABELS:
            raise ValueError("联合复核必须明确选择 Case 标签。")
        if not key:
            raise ValueError("联合复核必须提供 Idempotency-Key。")
        evidence = sorted({str(value or "").strip() for value in missing_evidence if str(value or "").strip()})
        clean_tags = sorted({str(value or "").strip() for value in tags if str(value or "").strip()})
        payload_fingerprint = _fingerprint({
            "issue_id": issue_key, "campaign_id": campaign_key,
            "model_run_id": run_key, "reviewer": actor,
            "model_review_status": status, "reason": str(reason or ""),
            "missing_evidence": evidence, "expected_output": output,
            "tags": clean_tags, "rationale": str(rationale or ""),
            "expected_model_review_storage_id": expected_model_review_storage_id,
            "expected_case_revision_id": expected_case_revision_id,
            "expected_label_state_fingerprint": str(expected_label_state_fingerprint or ""),
        })
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            replay = conn.execute(
                """
                SELECT * FROM combined_review_submissions
                WHERE campaign_id=? AND issue_id=? AND lower(reviewer)=lower(?)
                  AND idempotency_key=?
                """,
                (campaign_key, issue_key, actor, key),
            ).fetchone()
            if replay is not None:
                if str(replay["idempotency_fingerprint"] or "") != payload_fingerprint:
                    raise AnnotationConflictError("Idempotency-Key 已用于不同联合复核内容。")
                context = self._combined_context_on_connection(
                    conn, issue_id=issue_key, campaign_id=campaign_key, reviewer=actor
                    , model_run_id=run_key
                )
                return {
                    "submission_group_id": str(replay["id"]),
                    "case_action": str(replay["case_action"]),
                    "duplicate": True,
                    **context,
                }
            context = self._combined_context_on_connection(
                conn, issue_id=issue_key, campaign_id=campaign_key, reviewer=actor
                , model_run_id=run_key
            )
            campaign = context["campaign"]
            if str(campaign.get("purpose") or "") != "model_review":
                raise ValueError("联合复核仅适用于模型复核任务。")
            if str(campaign.get("workflow_mode") or "model_review_only") != "model_review_and_case_label":
                raise PermissionError("当前任务未启用联合复核。")
            if bool(campaign.get("legacy_read_only")) or str(campaign.get("lifecycle") or "") != "active":
                raise PermissionError("当前联合复核任务只读或未激活。")
            if str(campaign.get("evaluation_run_id") or "") != run_key:
                raise ValueError("当前 Model Run 与联合复核任务不匹配。")
            if campaign_key and not context["assigned"]:
                raise PermissionError("当前账号不在联合复核任务中。")
            active_scope = conn.execute(
                "SELECT status FROM labeling_scope_state WHERE baseline_scope=?",
                (str(context["issue"].get("baseline_scope") or ""),),
            ).fetchone()
            if active_scope is None or str(active_scope["status"] or "") != "active":
                raise PermissionError("当前数据集尚未启用 Case 标注写入。")
            role = conn.execute("SELECT role FROM access_users WHERE username=?", (actor,)).fetchone()
            if role is None or str(role["role"] or "") != "admin":
                raise PermissionError("联合复核需要 Case 标注管理员权限。")
            if context["model_review_storage_id"] != expected_model_review_storage_id:
                raise AnnotationConflictError("模型复核已变化，请刷新后重新确认。")
            if context["case_revision_id"] != expected_case_revision_id:
                raise LabelAnnotationConflictError("Case 标签 vote 已变化，请刷新后重新确认。")
            if context["label_state_fingerprint"] != str(expected_label_state_fingerprint or ""):
                raise LabelAnnotationConflictError("共享 Case 标签结论已变化，请刷新后重新确认。")
            now = utc_now()
            current_case = context.get("case_revision") or {}
            if int(context.get("case_revision_id") or 0) and str(current_case.get("expected_output") or "") == output:
                case_action = "acknowledged"
                label_revision_id = int(context["case_revision_id"])
                label_case_id = str(context["label_case_id"])
                appended_label_revision_id = None
            else:
                label_case_id = str(context.get("label_case_id") or "")
                if not label_case_id:
                    scope = str(context["issue"].get("baseline_scope") or "")
                    existing_case = conn.execute(
                        "SELECT id FROM label_cases WHERE baseline_scope=? AND issue_id=? AND task_id='' AND source_run_id=''",
                        (scope, issue_key),
                    ).fetchone()
                    label_case_id = str(existing_case["id"]) if existing_case is not None else f"label-{uuid4().hex}"
                    if existing_case is None:
                        conn.execute(
                            """
                            INSERT INTO label_cases (
                                id, baseline_scope, issue_id, task_id, source_run_id,
                                seen_gt_label, seen_gt_source, created_at
                            ) VALUES (?, ?, ?, '', '', ?, ?, ?)
                            """,
                            (
                                label_case_id, scope, issue_key,
                                str(context["issue"].get("gt_label") or ""),
                                str(context["issue"].get("gt_source") or ""), now,
                            ),
                        )
                sql = """
                    INSERT INTO label_revisions (
                        label_case_id, expected_output, tags_json, evidence_gaps_json,
                        rationale, is_excluded, author, author_source,
                        author_verified, revision_kind, supersedes_id,
                        source_annotation_id, created_at
                    ) VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, 'submission', ?, NULL, ?)
                """
                if self.backend == "postgresql":
                    sql += " RETURNING id"
                cursor = conn.execute(
                    sql,
                    (
                        label_case_id, output, _json(clean_tags), str(rationale or ""),
                        False, actor, str(reviewer_source or "legacy"), True,
                        context.get("case_revision_id"), now,
                    ),
                )
                label_revision_id = int(cursor.fetchone()["id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
                appended_label_revision_id = label_revision_id
                case_action = "submitted"
            post_label_state = self.project_issue_label_states(
                str(context["issue"].get("baseline_scope") or ""), [issue_key],
                include_sources=True, connection=conn,
            ).get(issue_key, {})
            model_sql = """
                INSERT INTO model_review_revisions (
                    model_run_id, issue_id, campaign_id, reference_id,
                    work_split_id, status, reason, missing_evidence_json,
                    label_state_fingerprint, label_state_json, reviewer,
                    reviewer_source, reviewer_verified, supersedes_id,
                    legacy_base_annotation_id, legacy_annotation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """
            if self.backend == "postgresql":
                model_sql += " RETURNING id"
            cursor = conn.execute(
                model_sql,
                (
                    run_key, issue_key, campaign_key, str(campaign.get("reference_id") or ""),
                    campaign_key, status, str(reason or ""), _json(evidence),
                    model_review_label_fingerprint(post_label_state), _json(post_label_state),
                    actor, str(reviewer_source or "legacy"), True,
                    context.get("model_review_storage_id"), now,
                ),
            )
            model_revision_id = int(cursor.fetchone()["id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO model_review_heads (
                    model_run_id, issue_id, campaign_id, reference_id,
                    reviewer, revision_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_run_id, issue_id, campaign_id, reference_id, reviewer)
                DO UPDATE SET revision_id=excluded.revision_id, updated_at=excluded.updated_at
                """,
                (
                    run_key, issue_key, campaign_key, str(campaign.get("reference_id") or ""),
                    actor, model_revision_id, now,
                ),
            )
            group_id = str(uuid4())
            conn.execute(
                """
                INSERT INTO combined_review_submissions (
                    id, campaign_id, issue_id, reviewer, model_run_id,
                    model_review_revision_id, label_case_id, label_revision_id,
                    acknowledged_label_revision_id, case_action, idempotency_key,
                    idempotency_fingerprint, created_by_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id, campaign_key, issue_key, actor, run_key,
                    model_revision_id, label_case_id, appended_label_revision_id,
                    label_revision_id if case_action == "acknowledged" else None,
                    case_action, key, payload_fingerprint,
                    str(reviewer_source or "legacy"), now,
                ),
            )
            if campaign_key:
                conn.execute(
                    """
                    INSERT INTO combined_review_progress (
                        campaign_id, issue_id, reviewer, model_review_submitted,
                        case_label_acknowledged, model_review_revision_id,
                        case_label_revision_id, submission_group_id,
                        model_review_submitted_at, case_label_acknowledged_at, updated_at
                    ) VALUES (?, ?, ?, true, true, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(campaign_id, issue_id, reviewer) DO UPDATE SET
                        model_review_submitted=true, case_label_acknowledged=true,
                        model_review_revision_id=excluded.model_review_revision_id,
                        case_label_revision_id=excluded.case_label_revision_id,
                        submission_group_id=excluded.submission_group_id,
                        model_review_submitted_at=excluded.model_review_submitted_at,
                        case_label_acknowledged_at=excluded.case_label_acknowledged_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        campaign_key, issue_key, actor, model_revision_id,
                        label_revision_id, group_id, now, now, now,
                    ),
                )
            self._mark_labeling_change(conn)
            context = self._combined_context_on_connection(
                conn, issue_id=issue_key, campaign_id=campaign_key, reviewer=actor
                , model_run_id=run_key
            )
            return {
                "submission_group_id": group_id,
                "case_action": case_action,
                "duplicate": False,
                **context,
            }
