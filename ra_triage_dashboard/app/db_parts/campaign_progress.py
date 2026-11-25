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


class DatabaseCampaignProgressMixin:
    """Watermark-cached campaign progress batching and public campaign listing."""

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

    def _campaign_progress_watermark(self, conn: Any) -> tuple[Any, ...] | None:
        row = conn.execute(
            """
            SELECT
                (SELECT revision FROM dashboard_change_revision WHERE id = 1) AS rev,
                (SELECT COUNT(*) FROM combined_review_progress) AS cp_n,
                (SELECT MAX(updated_at) FROM combined_review_progress) AS cp_m,
                (SELECT COUNT(*) FROM human_assignment_roles) AS hr_n,
                (SELECT COUNT(*) FROM label_import_suppressed_revisions) AS sup_n,
                (SELECT COUNT(*) FROM campaign_issue_members) AS cim_n,
                (SELECT COUNT(*) FROM campaign_reference_items) AS cri_n,
                (SELECT COUNT(*) FROM label_cases) AS lc_n,
                (SELECT COALESCE(MAX(id), 0) FROM label_revisions) AS lr_max,
                (SELECT COUNT(*) FROM label_revisions) AS lr_n,
                (SELECT COALESCE(MAX(id), 0) FROM label_resolutions) AS lres_max,
                (SELECT COUNT(*) FROM label_resolutions) AS lres_n,
                (SELECT COALESCE(MAX(id), 0) FROM model_review_revisions) AS mr_max,
                (SELECT COUNT(*) FROM model_review_heads) AS mh_n,
                (SELECT MAX(updated_at) FROM model_review_heads) AS mh_m
            """
        ).fetchone()
        if row is None:
            return None
        return (
            int(row["rev"] or 0),
            int(row["cp_n"] or 0),
            str(row["cp_m"] or ""),
            int(row["hr_n"] or 0),
            int(row["sup_n"] or 0),
            int(row["cim_n"] or 0),
            int(row["cri_n"] or 0),
            int(row["lc_n"] or 0),
            int(row["lr_max"] or 0),
            int(row["lr_n"] or 0),
            int(row["lres_max"] or 0),
            int(row["lres_n"] or 0),
            int(row["mr_max"] or 0),
            int(row["mh_n"] or 0),
            str(row["mh_m"] or ""),
        )

    @staticmethod
    def _campaign_row_cache_signature(row: Any) -> tuple[Any, ...]:
        keys = set(row.keys())
        def _val(name: str, default: Any = "") -> Any:
            return row[name] if name in keys else default
        return (
            str(_val("id", "")),
            str(_val("lifecycle", "") or ""),
            str(_val("purpose", "") or ""),
            str(_val("workflow_mode", "") or ""),
            bool(_val("legacy_read_only", False)),
            int(_val("config_revision", 0) or 0),
            str(_val("updated_at", "") or ""),
            str(_val("evaluation_run_id", "") or ""),
            str(_val("reference_id", "") or ""),
            str(_val("workset_id", "") or ""),
            str(_val("selection_source_run_id", "") or ""),
        )

    def _campaign_progress_batch(
        self, conn: Any, campaign_rows: Sequence[Any], *, use_cache: bool = False
    ) -> dict[str, dict[str, Any]]:
        campaigns = {str(row["id"]): row for row in campaign_rows}
        ids = list(campaigns)
        if not ids:
            return {}
        cache_key: tuple[Any, ...] | None = None
        if use_cache:
            watermark = self._campaign_progress_watermark(conn)
            if watermark is not None:
                row_sig = tuple(
                    sorted(self._campaign_row_cache_signature(row) for row in campaign_rows)
                )
                cache_key = (watermark, row_sig)
                with self._campaign_progress_cache_lock:
                    cached = self._campaign_progress_cache.get(cache_key)
                    if cached is not None:
                        self._campaign_progress_cache.move_to_end(cache_key)
                        return copy.deepcopy(cached)
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
        combined_progress: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
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
                JOIN model_review_revisions revision
                  ON revision.model_run_id = split.evaluation_run_id
                JOIN model_review_heads head
                  ON head.revision_id = revision.id
                WHERE split.id IN ({model_placeholders})
                  AND (head.campaign_id = split.id OR revision.work_split_id = split.id)
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
            combined_rows = conn.execute(
                f"""
                SELECT * FROM combined_review_progress
                WHERE campaign_id IN ({model_placeholders})
                """,
                model_ids,
            ).fetchall()
            for row in combined_rows:
                combined_progress[(str(row["campaign_id"]), str(row["issue_id"]))][
                    str(row["reviewer"] or "").lower()
                ] = {key: row[key] for key in row.keys()}

        progress: dict[str, dict[str, Any]] = {}
        for cid, campaign in campaigns.items():
            purpose = str(campaign["purpose"] or "")
            summary: dict[str, Any] = {
                "campaign_id": cid,
                "purpose": purpose or None,
                "workflow_mode": str(campaign["workflow_mode"] or "model_review_only"),
                "lifecycle": str(campaign["lifecycle"] or "active"),
                "legacy_read_only": bool(campaign["legacy_read_only"]),
                "member_count": len(member_by_campaign.get(cid, [])),
                "assigned_issue_count": 0,
                "unassigned_issue_count": 0,
                "required_submitter_count": 0,
                "submitted_submitter_count": 0,
                "model_review_submitted_count": 0,
                "case_label_acknowledged_count": 0,
                "overall_completed_count": 0,
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
                    if str(campaign["workflow_mode"] or "model_review_only") == "model_review_and_case_label":
                        markers = combined_progress.get((cid, issue), {})
                        model_names = {
                            name for name in names
                            if bool((markers.get(name) or {}).get("model_review_submitted"))
                        }
                        case_names = {
                            name for name in names
                            if bool((markers.get(name) or {}).get("case_label_acknowledged"))
                        }
                        submitted_names = model_names & case_names
                        source_revision_ids = [
                            int((markers[name] or {}).get("model_review_revision_id") or 0)
                            for name in sorted(model_names)
                            if int((markers[name] or {}).get("model_review_revision_id") or 0) > 0
                        ]
                        summary["model_review_submitted_count"] += len(model_names)
                        summary["case_label_acknowledged_count"] += len(case_names)
                        summary["overall_completed_count"] += len(submitted_names)
                        if len(submitted_names) >= required:
                            state = "completed"
                        elif model_names or case_names:
                            state = "in_progress"
                        else:
                            state = "pending"
                        submitted = len(submitted_names)
                    else:
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
        if cache_key is not None:
            with self._campaign_progress_cache_lock:
                self._campaign_progress_cache[cache_key] = copy.deepcopy(progress)
                self._campaign_progress_cache.move_to_end(cache_key)
                while len(self._campaign_progress_cache) > 64:
                    self._campaign_progress_cache.popitem(last=False)
        return progress

    def list_campaigns(
        self,
        *,
        baseline_scopes: Sequence[str] | None = None,
        issue_ids: Sequence[str] = (),
        purpose: str = "",
        lifecycle: str = "current",
        task_group_id: str = "",
        include_legacy: bool = True,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        scopes = self._normalize_baseline_scopes(baseline_scopes)
        normalized_purpose = str(purpose or "").strip().lower()
        normalized_lifecycle = normalize_task_lifecycle(lifecycle)
        if normalized_purpose and normalized_purpose not in CAMPAIGN_PURPOSES:
            raise ValueError("Campaign purpose 不合法。")
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or 50), 100))
        where = ["1 = 1"]
        params: list[Any] = []
        if normalized_purpose:
            where.append("split.purpose = ?")
            params.append(normalized_purpose)
        lifecycle_clause, lifecycle_params = task_lifecycle_where(normalized_lifecycle)
        where.append(lifecycle_clause)
        params.extend(lifecycle_params)
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
        if issue_ids:
            where.append("EXISTS (SELECT 1 FROM campaign_issue_members selected_member "
                         "WHERE selected_member.campaign_id=split.id AND selected_member.issue_id IN ("
                         + ",".join("?" for _ in issue_ids) + "))")
            params.extend(issue_ids)
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
            progress = self._campaign_progress_batch(conn, rows, use_cache=True)
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
            "workflow_mode": str(row["workflow_mode"] or "model_review_only"),
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
