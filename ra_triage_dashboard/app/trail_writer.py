"""Fail-closed writer for the Dashboard Trail Attribute Update workflow.

The dashboard owns the review selection and audit payload, while the
``ra_auto_triage`` checkout remains the only source of Trail authentication
and transport details.  This module deliberately imports that client only
when an explicitly enabled, verified write is committed.  It never logs
tokens or the full request payload and never mutates caller-owned objects.
"""

from __future__ import annotations

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


LABELS = ("误触发", "正确触发", "无需协助")
TRAIL_OPERATION_MARKER_PREFIX = "[RA-Triage-Dashboard operation:"
_LABEL_ALIASES = {
    "mismatch": "误触发",
    "match": "正确触发",
    "none": "无需协助",
    "false_positive": "误触发",
    "true_positive": "正确触发",
    "no_assist": "无需协助",
}


def normalise_model_label(value: Any) -> str:
    """Return the canonical three-class label or an empty string."""

    text = str(value or "").strip()
    if text in LABELS:
        return text
    return _LABEL_ALIASES.get(text.lower(), "")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries without mutating either argument."""

    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def attach_trail_operation_id(
    changes: Iterable[dict[str, Any]],
    *,
    operation_id: str,
    info_field: str = "ra_stuck_auto_result_info",
) -> list[dict[str, Any]]:
    """Bind every field update to the immutable preview digest.

    The operation ID lives in the Dashboard namespace, so a retry of the same
    digest writes the same value and can be verified by a post-write readback.
    Caller-owned changes are never mutated.
    """

    normalized = str(operation_id or "").strip()[:128]
    if not normalized:
        raise ValueError("Trail 操作缺少 operation_id。")
    output: list[dict[str, Any]] = []
    for change in changes:
        item = deepcopy(change)
        info = _json_object(item.get(info_field))
        info = deep_merge_dict(
            info,
            {"ra_triage_dashboard": {"operation_id": normalized}},
        )
        item[info_field] = info
        output.append(item)
    return output


def trail_operation_comment(comment: str, operation_id: str) -> str:
    """Append a deterministic, human-readable marker to a Trail Comment."""

    body = str(comment or "").strip()
    normalized = str(operation_id or "").strip()[:128]
    if not normalized:
        return body[:4000]
    marker = f"{TRAIL_OPERATION_MARKER_PREFIX}{normalized}]"
    if marker in body:
        return body[:4000]
    if not body:
        return marker[:4000]
    room = max(0, 4000 - len(marker) - 2)
    return f"{body[:room]}\n\n{marker}"[:4000]


def decorate_trail_comments(
    changes: Iterable[dict[str, Any]],
    *,
    operation_id: str,
) -> list[dict[str, Any]]:
    """Copy changes and add an idempotency marker only to requested Comments."""

    output: list[dict[str, Any]] = []
    for change in changes:
        item = deepcopy(change)
        if str(item.get("comment") or "").strip():
            item["comment"] = trail_operation_comment(item["comment"], operation_id)
        output.append(item)
    return output


def verify_trail_readback(
    changes: Iterable[dict[str, Any]],
    rows: Iterable[dict[str, Any]],
    *,
    result_field: str = "ra_stuck_auto_result",
    info_field: str = "ra_stuck_auto_result_info",
) -> dict[str, Any]:
    """Check every successfully changed Issue after Trail writes.

    We compare the model label when present, the operation marker, and the
    exclusion bit.  Unrelated JSON keys are intentionally not compared: Trail
    may normalize or order them while the Dashboard deep-merge contract only
    owns its namespace.
    """

    expected = {str(item.get("issue_id") or "").strip(): item for item in changes}
    actual = {str(item.get("issue_id") or "").strip(): item for item in rows}
    mismatched: list[str] = []
    missing: list[str] = []
    for issue_id, change in expected.items():
        if not issue_id:
            continue
        row = actual.get(issue_id)
        if row is None:
            missing.append(issue_id)
            continue
        expected_label = change.get(result_field)
        if expected_label is not None and str(row.get(result_field) or "").strip() != str(expected_label).strip():
            mismatched.append(issue_id)
            continue
        info = _json_object(row.get(info_field))
        dashboard = info.get("ra_triage_dashboard")
        if not isinstance(dashboard, dict):
            mismatched.append(issue_id)
            continue
        expected_info = _json_object(change.get(info_field))
        expected_dashboard = expected_info.get("ra_triage_dashboard")
        if not isinstance(expected_dashboard, dict):
            mismatched.append(issue_id)
            continue
        for key in ("operation_id", "should_exclude", "should_exclude_comment"):
            if key in expected_dashboard and dashboard.get(key) != expected_dashboard.get(key):
                mismatched.append(issue_id)
                break
    return {
        "checked_count": len(expected),
        "verified_count": len(expected) - len(set(missing) | set(mismatched)),
        "missing_issue_ids": sorted(set(missing)),
        "mismatched_issue_ids": sorted(set(mismatched)),
        "ok": not missing and not mismatched,
    }


def build_trail_changes(
    items: Iterable[dict[str, Any]],
    *,
    current_rows: Iterable[dict[str, Any]] = (),
    result_field: str = "ra_stuck_auto_result",
    info_field: str = "ra_stuck_auto_result_info",
    write_result_field: bool = True,
) -> list[dict[str, Any]]:
    """Build immutable Trail ``multi_update`` changes from a preview.

    The current info field is read from the same Trail view before commit and
    deep-merged with the Dashboard namespace.  Missing/invalid labels fail
    the whole operation before the first network request only when the model
    result field is also being written; info-only updates do not depend on a
    label value.
    """

    current_by_issue = {
        str(row.get("issue_id") or "").strip(): row
        for row in current_rows
        if str(row.get("issue_id") or "").strip()
    }
    changes: list[dict[str, Any]] = []
    for item in items:
        issue_id = str(item.get("issue_id") or "").strip()
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        label = normalise_model_label(model.get("label"))
        if not issue_id:
            raise ValueError("Trail 更新项缺少 issue_id。")
        if write_result_field and not label:
            raise ValueError(f"{issue_id} 的模型 label 不是三分类值，已停止提交。")
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        patch = target.get("patch") if isinstance(target.get("patch"), dict) else {}
        current = current_by_issue.get(issue_id) or {}
        current_info = _json_object(current.get(info_field))
        merged_info = deep_merge_dict(current_info, patch)
        # The info-only workflow writes only the Dashboard-owned exclusion
        # marker and optional exclusion explanation. Keep the legacy
        # model_result object only for callers that explicitly write the model
        # result field as well.
        if write_result_field:
            merged_info["model_result"] = {
                "label": label,
                "reason": str(model.get("reason") or "").strip(),
                "confidence": model.get("confidence"),
            }
        review = item.get("review") if isinstance(item.get("review"), dict) else {}
        comment_text = str(item.get("comment") or review.get("note") or "").strip()[:4000]
        # ``comment`` is an operator-facing name used by the preview contract.
        # It must not be sent as a top-level Trail Comment.  Trail comments
        # are stored in the Dashboard namespace of the JSON info field so the
        # exclusion marker and its reason remain one atomic, deep-merged
        # update.
        if comment_text:
            merged_info = deep_merge_dict(
                merged_info,
                {"ra_triage_dashboard": {"should_exclude_comment": comment_text}},
            )
        change = {
            "issue_id": issue_id,
            info_field: merged_info,
        }
        if write_result_field:
            change[result_field] = label
        changes.append(change)
    return changes


def build_manual_exclusion_changes(
    issue_ids: Iterable[str],
    *,
    current_rows: Iterable[dict[str, Any]] = (),
    info_field: str = "ra_stuck_auto_result_info",
    comment: str = "",
    comment_by_issue: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build an Issue-ID-only exclusion patch.

    Direct shielding deliberately updates only the dashboard namespace inside
    ``ra_stuck_auto_result_info``.  It does not invent or overwrite the model
    label in ``ra_stuck_auto_result``.  The caller must read the same Trail
    rows immediately before building this patch so unrelated JSON keys are
    retained by the deep merge.
    """

    current_by_issue = {
        str(row.get("issue_id") or "").strip(): row
        for row in current_rows
        if str(row.get("issue_id") or "").strip()
    }
    normalized_comment = str(comment or "").strip()[:4000]
    normalized_comments = {
        str(issue_id or "").strip(): str(note or "").strip()[:4000]
        for issue_id, note in (comment_by_issue or {}).items()
        if str(issue_id or "").strip()
    }
    changes: list[dict[str, Any]] = []
    for raw_issue_id in issue_ids:
        issue_id = str(raw_issue_id or "").strip()
        if not issue_id:
            continue
        current = current_by_issue.get(issue_id) or {}
        current_info = _json_object(current.get(info_field))
        patch = {"ra_triage_dashboard": {"should_exclude": True}}
        merged_info = deep_merge_dict(current_info, patch)
        change: dict[str, Any] = {
            "issue_id": issue_id,
            info_field: merged_info,
        }
        issue_comment = normalized_comments.get(issue_id, normalized_comment)
        if issue_comment:
            merged_info = deep_merge_dict(
                merged_info,
                {"ra_triage_dashboard": {"should_exclude_comment": issue_comment}},
            )
            change[info_field] = merged_info
        changes.append(change)
    return changes


