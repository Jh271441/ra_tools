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


def normalise_trail_info_value(value: Any) -> Any:
    """Trail dataframe empty cells arrive as float NaN, not malformed JSON.

    Only normalize that transport sentinel; strings such as "NaN", infinity,
    numbers, and non-object JSON still fail validation.
    """
    return None if isinstance(value, float) and value != value else value


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

    A nonempty local note must match the remote note. An empty local note
    requests no reason change and preserves any existing remote text.
    """

    return {issue: detail["legacy_status"] for issue, detail in trail_update_details(
        sync_result, issue_ids, info_field=info_field, expected_comments=expected_comments
    ).items()}


def exclusion_comparison(marker: bool | None, current_comment: str, local_comment: str) -> dict[str, Any]:
    """An empty local reason means preserve the remote text, never erase it."""
    remote = normalise_exclusion_comment(current_comment)
    local = normalise_exclusion_comment(local_comment)
    reason_changed = bool(local) and local != remote
    if marker is not True:
        state = "needs_exclusion"
    elif reason_changed:
        state = "reason_changed" if remote else "reason_missing"
    elif local:
        state = "synced"
    else:
        state = "excluded_keep_reason" if remote else "excluded_no_reason"
    return {
        "state": state, "trail_should_exclude": marker,
        "trail_comment": remote, "local_comment": local,
        "trail_modified_at": None,
        "needs_exclusion_update": marker is not True,
        "needs_reason_update": reason_changed,
        "legacy_status": "pending" if marker is not True or reason_changed else "synced",
    }


def trail_update_details(sync_result: Any, issue_ids: list[str], *, info_field: str,
                         expected_comments: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    raw_rows = getattr(sync_result, "rows", []) or []
    rows = {as_text(row.get("issue_id")): row for row in raw_rows}
    duplicates = {issue for issue in rows if sum(as_text(row.get("issue_id")) == issue for row in raw_rows) > 1}
    details = {}
    for issue in issue_ids:
        failure = "query_failed" if not getattr(sync_result, "complete", False) else "not_found" if issue not in rows else ""
        if not failure:
            raw = normalise_trail_info_value(rows[issue].get(info_field))
            try:
                decoded = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
                invalid = decoded is not None and decoded != "" and not isinstance(decoded, dict)
                if isinstance(decoded, dict) and "ra_triage_dashboard" in decoded:
                    invalid = not isinstance(decoded["ra_triage_dashboard"], dict)
                if invalid or issue in duplicates:
                    failure = "query_failed"
            except (TypeError, ValueError):
                failure = "query_failed"
        if failure:
            details[issue] = {"state": failure, "legacy_status": failure,
                "trail_should_exclude": None, "trail_comment": None,
                "local_comment": normalise_exclusion_comment((expected_comments or {}).get(issue)),
                "needs_exclusion_update": False, "needs_reason_update": False,
                "trail_modified_at": None}
            continue
        marker, remote = dashboard_exclusion_values(rows[issue].get(info_field))
        # Legacy callers without an expected note only compare the marker.
        local = remote if expected_comments is None else (expected_comments or {}).get(issue, "")
        details[issue] = exclusion_comparison(marker, remote, local)
    return details


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
