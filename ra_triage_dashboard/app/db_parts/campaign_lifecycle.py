"""Campaign domain submodule extracted from db_parts/campaigns.py (Phase 2B)."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Sequence
from uuid import uuid4

from ..review_analysis import REASON_THEME_CATALOG, classify_review_reason
from .campaign_common import (
    CAMPAIGN_LIFECYCLES,
    CAMPAIGN_PURPOSES,
    DISCUSSION_CHANNELS,
    CampaignConflictError,
    CampaignReadOnlyError,
    _fingerprint,
    _safe_json_value,
    _split_snapshot_assignments,
    campaign_inventory_fingerprint,
)
from .shared import _json, _json_load, utc_now
from .task_lifecycle import normalize_task_lifecycle, task_lifecycle_where


class DatabaseCampaignLifecycleMixin:
    """Campaign assignment updates, close/reopen/transition, revisions, and label exports."""

    def campaign_label_analysis_export(
        self,
        campaign_id: str,
        *,
        query: str = "",
        assignee: str = "",
        state: str = "all",
    ) -> dict[str, Any] | None:
        campaign_detail = self.get_campaign(
            campaign_id,
            page=1,
            page_size=5000,
            assignee=assignee,
            state=state,
            query=str(query or "").strip()[:128],
        )
        if campaign_detail is None:
            return None
        campaign = campaign_detail.get("campaign") or {}
        if campaign.get("purpose") != "labeling":
            raise ValueError("Label Analysis 只适用于 Labeling Campaign。")
        issue_ids = [str(item["issue_id"]) for item in campaign_detail.get("issues") or []]
        revisions_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
        task_id = str(campaign.get("id") or campaign_id)
        source_run_id = str(campaign.get("selection_source_run_id") or "")
        with self.connect() as conn:
            for offset in range(0, len(issue_ids), 500):
                batch = issue_ids[offset:offset + 500]
                if not batch:
                    continue
                rows = conn.execute(
                    f"""
                    SELECT label_case.issue_id, label_case.id AS label_case_id,
                           label_case.source_run_id, revision.id AS revision_id,
                           revision.expected_output, revision.tags_json,
                           revision.evidence_gaps_json, revision.rationale,
                           revision.is_excluded, revision.author,
                           revision.author_source, revision.author_verified,
                           revision.revision_kind, revision.supersedes_id,
                           revision.created_at
                    FROM label_cases label_case
                    JOIN label_revisions revision ON revision.label_case_id = label_case.id
                    WHERE label_case.task_id = ?
                      AND label_case.issue_id IN ({', '.join('?' for _ in batch)})
                      AND (COALESCE(?, '') = '' OR label_case.source_run_id = ?)
                    ORDER BY label_case.issue_id, lower(revision.author), revision.id
                    """,
                    (task_id, *batch, source_run_id, source_run_id),
                ).fetchall()
                for row in rows:
                    revisions_by_issue[str(row["issue_id"])].append({
                        "label_case_id": str(row["label_case_id"]),
                        "source_run_id": str(row["source_run_id"] or ""),
                        "revision_id": int(row["revision_id"]),
                        "expected_output": str(row["expected_output"] or ""),
                        "tags": _json_load(row["tags_json"], []),
                        "evidence_gaps": _json_load(row["evidence_gaps_json"], []),
                        "rationale": str(row["rationale"] or ""),
                        "is_excluded": bool(row["is_excluded"]),
                        "author": str(row["author"] or ""),
                        "author_source": str(row["author_source"] or "legacy"),
                        "author_verified": bool(row["author_verified"]),
                        "revision_kind": str(row["revision_kind"] or ""),
                        "supersedes_id": int(row["supersedes_id"]) if row["supersedes_id"] else None,
                        "created_at": str(row["created_at"] or ""),
                    })
        for item in campaign_detail.get("issues") or []:
            item["label_revisions"] = revisions_by_issue.get(str(item["issue_id"]), [])
        return campaign_detail

    def update_campaign_assignment(
        self,
        *,
        campaign_id: str,
        issue_id: str,
        action: str,
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        expected_revision: int,
        idempotency_key: str,
        assignee: str = "",
        from_assignee: str = "",
        assignment_kind: str = "base",
        reason: str = "",
    ) -> dict[str, Any]:
        campaign_key = str(campaign_id or "").strip()
        issue_key = str(issue_id or "").strip()
        operation = str(action or "").strip().lower()
        target = str(assignee or "").strip().lower()
        source = str(from_assignee or "").strip().lower()
        actor_name = str(actor or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        kind = str(assignment_kind or "base").strip().lower()
        if operation not in {"assign", "unassign", "reassign"}:
            raise ValueError("assignment action 只能是 assign、unassign 或 reassign。")
        if operation in {"assign", "reassign"} and not self._CAMPAIGN_USER_RE.fullmatch(target):
            raise ValueError("Assignee 账号格式非法。")
        if operation in {"unassign", "reassign"} and not self._CAMPAIGN_USER_RE.fullmatch(source):
            raise ValueError("待移除 Assignee 账号格式非法。")
        if kind not in self._CAMPAIGN_ASSIGNMENT_KINDS or not actor_name or not key:
            raise ValueError("assignment kind、操作人和 idempotency_key 必须有效。")
        if operation == "reassign" and target == source:
            raise ValueError("新旧 Assignee 不能相同。")
        fingerprint = _fingerprint({
            "campaign_id": campaign_key, "issue_id": issue_key, "action": operation,
            "assignee": target, "from_assignee": source, "assignment_kind": kind,
            "reason": str(reason or ""), "expected_revision": int(expected_revision),
        })
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            existing = conn.execute(
                "SELECT idempotency_fingerprint FROM campaign_assignment_audit "
                "WHERE campaign_id = ? AND idempotency_key = ?",
                (campaign_key, key),
            ).fetchone()
            if existing is not None:
                if str(existing["idempotency_fingerprint"] or "") != fingerprint:
                    raise CampaignConflictError("assignment idempotency key 已用于不同变更。")
                return {"campaign_id": campaign_key, "issue_id": issue_key, "changed": False, "replayed": True}
            split = conn.execute(
                "SELECT * FROM issue_work_splits WHERE id = ?"
                + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                (campaign_key,),
            ).fetchone()
            if split is None:
                raise ValueError("Campaign 不存在。")
            if bool(split["legacy_read_only"]) or not str(split["purpose"] or ""):
                raise CampaignReadOnlyError("未分类的 legacy Campaign 只读。")
            if str(split["lifecycle"] or "") != "active":
                raise CampaignReadOnlyError("只有 active Campaign 可以调整任务分配。")
            revision = int(split["config_revision"] or 1)
            if revision != int(expected_revision):
                raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
            member = conn.execute(
                "SELECT * FROM campaign_issue_members WHERE campaign_id = ? AND issue_id = ?",
                (campaign_key, issue_key),
            ).fetchone()
            if member is None:
                raise ValueError("Issue 不属于该 Campaign。")
            current_rows = conn.execute(
                "SELECT assignee, assignment_kind FROM review_work_assignments "
                "WHERE split_id = ? AND issue_id = ? ORDER BY lower(assignee)",
                (campaign_key, issue_key),
            ).fetchall()
            current = {str(row["assignee"] or "").strip().lower(): str(row["assignment_kind"] or "base") for row in current_rows}
            if current:
                allocation_rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM review_work_assignments WHERE split_id=? ORDER BY issue_id,ordinal,assignee",
                    (campaign_key,),
                ).fetchall()]
                protection = self._allocation_protection(conn, dict(split), allocation_rows)
                if (issue_key, source) in protection["protected"]:
                    raise ValueError("该负责人已有保存或受保护的工作，必须保留原分配 / This author's saved or protected work must retain its assignment")
                # Explicit formal admission of an objection adds a new position;
                # it does not transfer an existing person's protected work. Keep
                # that established workflow separate from bulk redistribution.
                formal_admission = operation == "assign" and conn.execute(
                    "SELECT 1 FROM human_version_tasks WHERE campaign_id=?", (campaign_key,),
                ).fetchone() is not None
                if operation in {"assign", "unassign"} and protection["has_evidence"] and not formal_admission:
                    raise ValueError("已有保存的任务须保留原覆盖人数 / Tasks with saved work must retain their coverage counts")
                if (issue_key, target) in protection["forbidden"] and not formal_admission:
                    raise ValueError("目标人员有未关联的历史记录，不能自动作为新分配 / The recipient has unlinked historical work and cannot receive this slot")
                if operation == "reassign" and conn.execute(
                    "SELECT 1 FROM human_version_tasks WHERE campaign_id=?", (campaign_key,),
                ).fetchone():
                    recipient = conn.execute(
                        "SELECT a.role AS permission,h.role FROM access_users a "
                        "JOIN human_user_roles h ON h.username=a.username WHERE a.username=?", (target,),
                    ).fetchone()
                    retained_roles = {protection["captured_roles"].get((issue_key, p))
                                      for p in current if p != source}
                    allocation = _json_load(split["filter_json"], {}).get("task_allocation") or {}
                    if (not recipient or recipient["permission"] not in {"writer", "admin"}
                            or recipient["role"] not in {"rd", "te"}):
                        raise ValueError("接收人需要正式标注资格 / The recipient needs eligibility for formal review")
                    if not allocation.get("groups") and not {"rd", "te"} <= retained_roles | {recipient["role"]}:
                        raise ValueError("转派后仍须保留有效的 RD 和 TE 覆盖 / Reassignment must retain eligible RD and TE coverage")
            if operation == "assign":
                if target in current:
                    raise ValueError("该 Issue 已经分配给此 Assignee。")
                changes = [("assigned", "", target, kind)]
            else:
                if source not in current:
                    raise ValueError("找不到待移除的当前 Assignee。")
                submitted_sql = (
                    "SELECT 1 FROM label_cases item JOIN label_revisions revision "
                    "ON revision.label_case_id=item.id WHERE item.task_id=? AND item.issue_id=? "
                    "AND lower(revision.author)=? AND revision.revision_kind IN ('submission','legacy') "
                    "AND (COALESCE(?, '')='' OR item.source_run_id=?) LIMIT 1"
                    if str(split["purpose"]) == "labeling"
                    else "SELECT 1 FROM model_review_heads head JOIN model_review_revisions revision "
                    "ON revision.id=head.revision_id WHERE head.issue_id=? AND lower(head.reviewer)=? "
                    "AND revision.model_run_id=? AND revision.status IN ('in_progress','completed','blocked_by_label') "
                    "AND (head.campaign_id=? OR revision.work_split_id=?) LIMIT 1"
                )
                if str(split["purpose"]) == "labeling":
                    submitted_params = (campaign_key, issue_key, source,
                                        str(split["selection_source_run_id"] or ""),
                                        str(split["selection_source_run_id"] or ""))
                else:
                    submitted_params = (issue_key, source, str(split["evaluation_run_id"] or ""), campaign_key, campaign_key)
                if conn.execute(submitted_sql, submitted_params).fetchone() is not None:
                    raise ValueError("该 Assignee 已提交结果；保留原分配以保护审核记录。")
                if operation == "reassign" and target in current:
                    raise ValueError("该 Issue 已经分配给目标 Assignee。")
                changes = [("unassigned" if operation == "unassign" else "reassigned",
                            source, target if operation == "reassign" else "", current[source])]
            now = utc_now()
            new_revision = revision + 1
            for audit_action, old_name, new_name, old_kind in changes:
                if old_name:
                    conn.execute(
                        "DELETE FROM review_work_assignments WHERE split_id=? AND issue_id=? AND assignee=?",
                        (campaign_key, issue_key, old_name),
                    )
                if new_name:
                    conn.execute(
                        "INSERT INTO review_work_assignments (split_id, issue_id, assignee, assignment_kind, ordinal, assigned_by, assigned_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (campaign_key, issue_key, new_name, kind if operation == "assign" else old_kind,
                         int(member["ordinal"] or 1), actor_name, now),
                    )
                conn.execute(
                    """
                    INSERT INTO campaign_assignment_audit (
                        campaign_id, issue_id, action, assignment_kind,
                        from_assignee, to_assignee, changed_by, changed_by_source,
                        changed_by_verified, config_revision, idempotency_key,
                        idempotency_fingerprint, reason, changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (campaign_key, issue_key, audit_action, old_kind, old_name, new_name,
                     actor_name, str(actor_source or "legacy"), bool(actor_verified),
                     new_revision, key, fingerprint, str(reason or "")[:500], now),
                )
                if old_name and new_name:
                    conn.execute(
                        "INSERT INTO review_work_assignment_changes (split_id, issue_id, from_assignee, to_assignee, changed_by, changed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (campaign_key, issue_key, old_name, new_name, actor_name, now),
                    )
            updated_assignments = conn.execute(
                "SELECT assignee, assignment_kind FROM review_work_assignments "
                "WHERE split_id=? AND issue_id=? ORDER BY lower(assignee)",
                (campaign_key, issue_key),
            ).fetchall()
            assignment_names = [str(row["assignee"] or "").strip().lower() for row in updated_assignments]
            assignment_kinds = sorted({str(row["assignment_kind"] or "base") for row in updated_assignments})
            conn.execute(
                "UPDATE campaign_issue_members SET required_submitter_count=?, reviewers_per_issue=?, "
                "assignment_kinds_json=?, config_revision=? WHERE campaign_id=? AND issue_id=?",
                (len(assignment_names), len(assignment_names), _json(assignment_kinds),
                 new_revision, campaign_key, issue_key),
            )
            updated = conn.execute(
                "UPDATE issue_work_splits SET config_revision=?, updated_by=?, updated_by_source=?, "
                "updated_by_verified=?, updated_at=? WHERE id=? AND config_revision=? AND lifecycle='active'",
                (new_revision, actor_name, str(actor_source or "legacy"), bool(actor_verified), now, campaign_key, revision),
            )
            if int(updated.rowcount or 0) != 1:
                raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
            self._campaign_refresh_compat_assignment_snapshot(conn, campaign_key)
            self._campaign_insert_revision(
                conn, campaign_id=campaign_key, revision_no=new_revision,
                changed_by=actor_name, changed_by_source=str(actor_source or "legacy"),
                changed_by_verified=bool(actor_verified), change_source="assignment",
                idempotency_key=key,
            )
            self._mark_change_topic(conn, "review")
            if str(split["purpose"]) == "labeling":
                self._mark_change_topic(conn, "labeling")
        return {"campaign_id": campaign_key, "issue_id": issue_key, "changed": True,
                "config_revision": int(expected_revision) + 1,
                "campaign": self.get_campaign(campaign_key, page=1, page_size=20)}

    def close_campaign(
        self,
        *,
        campaign_id: str,
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        expected_revision: int,
        idempotency_key: str,
        reason: str = "",
    ) -> dict[str, Any]:
        campaign_key = str(campaign_id or "").strip()
        actor_name = str(actor or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        explanation = str(reason or "").strip()[:500]
        if not campaign_key or not actor_name or not key:
            raise ValueError("Campaign、操作人和 idempotency_key 不能为空。")
        fingerprint = _fingerprint({
            "action": "closed", "campaign_id": campaign_key,
            "expected_revision": int(expected_revision), "reason": explanation,
        })
        snapshot_id = ""
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            existing = conn.execute(
                "SELECT snapshot_id, idempotency_fingerprint FROM campaign_lifecycle_audit "
                "WHERE campaign_id = ? AND idempotency_key = ?",
                (campaign_key, key),
            ).fetchone()
            if existing is not None:
                if str(existing["idempotency_fingerprint"] or "").strip() != fingerprint:
                    raise CampaignConflictError("close idempotency key 已用于不同操作。")
                snapshot_id = str(existing["snapshot_id"] or "")
            else:
                split = conn.execute(
                    "SELECT * FROM issue_work_splits WHERE id = ?"
                    + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                    (campaign_key,),
                ).fetchone()
                if split is None:
                    raise ValueError("Campaign 不存在。")
                revision = int(split["config_revision"] or 1)
                if str(split["lifecycle"] or "") == "closed":
                    if int(split["closed_revision"] or 0) != int(expected_revision):
                        raise CampaignConflictError("Campaign 已关闭且版本与请求不一致。")
                    snapshot_id = str(split["latest_close_snapshot_id"] or "")
                else:
                    if bool(split["legacy_read_only"]) or not str(split["purpose"] or ""):
                        raise CampaignReadOnlyError("未分类的 legacy Campaign 只读，不能关闭。")
                    if str(split["lifecycle"] or "") != "active":
                        raise CampaignReadOnlyError("只有 active Campaign 可以关闭。")
                    if revision != int(expected_revision):
                        raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
                    summary = self._campaign_progress_batch(conn, [split]).get(campaign_key, {})
                    issue_items = list(summary.get("issues") or [])
                    status_counts = dict(summary.get("state_counts") or {})
                    assignment_rows = conn.execute(
                        "SELECT issue_id, assignee, assignment_kind, ordinal FROM review_work_assignments "
                        "WHERE split_id = ? ORDER BY issue_id, lower(assignee), ordinal",
                        (campaign_key,),
                    ).fetchall()
                    assignment_source = [
                        {"issue_id": str(row["issue_id"]), "assignee": str(row["assignee"] or ""),
                         "assignment_kind": str(row["assignment_kind"] or "base"),
                         "ordinal": int(row["ordinal"] or 1)}
                        for row in assignment_rows
                    ]
                    source_fingerprint = _fingerprint({
                        "campaign_id": campaign_key,
                        "config_revision": revision,
                        "assignments": assignment_source,
                        "progress": issue_items,
                    })
                    snapshot_id = f"campaign-close-{uuid4().hex}"
                    now = utc_now()
                    conn.execute(
                        """
                        INSERT INTO campaign_close_snapshots (
                            id, campaign_id, config_revision, member_count,
                            assigned_issue_count, required_submitter_count,
                            submitted_submitter_count, completed_issue_count,
                            pending_issue_count, conflict_issue_count,
                            adjudicated_issue_count, stale_issue_count,
                            blocked_issue_count, status_counts_json,
                            result_snapshot_json, source_fingerprint, closed_by,
                            closed_by_source, closed_by_verified, closed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (snapshot_id, campaign_key, revision,
                         int(summary.get("member_count") or 0),
                         int(summary.get("assigned_issue_count") or 0),
                         int(summary.get("required_submitter_count") or 0),
                         int(summary.get("submitted_submitter_count") or 0),
                         int(summary.get("completed_issue_count") or 0),
                         int(summary.get("pending_issue_count") or 0),
                         int(summary.get("conflict_issue_count") or 0),
                         int(summary.get("adjudicated_issue_count") or 0),
                         int(summary.get("stale_issue_count") or 0),
                         int(summary.get("blocked_issue_count") or 0),
                         _json(status_counts),
                         _json({"progress": summary, "assignments": assignment_source}),
                         source_fingerprint, actor_name, str(actor_source or "legacy"),
                         bool(actor_verified), now),
                    )
                    state_by_issue = {str(item["issue_id"]): item for item in issue_items}
                    for member in conn.execute(
                        "SELECT issue_id, required_submitter_count FROM campaign_issue_members "
                        "WHERE campaign_id = ? ORDER BY ordinal",
                        (campaign_key,),
                    ).fetchall():
                        issue_id = str(member["issue_id"])
                        state = state_by_issue.get(issue_id, {})
                        result_state = str(state.get("state") or "pending")
                        if result_state == "unassigned":
                            result_state = "pending"
                        if result_state not in {"pending", "completed", "conflict", "adjudicated", "stale", "blocked"}:
                            result_state = "pending"
                        submitted_count = int(state.get("submitted") or 0)
                        conn.execute(
                            """
                            INSERT INTO campaign_close_snapshot_items (
                                snapshot_id, campaign_id, issue_id,
                                required_submitter_count, submitted_submitter_count,
                                result_state, status_counts_json, source_revision_ids_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (snapshot_id, campaign_key, issue_id,
                             int(member["required_submitter_count"] or 0),
                             submitted_count, result_state,
                             _json({"state": result_state}),
                             _json(state.get("source_revision_ids") or [])),
                        )
                    conn.execute(
                        """
                        INSERT INTO campaign_lifecycle_audit (
                            campaign_id, action, from_lifecycle, to_lifecycle,
                            config_revision, changed_by, changed_by_source,
                            changed_by_verified, snapshot_id, idempotency_key,
                            idempotency_fingerprint, reason, changed_at
                        ) VALUES (?, 'closed', 'active', 'closed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (campaign_key, revision, actor_name, str(actor_source or "legacy"),
                         bool(actor_verified), snapshot_id, key, fingerprint, explanation, now),
                    )
                    updated = conn.execute(
                        """
                        UPDATE issue_work_splits
                        SET lifecycle = 'closed', closed_by = ?, closed_by_source = ?,
                            closed_by_verified = ?, closed_at = ?, closed_revision = ?,
                            latest_close_snapshot_id = ?, updated_by = ?,
                            updated_by_source = ?, updated_by_verified = ?, updated_at = ?
                        WHERE id = ? AND config_revision = ?
                        """,
                        (actor_name, str(actor_source or "legacy"), bool(actor_verified),
                         now, revision, snapshot_id, actor_name,
                         str(actor_source or "legacy"), bool(actor_verified), now,
                         campaign_key, revision),
                    )
                    if int(updated.rowcount or 0) != 1:
                        raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
                    self._mark_change_topic(conn, "review")
                    if str(split["purpose"] or "") == "labeling":
                        self._mark_change_topic(conn, "labeling")
        return {"snapshot_id": snapshot_id, "campaign": self.get_campaign(campaign_key)}

    def reopen_campaign(
        self,
        *,
        campaign_id: str,
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        expected_revision: int,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        campaign_key = str(campaign_id or "").strip()
        actor_name = str(actor or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        explanation = str(reason or "").strip()[:500]
        if not campaign_key or not actor_name or not key or not explanation:
            raise ValueError("Campaign、操作人、idempotency_key 和 reopening reason 不能为空。")
        fingerprint = _fingerprint({
            "action": "reopened", "campaign_id": campaign_key,
            "expected_revision": int(expected_revision), "reason": explanation,
        })
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            existing = conn.execute(
                "SELECT idempotency_fingerprint FROM campaign_lifecycle_audit "
                "WHERE campaign_id = ? AND idempotency_key = ?",
                (campaign_key, key),
            ).fetchone()
            if existing is not None:
                if str(existing["idempotency_fingerprint"] or "").strip() != fingerprint:
                    raise CampaignConflictError("reopen idempotency key 已用于不同操作。")
            else:
                split = conn.execute(
                    "SELECT * FROM issue_work_splits WHERE id = ?"
                    + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                    (campaign_key,),
                ).fetchone()
                if split is None:
                    raise ValueError("Campaign 不存在。")
                if bool(split["legacy_read_only"]) or not str(split["purpose"] or ""):
                    raise CampaignReadOnlyError("未分类的 legacy Campaign 只读，不能重新打开。")
                if str(split["lifecycle"] or "") != "closed":
                    raise CampaignReadOnlyError("只有 closed Campaign 可以重新打开。")
                revision = int(split["config_revision"] or 1)
                if revision != int(expected_revision) or int(split["closed_revision"] or 0) != revision:
                    raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
                new_revision = revision + 1
                now = utc_now()
                snapshot_id = str(split["latest_close_snapshot_id"] or "")
                conn.execute(
                    """
                    INSERT INTO campaign_lifecycle_audit (
                        campaign_id, action, from_lifecycle, to_lifecycle,
                        config_revision, changed_by, changed_by_source,
                        changed_by_verified, snapshot_id, idempotency_key,
                        idempotency_fingerprint, reason, changed_at
                    ) VALUES (?, 'reopened', 'closed', 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (campaign_key, new_revision, actor_name, str(actor_source or "legacy"),
                     bool(actor_verified), snapshot_id, key, fingerprint, explanation, now),
                )
                updated = conn.execute(
                    "UPDATE issue_work_splits SET lifecycle='active', config_revision=?, "
                    "closed_by='', closed_by_source='legacy', closed_by_verified=false, "
                    "closed_at=NULL, closed_revision=NULL, updated_by=?, updated_by_source=?, "
                    "updated_by_verified=?, updated_at=? WHERE id=? AND config_revision=?",
                    (new_revision, actor_name, str(actor_source or "legacy"),
                     bool(actor_verified), now, campaign_key, revision),
                )
                if int(updated.rowcount or 0) != 1:
                    raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
                conn.execute(
                    "UPDATE campaign_issue_members SET config_revision=? WHERE campaign_id=?",
                    (new_revision, campaign_key),
                )
                self._campaign_insert_revision(
                    conn, campaign_id=campaign_key, revision_no=new_revision,
                    changed_by=actor_name, changed_by_source=str(actor_source or "legacy"),
                    changed_by_verified=bool(actor_verified), change_source="reopen",
                    idempotency_key=key,
                )
                self._mark_change_topic(conn, "review")
                if str(split["purpose"] or "") == "labeling":
                    self._mark_change_topic(conn, "labeling")
        return {"campaign": self.get_campaign(campaign_key)}

    def transition_campaign(
        self,
        *,
        campaign_id: str,
        action: str,
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        expected_revision: int,
        idempotency_key: str,
        reason: str = "",
    ) -> dict[str, Any]:
        campaign_key = str(campaign_id or "").strip()
        operation = str(action or "").strip().lower()
        actor_name = str(actor or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        explanation = str(reason or "").strip()[:500]
        transitions = {
            "activate": ({"draft"}, "active", "activated"),
            "cancel": ({"draft", "active"}, "cancelled", "cancelled"),
            "supersede": ({"active"}, "superseded", "superseded"),
        }
        if operation not in transitions:
            raise ValueError("Campaign transition 只能是 activate、cancel 或 supersede。")
        if not campaign_key or not actor_name or not key:
            raise ValueError("Campaign、操作人和 idempotency_key 不能为空。")
        if operation in {"cancel", "supersede"} and not explanation:
            raise ValueError("取消或替代 Campaign 必须填写原因。")
        try:
            expected = int(expected_revision)
        except (TypeError, ValueError) as exc:
            raise ValueError("expected_revision 必须是正整数。") from exc
        if expected < 1:
            raise ValueError("expected_revision 必须是正整数。")
        allowed_sources, target_lifecycle, audit_action = transitions[operation]
        fingerprint = _fingerprint({
            "action": operation,
            "campaign_id": campaign_key,
            "expected_revision": expected,
            "reason": explanation,
        })
        replayed = False
        with self._write_lock, self.connect() as conn:
            self._lock_task_work(conn)
            existing = conn.execute(
                "SELECT idempotency_fingerprint FROM campaign_lifecycle_audit "
                "WHERE campaign_id = ? AND idempotency_key = ?",
                (campaign_key, key),
            ).fetchone()
            if existing is not None:
                if str(existing["idempotency_fingerprint"] or "").strip() != fingerprint:
                    raise CampaignConflictError("lifecycle idempotency key 已用于不同操作。")
                replayed = True
            else:
                split = conn.execute(
                    "SELECT * FROM issue_work_splits WHERE id = ?"
                    + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                    (campaign_key,),
                ).fetchone()
                if split is None:
                    raise ValueError("Campaign 不存在。")
                if bool(split["legacy_read_only"]) or not str(split["purpose"] or ""):
                    raise CampaignReadOnlyError("未分类的 legacy Campaign 只读，不能更改生命周期。")
                current_lifecycle = str(split["lifecycle"] or "")
                if current_lifecycle not in allowed_sources:
                    raise CampaignReadOnlyError(
                        f"不允许 Campaign 从 {current_lifecycle or 'unknown'} 转换为 {target_lifecycle}。"
                    )
                revision = int(split["config_revision"] or 1)
                if revision != expected:
                    raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
                new_revision = revision + 1
                now = utc_now()
                conn.execute(
                    """
                    INSERT INTO campaign_lifecycle_audit (
                        campaign_id, action, from_lifecycle, to_lifecycle,
                        config_revision, changed_by, changed_by_source,
                        changed_by_verified, snapshot_id, idempotency_key,
                        idempotency_fingerprint, reason, changed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                    """,
                    (campaign_key, audit_action, current_lifecycle, target_lifecycle,
                     new_revision, actor_name, str(actor_source or "legacy"),
                     bool(actor_verified), key, fingerprint, explanation, now),
                )
                conn.execute(
                    "UPDATE campaign_issue_members SET config_revision = ? WHERE campaign_id = ?",
                    (new_revision, campaign_key),
                )
                updated = conn.execute(
                    """
                    UPDATE issue_work_splits
                    SET lifecycle = ?, config_revision = ?, updated_by = ?,
                        updated_by_source = ?, updated_by_verified = ?, updated_at = ?
                    WHERE id = ? AND config_revision = ? AND lifecycle = ?
                    """,
                    (target_lifecycle, new_revision, actor_name,
                     str(actor_source or "legacy"), bool(actor_verified), now,
                     campaign_key, revision, current_lifecycle),
                )
                if int(updated.rowcount or 0) != 1:
                    raise CampaignConflictError("Campaign 配置已更新，请刷新后重试。")
                self._campaign_insert_revision(
                    conn,
                    campaign_id=campaign_key,
                    revision_no=new_revision,
                    changed_by=actor_name,
                    changed_by_source=str(actor_source or "legacy"),
                    changed_by_verified=bool(actor_verified),
                    change_source=operation,
                    idempotency_key=key,
                )
                self._mark_change_topic(conn, "review")
                if str(split["purpose"] or "") == "labeling":
                    self._mark_change_topic(conn, "labeling")
        return {
            "campaign": self.get_campaign(campaign_key),
            "action": operation,
            "changed": not replayed,
            "replayed": replayed,
        }

    def _campaign_insert_revision(
        self,
        conn: Any,
        *,
        campaign_id: str,
        revision_no: int,
        changed_by: str,
        changed_by_source: str,
        changed_by_verified: bool,
        change_source: str,
        idempotency_key: str = "",
        allocation_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        split = conn.execute(
            "SELECT * FROM issue_work_splits WHERE id = ?", (campaign_id,)
        ).fetchone()
        if split is None:
            raise ValueError("Campaign 不存在。")
        workset_source = conn.execute(
            "SELECT selection_source_run_id FROM review_worksets WHERE id = ?",
            (str(split["workset_id"] or ""),),
        ).fetchone() if str(split["workset_id"] or "") else None
        selection_source_run_id = str(
            (workset_source["selection_source_run_id"] if workset_source is not None else "")
            or split["selection_source_run_id"] or ""
        )
        member_rows = conn.execute(
            """
            SELECT campaign_id, issue_id, baseline_scope, ordinal,
                   required_submitter_count, reviewers_per_issue, assignment_kinds_json
            FROM campaign_issue_members WHERE campaign_id = ?
            ORDER BY ordinal, issue_id
            """,
            (campaign_id,),
        ).fetchall()
        members = [
            {
                "issue_id": str(row["issue_id"]),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "ordinal": int(row["ordinal"] or 0),
                "required_submitter_count": int(row["required_submitter_count"] or 0),
                "reviewers_per_issue": int(row["reviewers_per_issue"] or 0),
                "assignment_kinds": _json_load(row["assignment_kinds_json"], []),
            }
            for row in member_rows
        ]
        assignment_rows = conn.execute(
            """
            SELECT issue_id, assignee, assignment_kind, ordinal
            FROM review_work_assignments WHERE split_id = ?
            ORDER BY issue_id, lower(assignee), ordinal
            """,
            (campaign_id,),
        ).fetchall()
        assignments = [
            {
                "issue_id": str(row["issue_id"]),
                "assignee": str(row["assignee"] or "").strip().lower(),
                "assignment_kind": str(row["assignment_kind"] or "base"),
                "ordinal": int(row["ordinal"] or 1),
            }
            for row in assignment_rows
        ]
        members_sha = _fingerprint(members)
        required_total = sum(item["required_submitter_count"] for item in members)
        config = {
            "campaign_id": campaign_id,
            "task_allocation": _json_load(split["filter_json"], {}).get("task_allocation"),
            "allocation_request_fingerprint": _json_load(split["filter_json"], {}).get("allocation_request_fingerprint"),
            "reviewers_per_issue": int(split["reviewers_per_issue"] or 1),
            "overlap_ratio": float(split["overlap_ratio"] or 0),
            "purpose": str(split["purpose"] or "") or None,
            "workset_id": str(split["workset_id"] or ""),
            "evaluation_run_id": str(split["evaluation_run_id"] or ""),
            "selection_source_run_id": selection_source_run_id,
            "reference_type": str(split["reference_type"] or ""),
            "reference_id": str(split["reference_id"] or ""),
            "reference_sha256": str(split["reference_sha256"] or ""),
            "lifecycle": str(split["lifecycle"] or "active"),
            "legacy_mapping_status": str(split["legacy_mapping_status"] or ""),
            "legacy_read_only": bool(split["legacy_read_only"]),
            "campaign_name": str(split["campaign_name"] or ""),
            "members_sha256": members_sha,
            "member_count": len(members),
            "required_submitter_count": required_total,
            "assignments": assignments,
        }
        if allocation_receipt is not None:
            config["allocation_receipt"] = allocation_receipt
        config_json = _json(config)
        config_sha = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
        now = utc_now()
        conn.execute(
            """
            INSERT INTO campaign_config_revisions (
                campaign_id, revision_no, purpose, workset_id, evaluation_run_id,
                reference_type, reference_id, lifecycle, member_count,
                required_submitter_count, members_sha256, config_json,
                config_sha256, changed_by, changed_by_source,
                changed_by_verified, change_source, changed_at,
                idempotency_key, idempotency_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, revision_no) DO NOTHING
            """,
            (
                campaign_id,
                int(revision_no),
                str(split["purpose"] or "") or None,
                str(split["workset_id"] or ""),
                str(split["evaluation_run_id"] or ""),
                str(split["reference_type"] or ""),
                str(split["reference_id"] or ""),
                str(split["lifecycle"] or "active"),
                len(members),
                required_total,
                members_sha,
                config_json,
                config_sha,
                str(changed_by or ""),
                str(changed_by_source or "legacy"),
                bool(changed_by_verified),
                str(change_source or "user"),
                now,
                str(idempotency_key or ""),
                _fingerprint({"key": idempotency_key, "config": config_sha}) if idempotency_key else "",
            ),
        )
        conn.executemany(
            """
            INSERT INTO campaign_config_members (
                campaign_id, revision_no, issue_id, ordinal,
                required_submitter_count, reviewers_per_issue, assignment_kinds_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(campaign_id, revision_no, issue_id) DO NOTHING
            """,
            [
                (
                    campaign_id,
                    int(revision_no),
                    item["issue_id"],
                    item["ordinal"],
                    item["required_submitter_count"],
                    item["reviewers_per_issue"],
                    _json(item["assignment_kinds"]),
                )
                for item in members
            ],
        )
        return {"revision_no": int(revision_no), "config_sha256": config_sha, "members_sha256": members_sha}

