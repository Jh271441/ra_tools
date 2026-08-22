"""Pure contracts for the controlled Trail issue-exclusion workflow.

This module deliberately has no runtime/database/Trail-client import.  The
router owns HTTP, identity and I/O; draft builders and status projections share
these deterministic helpers.  Keeping the contract here makes it possible to
unit-test a proposed write without bootstrapping the Dashboard application.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Mapping

from .contracts import ISSUE_ID_RE


TRAIL_RESULT_FIELD = "ra_stuck_auto_result"
TRAIL_INFO_FIELD = "ra_stuck_auto_result_info"
TRAIL_TARGET_FIELD = TRAIL_INFO_FIELD
TRAIL_TARGET_PATH = "ra_triage_dashboard.should_exclude"
TRAIL_COMMENT_PATH = "ra_triage_dashboard.should_exclude_comment"
TRAIL_DRAFT_SCHEMA = "trail-attribute-update-v2"
TRAIL_ISSUE_DRAFT_SCHEMA = "trail-issue-exclusion-v2"
TRAIL_ISSUE_IMPORT_PREVIEW_SCHEMA = "trail-issue-import-preview-v1"
TRAIL_ISSUE_EXCLUSION_COMMENT = (
    "问题排除：Issue ID 直接屏蔽（仅写入 should_exclude=true，模型 label 不变）。"
)


def as_text(value: Any) -> str:
    """Match the HTTP compatibility text normalization without runtime imports."""

    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used in preview digests."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dashboard_exclusion_values(value: Any) -> tuple[bool | None, str]:
    """Read only this Dashboard's marker and normalized exclusion note."""

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = {}
    if not isinstance(value, dict):
        return None, ""
    dashboard = value.get("ra_triage_dashboard")
    if not isinstance(dashboard, dict):
        return None, ""
    marker = dashboard.get("should_exclude")
    note = as_text(dashboard.get("should_exclude_comment")).strip()[:4000]
    return (marker if isinstance(marker, bool) else None), note


def normalise_exclusion_comment(value: Any) -> str:
    """Use the exact bounded string the info-only writer persists."""

    return as_text(value).strip()[:4000]


def expected_exclusion_comments(items: list[dict[str, Any]]) -> dict[str, str]:
    """Extract the Dashboard-owned note from a signed preview."""

    expected: dict[str, str] = {}
    for item in items:
        issue_id = as_text(item.get("issue_id")).strip()
        target = item.get("target") if isinstance(item.get("target"), Mapping) else {}
        patch = target.get("patch") if isinstance(target.get("patch"), Mapping) else {}
        dashboard = (
            patch.get("ra_triage_dashboard")
            if isinstance(patch.get("ra_triage_dashboard"), Mapping)
            else {}
        )
        if issue_id:
            expected[issue_id] = normalise_exclusion_comment(
                dashboard.get("should_exclude_comment", item.get("comment", ""))
            )
    return expected


def trail_update_statuses(
    sync_result: Any,
    issue_ids: list[str],
    *,
    info_field: str,
    expected_comments: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Project one complete Trail snapshot into per-Issue write states.

    A record is synchronized only when both the namespaced marker and its
    normalized note match.  This prevents an old reason from being silently
    treated as the same exclusion decision.
    """

    normalized_ids = [as_text(issue_id) for issue_id in issue_ids if as_text(issue_id)]
    rows_by_issue = {
        as_text(row.get("issue_id")): row
        for row in (getattr(sync_result, "rows", None) or [])
        if as_text(row.get("issue_id"))
    }
    if not bool(getattr(sync_result, "complete", False)):
        return {issue_id: "query_failed" for issue_id in normalized_ids}
    statuses: dict[str, str] = {}
    for issue_id in normalized_ids:
        row = rows_by_issue.get(issue_id)
        if row is None:
            statuses[issue_id] = "not_found"
            continue
        marker, current_comment = dashboard_exclusion_values(row.get(info_field))
        expected_comment = normalise_exclusion_comment(
            (expected_comments or {}).get(issue_id, "")
        )
        note_matches = expected_comments is None or current_comment == expected_comment
        statuses[issue_id] = "synced" if marker is True and note_matches else "pending"
    return statuses


def trail_update_status_summary(statuses: Mapping[str, str]) -> dict[str, int]:
    """Return compact stable counts for a status projection."""

    summary: dict[str, int] = {}
    for status in statuses.values():
        normalized = as_text(status) or "not_checked"
        summary[normalized] = summary.get(normalized, 0) + 1
    return summary


def normalise_issue_ids(raw: Any) -> tuple[list[str], list[str]]:
    """Normalize a bounded direct Issue-ID request without URL extraction."""

    values: list[Any]
    if isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = re.split(r"[\s,，、;；|]+", as_text(raw))
    ids: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = as_text(value).strip()
        if not text:
            continue
        if not ISSUE_ID_RE.fullmatch(text):
            invalid.append(text[:128])
            continue
        if text not in seen:
            seen.add(text)
            ids.append(text)
    return sorted(ids), invalid


def normalise_issue_entries(
    raw: Any,
    *,
    fallback_comment: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Expand editable Issue rows into one canonical entry per Issue ID."""

    default_comment = as_text(fallback_comment).strip()[:4000]
    if isinstance(raw, (list, tuple)):
        values: list[Any] = list(raw)
    elif isinstance(raw, dict):
        values = [raw]
    else:
        values = re.split(r"[\s,，、;；|]+", as_text(raw))

    entries: list[dict[str, Any]] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for value in values:
        source: dict[str, Any] | None = None
        if isinstance(value, Mapping):
            raw_issue_id = value.get("issue_id", value.get("id", ""))
            comment = as_text(value.get("comment", value.get("note", default_comment))).strip()[:4000]
            raw_source = value.get("source")
            if raw_source is not None:
                if not isinstance(raw_source, Mapping):
                    issue_text = as_text(raw_issue_id).strip() or "未填写 Issue ID"
                    invalid.append(f"{issue_text}（标注来源格式无效）")
                    continue
                source = dict(raw_source)
        else:
            raw_issue_id = value
            comment = default_comment
        issue_id = as_text(raw_issue_id).strip()
        if not issue_id:
            continue
        if not ISSUE_ID_RE.fullmatch(issue_id):
            invalid.append(issue_id[:128])
            continue
        if issue_id in seen:
            invalid.append(f"{issue_id}（重复）")
            continue
        seen.add(issue_id)
        entry: dict[str, Any] = {"issue_id": issue_id, "comment": comment}
        if source is not None:
            entry["source"] = source
        entries.append(entry)
    entries.sort(key=lambda item: item["issue_id"])
    return entries, invalid
