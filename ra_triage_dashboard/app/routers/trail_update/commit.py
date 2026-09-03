"""Trail attribute update commit domain."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Mapping

from ...db import REVIEW_STATUSES
from ...support.common import _as_text
from ...runtime import database, settings
from ...review_workflow import derive_review_status
from ...trail_sync import read_trail_model_fields
from ...trail_writer import normalise_model_label, verify_trail_readback
from .imports import _append_historical_source_note, _historical_source_payload
from .preview import _review_exclusion_candidate_cache


logger = logging.getLogger("ra_triage_dashboard.trail_update")

# Serializes the final fresh-preview/write/readback critical section only.
_commit_lock = threading.Lock()

def _append_exclusion_note(note: str, exclusion_note: str) -> str:
    """Add the submitted Issue-exclusion comment to the new Review version."""

    current = _as_text(note).strip()
    exclusion = _as_text(exclusion_note).strip()
    if not exclusion or exclusion in current:
        return current[:4000]
    suffix = f"问题排除说明：{exclusion}"
    if not current:
        return suffix[:4000]
    available = max(0, 4000 - len(suffix) - 2)
    return f"{current[:available].rstrip()}\n\n{suffix}"[:4000]

def _mark_local_review_exclusions(
    issue_ids: list[str],
    *,
    actor: Any,
    fallback_note: str = "",
    fallback_notes: Mapping[str, str] | None = None,
    source_notes: Mapping[str, str] | None = None,
    mentions_by_issue: Mapping[str, list[str]] | None = None,
    notification_recipients_by_issue: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Persist the direct shielding result into the Review exclusion flag.

    The Trail Issue-ID workflow is an issue-level action, but the Review page
    stores ``应该排除`` in its append-only annotation history.  Once Trail has
    been written and read back successfully, create a new annotation in the
    same Run as the latest Review for each Issue.  Existing expected output,
    Tags and missing evidence are copied unchanged; the submitted exclusion
    comment is appended to the note and ``is_excluded`` is forced to ``True``.
    Repeating the same operation is idempotent when the latest annotation is
    already excluded.
    """

    normalized_ids = list(dict.fromkeys(
        str(issue_id or "").strip()
        for issue_id in issue_ids
        if str(issue_id or "").strip()
    ))
    result: dict[str, Any] = {
        "requested_count": len(normalized_ids),
        "marked_count": 0,
        "already_excluded_count": 0,
        # An Issue can exist in Trail but not belong to any baseline currently
        # loaded by this dashboard.  That is not a Trail write failure: retain
        # it separately so callers can describe the partial local sync without
        # incorrectly reporting the whole operation as failed.
        "not_in_dashboard_count": 0,
        "not_in_dashboard_issue_ids": [],
        "failed_count": 0,
        "failed_issue_ids": [],
        "failure_messages": {},
        "notification_queued_count": 0,
    }
    actor_name = _as_text(getattr(actor, "username", ""))
    actor_source = _as_text(getattr(actor, "source", "")) or "trail_attribute_update"
    actor_verified = bool(getattr(actor, "verified", False))
    normalized_fallback_note = _as_text(fallback_note).strip()[:4000]
    normalized_fallback_notes = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (fallback_notes or {}).items()
        if _as_text(issue_id).strip()
    }
    normalized_source_notes = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (source_notes or {}).items()
        if _as_text(issue_id).strip()
    }
    for issue_id in normalized_ids:
        try:
            case = database.get_case(issue_id)
            if case is None:
                result["not_in_dashboard_count"] += 1
                result["not_in_dashboard_issue_ids"].append(issue_id)
                continue
            annotations = [
                item for item in (case.get("annotations") or [])
                if isinstance(item, dict)
            ]
            current = annotations[0] if annotations else {}
            if bool(current.get("is_excluded")):
                result["already_excluded_count"] += 1
                continue
            expected_output = normalise_model_label(
                current.get("expected_output") or current.get("label")
            )
            current_review_status = _as_text(current.get("review_status"))
            review_status = (
                current_review_status
                if current_review_status in REVIEW_STATUSES
                else derive_review_status(expected_output, case.get("gt_label"))
            )
            previous_id = current.get("id")
            if previous_id not in (None, "", 0, "0"):
                previous_id = int(previous_id)
            else:
                previous_id = None
            annotation_kwargs: dict[str, Any] = dict(
                issue_id=issue_id,
                model_run_id=_as_text(current.get("model_run_id")),
                label=expected_output,
                review_status=review_status,
                is_excluded=True,
                tags=list(current.get("tags") or []),
                missing_evidence=list(current.get("missing_evidence") or []),
                note=_append_historical_source_note(
                    _append_exclusion_note(
                        _as_text(current.get("note")),
                        normalized_fallback_notes.get(issue_id)
                        or normalized_fallback_note,
                    ),
                    normalized_source_notes.get(issue_id, ""),
                ),
                author=actor_name,
                author_source=actor_source,
                author_verified=actor_verified,
                expected_previous_annotation_id=previous_id,
            )
            if mentions_by_issue is not None:
                annotation_kwargs["mentions"] = list(
                    mentions_by_issue.get(issue_id, [])
                )
            if notification_recipients_by_issue is not None:
                annotation_kwargs["notification_recipients"] = list(
                    notification_recipients_by_issue.get(issue_id, [])
                )
            database.create_annotation(**annotation_kwargs)
            result["marked_count"] += 1
            result["notification_queued_count"] += len(
                (notification_recipients_by_issue or {}).get(issue_id, [])
            )
        except Exception as exc:
            result["failed_count"] += 1
            result["failed_issue_ids"].append(issue_id)
            result["failure_messages"][issue_id] = str(exc)[:240]
    result["ok"] = result["failed_count"] == 0
    if result["marked_count"]:
        # A direct Issue action changes the exact source projection consumed by
        # the Review-exclusion tab. Do not make an operator wait for the short
        # local TTL after a successful write/readback.
        _review_exclusion_candidate_cache.clear()
    return result

