"""Run-independent Campaign metadata and progress storage (S4)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Sequence
from uuid import uuid4

from ..review_analysis import REASON_THEME_CATALOG, classify_review_reason
from .shared import _json, _json_load, utc_now

CAMPAIGN_PURPOSES = {"labeling", "model_review"}
CAMPAIGN_LIFECYCLES = {"draft", "active", "closed", "cancelled", "superseded"}
DISCUSSION_CHANNELS = {"case", "campaign", "model_review", "legacy"}


class CampaignConflictError(RuntimeError):
    """Raised when an optimistic Campaign version is stale."""


class CampaignReadOnlyError(ValueError):
    """Raised when a legacy/closed Campaign cannot accept new mutations."""


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, (dict, list, bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return str(value)


def campaign_inventory_fingerprint(connection: Any) -> str:
    """Hash the legacy inputs used by S4 mapping, never returning raw Issue IDs."""

    source: dict[str, Any] = {}
    queries = {
        "splits": """
            SELECT id, task_kind, model_run_id, workset_id, selection_source_run_id,
                   mode, reviewers_per_issue, overlap_ratio, total_count,
                   assignment_count, assignees_json, created_at
            FROM issue_work_splits ORDER BY id
        """,
        "assignments": """
            SELECT split_id, issue_id, assignee, assignment_kind, ordinal,
                   assigned_by, assigned_at
            FROM review_work_assignments
            WHERE assigned_by <> 's4-migration-snapshot'
            ORDER BY split_id, issue_id, lower(assignee)
        """,
        "worksets": """
            SELECT id, baseline_scope, selection_source_run_id, member_count,
                   members_sha256, source_filter_json
            FROM review_worksets ORDER BY id
        """,
        "workset_items": """
            SELECT workset_id, issue_id, ordinal
            FROM review_workset_items ORDER BY workset_id, ordinal, issue_id
        """,
        "label_cases": """
            SELECT id, baseline_scope, issue_id, task_id, source_run_id, created_at
            FROM label_cases ORDER BY id
        """,
        "label_revisions": """
            SELECT id, label_case_id, expected_output, author, revision_kind,
                   supersedes_id, source_annotation_id, created_at
            FROM label_revisions ORDER BY id
        """,
        "legacy_review_annotations": """
            SELECT id, issue_id, model_run_id, work_split_id, label,
                   review_status, is_excluded, tags_json, missing_evidence_json,
                   note, author, supersedes_id, created_at
            FROM annotations WHERE work_split_id <> '' ORDER BY id
        """,
        "label_comment_links": """
            SELECT comment_id, baseline_scope, issue_id, task_id, source_run_id,
                   policy_version, linked_at
            FROM label_comment_links ORDER BY comment_id
        """,
        "review_comments": """
            SELECT id, issue_id, model_run_id, reply_to_id, author, body, created_at
            FROM review_comments ORDER BY id
        """,
        "model_review_revisions": """
            SELECT id, model_run_id, issue_id, campaign_id, reference_id,
                   work_split_id, status, reviewer, supersedes_id, created_at
            FROM model_review_revisions ORDER BY id
        """,
    }
    for key, sql in queries.items():
        rows = connection.execute(sql).fetchall()
        source[key] = [
            {column: _safe_json_value(row[column]) for column in row.keys()}
            for row in rows
        ]
    return _fingerprint(source)


def _split_snapshot_assignments(value: Any) -> list[dict[str, Any]]:
    members = _json_load(value, [])
    if not isinstance(members, list):
        return []
    result: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        assignee = str(member.get("name") or "").strip().lower()
        if not assignee:
            continue
        items = member.get("items") if isinstance(member.get("items"), list) else []
        if not items:
            items = [{"issue_id": issue_id} for issue_id in member.get("issue_ids") or []]
        for ordinal, item in enumerate(items, 1):
            if not isinstance(item, dict):
                continue
            issue_id = str(item.get("issue_id") or "").strip()
            if not issue_id:
                continue
            result.append(
                {
                    "issue_id": issue_id,
                    "assignee": assignee,
                    "assignment_kind": str(item.get("assignment_kind") or "base"),
                    "ordinal": int(item.get("ordinal") or ordinal),
                }
            )
    return result


class DatabaseCampaignMixin:
    """Unified Campaign read/write domain backed by the legacy split table."""

    _CAMPAIGN_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
    _CAMPAIGN_ASSIGNMENT_KINDS = {"base", "cross", "full"}

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
        if workset is not None:
            if len(scopes) != 1 or scopes[0] != str(workset["baseline_scope"] or ""):
                raise ValueError("Campaign members 与 Workset scope 不匹配。")
            workset_items = conn.execute(
                "SELECT issue_id FROM review_workset_items WHERE workset_id = ? ORDER BY ordinal",
                (workset_id,),
            ).fetchall()
            if {str(row["issue_id"]) for row in workset_items} != set(issue_ids):
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
                reference_type, reference_id, reference_sha256, lifecycle,
                config_revision, created_by_source, created_by_verified,
                updated_by, updated_by_source, updated_by_verified, updated_at,
                legacy_read_only, legacy_mapping_status, idempotency_key,
                idempotency_fingerprint, campaign_name, task_group_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, 1, ?, ?, ?, ?, ?, ?, false, 'native_s4', ?, ?, ?, ?)
            """,
            (
                campaign_id, actor_name, now, spec.get("seed"), len(normalized_members),
                _json(filter_snapshot), _json(assignees_json), mode, max_reviewers,
                evaluation_run_id, overlap_ratio, assignment_count,
                "labeling" if purpose == "labeling" else "s4_model_review",
                workset_id, selection_source_run_id, purpose, evaluation_run_id or None,
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
                "SELECT baseline_scope FROM review_worksets WHERE id = ?", (workset_id,)
            ).fetchone() if workset_id else None
            if workset is None:
                raise ValueError("Task Group 必须绑定已存在的共享 Workset。")
            workset_scope = str(workset["baseline_scope"] or "")
            first_spec = campaigns[0]
            requested_references = first_spec.get("references")
            first_reference_spec: dict[str, Any] = first_spec
            if isinstance(requested_references, list):
                first_reference_spec = next((
                    item for item in requested_references
                    if isinstance(item, dict)
                    and str(item.get("baseline_scope") or "").strip() == workset_scope
                ), {})
            group_reference = self._campaign_reference_for_scope(
                conn,
                baseline_scope=workset_scope,
                reference_type=str(first_reference_spec.get("reference_type") or ""),
                reference_id=str(first_reference_spec.get("reference_id") or ""),
            )
            reference_summary = [
                {"evaluation_run_id": str(spec.get("evaluation_run_id") or ""),
                 "reference_type": group_reference["reference_type"],
                 "reference_id": group_reference["reference_id"],
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
            progress = self._campaign_progress_batch(conn, [row]).get(campaign_key, {})
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
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
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
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
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
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
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
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
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

    @staticmethod
    def _campaign_reference_for_scope(
        conn: Any,
        *,
        baseline_scope: str,
        reference_type: str = "",
        reference_id: str = "",
    ) -> dict[str, str]:
        scope = str(baseline_scope or "").strip()
        kind = str(reference_type or "").strip()
        ref_id = str(reference_id or "").strip()
        if not scope:
            raise ValueError("Campaign reference 必须关联数据集 scope。")
        if not kind and not ref_id:
            row = conn.execute(
                """
                SELECT snapshot.id, snapshot.content_sha256
                FROM gt_snapshot_active active
                JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
                WHERE active.baseline_scope = ?
                """,
                (scope,),
            ).fetchone()
            if row is not None:
                kind, ref_id = "gt_snapshot", str(row["id"])
        if kind == "gt_snapshot":
            row = conn.execute(
                "SELECT id, baseline_scope, content_sha256 FROM gt_snapshots WHERE id = ?",
                (ref_id,),
            ).fetchone()
            if row is None or str(row["baseline_scope"] or "") != scope:
                raise ValueError("GT snapshot 与 Campaign 数据集不匹配。")
            return {"baseline_scope": scope, "reference_type": kind, "reference_id": ref_id,
                    "reference_sha256": str(row["content_sha256"] or "")}
        if kind == "label_result_snapshot":
            row = conn.execute(
                "SELECT id, baseline_scope, content_sha256 FROM label_result_snapshots WHERE id = ?",
                (ref_id,),
            ).fetchone()
            if row is None or str(row["baseline_scope"] or "") != scope:
                raise ValueError("Label snapshot 与 Campaign 数据集不匹配。")
            return {"baseline_scope": scope, "reference_type": kind, "reference_id": ref_id,
                    "reference_sha256": str(row["content_sha256"] or "")}
        raise ValueError("Campaign reference_type 目前只支持 GT 或 Label snapshot。")

    def apply_legacy_campaign_inventory(
        self,
        *,
        inventory: dict[str, Any],
        expected_inventory_sha256: str,
        policy_version: str,
        actor: str,
    ) -> dict[str, Any]:
        """Apply only the read-only dry-run mappings; unresolved rows stay read-only."""

        actor_name = str(actor or "").strip()
        version = str(policy_version or "").strip()
        if not actor_name or not version:
            raise ValueError("迁移人和 policy_version 不能为空。")
        if str(inventory.get("source_inventory_sha256") or "") != str(expected_inventory_sha256):
            raise CampaignConflictError("S4 inventory SHA 与 apply 期望值不一致。")
        split_specs = {
            str(item.get("legacy_split_id") or ""): item
            for item in inventory.get("splits") or []
            if str(item.get("legacy_split_id") or "")
        }
        now = utc_now()
        results: list[dict[str, Any]] = []
        mapped = read_only = already = 0
        placeholders = ", ".join("?" for _ in split_specs)
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            current_fingerprint = campaign_inventory_fingerprint(conn)
            if current_fingerprint != str(expected_inventory_sha256):
                raise CampaignConflictError("S4 legacy data 在 inventory 后发生变化。")
            if not split_specs:
                return {"mapped": 0, "read_only": 0, "already_applied": 0,
                        "inventory_sha256": current_fingerprint, "items": []}
            rows = conn.execute(
                f"SELECT * FROM issue_work_splits WHERE id IN ({placeholders}) ORDER BY id",
                tuple(split_specs),
            ).fetchall()
            if len(rows) != len(split_specs):
                raise CampaignConflictError("S4 inventory 中的旧 split 集合与数据库不一致。")
            for raw in rows:
                split = {key: raw[key] for key in raw.keys()}
                split_id = str(split["id"])
                spec = split_specs[split_id]
                existing = conn.execute(
                    "SELECT campaign_id, mapping_status, source_inventory_sha256 "
                    "FROM campaign_migration_map WHERE source_table = 'issue_work_splits' "
                    "AND source_id = ? AND policy_version = ?",
                    (split_id, version),
                ).fetchone()
                if existing is not None:
                    if str(existing["source_inventory_sha256"] or "") != current_fingerprint:
                        raise CampaignConflictError("已迁移 Campaign 的 source inventory SHA 发生变化。")
                    already += 1
                    results.append({"legacy_split_id": split_id, "status": "already_applied"})
                    continue

                if str(split.get("purpose") or ""):
                    already += 1
                    results.append({
                        "legacy_split_id": split_id,
                        "status": "already_classified",
                        "purpose": str(split.get("purpose") or ""),
                    })
                    continue

                purpose = str(spec.get("proposed_purpose") or "").strip() or None
                mapping_status = "ambiguous_legacy_read_only"
                evidence: list[str] = []
                workset_id = str(split.get("workset_id") or "").strip()
                workset = conn.execute(
                    "SELECT * FROM review_worksets WHERE id = ?", (workset_id,)
                ).fetchone() if workset_id else None
                task_kind = str(split.get("task_kind") or "legacy").strip().lower()
                label_case_count = int(conn.execute(
                    "SELECT COUNT(*) AS n FROM label_cases WHERE task_id = ?", (split_id,)
                ).fetchone()["n"])
                label_comment_count = int(conn.execute(
                    "SELECT COUNT(*) AS n FROM label_comment_links WHERE task_id = ?", (split_id,)
                ).fetchone()["n"])
                model_revision_count = int(conn.execute(
                    "SELECT COUNT(*) AS n FROM model_review_revisions WHERE work_split_id = ?",
                    (split_id,),
                ).fetchone()["n"])
                has_label_evidence = bool(
                    task_kind == "labeling" or workset is not None
                    or label_case_count or label_comment_count
                )
                has_model_evidence = bool(task_kind == "model_review" or model_revision_count)
                if task_kind == "labeling":
                    evidence.append("legacy_task_kind_labeling")
                if task_kind == "model_review":
                    evidence.append("legacy_task_kind_model_review")
                if workset is not None:
                    evidence.append("linked_review_workset")
                if label_case_count:
                    evidence.append("linked_label_cases")
                if label_comment_count:
                    evidence.append("linked_label_discussions")
                if model_revision_count:
                    evidence.append("run_bound_model_review_revisions")
                if has_label_evidence and has_model_evidence:
                    purpose = None
                    mapping_status = "conflicting_evidence_read_only"
                elif purpose == "labeling" and has_label_evidence and not has_model_evidence:
                    mapping_status = "mapped_from_explicit_label_evidence"
                elif purpose == "model_review" and has_model_evidence and not has_label_evidence:
                    mapping_status = "mapped_from_explicit_model_review_evidence"
                elif purpose is not None:
                    purpose = None
                    mapping_status = "purpose_not_supported_by_source_evidence_read_only"
                legacy_run_id = str(split.get("model_run_id") or "").strip()
                evaluation_run_id = ""
                legacy_read_only = purpose is None
                if purpose == "labeling" and workset is None:
                    purpose = None
                    legacy_read_only = True
                    mapping_status = "missing_workset_read_only"
                elif purpose == "model_review":
                    candidate_run = legacy_run_id
                    if not candidate_run:
                        run_ids = conn.execute(
                            "SELECT DISTINCT model_run_id FROM model_review_revisions "
                            "WHERE work_split_id = ? AND model_run_id <> '' ORDER BY model_run_id",
                            (split_id,),
                        ).fetchall()
                        candidate_run = str(run_ids[0]["model_run_id"] or "") if len(run_ids) == 1 else ""
                    if candidate_run and conn.execute(
                        "SELECT 1 FROM model_runs WHERE id = ?", (candidate_run,)
                    ).fetchone() is not None:
                        evaluation_run_id = candidate_run
                    else:
                        purpose = None
                        legacy_read_only = True
                        mapping_status = "missing_evaluation_run_read_only"

                workset_scope = str(workset["baseline_scope"] or "") if workset is not None else ""
                if purpose == "labeling" and workset_scope:
                    selection_source_run_id = str(
                        workset["selection_source_run_id"] or split.get("selection_source_run_id") or ""
                    )
                else:
                    selection_source_run_id = str(split.get("selection_source_run_id") or "")

                assignment_rows = conn.execute(
                    """
                    SELECT split_id, issue_id, lower(trim(assignee)) AS assignee,
                           assignment_kind, ordinal, assigned_by, assigned_at
                    FROM review_work_assignments WHERE split_id = ?
                    ORDER BY issue_id, lower(trim(assignee)), ordinal
                    """,
                    (split_id,),
                ).fetchall()
                assignment_by_issue: dict[str, dict[str, Any]] = {}
                for assignment in assignment_rows:
                    issue = str(assignment["issue_id"] or "")
                    member = assignment_by_issue.setdefault(
                        issue, {"assignees": set(), "kinds": set(), "rows": []}
                    )
                    member["assignees"].add(str(assignment["assignee"] or ""))
                    member["kinds"].add(str(assignment["assignment_kind"] or "base"))
                    member["rows"].append({key: assignment[key] for key in assignment.keys()})
                if not assignment_rows:
                    for assignment in _split_snapshot_assignments(split.get("assignees_json")):
                        issue = assignment["issue_id"]
                        assignment["assigned_by"] = "s4-migration-snapshot"
                        assignment["assigned_at"] = str(split.get("created_at") or now)
                        member = assignment_by_issue.setdefault(
                            issue, {"assignees": set(), "kinds": set(), "rows": []}
                        )
                        member["assignees"].add(assignment["assignee"])
                        member["kinds"].add(assignment["assignment_kind"])
                        member["rows"].append(assignment)
                        conn.execute(
                            """
                            INSERT INTO review_work_assignments (
                                split_id, issue_id, assignee, assignment_kind,
                                ordinal, assigned_by, assigned_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(split_id, issue_id, assignee) DO NOTHING
                            """,
                            (split_id, issue, assignment["assignee"],
                             assignment["assignment_kind"], assignment["ordinal"],
                             assignment["assigned_by"], assignment["assigned_at"]),
                        )

                if workset is not None:
                    member_rows = conn.execute(
                        "SELECT item.issue_id, item.ordinal, issue.baseline_scope "
                        "FROM review_workset_items item JOIN issues issue ON issue.issue_id=item.issue_id "
                        "WHERE item.workset_id=? ORDER BY item.ordinal, item.issue_id",
                        (workset_id,),
                    ).fetchall()
                else:
                    member_rows = conn.execute(
                        f"SELECT issue.issue_id, issue.baseline_scope FROM issues issue "
                        f"WHERE issue.issue_id IN ({', '.join('?' for _ in assignment_by_issue)}) "
                        "ORDER BY issue.baseline_scope, issue.issue_id",
                        tuple(assignment_by_issue),
                    ).fetchall() if assignment_by_issue else []
                member_set = {str(item["issue_id"]) for item in member_rows}
                extra_assigned = set(assignment_by_issue) - member_set
                if extra_assigned:
                    legacy_read_only = True
                    mapping_status = "assignment_snapshot_outside_workset_read_only"
                    purpose = None
                refs: list[dict[str, str]] = []
                scopes = sorted({str(item["baseline_scope"] or "") for item in member_rows if str(item["baseline_scope"] or "")})
                reference_error = False
                for scope in scopes:
                    active_ref = conn.execute(
                        "SELECT snapshot.id, snapshot.content_sha256 FROM gt_snapshot_active active "
                        "JOIN gt_snapshots snapshot ON snapshot.id=active.snapshot_id "
                        "WHERE active.baseline_scope=?",
                        (scope,),
                    ).fetchone()
                    if active_ref is None:
                        reference_error = True
                        continue
                    refs.append({
                        "baseline_scope": scope,
                        "reference_type": "gt_snapshot",
                        "reference_id": str(active_ref["id"]),
                        "reference_sha256": str(active_ref["content_sha256"] or ""),
                    })
                if reference_error or not refs:
                    legacy_read_only = True
                    if purpose is not None:
                        mapping_status = "missing_gt_reference_read_only"
                if purpose is None:
                    legacy_read_only = True
                if refs:
                    if len(refs) == 1:
                        top_reference_type = refs[0]["reference_type"]
                        top_reference_id = refs[0]["reference_id"]
                        top_reference_sha = refs[0]["reference_sha256"]
                    else:
                        top_reference_type = "reference_set"
                        top_reference_id = _fingerprint(refs)
                        top_reference_sha = top_reference_id
                else:
                    top_reference_type = "legacy_unresolved"
                    top_reference_id = split_id
                    top_reference_sha = ""
                if purpose == "model_review" and not evaluation_run_id:
                    purpose = None
                    legacy_read_only = True
                    mapping_status = "missing_evaluation_run_read_only"
                if purpose == "labeling":
                    evaluation_run_id = ""

                conn.execute(
                    """
                    UPDATE issue_work_splits
                    SET purpose = ?, evaluation_run_id = ?, reference_type = ?,
                        reference_id = ?, reference_sha256 = ?, lifecycle = 'active',
                        config_revision = 1, legacy_read_only = ?,
                        legacy_mapping_status = ?, campaign_name = COALESCE(NULLIF(campaign_name, ''), ?),
                        updated_by = ?, updated_by_source = 's4_migration',
                        updated_by_verified = false, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        purpose,
                        evaluation_run_id or None,
                        top_reference_type,
                        top_reference_id,
                        top_reference_sha,
                        bool(legacy_read_only),
                        mapping_status,
                        str(workset["name"] or "") if workset is not None else f"Legacy split {split_id[:12]}",
                        actor_name,
                        now,
                        split_id,
                    ),
                )
                for reference in refs:
                    conn.execute(
                        """
                        INSERT INTO campaign_reference_items (
                            campaign_id, baseline_scope, reference_type,
                            reference_id, reference_sha256, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(campaign_id, baseline_scope) DO NOTHING
                        """,
                        (split_id, reference["baseline_scope"], reference["reference_type"],
                         reference["reference_id"], reference["reference_sha256"], now),
                    )
                member_hash_payload: list[dict[str, Any]] = []
                for ordinal, item in enumerate(member_rows, 1):
                    issue = str(item["issue_id"])
                    assignment = assignment_by_issue.get(issue, {"assignees": set(), "kinds": set(), "rows": []})
                    required = len({name for name in assignment["assignees"] if name})
                    kinds = sorted(assignment["kinds"])
                    conn.execute(
                        """
                        INSERT INTO campaign_issue_members (
                            campaign_id, issue_id, baseline_scope, ordinal,
                            required_submitter_count, reviewers_per_issue,
                            assignment_kinds_json, config_revision, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT(campaign_id, issue_id) DO NOTHING
                        """,
                        (split_id, issue, str(item["baseline_scope"] or ""),
                         int(item["ordinal"] or ordinal) if "ordinal" in item.keys() else ordinal,
                         required, required, _json(kinds), now),
                    )
                    member_hash_payload.append({
                        "issue_id": issue,
                        "baseline_scope": str(item["baseline_scope"] or ""),
                        "required_submitter_count": required,
                        "reviewers_per_issue": required,
                        "assignment_kinds": kinds,
                    })
                    for assignment_row in assignment["rows"]:
                        assignee = str(assignment_row.get("assignee") or "")
                        if not assignee:
                            continue
                        kind = str(assignment_row.get("assignment_kind") or "base")
                        ordinal_value = int(assignment_row.get("ordinal") or 1)
                        assignment_key = _fingerprint([split_id, issue, assignee, kind, ordinal_value])
                        conn.execute(
                            """
                            INSERT INTO campaign_assignment_audit (
                                campaign_id, issue_id, action, assignment_kind,
                                to_assignee, changed_by, changed_by_source,
                                changed_by_verified, config_revision, idempotency_key,
                                reason, changed_at
                            ) VALUES (?, ?, 'legacy_snapshot', ?, ?, ?, 'legacy', false, 1, ?, ?, ?)
                            ON CONFLICT DO NOTHING
                            """,
                            (split_id, issue, kind, assignee,
                             str(assignment_row.get("assigned_by") or ""),
                             "legacy:"+assignment_key,
                             mapping_status, str(assignment_row.get("assigned_at") or now)),
                        )
                members_sha = _fingerprint(member_hash_payload)
                config_count = sum(int(item["required_submitter_count"]) for item in member_hash_payload)
                config = {
                    "campaign_id": split_id,
                    "source_table": "issue_work_splits",
                    "legacy_task_kind": str(split.get("task_kind") or "legacy"),
                    "purpose": purpose,
                    "mapping_status": mapping_status,
                    "mapping_evidence": evidence,
                    "legacy_read_only": legacy_read_only,
                    "workset_id": workset_id,
                    "selection_source_run_id": selection_source_run_id,
                    "evaluation_run_id": evaluation_run_id,
                    "reference_type": top_reference_type,
                    "reference_id": top_reference_id,
                    "reference_sha256": top_reference_sha,
                    "lifecycle": "active",
                    "members_sha256": members_sha,
                    "member_count": len(member_hash_payload),
                    "required_submitter_count": config_count,
                }
                config_json = _json(config)
                config_sha = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    INSERT INTO campaign_config_revisions (
                        campaign_id, revision_no, purpose, workset_id, evaluation_run_id,
                        reference_type, reference_id, lifecycle, member_count,
                        required_submitter_count, members_sha256, config_json,
                        config_sha256, changed_by, changed_by_source,
                        changed_by_verified, change_source, changed_at,
                        idempotency_key, idempotency_fingerprint
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, 's4_migration', false, 'legacy_import', ?, ?, ?)
                    ON CONFLICT(campaign_id, revision_no) DO NOTHING
                    """,
                    (split_id, purpose, workset_id, evaluation_run_id or None,
                     top_reference_type, top_reference_id, len(member_hash_payload),
                     config_count, members_sha, config_json, config_sha, actor_name,
                     now, "legacy:"+split_id, _fingerprint([split_id, current_fingerprint])),
                )
                conn.executemany(
                    """
                    INSERT INTO campaign_config_members (
                        campaign_id, revision_no, issue_id, ordinal,
                        required_submitter_count, reviewers_per_issue, assignment_kinds_json
                    ) VALUES (?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(campaign_id, revision_no, issue_id) DO NOTHING
                    """,
                    [(split_id, item["issue_id"], ordinal,
                      item["required_submitter_count"], item["reviewers_per_issue"],
                      _json(item["assignment_kinds"]))
                     for ordinal, item in enumerate(member_hash_payload, 1)],
                )
                conn.execute(
                    """
                    INSERT INTO campaign_migration_map (
                        source_table, source_id, campaign_id, purpose,
                        mapping_status, mapping_evidence_json,
                        source_inventory_sha256, policy_version, created_at
                    ) VALUES ('issue_work_splits', ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_table, source_id, policy_version) DO NOTHING
                    """,
                    (split_id, split_id, purpose, mapping_status, _json(evidence),
                     current_fingerprint, version, now),
                )
                if legacy_read_only:
                    read_only += 1
                else:
                    mapped += 1
                results.append({"legacy_split_id": split_id, "purpose": purpose,
                                "mapping_status": mapping_status,
                                "read_only": legacy_read_only})
            if hasattr(self, "_mark_change_topic"):
                self._mark_change_topic(conn, "review")
                self._mark_change_topic(conn, "labeling")
        return {"mapped": mapped, "read_only": read_only, "already_applied": already,
                "inventory_sha256": current_fingerprint, "items": results}

    @staticmethod
    def _campaign_reference_relation(output: str, reference: dict[str, str]) -> str:
        if output not in {"误触发", "正确触发", "无需协助"}:
            return "unknown"
        reference_type = str(reference.get("reference_type") or "")
        expected = str(reference.get("reference_label") or "")
        reference_state = str(reference.get("reference_state") or "unknown")
        if reference_type == "gt_snapshot":
            if reference_state == "missing" or not expected:
                return "fills_missing_gt"
            return "matches_gt" if output == expected else "differs_from_gt"
        if reference_type == "label_result_snapshot":
            if reference_state != "resolved" or not expected:
                return "unknown"
            return "matches_reference" if output == expected else "differs_from_reference"
        return "unknown"

    def _campaign_progress_batch(
        self, conn: Any, campaign_rows: Sequence[Any]
    ) -> dict[str, dict[str, Any]]:
        campaigns = {str(row["id"]): row for row in campaign_rows}
        ids = list(campaigns)
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        members = conn.execute(
            f"""
            SELECT member.campaign_id, member.issue_id, member.baseline_scope,
                   member.required_submitter_count, member.reviewers_per_issue,
                   member.ordinal, issue.scenario
            FROM campaign_issue_members member
            JOIN issues issue ON issue.issue_id = member.issue_id
            WHERE member.campaign_id IN ({placeholders})
            ORDER BY member.campaign_id, member.ordinal, member.issue_id
            """,
            ids,
        ).fetchall()
        assignments = conn.execute(
            f"""
            SELECT split_id AS campaign_id, issue_id, lower(trim(assignee)) AS assignee,
                   assignment_kind, ordinal
            FROM review_work_assignments WHERE split_id IN ({placeholders})
            ORDER BY split_id, issue_id, lower(trim(assignee)), ordinal
            """,
            ids,
        ).fetchall()
        reference_items = conn.execute(
            f"SELECT campaign_id, baseline_scope, reference_type, reference_id, reference_sha256 "
            f"FROM campaign_reference_items WHERE campaign_id IN ({placeholders})",
            ids,
        ).fetchall()
        issue_ids_by_scope: dict[tuple[str, str], list[str]] = defaultdict(list)
        for member in members:
            issue_ids_by_scope[(str(member["campaign_id"]), str(member["baseline_scope"] or ""))].append(str(member["issue_id"]))
        reference_by_issue: dict[tuple[str, str], dict[str, str]] = {}
        for reference in reference_items:
            campaign_key = str(reference["campaign_id"])
            scope = str(reference["baseline_scope"] or "")
            reference_type = str(reference["reference_type"] or "")
            reference_id = str(reference["reference_id"] or "")
            issue_ids = issue_ids_by_scope.get((campaign_key, scope), [])
            if not issue_ids:
                continue
            for offset in range(0, len(issue_ids), 500):
                batch = issue_ids[offset:offset + 500]
                batch_placeholders = ", ".join("?" for _ in batch)
                if reference_type == "gt_snapshot":
                    for issue_id in batch:
                        reference_by_issue[(campaign_key, issue_id)] = {
                            "reference_type": reference_type,
                            "reference_id": reference_id,
                            "reference_state": "missing",
                            "reference_label": "",
                        }
                    reference_rows = conn.execute(
                        f"SELECT issue_id, gt_label FROM gt_snapshot_items "
                        f"WHERE snapshot_id = ? AND issue_id IN ({batch_placeholders})",
                        (reference_id, *batch),
                    ).fetchall()
                    for ref_row in reference_rows:
                        reference_by_issue[(campaign_key, str(ref_row["issue_id"]))] = {
                            "reference_type": reference_type,
                            "reference_id": reference_id,
                            "reference_state": "resolved" if str(ref_row["gt_label"] or "") else "missing",
                            "reference_label": str(ref_row["gt_label"] or ""),
                        }
                elif reference_type == "label_result_snapshot":
                    for issue_id in batch:
                        reference_by_issue[(campaign_key, issue_id)] = {
                            "reference_type": reference_type,
                            "reference_id": reference_id,
                            "reference_state": "unknown",
                            "reference_label": "",
                        }
                    reference_rows = conn.execute(
                        f"SELECT issue_id, state, expected_output FROM label_result_snapshot_items "
                        f"WHERE snapshot_id = ? AND baseline_scope = ? AND issue_id IN ({batch_placeholders})",
                        (reference_id, scope, *batch),
                    ).fetchall()
                    for ref_row in reference_rows:
                        ref_state = str(ref_row["state"] or "unknown")
                        ref_label = str(ref_row["expected_output"] or "") if ref_state == "resolved" else ""
                        reference_by_issue[(campaign_key, str(ref_row["issue_id"]))] = {
                            "reference_type": reference_type,
                            "reference_id": reference_id,
                            "reference_state": ref_state,
                            "reference_label": ref_label,
                        }
        member_by_campaign: dict[str, list[Any]] = defaultdict(list)
        member_by_issue: dict[tuple[str, str], Any] = {}
        for member in members:
            cid = str(member["campaign_id"])
            issue = str(member["issue_id"])
            member_by_campaign[cid].append(member)
            member_by_issue[(cid, issue)] = member
        assignment_by_issue: dict[tuple[str, str], set[str]] = defaultdict(set)
        assignee_counts: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
        for assignment in assignments:
            cid = str(assignment["campaign_id"])
            issue = str(assignment["issue_id"])
            name = str(assignment["assignee"] or "").strip().lower()
            if not name:
                continue
            assignment_by_issue[(cid, issue)].add(name)
            assignee_counts[cid].setdefault(name, {
                "assigned_slots": 0,
                "submitted_slots": 0,
                "completed_slots": 0,
                "label_output_counts": {label: 0 for label in ("误触发", "正确触发", "无需协助")},
                "reference_relation_counts": {state: 0 for state in ("matches_gt", "differs_from_gt", "fills_missing_gt", "matches_reference", "differs_from_reference", "unknown")},
            })
            assignee_counts[cid][name]["assigned_slots"] += 1

        label_ids = [cid for cid, row in campaigns.items() if str(row["purpose"] or "") == "labeling"]
        label_heads_by_case: dict[str, list[Any]] = defaultdict(list)
        resolutions_by_case: dict[str, Any] = {}
        if label_ids:
            label_placeholders = ", ".join("?" for _ in label_ids)
            head_rows = conn.execute(
                f"""
                WITH ranked AS (
                    SELECT label_case.task_id AS campaign_id,
                           label_case.id AS label_case_id,
                           label_case.issue_id,
                           label_revision.id AS revision_id,
                           lower(label_revision.author) AS author,
                           label_revision.expected_output,
                           label_revision.tags_json,
                           label_revision.evidence_gaps_json,
                           label_revision.rationale,
                           label_revision.is_excluded,
                           label_revision.revision_kind,
                           ROW_NUMBER() OVER (
                               PARTITION BY label_case.id, lower(label_revision.author)
                               ORDER BY label_revision.id DESC
                           ) AS row_number
                    FROM label_cases label_case
                    JOIN issue_work_splits split ON split.id = label_case.task_id
                    LEFT JOIN review_worksets workset ON workset.id = split.workset_id
                    JOIN label_revisions label_revision
                      ON label_revision.label_case_id = label_case.id
                    WHERE label_case.task_id IN ({label_placeholders})
                      AND split.purpose = 'labeling'
                      AND label_revision.revision_kind IN ('submission', 'legacy')
                      AND (COALESCE(NULLIF(workset.selection_source_run_id, ''), split.selection_source_run_id, '') = ''
                           OR label_case.source_run_id = COALESCE(NULLIF(workset.selection_source_run_id, ''), split.selection_source_run_id, ''))
                )
                SELECT campaign_id, label_case_id, issue_id, revision_id,
                       author, expected_output, tags_json, evidence_gaps_json,
                       rationale, is_excluded, revision_kind
                FROM ranked WHERE row_number = 1
                """,
                label_ids,
            ).fetchall()
            for row in head_rows:
                label_heads_by_case[str(row["label_case_id"])].append(row)
            resolution_rows = conn.execute(
                f"""
                WITH relevant AS (
                    SELECT label_case.id AS label_case_id
                    FROM label_cases label_case
                    JOIN issue_work_splits split ON split.id = label_case.task_id
                    LEFT JOIN review_worksets workset ON workset.id = split.workset_id
                    WHERE label_case.task_id IN ({label_placeholders})
                      AND split.purpose = 'labeling'
                      AND (COALESCE(NULLIF(workset.selection_source_run_id, ''), split.selection_source_run_id, '') = ''
                           OR label_case.source_run_id = COALESCE(NULLIF(workset.selection_source_run_id, ''), split.selection_source_run_id, ''))
                ), ranked AS (
                    SELECT resolution.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY resolution.label_case_id
                               ORDER BY resolution.id DESC
                           ) AS row_number
                    FROM label_resolutions resolution
                    JOIN relevant ON relevant.label_case_id = resolution.label_case_id
                )
                SELECT ranked.label_case_id, ranked.id, ranked.result_revision_id,
                       ranked.source_revision_ids_json
                FROM ranked WHERE ranked.row_number = 1
                """,
                label_ids,
            ).fetchall()
            resolutions_by_case = {str(row["label_case_id"]): row for row in resolution_rows}
            result_revision_ids = sorted({
                int(row["result_revision_id"])
                for row in resolution_rows
                if row["result_revision_id"] not in (None, "")
            })
            result_revisions_by_id: dict[int, Any] = {}
            for offset in range(0, len(result_revision_ids), 400):
                batch = result_revision_ids[offset:offset + 400]
                result_rows = conn.execute(
                    f"SELECT id, label_case_id, expected_output, tags_json, evidence_gaps_json, rationale, is_excluded "
                    f"FROM label_revisions WHERE id IN ({', '.join('?' for _ in batch)})",
                    batch,
                ).fetchall()
                result_revisions_by_id.update({int(row["id"]): row for row in result_rows})

        model_ids = [cid for cid, row in campaigns.items() if str(row["purpose"] or "") == "model_review"]
        model_heads: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
        if model_ids:
            model_placeholders = ", ".join("?" for _ in model_ids)
            head_rows = conn.execute(
                f"""
                SELECT split.id AS campaign_id, revision.issue_id,
                       lower(revision.reviewer) AS reviewer, revision.status,
                       revision.id AS revision_id, revision.model_run_id,
                       head.campaign_id AS head_campaign_id,
                       head.reference_id AS head_reference_id
                FROM issue_work_splits split
                JOIN model_review_heads head
                  ON head.campaign_id = split.id
                  OR EXISTS (
                      SELECT 1 FROM model_review_revisions legacy_revision
                      WHERE legacy_revision.id = head.revision_id
                        AND legacy_revision.work_split_id = split.id
                  )
                JOIN model_review_revisions revision ON revision.id = head.revision_id
                WHERE split.id IN ({model_placeholders})
                  AND revision.model_run_id = split.evaluation_run_id
                  AND (head.campaign_id = split.id OR head.campaign_id = '')
                  AND (head.reference_id = split.reference_id OR head.reference_id = '')
                """,
                model_ids,
            ).fetchall()
            for row in head_rows:
                cid = str(row["campaign_id"])
                issue = str(row["issue_id"])
                reviewer = str(row["reviewer"] or "").lower()
                model_heads[(cid, issue)][reviewer] = {
                    "status": str(row["status"] or "pending"),
                    "revision_id": int(row["revision_id"]),
                }

        progress: dict[str, dict[str, Any]] = {}
        for cid, campaign in campaigns.items():
            purpose = str(campaign["purpose"] or "")
            summary: dict[str, Any] = {
                "campaign_id": cid,
                "purpose": purpose or None,
                "lifecycle": str(campaign["lifecycle"] or "active"),
                "legacy_read_only": bool(campaign["legacy_read_only"]),
                "member_count": len(member_by_campaign.get(cid, [])),
                "assigned_issue_count": 0,
                "unassigned_issue_count": 0,
                "required_submitter_count": 0,
                "submitted_submitter_count": 0,
                "completed_issue_count": 0,
                "pending_issue_count": 0,
                "in_progress_issue_count": 0,
                "conflict_issue_count": 0,
                "adjudicated_issue_count": 0,
                "stale_issue_count": 0,
                "blocked_issue_count": 0,
                "state_counts": {key: 0 for key in ("pending", "in_progress", "completed", "conflict", "adjudicated", "stale", "blocked", "unassigned")},
                "label_output_counts": {label: 0 for label in ("误触发", "正确触发", "无需协助")},
                "reference_relation_counts": {state: 0 for state in ("matches_gt", "differs_from_gt", "fills_missing_gt", "matches_reference", "differs_from_reference", "unknown")},
                "tag_counts": {},
                "evidence_gap_counts": {},
                "scenario_counts": {},
                "excluded_issue_count": 0,
                "rationale_issue_count": 0,
                "unclustered_rationale_issue_count": 0,
                "rationale_theme_counts": {},
                "rationale_theme_catalog": [
                    {"key": str(item["key"]), "label": str(item["label"]),
                     "description": str(item["description"])}
                    for item in REASON_THEME_CATALOG
                ],
                "assignees": [],
                "issues": [],
            }
            if purpose not in CAMPAIGN_PURPOSES:
                summary["state"] = "legacy_read_only"
                progress[cid] = summary
                continue
            for member in member_by_campaign.get(cid, []):
                issue = str(member["issue_id"])
                required = int(member["required_submitter_count"] or 0)
                names = assignment_by_issue.get((cid, issue), set())
                reference = reference_by_issue.get((cid, issue), {
                    "reference_type": "",
                    "reference_id": "",
                    "reference_state": "unknown",
                    "reference_label": "",
                })
                if not names and required:
                    summary["state_counts"]["pending"] += 1
                    summary["pending_issue_count"] += 1
                    summary["required_submitter_count"] += required
                    summary["assigned_issue_count"] += 1
                    summary["issues"].append({"issue_id": issue, "state": "pending", "required": required, "submitted": 0, "expected_output": "", **reference, "reference_relation": "unknown", "source_revision_ids": []})
                    continue
                if required <= 0:
                    summary["unassigned_issue_count"] += 1
                    summary["state_counts"]["unassigned"] += 1
                    summary["issues"].append({"issue_id": issue, "state": "unassigned", "required": 0, "submitted": 0, "expected_output": "", **reference, "reference_relation": "unknown", "source_revision_ids": []})
                    continue
                summary["assigned_issue_count"] += 1
                summary["required_submitter_count"] += required
                state = "pending"
                submitted_names: set[str] = set()
                source_revision_ids: list[int] = []
                issue_tags: set[str] = set()
                issue_evidence_gaps: set[str] = set()
                issue_excluded = False
                issue_has_rationale = False
                issue_rationale_themes: set[str] = set()
                if purpose == "labeling":
                    case_ids = [
                        case_id for case_id, case_heads in label_heads_by_case.items()
                        if case_heads and str(case_heads[0]["campaign_id"]) == cid
                        and str(case_heads[0]["issue_id"]) == issue
                    ]
                    outputs: set[str] = set()
                    assignee_outputs: dict[str, set[str]] = defaultdict(set)
                    adjudicated = False
                    adjudicated_output = ""
                    stale_resolution = False
                    for case_id in case_ids:
                        assigned_heads = [
                            head for head in label_heads_by_case[case_id]
                            if str(head["author"] or "").lower() in names
                        ]
                        case_head_ids = sorted(int(head["revision_id"]) for head in assigned_heads)
                        source_revision_ids.extend(case_head_ids)
                        submitted_names.update(str(head["author"] or "").lower() for head in assigned_heads)
                        outputs.update(
                            str(head["expected_output"] or "")
                            for head in assigned_heads
                            if str(head["expected_output"] or "") in {"误触发", "正确触发", "无需协助"}
                        )
                        for head in assigned_heads:
                            output = str(head["expected_output"] or "")
                            author = str(head["author"] or "").lower()
                            issue_tags.update(
                                str(value) for value in _json_load(head["tags_json"], [])
                                if str(value or "").strip()
                            )
                            issue_evidence_gaps.update(
                                str(value) for value in _json_load(head["evidence_gaps_json"], [])
                                if str(value or "").strip()
                            )
                            issue_excluded = issue_excluded or bool(head["is_excluded"])
                            issue_has_rationale = issue_has_rationale or bool(str(head["rationale"] or "").strip())
                            issue_rationale_themes.update(
                                str(theme["key"])
                                for theme in classify_review_reason(head["rationale"])
                            )
                            if output in {"误触发", "正确触发", "无需协助"} and author:
                                assignee_outputs[author].add(output)
                        resolution = resolutions_by_case.get(case_id)
                        if resolution is not None:
                            expected_sources = sorted(int(value) for value in _json_load(resolution["source_revision_ids_json"], []) if int(value) > 0)
                            result_row = result_revisions_by_id.get(int(resolution["result_revision_id"]))
                            result_exists = bool(
                                result_row is not None
                                and str(result_row["label_case_id"] or "") == case_id
                            )
                            if expected_sources == case_head_ids and result_exists:
                                adjudicated = True
                                if result_row and str(result_row["expected_output"] or "") in {"误触发", "正确触发", "无需协助"}:
                                    adjudicated_output = str(result_row["expected_output"])
                                    outputs = {adjudicated_output}
                                    issue_tags = {
                                        str(value) for value in _json_load(result_row["tags_json"], [])
                                        if str(value or "").strip()
                                    }
                                    issue_evidence_gaps = {
                                        str(value) for value in _json_load(result_row["evidence_gaps_json"], [])
                                        if str(value or "").strip()
                                    }
                                    issue_excluded = bool(result_row["is_excluded"])
                                    issue_has_rationale = bool(str(result_row["rationale"] or "").strip())
                                    issue_rationale_themes = {
                                        str(theme["key"])
                                        for theme in classify_review_reason(result_row["rationale"])
                                    }
                            else:
                                stale_resolution = True
                    submitted = len(submitted_names)
                    if stale_resolution:
                        state = "stale"
                    elif adjudicated:
                        state = "adjudicated"
                    elif len(outputs) > 1:
                        state = "conflict"
                    elif submitted >= required and len(outputs) == 1:
                        state = "completed"
                    elif submitted:
                        state = "in_progress"
                else:
                    heads = model_heads.get((cid, issue), {})
                    assigned_statuses = {
                        reviewer: value["status"] for reviewer, value in heads.items()
                        if reviewer in names
                    }
                    source_revision_ids = [int(heads[reviewer]["revision_id"]) for reviewer in sorted(assigned_statuses)]
                    submitted_names = {
                        reviewer for reviewer, status in assigned_statuses.items()
                        if status in {"in_progress", "completed", "blocked_by_label"}
                    }
                    if any(status == "blocked_by_label" for status in assigned_statuses.values()):
                        state = "blocked"
                    elif len([name for name, status in assigned_statuses.items() if status == "completed"]) >= required:
                        state = "completed"
                    elif any(status == "in_progress" for status in assigned_statuses.values()):
                        state = "in_progress"
                    else:
                        state = "pending"
                    submitted = len(submitted_names)
                summary["submitted_submitter_count"] += submitted
                summary["state_counts"][state] += 1
                key = {
                    "completed": "completed_issue_count",
                    "pending": "pending_issue_count",
                    "in_progress": "in_progress_issue_count",
                    "conflict": "conflict_issue_count",
                    "adjudicated": "adjudicated_issue_count",
                    "stale": "stale_issue_count",
                    "blocked": "blocked_issue_count",
                }.get(state)
                if key:
                    summary[key] += 1
                expected_output = (
                    adjudicated_output if purpose == "labeling" and adjudicated_output
                    else next(iter(outputs)) if purpose == "labeling" and len(outputs) == 1
                    else ""
                ) if purpose == "labeling" else ""
                reference_relation = self._campaign_reference_relation(expected_output, reference)
                if purpose == "labeling":
                    if expected_output:
                        summary["label_output_counts"][expected_output] += 1
                        summary["reference_relation_counts"][reference_relation] += 1
                    for tag in issue_tags:
                        summary["tag_counts"][tag] = int(summary["tag_counts"].get(tag, 0)) + 1
                    for gap in issue_evidence_gaps:
                        summary["evidence_gap_counts"][gap] = int(summary["evidence_gap_counts"].get(gap, 0)) + 1
                    scenario = str(member["scenario"] or "").strip()
                    if scenario:
                        summary["scenario_counts"][scenario] = int(summary["scenario_counts"].get(scenario, 0)) + 1
                    if issue_excluded:
                        summary["excluded_issue_count"] += 1
                    if issue_has_rationale:
                        summary["rationale_issue_count"] += 1
                    if issue_has_rationale and not issue_rationale_themes:
                        summary["unclustered_rationale_issue_count"] += 1
                    for theme in issue_rationale_themes:
                        summary["rationale_theme_counts"][theme] = int(
                            summary["rationale_theme_counts"].get(theme, 0)
                        ) + 1
                summary["issues"].append({
                    "issue_id": issue,
                    "state": state,
                    "required": required,
                    "submitted": submitted,
                    "expected_output": expected_output,
                    **reference,
                    "reference_relation": reference_relation,
                    "tags": sorted(issue_tags) if purpose == "labeling" else [],
                    "evidence_gaps": sorted(issue_evidence_gaps) if purpose == "labeling" else [],
                    "is_excluded": bool(issue_excluded) if purpose == "labeling" else False,
                    "rationale_present": bool(issue_has_rationale) if purpose == "labeling" else False,
                    "source_revision_ids": sorted(set(source_revision_ids)),
                })
                for name in names:
                    assignee = assignee_counts[cid].setdefault(name, {
                        "assigned_slots": 0,
                        "submitted_slots": 0,
                        "completed_slots": 0,
                        "label_output_counts": {label: 0 for label in ("误触发", "正确触发", "无需协助")},
                        "reference_relation_counts": {relation: 0 for relation in ("matches_gt", "differs_from_gt", "fills_missing_gt", "matches_reference", "differs_from_reference", "unknown")},
                    })
                    if name in submitted_names:
                        assignee["submitted_slots"] += 1
                    if state in {"completed", "adjudicated"} and name in submitted_names:
                        assignee["completed_slots"] += 1
                    if purpose == "labeling":
                        for label in assignee_outputs.get(name, set()):
                            assignee["label_output_counts"][label] += 1
                            assignee["reference_relation_counts"][self._campaign_reference_relation(label, reference)] += 1
            summary["assignees"] = [
                {"name": name, **counts}
                for name, counts in sorted(assignee_counts.get(cid, {}).items())
            ]
            summary["completion_ratio"] = (
                round(summary["completed_issue_count"] / summary["assigned_issue_count"], 4)
                if summary["assigned_issue_count"] else 0.0
            )
            summary["state"] = (
                "conflict" if summary["conflict_issue_count"] else
                "blocked" if summary["blocked_issue_count"] else
                "pending" if summary["pending_issue_count"] or summary["in_progress_issue_count"] else
                "completed"
            )
            progress[cid] = summary
        return progress

    def list_campaigns(
        self,
        *,
        baseline_scopes: Sequence[str] | None = None,
        purpose: str = "",
        lifecycle: str = "all",
        task_group_id: str = "",
        include_legacy: bool = True,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        scopes = self._normalize_baseline_scopes(baseline_scopes)
        normalized_purpose = str(purpose or "").strip().lower()
        normalized_lifecycle = str(lifecycle or "all").strip().lower()
        if normalized_purpose and normalized_purpose not in CAMPAIGN_PURPOSES:
            raise ValueError("Campaign purpose 不合法。")
        if normalized_lifecycle not in {"all", *CAMPAIGN_LIFECYCLES}:
            raise ValueError("Campaign lifecycle 不合法。")
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or 50), 100))
        where = ["1 = 1"]
        params: list[Any] = []
        if normalized_purpose:
            where.append("split.purpose = ?")
            params.append(normalized_purpose)
        if normalized_lifecycle != "all":
            where.append("split.lifecycle = ?")
            params.append(normalized_lifecycle)
        if task_group_id:
            where.append("split.task_group_id = ?")
            params.append(str(task_group_id).strip())
        if not include_legacy:
            where.append("split.purpose IS NOT NULL AND split.legacy_read_only = ?")
            params.append(False)
        if scopes:
            placeholders = ", ".join("?" for _ in scopes)
            where.append(
                f"EXISTS (SELECT 1 FROM campaign_issue_members member "
                f"WHERE member.campaign_id = split.id AND member.baseline_scope IN ({placeholders}))"
            )
            params.extend(scopes)
        term = str(query or "").strip()[:128]
        if term:
            where.append("(split.id LIKE ? OR split.campaign_name LIKE ? OR workset.name LIKE ?)")
            pattern = f"%{term}%"
            params.extend([pattern, pattern, pattern])
        clause = " AND ".join(where)
        with self.connect() as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) AS n FROM issue_work_splits split "
                f"LEFT JOIN review_worksets workset ON workset.id=split.workset_id WHERE {clause}",
                params,
            ).fetchone()["n"])
            offset = (safe_page - 1) * safe_page_size
            rows = conn.execute(
                f"""
                SELECT split.*, workset.name AS workset_name,
                       workset.baseline_scope AS workset_baseline_scope,
                       workset.member_count AS workset_member_count,
                       workset.members_sha256 AS workset_members_sha256,
                       workset.selection_source_run_id AS workset_selection_source_run_id
                FROM issue_work_splits split
                LEFT JOIN review_worksets workset ON workset.id=split.workset_id
                WHERE {clause}
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, safe_page_size, offset),
            ).fetchall()
            progress = self._campaign_progress_batch(conn, rows)
            scopes_by_campaign: dict[str, list[str]] = defaultdict(list)
            ids = [str(row["id"]) for row in rows]
            if ids:
                placeholders = ", ".join("?" for _ in ids)
                scope_rows = conn.execute(
                    f"SELECT campaign_id, baseline_scope FROM campaign_issue_members "
                    f"WHERE campaign_id IN ({placeholders}) GROUP BY campaign_id, baseline_scope "
                    f"ORDER BY campaign_id, baseline_scope",
                    ids,
                ).fetchall()
                for row in scope_rows:
                    scopes_by_campaign[str(row["campaign_id"])].append(str(row["baseline_scope"] or ""))
        items: list[dict[str, Any]] = []
        for row in rows:
            cid = str(row["id"])
            item = self._campaign_public_dict(row)
            item["baseline_scopes"] = [scope for scope in scopes_by_campaign.get(cid, []) if scope]
            summary = progress.get(cid, {})
            item["progress"] = {
                key: value for key, value in summary.items()
                if key not in {
                    "issues", "assignees", "label_output_counts",
                    "reference_relation_counts", "tag_counts",
                    "evidence_gap_counts", "scenario_counts",
                    "excluded_issue_count", "rationale_issue_count",
                }
            }
            item["workload"] = [
                {key: value for key, value in person.items()
                 if key in {"assigned_slots", "submitted_slots", "completed_slots"}}
                for person in summary.get("assignees", [])
            ]
            items.append(item)
        return {"items": items, "total": total, "page": safe_page, "page_size": safe_page_size,
                "page_count": max(1, (total + safe_page_size - 1) // safe_page_size)}

    @staticmethod
    def _campaign_public_dict(row: Any) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": str(row["id"]),
            "campaign_id": str(row["id"]),
            "canonical_url": f"/campaigns/{row['id']}",
            "name": str(row["campaign_name"] or row["workset_name"] or ""),
            "purpose": str(row["purpose"] or "") or None,
            "legacy_read_only": bool(row["legacy_read_only"]),
            "legacy_mapping_status": str(row["legacy_mapping_status"] or ""),
            "lifecycle": str(row["lifecycle"] or "active"),
            "config_revision": int(row["config_revision"] or 1),
            "workset_id": str(row["workset_id"] or ""),
            "workset_name": str(row["workset_name"] or ""),
            "workset_baseline_scope": str(row["workset_baseline_scope"] or ""),
            "workset_member_count": int(row["workset_member_count"] or 0),
            "workset_members_sha256": str(row["workset_members_sha256"] or ""),
            "selection_source_run_id": str(row["workset_selection_source_run_id"] or row["selection_source_run_id"] or ""),
            "evaluation_run_id": str(row["evaluation_run_id"] or ""),
            "reference_type": str(row["reference_type"] or ""),
            "reference_id": str(row["reference_id"] or ""),
            "reference_sha256": str(row["reference_sha256"] or ""),
            "task_group_id": str(row["task_group_id"] or ""),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy") if "created_by_source" in keys else "legacy",
            "created_by_verified": bool(row["created_by_verified"]) if "created_by_verified" in keys else False,
            "created_at": str(row["created_at"] or ""),
            "updated_by": str(row["updated_by"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "closed_by": str(row["closed_by"] or ""),
            "closed_at": str(row["closed_at"] or ""),
            "closed_revision": int(row["closed_revision"] or 0),
            "latest_close_snapshot_id": str(row["latest_close_snapshot_id"] or ""),
        }
