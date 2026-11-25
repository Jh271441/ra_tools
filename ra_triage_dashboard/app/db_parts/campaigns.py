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
from .campaign_legacy import DatabaseCampaignLegacyMixin
from .campaign_lifecycle import DatabaseCampaignLifecycleMixin
from .campaign_progress import DatabaseCampaignProgressMixin

class DatabaseCampaignMixin(
    DatabaseCampaignLifecycleMixin,
    DatabaseCampaignLegacyMixin,
    DatabaseCampaignProgressMixin,
):
    """Unified Campaign read/write domain backed by the legacy split table."""

    _CAMPAIGN_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
    _CAMPAIGN_ASSIGNMENT_KINDS = {"base", "cross", "full"}
    _CAMPAIGN_WORKFLOW_MODES = {"model_review_only", "model_review_and_case_label"}

    def _campaign_create_in_connection(
        self,
        conn: Any,
        *,
        spec: dict[str, Any],
        actor: str,
        actor_source: str,
        actor_verified: bool,
        task_group_id: str = "",
        child_idempotency_key: str = "",
        child_idempotency_fingerprint: str = "",
    ) -> str:
        purpose = str(spec.get("purpose") or "").strip().lower()
        if purpose not in CAMPAIGN_PURPOSES:
            raise ValueError("Campaign purpose 只能是 labeling 或 model_review。")
        workflow_mode = str(spec.get("workflow_mode") or "model_review_only").strip().lower()
        if workflow_mode not in self._CAMPAIGN_WORKFLOW_MODES:
            raise ValueError("workflow_mode 不合法。")
        if purpose != "model_review" and workflow_mode != "model_review_only":
            raise ValueError("联合复核模式仅适用于 Model Review Campaign。")
        initial_lifecycle = str(spec.get("lifecycle") or "active").strip().lower()
        if initial_lifecycle not in {"draft", "active"}:
            raise ValueError("新建 Campaign 的 lifecycle 只能是 draft 或 active。")
        evaluation_run_id = str(spec.get("evaluation_run_id") or "").strip()
        if purpose == "model_review":
            if not evaluation_run_id:
                raise ValueError("Model Review Campaign 必须绑定一个 Model Run。")
            if conn.execute("SELECT 1 FROM model_runs WHERE id = ?", (evaluation_run_id,)).fetchone() is None:
                raise ValueError("Model Run 不存在。")
        else:
            evaluation_run_id = ""
        if purpose == "model_review" and conn.execute("SELECT 1 FROM version_datasets WHERE run_id=?",(evaluation_run_id,)).fetchone():
            dataset=conn.execute('SELECT id FROM version_datasets WHERE run_id=?',(evaluation_run_id,)).fetchone()
            if self._version_registration(conn,dataset['id']):raise ValueError('Use direct append to the existing version task')
        workset_id = str(spec.get("workset_id") or "").strip()
        workset = conn.execute(
            "SELECT * FROM review_worksets WHERE id = ?", (workset_id,)
        ).fetchone() if workset_id else None
        if workset_id and workset is None:
            raise ValueError("Workset 不存在。")
        if purpose == "model_review" and workset is None:
            raise ValueError("Model Review Campaign 必须绑定冻结 Workset。")
        if purpose == "labeling" and workset is None:
            raise ValueError("Labeling Campaign 必须绑定冻结 Workset。")
        raw_members = spec.get("members")
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError("Campaign members 必须是非空数组。")
        if len(raw_members) > 5000:
            raise ValueError("一个 Campaign 最多包含 5000 个 Issue。")
        normalized_members: list[dict[str, Any]] = []
        seen_issues: set[str] = set()
        for ordinal, raw in enumerate(raw_members, 1):
            if not isinstance(raw, dict):
                raise ValueError("Campaign member 必须是对象。")
            issue_id = str(raw.get("issue_id") or "").strip()
            if not issue_id or issue_id in seen_issues:
                raise ValueError("Campaign members 含空 Issue 或重复 Issue。")
            seen_issues.add(issue_id)
            raw_assignees = raw.get("assignees", raw.get("assignments", []))
            if not isinstance(raw_assignees, list):
                raise ValueError("每个 Issue 的 assignees 必须是数组。")
            assignees: list[dict[str, Any]] = []
            seen_assignees: set[str] = set()
            for assignment in raw_assignees:
                if isinstance(assignment, str):
                    name, kind = assignment.strip().lower(), "base"
                elif isinstance(assignment, dict):
                    name = str(assignment.get("assignee") or assignment.get("name") or "").strip().lower()
                    kind = str(assignment.get("assignment_kind") or "base").strip().lower()
                else:
                    raise ValueError("Assignee 必须是账号字符串或对象。")
                if not self._CAMPAIGN_USER_RE.fullmatch(name):
                    raise ValueError("Assignee 账号格式非法。")
                if kind not in self._CAMPAIGN_ASSIGNMENT_KINDS:
                    raise ValueError("Assignment kind 只能是 base、cross 或 full。")
                if name in seen_assignees:
                    raise ValueError("同一 Issue 不能重复分配给同一个人。")
                seen_assignees.add(name)
                assignees.append({"assignee": name, "assignment_kind": kind})
            normalized_members.append({
                "issue_id": issue_id,
                "ordinal": int(raw.get("ordinal") or ordinal),
                "assignees": assignees,
            })
        issue_ids = [item["issue_id"] for item in normalized_members]
        issue_rows: list[Any] = []
        for offset in range(0, len(issue_ids), 500):
            batch = issue_ids[offset:offset + 500]
            issue_rows.extend(conn.execute(
                f"SELECT issue_id, baseline_scope FROM issues WHERE issue_id IN ({', '.join('?' for _ in batch)})",
                batch,
            ).fetchall())
        scope_by_issue = {str(row["issue_id"]): str(row["baseline_scope"] or "") for row in issue_rows}
        if set(scope_by_issue) != set(issue_ids):
            raise ValueError("Campaign members 中包含不存在的 Issue。")
        for member in normalized_members:
            member["baseline_scope"] = scope_by_issue[member["issue_id"]]
            if not member["baseline_scope"]:
                raise ValueError("Campaign Issue 缺少 baseline scope。")
        scopes = sorted({item["baseline_scope"] for item in normalized_members})
        if workflow_mode == "model_review_and_case_label":
            active_rows = conn.execute(
                f"SELECT baseline_scope FROM labeling_scope_state WHERE status='active' AND baseline_scope IN ({', '.join('?' for _ in scopes)})",
                scopes,
            ).fetchall()
            if {str(row["baseline_scope"] or "") for row in active_rows} != set(scopes):
                raise ValueError("联合复核只能使用已启用 Case 标注的数据集。")
            assigned_names = sorted({
                assignment["assignee"]
                for member in normalized_members for assignment in member["assignees"]
            })
            if assigned_names:
                role_rows = conn.execute(
                    f"SELECT username, role FROM access_users WHERE username IN ({', '.join('?' for _ in assigned_names)})",
                    assigned_names,
                ).fetchall()
                roles = {str(row["username"]): str(row["role"] or "") for row in role_rows}
                unavailable = [
                    name for name in assigned_names
                    if roles.get(name) not in {"writer", "admin"}
                ]
                if unavailable:
                    raise ValueError("联合复核负责人缺少 Case 标注权限：" + "、".join(unavailable))
        if workset is not None:
            workset_scope_rows = conn.execute(
                "SELECT baseline_scope FROM review_workset_scopes "
                "WHERE workset_id = ? ORDER BY ordinal",
                (workset_id,),
            ).fetchall()
            workset_scopes = [
                str(row["baseline_scope"] or "") for row in workset_scope_rows
                if str(row["baseline_scope"] or "")
            ]
            if not workset_scopes and str(workset["baseline_scope"] or ""):
                workset_scopes = [str(workset["baseline_scope"] or "")]
            if set(scopes) != set(workset_scopes):
                raise ValueError("Campaign members 与多 scope Workset scope 集合不匹配。")
            workset_items = conn.execute(
                """
                SELECT item.issue_id, issue.baseline_scope
                FROM review_workset_items item
                JOIN issues issue ON issue.issue_id = item.issue_id
                WHERE item.workset_id = ? ORDER BY item.ordinal
                """,
                (workset_id,),
            ).fetchall()
            expected_by_scope: dict[str, set[str]] = defaultdict(set)
            for row in workset_items:
                expected_by_scope[str(row["baseline_scope"] or "")].add(str(row["issue_id"]))
            actual_by_scope: dict[str, set[str]] = defaultdict(set)
            for member in normalized_members:
                actual_by_scope[member["baseline_scope"]].add(member["issue_id"])
            if expected_by_scope != actual_by_scope:
                raise ValueError("Campaign members 必须完整匹配其冻结 Workset。")
        references_by_scope: dict[str, dict[str, str]] = {}
        requested_references = spec.get("references")
        if isinstance(requested_references, list):
            reference_specs = {
                str(item.get("baseline_scope") or "").strip(): item
                for item in requested_references if isinstance(item, dict)
            }
        else:
            reference_specs = {scope: spec for scope in scopes}
        for scope in scopes:
            requested = reference_specs.get(scope, {})
            references_by_scope[scope] = self._campaign_reference_for_scope(
                conn,
                baseline_scope=scope,
                reference_type=str(requested.get("reference_type") or ""),
                reference_id=str(requested.get("reference_id") or ""),
            )
        reference_values = list(references_by_scope.values())
        if len(reference_values) == 1:
            top_reference_type = reference_values[0]["reference_type"]
            top_reference_id = reference_values[0]["reference_id"]
            top_reference_sha = reference_values[0]["reference_sha256"]
        else:
            top_reference_id = _fingerprint(reference_values)
            top_reference_type = "reference_set"
            top_reference_sha = top_reference_id
        if purpose == "model_review":
            selection_source_run_id = str(spec.get("selection_source_run_id") or "").strip()
            if workset is not None:
                selection_source_run_id = str(workset["selection_source_run_id"] or selection_source_run_id)
        else:
            selection_source_run_id = ""
        campaign_name = str(spec.get("name") or spec.get("campaign_name") or "").strip()[:160]
        if not campaign_name:
            campaign_name = f"{purpose} · {len(normalized_members)} Issues"
        mode = "blind" if purpose == "model_review" and any(len(item["assignees"]) > 1 for item in normalized_members) else ("labeling" if purpose == "labeling" else "single")
        max_reviewers = max((len(item["assignees"]) for item in normalized_members), default=0)
        try:
            overlap_ratio = float(spec.get("overlap_ratio") if spec.get("overlap_ratio") is not None else (1.0 if max_reviewers > 1 else 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("overlap_ratio 必须是 0 到 1 之间的数字。") from exc
        if not 0 <= overlap_ratio <= 1:
            raise ValueError("overlap_ratio 必须是 0 到 1 之间的数字。")
        actor_name = str(actor or "").strip()
        if not actor_name:
            raise ValueError("Campaign 创建人不能为空。")
        idempotency_key = str(child_idempotency_key or spec.get("idempotency_key") or "").strip()[:160]
        idempotency_fingerprint = str(child_idempotency_fingerprint or "").strip()
        if not idempotency_fingerprint:
            idempotency_fingerprint = _fingerprint({
                "purpose": purpose, "name": campaign_name, "workset_id": workset_id,
                "evaluation_run_id": evaluation_run_id, "selection_source_run_id": selection_source_run_id,
                "workflow_mode": workflow_mode,
                "references": reference_values, "members": normalized_members,
                "task_group_id": task_group_id,
            })
        if idempotency_key:
            existing = conn.execute(
                "SELECT id, idempotency_fingerprint FROM issue_work_splits WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["idempotency_fingerprint"] or "") != idempotency_fingerprint:
                    raise CampaignConflictError("Campaign idempotency key 已用于不同配置。")
                return str(existing["id"])
        now = utc_now()
        campaign_id = f"campaign-{uuid4().hex}"
        assignments_compat: dict[str, list[dict[str, Any]]] = defaultdict(list)
        assignment_count = 0
        for member in normalized_members:
            for assignment in member["assignees"]:
                assignments_compat[assignment["assignee"]].append({
                    "issue_id": member["issue_id"],
                    "assignment_kind": assignment["assignment_kind"],
                    "ordinal": member["ordinal"],
                })
                assignment_count += 1
        assignees_json = [
            {"name": name, "count": len(items), "items": items}
            for name, items in sorted(assignments_compat.items())
        ]
        filter_snapshot = spec.get("filters") if isinstance(spec.get("filters"), dict) else {}
        conn.execute(
            """
            INSERT INTO issue_work_splits (
                id, created_by, created_at, seed, total_count, filter_json,
                assignees_json, mode, reviewers_per_issue, model_run_id,
                overlap_ratio, assignment_count, task_kind, workset_id,
                selection_source_run_id, purpose, evaluation_run_id,
                workflow_mode,
                reference_type, reference_id, reference_sha256, lifecycle,
                config_revision, created_by_source, created_by_verified,
                updated_by, updated_by_source, updated_by_verified, updated_at,
                legacy_read_only, legacy_mapping_status, idempotency_key,
                idempotency_fingerprint, campaign_name, task_group_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, 1, ?, ?, ?, ?, ?, ?, false, 'native_s4', ?, ?, ?, ?)
            """,
            (
                campaign_id, actor_name, now, spec.get("seed"), len(normalized_members),
                _json(filter_snapshot), _json(assignees_json), mode, max_reviewers,
                evaluation_run_id, overlap_ratio, assignment_count,
                "labeling" if purpose == "labeling" else "s4_model_review",
                workset_id, selection_source_run_id, purpose, evaluation_run_id or None,
                workflow_mode,
                top_reference_type, top_reference_id, top_reference_sha,
                initial_lifecycle,
                str(actor_source or "legacy"), bool(actor_verified), actor_name,
                str(actor_source or "legacy"), bool(actor_verified), now,
                idempotency_key, idempotency_fingerprint, campaign_name,
                task_group_id or None,
            ),
        )
        for reference in reference_values:
            conn.execute(
                """
                INSERT INTO campaign_reference_items (
                    campaign_id, baseline_scope, reference_type, reference_id,
                    reference_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (campaign_id, reference["baseline_scope"], reference["reference_type"],
                 reference["reference_id"], reference["reference_sha256"], now),
            )
        for member in normalized_members:
            kinds = sorted({item["assignment_kind"] for item in member["assignees"]})
            required = len(member["assignees"])
            conn.execute(
                """
                INSERT INTO campaign_issue_members (
                    campaign_id, issue_id, baseline_scope, ordinal,
                    required_submitter_count, reviewers_per_issue,
                    assignment_kinds_json, config_revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (campaign_id, member["issue_id"], member["baseline_scope"],
                 member["ordinal"], required, required, _json(kinds), now),
            )
            for assignment in member["assignees"]:
                conn.execute(
                    """
                    INSERT INTO review_work_assignments (
                        split_id, issue_id, assignee, assignment_kind, ordinal,
                        assigned_by, assigned_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (campaign_id, member["issue_id"], assignment["assignee"],
                     assignment["assignment_kind"], member["ordinal"], actor_name, now),
                )
                conn.execute(
                    """
                    INSERT INTO campaign_assignment_audit (
                        campaign_id, issue_id, action, assignment_kind,
                        to_assignee, changed_by, changed_by_source,
                        changed_by_verified, config_revision, idempotency_key,
                        idempotency_fingerprint, reason, changed_at
                    ) VALUES (?, ?, 'assigned', ?, ?, ?, ?, ?, 1, ?, ?, 'campaign_created', ?)
                    """,
                    (campaign_id, member["issue_id"], assignment["assignment_kind"],
                     assignment["assignee"], actor_name, str(actor_source or "legacy"),
                     bool(actor_verified), f"create:{member['issue_id']}:{assignment['assignee']}",
                     _fingerprint([campaign_id, member["issue_id"], assignment]), now),
                )
        self._campaign_insert_revision(
            conn, campaign_id=campaign_id, revision_no=1, changed_by=actor_name,
            changed_by_source=str(actor_source or "legacy"),
            changed_by_verified=bool(actor_verified), change_source="create",
            idempotency_key=idempotency_key,
        )
        if task_group_id:
            conn.execute(
                "INSERT INTO review_task_group_campaigns (group_id, campaign_id, evaluation_run_id, ordinal, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_group_id, campaign_id, evaluation_run_id, int(spec.get("group_ordinal") or 1), now),
            )
        return campaign_id

    def create_campaign(
        self,
        *,
        spec: dict[str, Any],
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        key = str(idempotency_key or spec.get("idempotency_key") or "").strip()[:160]
        fingerprint = _fingerprint({key: spec}) if key else ""
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            campaign_id = self._campaign_create_in_connection(
                conn, spec=spec, actor=actor, actor_source=actor_source,
                actor_verified=actor_verified, child_idempotency_key=key,
                child_idempotency_fingerprint=fingerprint,
            )
            self._mark_change_topic(conn, "review")
            if str(spec.get("purpose") or "") == "labeling":
                self._mark_change_topic(conn, "labeling")
        return self.get_campaign(campaign_id) or {"id": campaign_id}

    def create_campaign_group(
        self,
        *,
        name: str,
        purpose: str,
        campaigns: list[dict[str, Any]],
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_purpose = str(purpose or "").strip().lower()
        if normalized_purpose not in CAMPAIGN_PURPOSES or not campaigns:
            raise ValueError("Task Group purpose 或 Campaign 列表不合法。")
        if normalized_purpose == "labeling" and len(campaigns) != 1:
            raise ValueError("Labeling Task Group 只能包含一个 Campaign。")
        if any(str(spec.get("purpose") or "").strip().lower() != normalized_purpose for spec in campaigns):
            raise ValueError("Task Group 下所有 Campaign 必须使用同一 purpose。")
        if normalized_purpose == "model_review":
            run_ids = [str(spec.get("evaluation_run_id") or "").strip() for spec in campaigns]
            if any(not run_id for run_id in run_ids) or len(set(run_ids)) != len(run_ids):
                raise ValueError("Model Review Task Group 必须为每个 Campaign 绑定唯一 Model Run。")
            workset_ids = {str(spec.get("workset_id") or "").strip() for spec in campaigns}
            if len(workset_ids) != 1 or not next(iter(workset_ids)):
                raise ValueError("Model Review Task Group 的子 Campaign 必须共享同一冻结 Workset。")
            reference_fingerprints = {
                _fingerprint({
                    "reference_type": str(spec.get("reference_type") or ""),
                    "reference_id": str(spec.get("reference_id") or ""),
                    "references": spec.get("references") or [],
                })
                for spec in campaigns
            }
            if len(reference_fingerprints) != 1:
                raise ValueError("Model Review Task Group 的子 Campaign 必须共享同一标签参考。")
        key = str(idempotency_key or "").strip()[:160]
        fingerprint = _fingerprint({"name": str(name or "").strip(), "purpose": normalized_purpose, "campaigns": campaigns})
        now = utc_now()
        actor_name = str(actor or "").strip()
        if not actor_name:
            raise ValueError("Task Group 创建人不能为空。")
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            if key:
                existing = conn.execute(
                    "SELECT id, idempotency_fingerprint FROM review_task_groups WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    if str(existing["idempotency_fingerprint"] or "") != fingerprint:
                        raise CampaignConflictError("Task Group idempotency key 已用于不同配置。")
                    group_id = str(existing["id"])
                    ids = [str(row["campaign_id"]) for row in conn.execute(
                        "SELECT campaign_id FROM review_task_group_campaigns WHERE group_id = ? ORDER BY ordinal",
                        (group_id,),
                    ).fetchall()]
                    return {"id": group_id, "name": str(name or ""),
                            "campaigns": [self.get_campaign(item) for item in ids]}
            group_id = f"campaign-group-{uuid4().hex}"
            workset_ids = {str(spec.get("workset_id") or "").strip() for spec in campaigns}
            workset_id = next(iter(workset_ids)) if len(workset_ids) == 1 else ""
            workset = conn.execute(
                "SELECT * FROM review_worksets WHERE id = ?", (workset_id,)
            ).fetchone() if workset_id else None
            if workset is None:
                raise ValueError("Task Group 必须绑定已存在的共享 Workset。")
            first_spec = campaigns[0]
            requested_references = first_spec.get("references")
            workset_scope_rows = conn.execute(
                "SELECT baseline_scope FROM review_workset_scopes WHERE workset_id = ? ORDER BY ordinal",
                (workset_id,),
            ).fetchall()
            workset_scopes = [
                str(row["baseline_scope"] or "") for row in workset_scope_rows
                if str(row["baseline_scope"] or "")
            ]
            if not workset_scopes and str(workset["baseline_scope"] or ""):
                workset_scopes = [str(workset["baseline_scope"] or "")]
            reference_specs = {
                str(item.get("baseline_scope") or "").strip(): item
                for item in requested_references or []
                if isinstance(item, dict)
            } if isinstance(requested_references, list) else {}
            group_references = []
            for scope in workset_scopes:
                requested = reference_specs.get(scope, first_spec if len(workset_scopes) == 1 else {})
                group_references.append(self._campaign_reference_for_scope(
                    conn,
                    baseline_scope=scope,
                    reference_type=str(requested.get("reference_type") or ""),
                    reference_id=str(requested.get("reference_id") or ""),
                ))
            if not group_references:
                raise ValueError("Task Group Workset 没有冻结 scope。")
            if len(group_references) == 1:
                group_reference = group_references[0]
            else:
                reference_set_sha = _fingerprint(group_references)
                group_reference = {
                    "baseline_scope": "",
                    "reference_type": "reference_set",
                    "reference_id": f"reference-set:{reference_set_sha}",
                    "reference_sha256": reference_set_sha,
                    "references": group_references,
                }
            reference_summary = [
                {"evaluation_run_id": str(spec.get("evaluation_run_id") or ""),
                 "reference_type": group_reference["reference_type"],
                 "reference_id": group_reference["reference_id"],
                 "references": group_references,
                 "workset_id": str(spec.get("workset_id") or "")}
                for spec in campaigns
            ]
            group_config = {"id": group_id, "name": str(name or "").strip()[:160],
                            "purpose": normalized_purpose, "reference": group_reference,
                            "campaigns": reference_summary}
            config_json = _json(group_config)
            config_sha = _fingerprint(group_config)
            run_ids = [str(spec.get("evaluation_run_id") or "").strip() for spec in campaigns if str(spec.get("evaluation_run_id") or "").strip()]
            conn.execute(
                """
                INSERT INTO review_task_groups (
                    id, purpose, name, lifecycle, config_revision, workset_id,
                    source_run_ids_json, reference_type, reference_id,
                    reference_sha256, idempotency_key, idempotency_fingerprint,
                    created_by, created_by_source, created_by_verified,
                    updated_by, updated_by_source, updated_by_verified,
                    updated_at, created_at
                ) VALUES (?, ?, ?, 'active', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (group_id, normalized_purpose, str(name or "").strip()[:160],
                 workset_id, _json(run_ids), group_reference["reference_type"],
                 group_reference["reference_id"], group_reference["reference_sha256"],
                 key, fingerprint, actor_name, str(actor_source or "legacy"),
                 bool(actor_verified), actor_name, str(actor_source or "legacy"),
                 bool(actor_verified), now, now),
            )
            conn.execute(
                """
                INSERT INTO review_task_group_revisions (
                    group_id, revision_no, config_json, config_sha256,
                    changed_by, changed_by_source, changed_by_verified, changed_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (group_id, config_json, config_sha, actor_name,
                 str(actor_source or "legacy"), bool(actor_verified), now),
            )
            campaign_ids = []
            for ordinal, spec in enumerate(campaigns, 1):
                child_spec = dict(spec)
                child_spec["group_ordinal"] = ordinal
                child_key = f"{key}:{ordinal}" if key else ""
                child_fp = _fingerprint({"group": fingerprint, "ordinal": ordinal, "spec": spec}) if key else ""
                campaign_ids.append(self._campaign_create_in_connection(
                    conn, spec=child_spec, actor=actor_name,
                    actor_source=actor_source, actor_verified=actor_verified,
                    task_group_id=group_id,
                    child_idempotency_key=child_key,
                    child_idempotency_fingerprint=child_fp,
                ))
            self._mark_change_topic(conn, "review")
            if normalized_purpose == "labeling":
                self._mark_change_topic(conn, "labeling")
        return {"id": group_id, "name": str(name or "").strip(),
                "purpose": normalized_purpose,
                "campaigns": [self.get_campaign(item) for item in campaign_ids]}

    def get_campaign_group(self, group_id: str) -> dict[str, Any] | None:
        group_key = str(group_id or "").strip()
        if not group_key:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_task_groups WHERE id = ?", (group_key,)
            ).fetchone()
            if row is None:
                return None
            campaign_rows = conn.execute(
                "SELECT campaign_id, evaluation_run_id, ordinal FROM review_task_group_campaigns "
                "WHERE group_id = ? ORDER BY ordinal, evaluation_run_id",
                (group_key,),
            ).fetchall()
            revisions = conn.execute(
                "SELECT revision_no, config_sha256, changed_by, changed_by_source, "
                "changed_by_verified, changed_at FROM review_task_group_revisions "
                "WHERE group_id = ? ORDER BY revision_no DESC LIMIT 50",
                (group_key,),
            ).fetchall()
            group = {
                "id": str(row["id"]),
                "purpose": str(row["purpose"] or ""),
                "name": str(row["name"] or ""),
                "lifecycle": str(row["lifecycle"] or "active"),
                "config_revision": int(row["config_revision"] or 1),
                "workset_id": str(row["workset_id"] or ""),
                "source_run_ids": _json_load(row["source_run_ids_json"], []),
                "reference_type": str(row["reference_type"] or ""),
                "reference_id": str(row["reference_id"] or ""),
                "reference_sha256": str(row["reference_sha256"] or ""),
                "created_by": str(row["created_by"] or ""),
                "created_by_source": str(row["created_by_source"] or "legacy"),
                "created_by_verified": bool(row["created_by_verified"]),
                "created_at": str(row["created_at"] or ""),
                "updated_by": str(row["updated_by"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "closed_by": str(row["closed_by"] or ""),
                "closed_at": str(row["closed_at"] or ""),
            }
            child_ids = [str(item["campaign_id"]) for item in campaign_rows]
            children = [
                {"campaign_id": str(item["campaign_id"]),
                 "evaluation_run_id": str(item["evaluation_run_id"] or ""),
                 "ordinal": int(item["ordinal"] or 0)}
                for item in campaign_rows
            ]
            revision_list = [
                {"revision_no": int(item["revision_no"]),
                 "config_sha256": str(item["config_sha256"] or ""),
                 "changed_by": str(item["changed_by"] or ""),
                 "changed_by_source": str(item["changed_by_source"] or "legacy"),
                 "changed_by_verified": bool(item["changed_by_verified"]),
                 "changed_at": str(item["changed_at"] or "")}
                for item in revisions
            ]
        return {
            "group": group,
            "children": children,
            "campaigns": [self.get_campaign(item) for item in child_ids],
            "revisions": revision_list,
        }

    def _campaign_refresh_compat_assignment_snapshot(self, conn: Any, campaign_id: str) -> None:
        rows = conn.execute(
            "SELECT issue_id, assignee, assignment_kind, ordinal FROM review_work_assignments "
            "WHERE split_id = ? ORDER BY lower(assignee), issue_id, ordinal",
            (campaign_id,),
        ).fetchall()
        members: dict[str, list[dict[str, Any]]] = defaultdict(list)
        per_issue: dict[str, int] = defaultdict(int)
        for row in rows:
            issue_id = str(row["issue_id"])
            assignee = str(row["assignee"] or "").strip().lower()
            members[assignee].append({
                "issue_id": issue_id,
                "assignment_kind": str(row["assignment_kind"] or "base"),
                "ordinal": int(row["ordinal"] or 1),
            })
            per_issue[issue_id] += 1
        snapshot = [
            {"name": name, "count": len(items), "items": items}
            for name, items in sorted(members.items()) if name
        ]
        conn.execute(
            "UPDATE issue_work_splits SET assignees_json = ?, assignment_count = ?, "
            "reviewers_per_issue = ? WHERE id = ?",
            (_json(snapshot), len(rows), max(per_issue.values(), default=0), campaign_id),
        )

    def get_campaign(
        self,
        campaign_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        assignee: str = "",
        state: str = "all",
        query: str = "",
    ) -> dict[str, Any] | None:
        campaign_key = str(campaign_id or "").strip()
        if not campaign_key:
            return None
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or 50), 5000))
        selected_assignee = str(assignee or "").strip().lower()
        selected_state = str(state or "all").strip().lower()
        if selected_state not in {"all", "pending", "in_progress", "completed", "conflict", "adjudicated", "stale", "blocked", "unassigned", "legacy_read_only"}:
            raise ValueError("Campaign Issue 状态筛选不合法。")
        search = str(query or "").strip().lower()[:128]
        campaign_key = self.resolve_version_campaign(campaign_key)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT split.*, workset.name AS workset_name,
                       workset.baseline_scope AS workset_baseline_scope,
                       workset.member_count AS workset_member_count,
                       workset.members_sha256 AS workset_members_sha256,
                       workset.selection_source_run_id AS workset_selection_source_run_id
                FROM issue_work_splits split
                LEFT JOIN review_worksets workset ON workset.id = split.workset_id
                WHERE split.id = ?
                """,
                (campaign_key,),
            ).fetchone()
            if row is None:
                return None
            campaign = self._campaign_public_dict(row)
            progress = self._campaign_progress_batch(conn, [row], use_cache=True).get(campaign_key, {})
            member_rows = conn.execute(
                "SELECT campaign_id, issue_id, baseline_scope, required_submitter_count, "
                "reviewers_per_issue, ordinal FROM campaign_issue_members "
                "WHERE campaign_id = ? ORDER BY ordinal, issue_id",
                (campaign_key,),
            ).fetchall()
            campaign["baseline_scopes"] = sorted({
                str(member["baseline_scope"] or "") for member in member_rows
                if str(member["baseline_scope"] or "")
            })
            assignment_rows = conn.execute(
                "SELECT issue_id, assignee, assignment_kind, ordinal, assigned_by, assigned_at "
                "FROM review_work_assignments WHERE split_id = ? "
                "ORDER BY issue_id, lower(assignee), ordinal",
                (campaign_key,),
            ).fetchall()
            assignments_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for assignment in assignment_rows:
                assignments_by_issue[str(assignment["issue_id"])].append({
                    "assignee": str(assignment["assignee"] or ""),
                    "assignment_kind": str(assignment["assignment_kind"] or "base"),
                    "ordinal": int(assignment["ordinal"] or 1),
                    "assigned_by": str(assignment["assigned_by"] or ""),
                    "assigned_at": str(assignment["assigned_at"] or ""),
                })
            progress_issues = {
                str(item["issue_id"]): item for item in progress.get("issues", [])
            }
            issue_specs = []
            for member in member_rows:
                issue_id = str(member["issue_id"])
                status = progress_issues.get(issue_id, {})
                if selected_state != "all" and str(status.get("state") or "legacy_read_only") != selected_state:
                    if not (selected_state == "legacy_read_only" and not campaign.get("purpose")):
                        continue
                issue_assignments = assignments_by_issue.get(issue_id, [])
                if selected_assignee and not any(item["assignee"].lower() == selected_assignee for item in issue_assignments):
                    continue
                issue_specs.append({
                    "issue_id": issue_id,
                    "baseline_scope": str(member["baseline_scope"] or ""),
                    "ordinal": int(member["ordinal"] or 0),
                    "required_submitter_count": int(member["required_submitter_count"] or 0),
                    "reviewers_per_issue": int(member["reviewers_per_issue"] or 0),
                    "state": str(status.get("state") or "legacy_read_only"),
                    "submitted": int(status.get("submitted") or 0),
                    "expected_output": str(status.get("expected_output") or ""),
                    "reference_type": str(status.get("reference_type") or ""),
                    "reference_id": str(status.get("reference_id") or ""),
                    "reference_state": str(status.get("reference_state") or "unknown"),
                    "reference_label": str(status.get("reference_label") or ""),
                    "reference_relation": str(status.get("reference_relation") or "unknown"),
                    "tags": list(status.get("tags") or []),
                    "evidence_gaps": list(status.get("evidence_gaps") or []),
                    "is_excluded": bool(status.get("is_excluded")),
                    "rationale_present": bool(status.get("rationale_present")),
                    "source_revision_ids": list(status.get("source_revision_ids") or []),
                    "assignments": issue_assignments,
                })
            if issue_specs:
                issue_ids = [item["issue_id"] for item in issue_specs]
                issue_rows: list[Any] = []
                for offset in range(0, len(issue_ids), 500):
                    batch = issue_ids[offset:offset + 500]
                    issue_rows.extend(conn.execute(
                        f"SELECT issue_id, title, scenario, gt_label, baseline_scope FROM issues "
                        f"WHERE issue_id IN ({', '.join('?' for _ in batch)})",
                        batch,
                    ).fetchall())
                issue_info = {str(item["issue_id"]): item for item in issue_rows}
                for item in issue_specs:
                    info = issue_info.get(item["issue_id"])
                    item["title"] = str(info["title"] or "") if info else ""
                    item["scenario"] = str(info["scenario"] or "") if info else ""
                    item["gt_label"] = str(info["gt_label"] or "") if info else ""
                if search:
                    rationale_issue_ids: set[str] = set()
                    if campaign.get("purpose") == "labeling":
                        rationale_rows = conn.execute(
                            """
                            SELECT DISTINCT label_case.issue_id
                            FROM label_cases label_case
                            JOIN label_revisions revision ON revision.label_case_id = label_case.id
                            JOIN issue_work_splits split ON split.id = label_case.task_id
                            LEFT JOIN review_worksets workset ON workset.id = split.workset_id
                            WHERE label_case.task_id = ?
                              AND LOWER(revision.rationale) LIKE ?
                              AND (COALESCE(NULLIF(workset.selection_source_run_id, ''), split.selection_source_run_id, '') = ''
                                   OR label_case.source_run_id = COALESCE(NULLIF(workset.selection_source_run_id, ''), split.selection_source_run_id, ''))
                            """,
                            (campaign_key, f"%{search}%"),
                        ).fetchall()
                        rationale_issue_ids = {str(item["issue_id"]) for item in rationale_rows}
                    issue_specs = [item for item in issue_specs if (
                        item["issue_id"] in rationale_issue_ids
                        or search in " ".join((item["issue_id"], item["title"], item["scenario"])).lower()
                    )]
            total = len(issue_specs)
            offset = (safe_page - 1) * safe_page_size
            page_issues = issue_specs[offset:offset + safe_page_size]
            revision_rows = conn.execute(
                "SELECT revision_no, config_sha256, changed_by, changed_by_source, "
                "changed_by_verified, change_source, changed_at "
                "FROM campaign_config_revisions WHERE campaign_id = ? "
                "ORDER BY revision_no DESC LIMIT 50",
                (campaign_key,),
            ).fetchall()
            assignment_audit_rows = conn.execute(
                "SELECT id, issue_id, action, assignment_kind, from_assignee, to_assignee, "
                "changed_by, changed_by_source, changed_by_verified, config_revision, "
                "reason, changed_at FROM campaign_assignment_audit "
                "WHERE campaign_id = ? ORDER BY id DESC LIMIT 200",
                (campaign_key,),
            ).fetchall()
            lifecycle_audit_rows = conn.execute(
                "SELECT id, action, from_lifecycle, to_lifecycle, config_revision, "
                "changed_by, changed_by_source, changed_by_verified, snapshot_id, reason, changed_at "
                "FROM campaign_lifecycle_audit WHERE campaign_id = ? "
                "ORDER BY id DESC LIMIT 100",
                (campaign_key,),
            ).fetchall()
            close_snapshot = None
            snapshot_id = str(row["latest_close_snapshot_id"] or "")
            if snapshot_id:
                snapshot = conn.execute(
                    "SELECT * FROM campaign_close_snapshots WHERE id = ?", (snapshot_id,)
                ).fetchone()
                if snapshot is not None:
                    close_snapshot = {
                        "id": str(snapshot["id"]),
                        "config_revision": int(snapshot["config_revision"] or 0),
                        "member_count": int(snapshot["member_count"] or 0),
                        "assigned_issue_count": int(snapshot["assigned_issue_count"] or 0),
                        "required_submitter_count": int(snapshot["required_submitter_count"] or 0),
                        "submitted_submitter_count": int(snapshot["submitted_submitter_count"] or 0),
                        "completed_issue_count": int(snapshot["completed_issue_count"] or 0),
                        "pending_issue_count": int(snapshot["pending_issue_count"] or 0),
                        "conflict_issue_count": int(snapshot["conflict_issue_count"] or 0),
                        "adjudicated_issue_count": int(snapshot["adjudicated_issue_count"] or 0),
                        "stale_issue_count": int(snapshot["stale_issue_count"] or 0),
                        "status_counts": _json_load(snapshot["status_counts_json"], {}),
                        "closed_by": str(snapshot["closed_by"] or ""),
                        "closed_at": str(snapshot["closed_at"] or ""),
                    }
            group = None
            if campaign.get("task_group_id"):
                group_row = conn.execute(
                    "SELECT id, purpose, name, lifecycle, config_revision, created_at "
                    "FROM review_task_groups WHERE id = ?", (campaign["task_group_id"],)
                ).fetchone()
                if group_row is not None:
                    group = {key: group_row[key] for key in group_row.keys()}
        public_progress = {key: value for key, value in progress.items() if key not in {"issues", "assignees"}}
        return {
            "campaign": campaign,
            "progress": public_progress,
            "assignees": progress.get("assignees", []),
            "issues": page_issues,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "page_count": max(1, (total + safe_page_size - 1) // safe_page_size),
            "close_snapshot": close_snapshot,
            "revisions": [
                {"revision_no": int(item["revision_no"]),
                 "config_sha256": str(item["config_sha256"] or ""),
                 "changed_by": str(item["changed_by"] or ""),
                 "changed_by_source": str(item["changed_by_source"] or ""),
                 "changed_by_verified": bool(item["changed_by_verified"]),
                 "change_source": str(item["change_source"] or ""),
                 "changed_at": str(item["changed_at"] or "")}
                for item in revision_rows
            ],
            "assignment_audit": [
                {"id": int(item["id"]),
                 "issue_id": str(item["issue_id"] or ""),
                 "action": str(item["action"] or ""),
                 "assignment_kind": str(item["assignment_kind"] or "base"),
                 "from_assignee": str(item["from_assignee"] or ""),
                 "to_assignee": str(item["to_assignee"] or ""),
                 "changed_by": str(item["changed_by"] or ""),
                 "changed_by_source": str(item["changed_by_source"] or ""),
                 "changed_by_verified": bool(item["changed_by_verified"]),
                 "config_revision": int(item["config_revision"] or 0),
                 "reason": str(item["reason"] or ""),
                 "changed_at": str(item["changed_at"] or "")}
                for item in assignment_audit_rows
            ],
            "lifecycle_audit": [
                {"id": int(item["id"]),
                 "action": str(item["action"] or ""),
                 "from_lifecycle": str(item["from_lifecycle"] or ""),
                 "to_lifecycle": str(item["to_lifecycle"] or ""),
                 "config_revision": int(item["config_revision"] or 0),
                 "changed_by": str(item["changed_by"] or ""),
                 "changed_by_source": str(item["changed_by_source"] or ""),
                 "changed_by_verified": bool(item["changed_by_verified"]),
                 "snapshot_id": str(item["snapshot_id"] or ""),
                 "reason": str(item["reason"] or ""),
                 "changed_at": str(item["changed_at"] or "")}
                for item in lifecycle_audit_rows
            ],
            "task_group": group,
        }