async def _readback_changes(
    changes: list[dict[str, Any]],
    stats: dict[str, Any],
    *,
    result_field: str,
    info_field: str,
) -> dict[str, Any]:
    """Read back every field-successful Issue and verify the owned markers."""

    failed = {str(item).strip() for item in stats.get("failed_issue_ids", []) if str(item).strip()}
    successful = [item for item in changes if str(item.get("issue_id") or "").strip() not in failed]
    issue_ids = [str(item.get("issue_id") or "").strip() for item in successful if str(item.get("issue_id") or "").strip()]
    if not issue_ids:
        return {
            "complete": True,
            "ok": True,
            "checked_count": 0,
            "verified_count": 0,
            "missing_issue_ids": [],
            "mismatched_issue_ids": [],
            "message": "没有字段成功项需要回读。",
        }
    result = await asyncio.to_thread(
        read_trail_model_fields,
        ra_root=settings.ra_auto_triage_root,
        issue_ids=issue_ids,
        view_id=settings.trail_view_id,
        chunk_size=settings.trail_sync_chunk_size,
    )
    verification = verify_trail_readback(
        successful,
        result.rows,
        result_field=result_field,
        info_field=info_field,
    )
    verification.update(
        {
            "complete": bool(result.complete),
            "ok": bool(result.complete and verification.get("ok")),
            "message": _as_text(result.message),
            "fields_visible": list(result.fields_visible),
        }
    )
    return verification

async def _save_issue_exclusion_history(
    *,
    operation_id: str,
    identity: Any,
    status: str,
    requested_entries: list[dict[str, Any]],
    synced_issue_ids: set[str] | None = None,
    failed_issue_ids: set[str] | None = None,
    external_only_issue_ids: set[str] | None = None,
    failure_messages: Mapping[str, str] | None = None,
    message: str = "",
) -> None:
    """Best-effort audit persistence for the direct Issue-ID workflow."""

    failures = failure_messages or {}
    synced = {
        str(item).strip()
        for item in (synced_issue_ids or set())
        if str(item).strip()
    }
    failed = {
        str(item).strip()
        for item in (failed_issue_ids or set())
        if str(item).strip()
    }
    external_only = {
        str(item).strip()
        for item in (external_only_issue_ids or set())
        if str(item).strip()
    }
    entries: list[dict[str, Any]] = []
    for item in requested_entries:
        issue_id = _as_text(item.get("issue_id")).strip()
        if not issue_id:
            continue
        if issue_id in failed:
            item_status = "failed"
            detail = _as_text(failures.get(issue_id)) or "Trail 写入、回读或本地看板同步失败。"
        elif issue_id in external_only:
            item_status = "trail_synced_not_in_dashboard"
            detail = "Trail 回读确认成功；该 Issue 不在当前看板数据集，未创建本地 Review 排除标记。"
        elif issue_id in synced:
            item_status = "synced"
            detail = "Trail 回读确认成功。"
        else:
            item_status = "pending" if status == "pending" else "unknown"
            detail = "等待提交结果。" if status == "pending" else "未返回明确结果。"
        entry = {
            "issue_id": issue_id,
            "comment": _as_text(item.get("comment")).strip()[:4000],
            "status": item_status,
            "detail": detail[:1000],
        }
        source = _historical_source_payload(item.get("source"))
        if source is not None:
            entry["source"] = source
        entries.append(entry)
    actor = {
        "username": _as_text(getattr(identity, "username", "")),
        "source": _as_text(getattr(identity, "source", "")),
        "verified": bool(getattr(identity, "verified", False)),
    }
    try:
        await asyncio.to_thread(
            database.upsert_trail_issue_exclusion_history,
            operation_id=operation_id,
            actor=actor["username"],
            actor_source=actor["source"],
            actor_verified=actor["verified"],
            status=status,
            requested_count=len(entries),
            synced_count=len(synced),
            failed_count=len(failed),
            entries=entries,
            message=message,
        )
    except Exception:  # pragma: no cover - audit must not block a Trail write
        logger.exception("Unable to persist Issue-ID shielding history")
