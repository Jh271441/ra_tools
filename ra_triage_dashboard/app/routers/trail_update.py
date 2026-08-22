"""Trail 属性更新：预览、字段能力检查与受控提交。

Review 的“应该排除”只会生成当前 Model Run 的候选项。当前生产写入只更新
``ra_stuck_auto_result_info.ra_triage_dashboard.should_exclude``，保留模型
label 不变。真正写 Trail 之前必须满足目标 view 可完整定位 Issue、请求来自
已验证的 SSO 写入用户、以及客户端提交的 SHA-256 与服务端重新计算结果一致。

默认 writer 仍关闭。这样在现有 2410 view 只有 ``ra_result``/``ra_info`` 时，
页面会明确告知字段缺失，并且绝不会把新契约误写到旧字段。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, File, Request, UploadFile

from ..auth import has_same_origin_mutation_marker, identity_can_write, request_identity
from ..contracts import ISSUE_ID_RE, MAX_UPLOAD_BYTES
from ..db import REVIEW_STATUSES
from ..http_support import (
    _as_text,
    _detail,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..import_parsing import parse_source_bytes
from ..issue_tag_sources import HISTORICAL_EXCLUSION_SOURCE_KIND
from ..runtime import baseline_registry, database, issue_tag_sources, settings
from ..review_workflow import derive_review_status
from ..trail_exclusion_contracts import (
    TRAIL_COMMENT_PATH,
    TRAIL_DRAFT_SCHEMA,
    TRAIL_INFO_FIELD,
    TRAIL_ISSUE_DRAFT_SCHEMA,
    TRAIL_ISSUE_EXCLUSION_COMMENT,
    TRAIL_ISSUE_IMPORT_PREVIEW_SCHEMA,
    TRAIL_RESULT_FIELD,
    TRAIL_TARGET_FIELD,
    TRAIL_TARGET_PATH,
    canonical_json as _canonical_json,
    dashboard_exclusion_values as _dashboard_exclusion_values,
    expected_exclusion_comments as _expected_exclusion_comments,
    normalise_exclusion_comment as _normalise_exclusion_comment,
    normalise_issue_entries as _normalise_issue_entries,
    normalise_issue_ids as _normalise_issue_ids,
    trail_update_status_summary as _trail_update_status_summary,
    trail_update_statuses as _trail_update_statuses,
)
from ..trail_exclusion_payloads import (
    build_direct_issue_exclusion_payload as _build_direct_issue_exclusion_payload,
    build_review_exclusion_payload as _build_review_exclusion_payload,
)
from ..trail_sync import read_trail_model_fields
from ..trail_writer import (
    attach_trail_operation_id,
    build_manual_exclusion_changes,
    build_trail_changes,
    deep_merge_dict,
    normalise_model_label,
    verify_trail_readback,
    write_trail_model_results,
)
from ..timed_cache import TimedSingleFlightCache
from ..upload_limits import UploadLimitExceeded, read_upload_limited

router = APIRouter()
logger = logging.getLogger("ra_triage_dashboard.trail_update")

_HISTORICAL_EXCLUSION_SOURCE_FIELDS = (
    "kind",
    "source_id",
    "label",
    "baseline_id",
    "filename",
    "sha256",
    "row_number",
    "issue_id",
    "column",
    "value",
)
_TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS = 5_000
_TRAIL_ISSUE_IMPORT_MAX_ENTRIES = 200
_TRAIL_ISSUE_IMPORT_ISSUE_ALIASES = (
    "issue_id",
    "issue id",
    "issueid",
    "issue",
    "问题id",
    "问题编号",
    "问题号",
)
_TRAIL_ISSUE_IMPORT_EXCLUDE_ALIASES = (
    "是否排除",
    "should_exclude",
    "should exclude",
    "isexcluded",
    "is_excluded",
    "exclude",
    "excluded",
    "排除",
    "需要排除",
)
_TRAIL_ISSUE_IMPORT_COMMENT_ALIASES = (
    "comment",
    "note",
    "exclusion_note",
    "exclusion comment",
    "排除说明",
    "备注",
    "说明",
    "原因",
    "reason",
    "should_exclude_comment",
)
_TRAIL_ISSUE_IMPORT_TRUE_VALUES = frozenset(
    {"1", "true", "yes", "y", "是", "排除", "需要排除", "需排除"}
)
_TRAIL_ISSUE_IMPORT_FALSE_VALUES = frozenset(
    {"0", "false", "no", "n", "否", "不排除", "无需排除", "不需要排除"}
)
_commit_lock = threading.Lock()
# Trail probes are remote and commonly arrive in a burst (initial page load,
# route transition, an explicit status refresh).  A short single-flight cache
# avoids repeating the same read while preserving the commit path's fresh,
# server-side verification.
_preview_capability_cache = TimedSingleFlightCache[
    tuple[int, str, str, tuple[str, ...]], dict[str, Any]
](ttl_seconds=90, max_entries=256)
# Candidate construction is local SQLite work, but can still dominate a page
# transition with multiple baselines. Keep it separate from the remote Trail
# cache so local rendering remains reusable without extending Trail freshness.
_review_exclusion_candidate_cache = TimedSingleFlightCache[
    tuple[str, tuple[str, ...]], list[dict[str, Any]]
](ttl_seconds=12, max_entries=128)
# The first Review-exclusion response deliberately contains no remote Trail
# read, so the browser can paint the local candidate list immediately.  Keep
# the signed, local expectation for that short window and let the compact
# status endpoint use it when comparing the single batched Trail read.  The
# browser supplies the preview digest; unknown/expired digests fail closed
# instead of silently falling back to a marker-only comparison.
# ``TimedSingleFlightCache``'s generic subscription is evaluated at import
# time on the Python 3.9 deployments.  Keep ``None`` in the value contract
# but avoid PEP-604 unions inside that runtime-evaluated subscription.
_preview_status_expectation_cache = TimedSingleFlightCache[str, Any](
    ttl_seconds=180,
    max_entries=512,
)


def _append_historical_source_note(note: str, source_note: str) -> str:
    """Keep an existing Review note while making historical provenance visible."""

    current = _as_text(note).strip()
    source = _as_text(source_note).strip()
    if not source:
        return current[:4000]
    if source in current:
        return current[:4000]
    if not current:
        return source[:4000]
    # Preserve the provenance even for a previously max-length note.  The
    # original human note stays first and is clipped only as much as needed.
    available = max(0, 4000 - len(source) - 2)
    return f"{current[:available].rstrip()}\n\n{source}"[:4000]


def _mark_local_review_exclusions(
    issue_ids: list[str],
    *,
    actor: Any,
    fallback_note: str = "",
    fallback_notes: Mapping[str, str] | None = None,
    source_notes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Persist the direct shielding result into the Review exclusion flag.

    The Trail Issue-ID workflow is an issue-level action, but the Review page
    stores ``应该排除`` in its append-only annotation history.  Once Trail has
    been written and read back successfully, create a new annotation in the
    same Run as the latest Review for each Issue.  Existing expected output,
    Tags, missing evidence and note are copied unchanged; only
    ``is_excluded`` is forced to ``True``.  Repeating the same operation is
    idempotent when the latest annotation is already excluded.
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
            database.create_annotation(
                issue_id=issue_id,
                model_run_id=_as_text(current.get("model_run_id")),
                label=expected_output,
                review_status=review_status,
                is_excluded=True,
                tags=list(current.get("tags") or []),
                missing_evidence=list(current.get("missing_evidence") or []),
                note=_append_historical_source_note(
                    _as_text(current.get("note"))
                    or normalized_fallback_notes.get(issue_id)
                    or normalized_fallback_note,
                    normalized_source_notes.get(issue_id, ""),
                ),
                author=actor_name,
                author_source=actor_source,
                author_verified=actor_verified,
                expected_previous_annotation_id=previous_id,
            )
            result["marked_count"] += 1
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


def _field_names() -> tuple[str, str]:
    return (
        _as_text(getattr(settings, "trail_attribute_result_field", "")) or TRAIL_RESULT_FIELD,
        _as_text(getattr(settings, "trail_attribute_info_field", "")) or TRAIL_INFO_FIELD,
    )


def _review_exclusion_candidate_rows(
    *,
    selected_run_id: str,
    baseline_scopes: list[str],
) -> list[dict[str, Any]]:
    """Load a short-lived local Review projection with per-scope coalescing."""

    cache_key = (selected_run_id, tuple(sorted(baseline_scopes)))
    return _review_exclusion_candidate_cache.get_or_load(
        cache_key,
        lambda: database.review_reason_rows(
            baseline_scopes=baseline_scopes,
            model_run_id=selected_run_id,
            comparison_status="all",
            is_excluded=True,
        ),
    )


def _capability_not_checked(result_field: str, info_field: str) -> dict[str, Any]:
    return {
        "view_id": int(settings.trail_view_id),
        "target_fields": [result_field, info_field],
        "fields_visible": [],
        "ready": False,
        "status": "not_checked",
        "message": "生成候选项后检查 Trail view 字段。",
    }

def _capability_payload(sync_result: Any, result_field: str, info_field: str) -> dict[str, Any]:
    visible = sorted(str(item) for item in (sync_result.fields_visible or ()))
    required = {result_field, info_field}
    complete = bool(sync_result.complete)
    coverage_complete = int(sync_result.returned_issues) == int(sync_result.queried_issues)
    ready = required.issubset(set(visible)) and complete and coverage_complete
    if ready:
        status = "ready"
    elif not complete:
        status = "unavailable"
    elif not coverage_complete:
        status = "missing_issues"
    else:
        status = "missing_fields"
    message = _as_text(sync_result.message)
    if complete and not coverage_complete:
        message = (
            f"{message} Trail 仅返回 {sync_result.returned_issues}/"
            f"{sync_result.queried_issues} 条 Issue；为避免写入错误对象，本次不可提交。"
        )
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [result_field, info_field],
        "fields_visible": visible,
        "queried_issues": int(sync_result.queried_issues),
        "returned_issues": int(sync_result.returned_issues),
        "ready": ready,
        "status": status,
        "message": message,
    }


def _capability_for_required_field(
    sync_result: Any,
    required_field: str,
) -> dict[str, Any]:
    """Return a capability view for a workflow that only needs one field."""

    visible = sorted(str(item) for item in (sync_result.fields_visible or ()))
    ready = required_field in set(visible) and bool(sync_result.complete)
    if ready:
        status = "ready"
    elif not sync_result.complete:
        status = "unavailable"
    else:
        status = "missing_fields"
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [required_field],
        "required_fields": [required_field],
        "fields_visible": visible,
        "queried_issues": int(sync_result.queried_issues),
        "returned_issues": int(sync_result.returned_issues),
        "ready": ready,
        "status": status,
        "message": _as_text(sync_result.message),
    }


def _capability_for_info_write(sync_result: Any, info_field: str) -> dict[str, Any]:
    """Validate an info-only write without requiring a model-label column.

    Trail's view response omits empty custom columns for older Issues even
    when the update API accepts those fields.  For the Review aggregate we
    therefore require a complete, one-to-one Issue snapshot, but do not make
    the model label a prerequisite: the commit path only writes the info
    field and the response explicitly records that the label is untouched.
    """

    visible = sorted(str(item) for item in (sync_result.fields_visible or ()))
    complete = bool(sync_result.complete)
    coverage_complete = int(sync_result.returned_issues) == int(sync_result.queried_issues)
    if not complete:
        status = "unavailable"
        ready = False
        message = _as_text(sync_result.message)
    elif not coverage_complete:
        status = "missing_issues"
        ready = False
        message = (
            f"{_as_text(sync_result.message)} Trail 仅返回 "
            f"{sync_result.returned_issues}/{sync_result.queried_issues} 条 Issue；"
            "为避免写入错误对象，本次不可提交。"
        )
    else:
        status = "ready"
        ready = True
        if info_field in visible:
            message = _as_text(sync_result.message)
        else:
            message = (
                f"Trail view {sync_result.view_id} 未为当前旧 Issue 返回 {info_field}；"
                "本次仅通过 info-only 接口新增/合并该字段，不改模型 label，提交后会回读确认。"
            )
    return {
        "view_id": int(sync_result.view_id),
        "target_fields": [info_field],
        "required_fields": [info_field],
        "fields_visible": visible,
        "queried_issues": int(sync_result.queried_issues),
        "returned_issues": int(sync_result.returned_issues),
        "ready": ready,
        "status": status,
        "message": message,
    }


def _remember_preview_status_expectations(payload: Mapping[str, Any]) -> None:
    """Make a local Review preview usable by the compact remote status read."""

    digest = _as_text(payload.get("payload_sha256"))
    if not digest:
        return
    expected = _expected_exclusion_comments(
        [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    )
    # Replace a possible cached negative lookup from an expired browser
    # preview.  Without this invalidation, reopening the page with the same
    # deterministic digest would keep returning that old ``None`` until its
    # TTL elapsed and leave the submit button needlessly unavailable.
    _preview_status_expectation_cache.invalidate(digest)
    _preview_status_expectation_cache.get_or_load(digest, lambda: expected)


def _preview_status_expectations(payload_sha256: str) -> dict[str, str] | None:
    """Fetch a short-lived signed expectation map without reconstructing rows."""

    digest = _as_text(payload_sha256)
    if not digest:
        return None
    value = _preview_status_expectation_cache.get_or_load(digest, lambda: None)
    return dict(value) if isinstance(value, dict) else None


def _read_preview_trail_status_sync(
    issue_ids: list[str],
    *,
    info_field: str,
    expected_comments: Mapping[str, str] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Read one batched status projection, coalescing duplicate probes.

    This function intentionally owns only the remote projection.  Building
    Review candidates stays in ``_build_preview`` so the initial page response
    does not have to wait for Trail or recreate the table after it returns.
    """

    normalized_ids = sorted({
        _as_text(issue_id).strip()
        for issue_id in issue_ids
        if _as_text(issue_id).strip()
    })
    normalised_comments = {
        issue_id: _normalise_exclusion_comment((expected_comments or {}).get(issue_id, ""))
        for issue_id in normalized_ids
    }
    expectation_signature = hashlib.sha256(
        _canonical_json(normalised_comments).encode("utf-8")
    ).hexdigest()
    cache_key = (
        int(settings.trail_view_id),
        info_field,
        expectation_signature,
        tuple(normalized_ids),
    )
    if refresh:
        _preview_capability_cache.invalidate(cache_key)

    def load() -> dict[str, Any]:
        sync_result = read_trail_model_fields(
            ra_root=settings.ra_auto_triage_root,
            issue_ids=normalized_ids,
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        statuses = _trail_update_statuses(
            sync_result,
            normalized_ids,
            info_field=info_field,
            expected_comments=normalised_comments,
        )
        return {
            "trail_capability": _capability_for_info_write(sync_result, info_field),
            "trail_update_statuses": statuses,
            "trail_update_status_summary": _trail_update_status_summary(statuses),
        }

    return _preview_capability_cache.get_or_load(cache_key, load)


async def _read_preview_trail_status(
    issue_ids: list[str],
    *,
    info_field: str,
    expected_comments: Mapping[str, str] | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Offload the cache/remote probe so route handlers keep the loop free."""

    return await asyncio.to_thread(
        _read_preview_trail_status_sync,
        issue_ids,
        info_field=info_field,
        expected_comments=expected_comments,
        refresh=refresh,
    )



def _historical_source_payload(value: Any) -> dict[str, Any] | None:
    """Copy the bounded, server-verified provenance shape into public drafts."""

    if not isinstance(value, Mapping):
        return None
    if _as_text(value.get("kind")) != HISTORICAL_EXCLUSION_SOURCE_KIND:
        return None
    source: dict[str, Any] = {}
    for key in _HISTORICAL_EXCLUSION_SOURCE_FIELDS:
        raw = value.get(key)
        if key == "row_number":
            try:
                number = int(raw)
            except (TypeError, ValueError):
                return None
            if number < 1:
                return None
            source[key] = number
            continue
        text = _as_text(raw).strip()
        if not text:
            return None
        source[key] = text[:512]
    return source


def _resolve_historical_exclusion_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Replace browser hints with the exact loaded-XLSX source and comment."""

    resolved: list[dict[str, Any]] = []
    invalid: list[str] = []
    for entry in entries:
        issue_id = _as_text(entry.get("issue_id")).strip()
        source = entry.get("source")
        if source is None:
            resolved.append(
                {"issue_id": issue_id, "comment": _as_text(entry.get("comment")).strip()[:4000]}
            )
            continue
        if not isinstance(source, Mapping):
            invalid.append(f"{issue_id}（历史抽检来源格式无效）")
            continue
        candidate = issue_tag_sources.resolve_exclusion_candidate(
            issue_id=issue_id,
            source=source,
        )
        if candidate is None:
            invalid.append(f"{issue_id}（历史抽检来源无效或已变化）")
            continue
        resolved_source = _historical_source_payload(candidate.get("source"))
        if resolved_source is None:
            # This is an internal contract failure.  Do not accept a source
            # record that cannot be represented in the signed preview.
            invalid.append(f"{issue_id}（历史抽检来源不可用）")
            continue
        resolved.append(
            {
                "issue_id": issue_id,
                "comment": _as_text(candidate.get("comment")).strip()[:4000],
                "source": resolved_source,
            }
        )
    resolved.sort(key=lambda item: item["issue_id"])
    return resolved, invalid


def _issue_import_header_key(value: Any) -> str:
    """Normalize a user-facing upload header without changing its value."""

    return re.sub(r"[\s_\-./（）()\[\]{}]+", "", _as_text(value)).casefold()


def _issue_import_normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized_key = _issue_import_header_key(key)
        if normalized_key and normalized_key not in normalized:
            normalized[normalized_key] = value
    return normalized


def _issue_import_field(
    row: Mapping[str, Any],
    aliases: tuple[str, ...],
) -> tuple[bool, Any]:
    """Return whether an aliased column exists, keeping False/0 values intact."""

    normalized = _issue_import_normalized_row(row)
    found = False
    for alias in aliases:
        key = _issue_import_header_key(alias)
        if key not in normalized:
            continue
        found = True
        value = normalized[key]
        # If duplicate equivalent columns exist, prefer a non-empty one while
        # still reporting that the field itself was present.
        if _as_text(value):
            return True, value
    return found, ""


def _issue_import_has_column(
    rows: list[Any],
    aliases: tuple[str, ...],
) -> bool:
    return any(
        isinstance(row, Mapping) and _issue_import_field(row, aliases)[0]
        for row in rows
    )


def _issue_import_exclusion_value(value: Any) -> bool | None:
    """Parse a deliberate yes/no cell; never use generic truthiness here."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    text = re.sub(r"\s+", "", _as_text(value)).casefold()
    if text in _TRAIL_ISSUE_IMPORT_TRUE_VALUES:
        return True
    if text in _TRAIL_ISSUE_IMPORT_FALSE_VALUES:
        return False
    return None


def _issue_import_issue_ids(value: Any) -> list[str]:
    """Accept one ID per cell, plus comma/newline-separated legacy JSON IDs."""

    if isinstance(value, (list, tuple)):
        ids: list[str] = []
        for item in value:
            ids.extend(_issue_import_issue_ids(item))
        return ids
    text = _as_text(value).strip()
    if not text:
        return []
    return [
        item.strip()
        for item in re.split(r"[\n\r,，、;；|]+", text)
        if item.strip()
    ]


def _issue_import_display_filename(value: Any) -> str:
    """Expose a bounded basename only; upload paths must never reach the UI."""

    raw = _as_text(value).replace("\\", "/")
    filename = Path(raw).name
    filename = re.sub(r"[\x00-\x1f\x7f]+", "", filename).strip()
    return filename[:120] or "issue-exclusions.xlsx"


def _issue_import_excel_source_note(
    *,
    filename: str,
    sheet: str,
    row_number: int,
    source_sha256: str,
) -> str:
    """Persist enough file provenance in the comment for later Trail audit."""

    return (
        f"Excel 上传来源：{filename}（工作表「{sheet}」第 {row_number} 行；"
        f"SHA-256: {source_sha256}；“是否排除”=“是”）。"
    )


def _issue_import_json_rows(value: Any) -> tuple[list[Any], dict[str, Any]]:
    """Extract legacy/exported Issue drafts into ordinary import rows.

    A downloaded Issue preview contains a nested ``draft`` and may carry a
    per-Issue comment map.  This extraction deliberately mirrors the old
    browser-only importer while moving validation and source handling to the
    server-side preview contract.
    """

    if isinstance(value, list):
        return list(value), {"fallback_comment": "", "comment_by_issue": {}}
    if not isinstance(value, Mapping):
        raise ValueError("JSON 顶层必须是对象或数组。")

    current: Any = value
    fallback_comment = ""
    comment_by_issue: dict[str, str] = {}
    for _ in range(4):
        if not isinstance(current, Mapping):
            break
        candidate_comment = _as_text(current.get("comment")).strip()[:4000]
        if candidate_comment:
            fallback_comment = candidate_comment
        candidate_comments = current.get("comment_by_issue")
        if isinstance(candidate_comments, Mapping):
            for issue_id, note in candidate_comments.items():
                normalized_issue_id = _as_text(issue_id).strip()
                if normalized_issue_id:
                    comment_by_issue[normalized_issue_id] = _as_text(note).strip()[:4000]
        nested = next(
            (
                current.get(key)
                for key in ("draft", "payload", "data")
                if isinstance(current.get(key), (Mapping, list))
            ),
            None,
        )
        if nested is None:
            break
        current = nested

    if isinstance(current, list):
        return list(current), {
            "fallback_comment": fallback_comment,
            "comment_by_issue": comment_by_issue,
        }
    if not isinstance(current, Mapping):
        raise ValueError("JSON 顶层必须是对象或数组。")

    for key in (
        "requested_entries",
        "entries",
        "items",
        "rows",
        "results",
        "issue_ids",
        "requested_issue_ids",
    ):
        if key not in current:
            continue
        raw_rows = current.get(key)
        if isinstance(raw_rows, (list, tuple)):
            rows = list(raw_rows)
        elif raw_rows is None:
            rows = []
        else:
            rows = [raw_rows]
        return rows, {
            "fallback_comment": fallback_comment or _as_text(current.get("comment")).strip()[:4000],
            "comment_by_issue": comment_by_issue,
        }
    if any(_issue_import_header_key(key) in {
        _issue_import_header_key(alias) for alias in _TRAIL_ISSUE_IMPORT_ISSUE_ALIASES
    } for key in current):
        return [dict(current)], {
            "fallback_comment": fallback_comment,
            "comment_by_issue": comment_by_issue,
        }
    raise ValueError("未找到 Issue ID 列表；请提供 entries、requested_entries 或 issue_ids。")


def build_trail_issue_import_preview(
    raw_rows: list[Any],
    *,
    import_format: str,
    filename: str = "",
    source_sha256: str = "",
    metadata: Mapping[str, Any] | None = None,
    fallback_comment: str = "",
    comment_by_issue: Mapping[str, Any] | None = None,
    require_exclusion_column: bool = False,
    row_number_offset: int = 1,
) -> dict[str, Any]:
    """Build a pure, non-writing preview for JSON/XLSX Issue shielding.

    Only rows whose explicit ``是否排除`` value is true become editor entries.
    False rows remain visible as skipped, and malformed IDs/flags/duplicates
    keep the preview non-applicable so no row is silently discarded.
    """

    mode = "excel" if import_format == "excel" else "json"
    all_rows = list(raw_rows)
    rows = all_rows[:_TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS]
    sheet = _as_text((metadata or {}).get("sheet")).strip()[:120] or "Sheet1"
    normalized_filename = _issue_import_display_filename(filename) if filename else ""
    normalized_hash = _as_text(source_sha256).strip()[:128]
    normalized_fallback_comment = _as_text(fallback_comment).strip()[:4000]
    normalized_comment_by_issue = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (comment_by_issue or {}).items()
        if _as_text(issue_id).strip()
    }
    global_errors: list[str] = []
    warnings: list[str] = []
    if len(all_rows) > _TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS:
        global_errors.append(
            f"导入最多预览 {_TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS} 行；当前文件有 {len(all_rows)} 行。"
        )
    if not all_rows:
        global_errors.append("未找到可解析的数据行。")
    if require_exclusion_column and all_rows and not _issue_import_has_column(
        rows, _TRAIL_ISSUE_IMPORT_EXCLUDE_ALIASES
    ):
        global_errors.append("缺少必填列「是否排除」（也支持 should_exclude / is_excluded）。")

    items: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    seen_selected: set[str] = set()
    defaulted_exclusion_count = 0
    invalid_count = 0
    skipped_count = 0
    for index, raw_row in enumerate(rows):
        row_number = index + row_number_offset
        if isinstance(raw_row, Mapping):
            row = raw_row
        elif mode == "json":
            row = {"issue_id": raw_row}
        else:
            invalid_count += 1
            items.append(
                {
                    "row_number": row_number,
                    "issue_id": "",
                    "should_exclude": None,
                    "comment": "",
                    "status": "invalid",
                    "message": "该行不是可识别的对象。",
                }
            )
            continue

        has_issue_column, raw_issue_ids = _issue_import_field(
            row, _TRAIL_ISSUE_IMPORT_ISSUE_ALIASES
        )
        issue_ids = _issue_import_issue_ids(raw_issue_ids) if has_issue_column else []
        has_exclusion_column, raw_exclusion = _issue_import_field(
            row, _TRAIL_ISSUE_IMPORT_EXCLUDE_ALIASES
        )
        should_exclude = _issue_import_exclusion_value(raw_exclusion)
        blank_exclusion = has_exclusion_column and not _as_text(raw_exclusion)
        used_legacy_default = mode == "json" and not has_exclusion_column
        if used_legacy_default:
            should_exclude = True
            defaulted_exclusion_count += 1
        _, raw_comment = _issue_import_field(row, _TRAIL_ISSUE_IMPORT_COMMENT_ALIASES)
        provided_comment = _as_text(raw_comment).strip()[:4000]
        raw_source = row.get("source") if isinstance(row, Mapping) else None
        source: dict[str, Any] | None = None
        source_error = ""
        if raw_source is not None:
            source = _historical_source_payload(raw_source)
            if source is None:
                source_error = "标注来源格式无效。"

        if not issue_ids:
            invalid_count += 1
            items.append(
                {
                    "row_number": row_number,
                    "issue_id": "",
                    "should_exclude": should_exclude,
                    "comment": provided_comment,
                    "status": "invalid",
                    "message": "缺少 Issue ID。",
                }
            )
            continue

        for issue_id in issue_ids:
            item: dict[str, Any] = {
                "row_number": row_number,
                "issue_id": issue_id[:128],
                "should_exclude": should_exclude,
                "comment": provided_comment,
                "status": "invalid",
                "message": "",
            }
            if not ISSUE_ID_RE.fullmatch(issue_id):
                invalid_count += 1
                item["message"] = "Issue ID 格式无效。"
                items.append(item)
                continue
            # Historical spot-check files leave ordinary rows blank instead
            # of explicitly writing “否”.  That is a clear non-selection,
            # not an invalid exclusion request: keep it visible as skipped so
            # the true rows can still be reviewed and imported together.
            if mode == "excel" and blank_exclusion:
                skipped_count += 1
                item["status"] = "skipped"
                item["message"] = "未填写是否排除；不会进入屏蔽草稿。"
                item["source_label"] = (
                    f"上传 Excel · {normalized_filename} · {sheet} 第 {row_number} 行"
                )
                items.append(item)
                continue
            if should_exclude is None:
                invalid_count += 1
                item["message"] = (
                    "「是否排除」仅支持 是/否、true/false、1/0。"
                    if has_exclusion_column
                    else "缺少必填列「是否排除」。"
                )
                items.append(item)
                continue
            if should_exclude is False:
                skipped_count += 1
                item["status"] = "skipped"
                item["message"] = "是否排除=否；不会进入屏蔽草稿。"
                if mode == "excel":
                    item["source_label"] = (
                        f"上传 Excel · {normalized_filename} · {sheet} 第 {row_number} 行"
                    )
                items.append(item)
                continue
            if source_error:
                invalid_count += 1
                item["message"] = source_error
                items.append(item)
                continue
            if source is not None and _as_text(source.get("issue_id")) != issue_id:
                invalid_count += 1
                item["message"] = "标注来源中的 Issue ID 与当前行不一致。"
                items.append(item)
                continue
            if issue_id in seen_selected:
                invalid_count += 1
                item["message"] = "该 Issue ID 与另一条“是否排除=是”的行重复。"
                items.append(item)
                continue

            seen_selected.add(issue_id)
            effective_comment = (
                normalized_comment_by_issue.get(issue_id)
                or provided_comment
                or normalized_fallback_comment
            )[:4000]
            if mode == "excel":
                source_note = _issue_import_excel_source_note(
                    filename=normalized_filename,
                    sheet=sheet,
                    row_number=row_number,
                    source_sha256=normalized_hash,
                )
                effective_comment = _append_historical_source_note(
                    effective_comment, source_note
                )
                item["source_label"] = (
                    f"上传 Excel · {normalized_filename} · {sheet} 第 {row_number} 行"
                )
            elif source is not None:
                item["source"] = source
            item["comment"] = effective_comment
            item["status"] = "ready"
            item["message"] = "将替换到屏蔽草稿；尚未写入 Trail。"
            entry: dict[str, Any] = {
                "issue_id": issue_id,
                "comment": effective_comment,
            }
            if source is not None:
                entry["source"] = source
            entries.append(entry)
            items.append(item)

    if defaulted_exclusion_count:
        warnings.append(
            f"{defaulted_exclusion_count} 行 JSON 未提供「是否排除」，已按“是”兼容旧草稿。"
        )
    if len(entries) > _TRAIL_ISSUE_IMPORT_MAX_ENTRIES:
        global_errors.append(
            f"单次按 Issue ID 屏蔽最多支持 {_TRAIL_ISSUE_IMPORT_MAX_ENTRIES} 条；当前有 {len(entries)} 条“是”。"
        )
    ready_count = len(entries)
    if global_errors:
        message = global_errors[0]
    elif invalid_count:
        message = f"发现 {invalid_count} 条需修正的行；修正后才能替换草稿。"
    elif not ready_count:
        message = "没有“是否排除=是”的行可导入。"
    else:
        message = f"预览就绪：{ready_count} 条将进入屏蔽草稿；尚未写入 Trail。"
    return {
        "schema_version": TRAIL_ISSUE_IMPORT_PREVIEW_SCHEMA,
        "mode": mode,
        "filename": normalized_filename,
        "source_sha256": normalized_hash,
        "metadata": {"sheet": sheet} if mode == "excel" else {},
        "contract": {
            "required": ["issue_id", "是否排除"] if mode == "excel" else ["issue_id"],
            "optional": ["comment"],
            "exclude_aliases": ["是否排除", "should_exclude", "is_excluded"],
        },
        "summary": {
            "source_row_count": len(all_rows),
            "previewed_row_count": len(rows),
            "ready_count": ready_count,
            "skipped_count": skipped_count,
            "invalid_count": invalid_count,
            "message": message,
        },
        "global_errors": global_errors,
        "warnings": warnings,
        "items": items,
        "entries": entries,
        "can_apply": bool(entries) and not invalid_count and not global_errors,
    }



def build_trail_attribute_update_payload(
    rows: list[dict[str, Any]],
    *,
    run: dict[str, Any],
    baseline_ids: list[str],
    baseline_scopes: list[str],
    result_field: str = TRAIL_RESULT_FIELD,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: dict[str, Any] | None = None,
    trail_statuses: dict[str, str] | None = None,
    trail_write_enabled: bool = False,
    write_mode: str = "model_and_info",
) -> dict[str, Any]:
    """Compatibility facade for the extracted deterministic draft builder.

    Keeping this public name protects existing API-level tests and extensions,
    while all live calls now share the framework-free implementation.
    """

    return _build_review_exclusion_payload(
        rows,
        run=run,
        baseline_ids=baseline_ids,
        baseline_scopes=baseline_scopes,
        result_field=result_field,
        info_field=info_field,
        trail_capability=trail_capability,
        trail_statuses=trail_statuses,
        trail_write_enabled=trail_write_enabled,
        write_mode=write_mode,
        not_checked_capability=_capability_not_checked(result_field, info_field),
    )


def build_trail_issue_exclusion_payload(
    issue_ids: list[str],
    *,
    current_rows: list[dict[str, Any]],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
    comment_by_issue: Mapping[str, str] | None = None,
    requested_entries: list[dict[str, Any]] | None = None,
    baseline_by_issue: Mapping[str, Mapping[str, Any]] | None = None,
    info_field: str = TRAIL_INFO_FIELD,
    trail_capability: dict[str, Any] | None = None,
    trail_write_enabled: bool = False,
) -> dict[str, Any]:
    """Compatibility facade for the extracted direct-Issue draft builder."""

    return _build_direct_issue_exclusion_payload(
        issue_ids,
        current_rows=current_rows,
        invalid_issue_ids=invalid_issue_ids,
        comment=comment,
        comment_by_issue=comment_by_issue,
        requested_entries=requested_entries,
        baseline_by_issue=baseline_by_issue,
        info_field=info_field,
        trail_capability=trail_capability,
        trail_write_enabled=trail_write_enabled,
        view_id=int(settings.trail_view_id),
        normalise_source=_historical_source_payload,
    )


async def _build_preview(
    request: Request,
    *,
    selected_run_id: str,
    baselines: str = "",
    probe_trail: bool = True,
    refresh_trail: bool = False,
) -> dict[str, Any]:
    baseline_ids = resolve_request_baseline_ids(baselines, request=request)
    baseline_scopes = resolve_request_baseline_scopes(baselines, request=request)
    if selected_run_id:
        run = await asyncio.to_thread(database.get_model_run, selected_run_id)
    else:
        run = {"id": "", "name": "全部 Model Runs", "source_name": ""}
    if selected_run_id and run is None:
        raise _detail(404, "模型 Run 不存在，无法生成 Trail 属性更新预览。")
    # The browser's initial paint intentionally skips the remote Trail probe;
    # cache only that local fast path. A checked/refresh request always takes
    # a fresh database snapshot so its signed write validation cannot reuse a
    # short-lived presentation result.
    if probe_trail:
        rows = await asyncio.to_thread(
            database.review_reason_rows,
            baseline_scopes=baseline_scopes,
            model_run_id=selected_run_id,
            comparison_status="all",
            is_excluded=True,
        )
    else:
        rows = await asyncio.to_thread(
            _review_exclusion_candidate_rows,
            selected_run_id=selected_run_id,
            baseline_scopes=baseline_scopes,
        )
    result_field, info_field = _field_names()
    review_write_enabled = bool(
        settings.trail_attribute_write_enabled
        and getattr(settings, "trail_attribute_review_write_enabled", False)
    )
    issue_ids = [_as_text(row.get("issue_id")) for row in rows if _as_text(row.get("issue_id"))]
    # Build the deterministic local draft first.  Its expected per-Issue note
    # is needed by the later batched Trail comparison, but this local work does
    # not touch Trail and stays on the fast first-paint path.
    initial_capability = _capability_not_checked(result_field, info_field)
    initial_capability["target_fields"] = [info_field]
    initial_capability["required_fields"] = [info_field]
    local_payload = await asyncio.to_thread(
        build_trail_attribute_update_payload,
        rows,
        run=run,
        baseline_ids=baseline_ids,
        baseline_scopes=baseline_scopes,
        result_field=result_field,
        info_field=info_field,
        trail_capability=initial_capability,
        trail_statuses=None,
        trail_write_enabled=review_write_enabled,
        write_mode="info_only",
    )
    expected_comments = _expected_exclusion_comments(local_payload.get("items") or [])
    # Trail status is a read-only projection and is useful even when the
    # controlled writer is disabled. Keep the first local paint cheap, then
    # perform one batched read when the caller explicitly asks for it.
    trail_statuses: dict[str, str] | None = None
    if issue_ids and probe_trail:
        projection = await _read_preview_trail_status(
            issue_ids,
            info_field=info_field,
            expected_comments=expected_comments,
            refresh=refresh_trail,
        )
        capability = dict(projection["trail_capability"])
        trail_statuses = dict(projection["trail_update_statuses"])
    else:
        capability = initial_capability
        # The first-paint request is intentionally still waiting for the
        # background probe. Keep rows in “查询中” until that single batched
        # read returns, regardless of whether writing is enabled.
        if not (issue_ids and not probe_trail):
            trail_statuses = {}
    payload = local_payload if not probe_trail else await asyncio.to_thread(
        build_trail_attribute_update_payload,
        rows,
        run=run,
        baseline_ids=baseline_ids,
        baseline_scopes=baseline_scopes,
        result_field=result_field,
        info_field=info_field,
        trail_capability=capability,
        trail_statuses=trail_statuses,
        trail_write_enabled=review_write_enabled,
        write_mode="info_only",
    )
    # The first page request deliberately skips the remote Trail capability
    # read so the local Review aggregate can paint immediately.  The browser
    # follows it with the checked request in the background and replaces the
    # payload before enabling a possible commit.
    payload["capability_pending"] = bool(issue_ids and not probe_trail)
    _remember_preview_status_expectations(payload)
    return payload


async def _build_direct_preview(
    *,
    issue_ids: list[str],
    invalid_issue_ids: list[str] | None = None,
    comment: str = "",
    comment_by_issue: Mapping[str, str] | None = None,
    requested_entries: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], Any]:
    """Read target fields and build the direct Issue-ID draft."""

    result_field, info_field = _field_names()
    sync_result = await asyncio.to_thread(
        read_trail_model_fields,
        ra_root=settings.ra_auto_triage_root,
        issue_ids=issue_ids,
        view_id=settings.trail_view_id,
        chunk_size=settings.trail_sync_chunk_size,
    )
    capability = _capability_for_info_write(sync_result, info_field)
    baseline_scopes = await asyncio.to_thread(
        database.issue_baseline_scopes,
        issue_ids,
    )
    baseline_by_issue = {
        issue_id: {
            "baseline_scope": scope,
            "baseline_id": baseline_registry.scope_to_id(scope) or "",
        }
        for issue_id, scope in baseline_scopes.items()
    }
    payload = await asyncio.to_thread(
        build_trail_issue_exclusion_payload,
        issue_ids,
        current_rows=sync_result.rows,
        invalid_issue_ids=invalid_issue_ids,
        comment=comment,
        comment_by_issue=comment_by_issue,
        requested_entries=requested_entries,
        baseline_by_issue=baseline_by_issue,
        info_field=info_field,
        trail_capability=capability,
        trail_write_enabled=settings.trail_attribute_write_enabled,
    )
    # The direct workflow does not update the model label, but the field is
    # retained in the capability response for operators comparing both tabs.
    payload["model_result_field"] = result_field
    return payload, sync_result


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


@router.get("/api/trail-attribute-update/preview")
async def trail_attribute_update_preview(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
    probe_trail: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """Return should-exclude rows for one Run or the all-Run aggregate."""

    return await _build_preview(
        request,
        selected_run_id=_as_text(model_run_id),
        baselines=baselines,
        probe_trail=probe_trail,
        refresh_trail=refresh,
    )


@router.get("/api/trail-attribute-update/status")
async def trail_attribute_update_status(
    issue_ids: str = "",
    payload_sha256: str = "",
    refresh: bool = False,
) -> dict[str, Any]:
    """Return only the batched Trail state for an existing Review preview.

    The browser uses this after the local candidate table has painted.  Keeping
    the remote state response compact avoids a second DB aggregation and, more
    importantly, avoids replacing the table/controls when Trail is slow.
    """

    normalized_ids, invalid_ids = _normalise_issue_ids(issue_ids)
    if invalid_ids:
        raise _detail(422, f"Issue ID 格式不合法：{', '.join(invalid_ids[:5])}")
    if len(normalized_ids) > 500:
        raise _detail(422, "一次最多查询 500 个 Issue。")
    result_field, info_field = _field_names()
    if not normalized_ids:
        capability = _capability_not_checked(result_field, info_field)
        capability["target_fields"] = [info_field]
        capability["required_fields"] = [info_field]
        return {
            "issue_ids": [],
            "trail_capability": capability,
            "trail_update_statuses": {},
            "trail_update_status_summary": {},
            "write_status": "disabled",
            "write_ready": False,
        }
    expected_comments = _preview_status_expectations(payload_sha256)
    # A digest is supplied by current clients.  If its short-lived local
    # expectation has expired, do not downgrade to marker-only matching: that
    # could incorrectly hide a changed exclusion note.  Ask the client to
    # reload the local preview instead.  Keep the no-digest fallback for one
    # rolling-deploy window with older cached static assets.
    if payload_sha256 and expected_comments is None:
        capability = _capability_not_checked(result_field, info_field)
        capability.update({
            "target_fields": [info_field],
            "required_fields": [info_field],
            "message": "本地排除预览已过期，请重新打开问题排除页面后再检查 Trail 状态。",
        })
        statuses = {issue_id: "query_failed" for issue_id in normalized_ids}
        return {
            "issue_ids": normalized_ids,
            "trail_capability": capability,
            "trail_update_statuses": statuses,
            "trail_update_status_summary": _trail_update_status_summary(statuses),
            "pending_count": 0,
            "write_status": "status_check_incomplete",
            "write_ready": False,
        }
    projection = await _read_preview_trail_status(
        normalized_ids,
        info_field=info_field,
        expected_comments=expected_comments,
        refresh=refresh,
    )
    capability = dict(projection["trail_capability"])
    review_write_enabled = bool(
        settings.trail_attribute_write_enabled
        and getattr(settings, "trail_attribute_review_write_enabled", False)
    )
    statuses = dict(projection["trail_update_statuses"])
    pending_count = sum(1 for status in statuses.values() if status == "pending")
    status_check_complete = all(
        status in {"pending", "synced"} for status in statuses.values()
    )
    write_status = "disabled"
    if review_write_enabled:
        if not capability.get("ready"):
            write_status = "fields_unavailable"
        elif not status_check_complete:
            write_status = "status_check_incomplete"
        elif not pending_count:
            write_status = "already_synced"
        else:
            write_status = "ready"
    return {
        "issue_ids": normalized_ids,
        "trail_capability": capability,
        "trail_update_statuses": statuses,
        "trail_update_status_summary": dict(
            projection["trail_update_status_summary"]
        ),
        "pending_count": pending_count,
        "write_status": write_status,
        "write_ready": write_status == "ready",
    }


@router.get("/api/trail-attribute-update/issue-history")
async def trail_issue_exclusion_history(
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List recent Issue-ID shielding submissions without contacting Trail."""

    return await asyncio.to_thread(
        database.list_trail_issue_exclusion_history,
        limit=max(1, min(int(limit), 100)),
        offset=max(0, int(offset)),
    )


@router.get("/api/trail-attribute-update/historical-exclusions")
async def trail_historical_exclusions(
    request: Request,
    baselines: str = "",
) -> dict[str, Any]:
    """Return read-only XLSX exclusion candidates for the selected baselines.

    Loading this list does not create a Review and does not contact Trail.  A
    user still has to build a preview and explicitly confirm a write.
    """

    baseline_ids = resolve_request_baseline_ids(baselines, request=request)
    items = await asyncio.to_thread(
        issue_tag_sources.exclusion_candidates,
        baseline_ids=baseline_ids,
    )
    return {
        "schema_version": "historical-exclusion-source-v1",
        "mode": "historical_spotcheck_xlsx",
        "baselines": baseline_ids,
        "count": len(items),
        "items": items,
    }


@router.post("/api/trail-attribute-update/issue-import/json-preview")
async def trail_issue_json_import_preview(request: Request) -> dict[str, Any]:
    """Parse an Issue-shielding JSON draft without changing the editor or Trail."""

    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "预览内容不是合法 JSON。") from exc
    try:
        rows, context = await asyncio.to_thread(_issue_import_json_rows, body)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    return await asyncio.to_thread(
        build_trail_issue_import_preview,
        rows,
        import_format="json",
        fallback_comment=_as_text(context.get("fallback_comment")),
        comment_by_issue=context.get("comment_by_issue"),
    )


@router.post("/api/trail-attribute-update/issue-import/excel-preview")
async def trail_issue_excel_import_preview(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Parse an XLSX/XLSM Issue-shielding sheet as a read-only preview."""

    filename = _issue_import_display_filename(file.filename or "issue-exclusions.xlsx")
    if Path(filename).suffix.lower() not in {".xlsx", ".xlsm"}:
        raise _detail(400, "请上传 .xlsx 或 .xlsm 文件。")
    try:
        content, source_sha256 = await read_upload_limited(
            file,
            max_bytes=MAX_UPLOAD_BYTES,
        )
    except UploadLimitExceeded as exc:
        raise _detail(413, "上传文件超过 64 MB 限制。") from exc
    if not content:
        raise _detail(400, "上传文件为空。")
    try:
        rows, metadata = await asyncio.to_thread(parse_source_bytes, filename, content)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, f"解析 Excel 失败: {exc}") from exc
    return await asyncio.to_thread(
        build_trail_issue_import_preview,
        rows,
        import_format="excel",
        filename=filename,
        source_sha256=source_sha256,
        metadata=metadata,
        require_exclusion_column=True,
        row_number_offset=2,
    )


@router.post("/api/trail-attribute-update/issue-preview")
async def trail_issue_exclusion_preview(request: Request) -> dict[str, Any]:
    """Preview direct Issue-ID shielding without contacting a write API."""

    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "预览内容不是合法 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "预览内容必须是 JSON 对象。")
    fallback_comment = _as_text(body.get("comment"))
    raw_entries = body.get("entries") if "entries" in body else body.get("issue_ids", [])
    normalized_entries, invalid = _normalise_issue_entries(
        raw_entries,
        fallback_comment=fallback_comment,
    )
    normalized_entries, source_invalid = _resolve_historical_exclusion_entries(
        normalized_entries
    )
    invalid.extend(source_invalid)
    normalized_ids = [item["issue_id"] for item in normalized_entries]
    if not normalized_ids and not invalid:
        raise _detail(400, "请输入至少一个 Issue ID。")
    if len(normalized_entries) + len(invalid) > 200:
        raise _detail(400, "单次按 Issue ID 屏蔽最多支持 200 条。")
    comment_by_issue = {item["issue_id"]: item["comment"] for item in normalized_entries}
    payload, _sync_result = await _build_direct_preview(
        issue_ids=normalized_ids,
        invalid_issue_ids=invalid,
        comment=fallback_comment,
        comment_by_issue=comment_by_issue,
        requested_entries=normalized_entries,
    )
    return payload


@router.post("/api/trail-attribute-update/commit")
async def trail_attribute_update_commit(request: Request) -> dict[str, Any]:
    """Commit an unchanged, field-validated preview to Trail in small chunks."""

    if not settings.trail_attribute_write_enabled:
        raise _detail(409, "Trail 属性写入开关尚未开启；当前仅允许预览和下载草稿。")
    if not getattr(settings, "trail_attribute_review_write_enabled", False):
        raise _detail(409, "Review 汇总写入已关闭；当前仅允许 Issue ID info-only 写入。")
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源写请求标记。")
    identity = await asyncio.to_thread(request_identity, request, settings)
    if not identity_can_write(identity, settings):
        raise _detail(403, "Trail 属性更新需要已验证的 SSO 写入权限。")
    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "提交内容不是合法 JSON。") from exc
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise _detail(400, "提交 Trail 更新前必须明确 confirm=true。")
    run_id = _as_text(body.get("model_run_id"))
    submitted_digest = _as_text(body.get("payload_sha256"))
    if not submitted_digest:
        raise _detail(400, "提交内容缺少 payload_sha256。")
    raw_baselines = body.get("baselines", "")
    if isinstance(raw_baselines, list):
        baseline_query = ",".join(_as_text(item) for item in raw_baselines if _as_text(item))
    else:
        baseline_query = _as_text(raw_baselines)
    # Serialize commits in this process.  The digest check below still makes
    # a stale browser preview fail closed across workers/processes.
    with _commit_lock:
        preview = await _build_preview(
            request,
            selected_run_id=run_id,
            baselines=baseline_query,
        )
        if submitted_digest != _as_text(preview.get("payload_sha256")):
            raise _detail(409, "预览已过期或内容发生变化，请重新生成后再提交。")
        if not preview.get("write_ready"):
            capability = preview.get("trail_capability") or {}
            message = _as_text(capability.get("message")) or "目标字段不可写。"
            raise _detail(409, f"Trail 属性更新未就绪：{message}")
        result_field, info_field = _field_names()
        sync_result = await asyncio.to_thread(
            read_trail_model_fields,
            ra_root=settings.ra_auto_triage_root,
            issue_ids=[_as_text(item.get("issue_id")) for item in preview.get("items", [])],
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        if (
            not sync_result.complete
            or int(sync_result.returned_issues) != int(sync_result.queried_issues)
        ):
            raise _detail(409, _as_text(sync_result.message) or "Trail Issue 回读不完整。")
        expected_comments = _expected_exclusion_comments(
            [item for item in (preview.get("items") or []) if isinstance(item, dict)]
        )
        statuses = _trail_update_statuses(
            sync_result,
            [_as_text(item.get("issue_id")) for item in preview.get("items", [])],
            info_field=info_field,
            expected_comments=expected_comments,
        )
        incomplete_ids = [
            issue_id for issue_id, status in statuses.items()
            if status not in {"synced", "pending"}
        ]
        if incomplete_ids:
            raise _detail(
                409,
                f"Trail 状态检查不完整，未写入任何 Issue：{', '.join(incomplete_ids[:8])}",
            )
        pending_items = [
            item for item in (preview.get("items") or [])
            if _as_text(statuses.get(_as_text(item.get("issue_id")))) == "pending"
        ]
        skipped_synced_issue_ids = sorted(
            issue_id for issue_id, status in statuses.items() if status == "synced"
        )
        if not pending_items:
            _preview_capability_cache.clear()
            return {
                "ok": True,
                "mode": "commit",
                "payload_sha256": submitted_digest,
                "model_run_id": run_id,
                "actor": {
                    "username": identity.username,
                    "source": identity.source,
                    "verified": identity.verified,
                },
                "write_mode": "info_only",
                "model_result_field": result_field,
                "target_fields": [info_field],
                "submitted_count": 0,
                "skipped_synced_issue_ids": skipped_synced_issue_ids,
                "trail_update_status_summary": _trail_update_status_summary(statuses),
                "stats": write_trail_model_results([], ra_root=settings.ra_auto_triage_root),
                "readback": {
                    "complete": True,
                    "ok": True,
                    "checked_count": 0,
                    "verified_count": 0,
                    "missing_issue_ids": [],
                    "mismatched_issue_ids": [],
                    "message": "所有候选项的排除标记和排除说明均已同步；未发送 Trail 写入。",
                },
            }
        changes = await asyncio.to_thread(
            build_trail_changes,
            pending_items,
            current_rows=sync_result.rows,
            result_field=result_field,
            info_field=info_field,
            write_result_field=False,
        )
        # Keep retries idempotent inside the same JSON info namespace.  No
        # separate Trail Comment request is made.
        changes = attach_trail_operation_id(changes, operation_id=submitted_digest)
        stats = await asyncio.to_thread(
            write_trail_model_results,
            changes,
            ra_root=settings.ra_auto_triage_root,
            chunk_size=settings.trail_attribute_write_chunk_size,
        )
        readback = await _readback_changes(
            changes,
            stats,
            result_field="",
            info_field=info_field,
        )
        _preview_capability_cache.clear()
    return {
        "ok": (
            not stats.get("failed_count")
            and not stats.get("comment_failed_count")
            and bool(readback.get("ok"))
        ),
        "mode": "commit",
        "payload_sha256": submitted_digest,
        "model_run_id": run_id,
        "actor": {
            "username": identity.username,
            "source": identity.source,
            "verified": identity.verified,
        },
        "write_mode": "info_only",
        "model_result_field": result_field,
        "target_fields": [info_field],
        "submitted_count": len(changes),
        "skipped_synced_issue_ids": skipped_synced_issue_ids,
        "trail_update_status_summary": _trail_update_status_summary(statuses),
        "stats": stats,
        "readback": readback,
    }


@router.post("/api/trail-attribute-update/issue-commit")
async def trail_issue_exclusion_commit(request: Request) -> dict[str, Any]:
    """Commit direct Issue-ID shielding through the info JSON field."""

    if not settings.trail_attribute_write_enabled:
        raise _detail(409, "Trail 属性写入开关尚未开启；当前仅允许预览和下载草稿。")
    if not has_same_origin_mutation_marker(request):
        raise _detail(403, "缺少同源写请求标记。")
    identity = await asyncio.to_thread(request_identity, request, settings)
    if not identity_can_write(identity, settings):
        raise _detail(403, "Trail 属性更新需要已验证的 SSO 写入权限。")
    try:
        body = await request.json()
    except Exception as exc:
        raise _detail(400, "提交内容不是合法 JSON。") from exc
    if not isinstance(body, dict) or body.get("confirm") is not True:
        raise _detail(400, "提交 Trail 更新前必须明确 confirm=true。")
    fallback_comment = _as_text(body.get("comment"))
    raw_entries = body.get("entries") if "entries" in body else body.get("issue_ids", [])
    requested_entries, invalid = _normalise_issue_entries(
        raw_entries,
        fallback_comment=fallback_comment,
    )
    requested_entries, source_invalid = _resolve_historical_exclusion_entries(
        requested_entries
    )
    invalid.extend(source_invalid)
    issue_ids = [item["issue_id"] for item in requested_entries]
    if invalid:
        raise _detail(400, "提交内容包含无法识别的 Issue ID。")
    if not issue_ids:
        raise _detail(400, "提交内容缺少 Issue ID。")
    if len(issue_ids) > 200:
        raise _detail(400, "单次按 Issue ID 屏蔽最多支持 200 条。")
    comment_by_issue = {item["issue_id"]: item["comment"] for item in requested_entries}
    submitted_digest = _as_text(body.get("payload_sha256"))
    if not submitted_digest:
        raise _detail(400, "提交内容缺少 payload_sha256。")
    with _commit_lock:
        preview, sync_result = await _build_direct_preview(
            issue_ids=issue_ids,
            comment=fallback_comment,
            comment_by_issue=comment_by_issue,
            requested_entries=requested_entries,
        )
        if submitted_digest != _as_text(preview.get("payload_sha256")):
            raise _detail(409, "预览已过期或内容发生变化，请重新生成后再提交。")
        # ``already_synced`` is a successful, idempotent terminal state for
        # Trail itself.  Still allow this request to refresh the local Review
        # exclusion flag below; do not send a duplicate field update.
        if (
            not preview.get("write_ready")
            and _as_text(preview.get("write_status")) != "already_synced"
        ):
            capability = preview.get("trail_capability") or {}
            detail = _as_text(capability.get("message")) or "目标字段不可写。"
            missing = preview.get("missing_issue_ids") or []
            if missing:
                detail = f"{detail} 未找到 Issue: {', '.join(str(item) for item in missing[:8])}"
            raise _detail(409, f"Issue ID 屏蔽未就绪：{detail}")
        # The preview contract normalizes an empty row note to an auditable
        # default.  Reuse each item's exact value for the info JSON field and
        # local Review annotation; no separate Trail Comment is written.
        effective_comments = {
            _as_text(item.get("issue_id")).strip(): _as_text(item.get("comment")).strip()[:4000]
            for item in (preview.get("items") or [])
            if _as_text(item.get("issue_id")).strip()
        }
        source_by_issue = {
            _as_text(item.get("issue_id")).strip(): _historical_source_payload(
                item.get("source")
            )
            for item in (preview.get("requested_entries") or [])
            if _as_text(item.get("issue_id")).strip()
            and _historical_source_payload(item.get("source")) is not None
        }
        source_notes = {
            issue_id: effective_comments.get(issue_id, "")
            for issue_id in source_by_issue
        }
        history_entries = [
            {
                "issue_id": issue_id,
                "comment": effective_comments.get(issue_id, ""),
                **(
                    {"source": source_by_issue[issue_id]}
                    if issue_id in source_by_issue
                    else {}
                ),
            }
            for issue_id in issue_ids
        ]
        statuses = {
            _as_text(item.get("issue_id")).strip(): _as_text(
                item.get("trail_update_status")
            )
            for item in (preview.get("items") or [])
            if _as_text(item.get("issue_id")).strip()
        }
        unchecked_issue_ids = sorted(
            issue_id
            for issue_id, status in statuses.items()
            if status not in {"pending", "synced"}
        )
        if unchecked_issue_ids:
            raise _detail(
                409,
                "Trail 状态检查不完整，未写入任何 Issue："
                f"{', '.join(unchecked_issue_ids[:8])}",
            )
        pending_issue_ids = sorted(
            issue_id for issue_id, status in statuses.items() if status == "pending"
        )
        skipped_synced_issue_ids = sorted(
            issue_id for issue_id, status in statuses.items() if status == "synced"
        )
        await _save_issue_exclusion_history(
            operation_id=submitted_digest,
            identity=identity,
            status="pending",
            requested_entries=history_entries,
            message=(
                f"已生成待提交记录：待写 {len(pending_issue_ids)} 条，"
                f"已同步跳过 {len(skipped_synced_issue_ids)} 条。"
            ),
        )
        _, info_field = _field_names()
        try:
            if pending_issue_ids:
                changes = await asyncio.to_thread(
                    build_manual_exclusion_changes,
                    pending_issue_ids,
                    current_rows=sync_result.rows,
                    info_field=info_field,
                    comment_by_issue=effective_comments,
                )
                changes = attach_trail_operation_id(changes, operation_id=submitted_digest)
                stats = await asyncio.to_thread(
                    write_trail_model_results,
                    changes,
                    ra_root=settings.ra_auto_triage_root,
                    chunk_size=settings.trail_attribute_write_chunk_size,
                )
                readback = await _readback_changes(
                    changes,
                    stats,
                    result_field="",
                    info_field=info_field,
                )
            else:
                # Keep the response contract identical for an idempotent
                # retry, without instantiating a Trail client or sending any
                # write request.
                changes = []
                stats = write_trail_model_results(
                    [], ra_root=settings.ra_auto_triage_root
                )
                readback = {
                    "complete": True,
                    "ok": True,
                    "checked_count": 0,
                    "verified_count": 0,
                    "missing_issue_ids": [],
                    "mismatched_issue_ids": [],
                    "message": "所有候选项的排除标记和排除说明均已同步；未发送 Trail 写入。",
                }
            field_failed = {
                str(item).strip()
                for item in stats.get("failed_issue_ids", [])
                if str(item).strip()
            }
            readback_failed = {
                str(item).strip()
                for item in (
                    list(readback.get("missing_issue_ids", []))
                    + list(readback.get("mismatched_issue_ids", []))
                )
                if str(item).strip()
            }
            newly_verified_issue_ids = [
                str(item.get("issue_id") or "").strip()
                for item in changes
                if str(item.get("issue_id") or "").strip()
                and str(item.get("issue_id") or "").strip() not in field_failed
                and str(item.get("issue_id") or "").strip() not in readback_failed
            ]
            verified_issue_ids = sorted(
                set(skipped_synced_issue_ids) | set(newly_verified_issue_ids)
            )
            local_review = (
                await asyncio.to_thread(
                    _mark_local_review_exclusions,
                    verified_issue_ids,
                    actor=identity,
                    fallback_notes=effective_comments,
                    source_notes=source_notes,
                )
                if readback.get("complete")
                else {
                    "requested_count": 0,
                    "marked_count": 0,
                    "already_excluded_count": 0,
                    "not_in_dashboard_count": 0,
                    "not_in_dashboard_issue_ids": [],
                    "failed_count": 0,
                    "failed_issue_ids": [],
                    "failure_messages": {},
                    "ok": False,
                    "status": "readback_incomplete",
                }
            )
        except Exception as exc:
            await _save_issue_exclusion_history(
                operation_id=submitted_digest,
                identity=identity,
                status="failed",
                requested_entries=history_entries,
                failed_issue_ids=set(issue_ids),
                message=f"提交异常：{str(exc)[:1000]}",
            )
            raise
        failed_issue_ids = field_failed | readback_failed
        local_failed_issue_ids = {
            str(item).strip()
            for item in local_review.get("failed_issue_ids", [])
            if str(item).strip()
        }
        not_in_dashboard_issue_ids = {
            str(item).strip()
            for item in local_review.get("not_in_dashboard_issue_ids", [])
            if str(item).strip()
        }
        trail_ok = (
            not stats.get("failed_count")
            and not stats.get("comment_failed_count")
            and bool(readback.get("ok"))
        )
        history_status = (
            "completed"
            if not failed_issue_ids and not local_failed_issue_ids
            else "partial" if verified_issue_ids else "failed"
        )
        history_message = (
            f"Trail 新写并回读 {len(newly_verified_issue_ids)}/{len(changes)} 条成功；"
            f"已同步跳过 {len(skipped_synced_issue_ids)} 条。"
            if readback.get("complete")
            else "Trail 回读不完整，未同步本地 Review 排除状态。"
        )
        if not_in_dashboard_issue_ids:
            history_message += (
                f" 其中 {len(not_in_dashboard_issue_ids)} 条不在当前看板数据集，"
                "未创建本地 Review 排除标记。"
            )
        if local_failed_issue_ids:
            history_message += (
                f" 本地 Review 排除标记失败 {len(local_failed_issue_ids)} 条。"
            )
        await _save_issue_exclusion_history(
            operation_id=submitted_digest,
            identity=identity,
            status=history_status,
            requested_entries=history_entries,
            synced_issue_ids=set(verified_issue_ids),
            failed_issue_ids=failed_issue_ids | local_failed_issue_ids,
            external_only_issue_ids=not_in_dashboard_issue_ids,
            failure_messages={
                **{
                    issue_id: "Trail 字段写入失败。"
                    for issue_id in field_failed
                },
                **{
                    issue_id: "Trail 回读校验失败。"
                    for issue_id in readback_failed
                },
                **{
                    issue_id: _as_text(
                        (local_review.get("failure_messages") or {}).get(issue_id)
                    ) or "本地 Review 排除标记失败。"
                    for issue_id in local_failed_issue_ids
                },
            },
            message=history_message,
        )
    return {
        # ``ok`` is the Trail write contract.  A Trail-only Issue is already
        # correctly updated and should not make the operator retry it simply
        # because the dashboard has no local case to annotate.
        "ok": trail_ok,
        "trail_ok": trail_ok,
        "local_review_ok": bool(local_review.get("ok")),
        "local_dashboard_sync_partial": bool(
            not_in_dashboard_issue_ids or local_failed_issue_ids
        ),
        "mode": "direct_issue_ids",
        "payload_sha256": submitted_digest,
        "actor": {
            "username": identity.username,
            "source": identity.source,
            "verified": identity.verified,
        },
        "target_fields": [info_field],
        "target_path": TRAIL_TARGET_PATH,
        "submitted_count": len(changes),
        "skipped_synced_issue_ids": skipped_synced_issue_ids,
        "trail_update_status_summary": _trail_update_status_summary(statuses),
        "stats": stats,
        "readback": readback,
        "local_review": local_review,
    }
