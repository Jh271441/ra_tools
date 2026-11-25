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


class DatabaseCampaignLegacyMixin:
    """Legacy S4 inventory mapping and reference scope helpers."""

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