def _trail_interface_factory(ra_root: Path) -> Callable[[], Any]:
    root = str(Path(ra_root).expanduser().resolve())

    def factory() -> Any:
        if root not in sys.path:
            sys.path.insert(0, root)
        importlib.invalidate_caches()
        from utils.trail_api import TrailInterface  # type: ignore[import-not-found]

        return TrailInterface()

    return factory


def write_trail_model_results(
    changes: list[dict[str, Any]],
    *,
    ra_root: Path,
    chunk_size: int = 10,
    client_factory: Callable[[], Any] | None = None,
    write_comments_separately: bool = False,
    comment_skip_issue_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Write Trail fields in bounded, checked chunks.

    The legacy client can dispatch ``comment`` itself, but does not expose the
    comment response separately.  New dashboard workflows set
    ``write_comments_separately=True`` so field and Comment results are
    auditable independently and a failed Comment never masquerades as a
    successful field write.
    """

    if not changes:
        return {
            "total": 0,
            "success_count": 0,
            "failed_count": 0,
            "failed_issue_ids": [],
            "chunks": [],
            "comment_total": 0,
            "comment_success_count": 0,
            "comment_failed_count": 0,
            "comment_failed_issue_ids": [],
            "comment_skipped_count": 0,
            "comment_skipped_issue_ids": [],
        }
    factory = client_factory or _trail_interface_factory(ra_root)
    client = factory()
    safe_size = max(1, min(50, int(chunk_size)))
    stats: dict[str, Any] = {
        "total": len(changes),
        "success_count": 0,
        "failed_count": 0,
        "failed_issue_ids": [],
        "chunks": [],
        "comment_total": sum(1 for item in changes if str(item.get("comment") or "").strip()),
        "comment_success_count": 0,
        "comment_failed_count": 0,
        "comment_failed_issue_ids": [],
        "comment_skipped_count": 0,
        "comment_skipped_issue_ids": [],
    }
    skip_comments = {str(issue_id).strip() for issue_id in comment_skip_issue_ids if str(issue_id).strip()}
    for start in range(0, len(changes), safe_size):
        chunk = changes[start : start + safe_size]
        issue_ids = [str(item["issue_id"]) for item in chunk]
        try:
            field_changes = []
            for item in chunk:
                field_change = deepcopy(item)
                field_change.pop("comment", None)
                field_changes.append(field_change)
            # TrailInterface currently pops issue_id/comment from its input;
            # pass a deep copy so the request remains available for audit/UI.
            response = client.update_issue_with_changes(
                field_changes if write_comments_separately else deepcopy(chunk),
                replace=True,
            )
            success = isinstance(response, dict) and response.get("msg") == "success"
            response_status = "success" if success else "failed"
        except Exception as exc:  # pragma: no cover - exercised with integration client
            success = False
            response_status = f"exception:{type(exc).__name__}"
        stats["chunks"].append(
            {"index": len(stats["chunks"]) + 1, "issue_count": len(chunk), "status": response_status}
        )
        if success:
            stats["success_count"] += len(chunk)
            if write_comments_separately:
                for item in chunk:
                    text = str(item.get("comment") or "").strip()[:4000]
                    if not text:
                        continue
                    issue_id = str(item.get("issue_id") or "").strip()
                    if issue_id in skip_comments:
                        stats["comment_skipped_count"] += 1
                        stats["comment_skipped_issue_ids"].append(issue_id)
                        continue
                    try:
                        comment_response = client.add_issue_comment(issue_id, text)
                        comment_success = (
                            isinstance(comment_response, dict)
                            and comment_response.get("msg") == "success"
                        )
                    except Exception:  # pragma: no cover - integration client
                        comment_success = False
                    if comment_success:
                        stats["comment_success_count"] += 1
                    else:
                        stats["comment_failed_count"] += 1
                        stats["comment_failed_issue_ids"].append(issue_id)
        else:
            stats["failed_count"] += len(chunk)
            stats["failed_issue_ids"].extend(issue_ids)
    return stats
