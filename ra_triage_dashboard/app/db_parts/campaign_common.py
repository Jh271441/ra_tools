"""Run-independent Campaign metadata and progress storage (S4)."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any, Sequence
from uuid import uuid4

from ..review_analysis import REASON_THEME_CATALOG, classify_review_reason
from .shared import _json, _json_load, utc_now
from .task_lifecycle import normalize_task_lifecycle, task_lifecycle_where

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


