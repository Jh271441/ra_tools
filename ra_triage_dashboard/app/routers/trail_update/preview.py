"""Trail attribute update preview domain."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Mapping

from fastapi import Request

from ...runtime import baseline_registry, database, settings
from ...support.baselines import (
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ...support.common import _as_text, _detail
from ...trail_exclusion_contracts import (
    TRAIL_INFO_FIELD,
    TRAIL_RESULT_FIELD,
    canonical_json as _canonical_json,
    expected_exclusion_comments as _expected_exclusion_comments,
    normalise_exclusion_comment as _normalise_exclusion_comment,
    trail_update_status_summary as _trail_update_status_summary,
    trail_update_statuses as _trail_update_statuses,
)
from ...trail_exclusion_payloads import (
    build_direct_issue_exclusion_payload as _build_direct_issue_exclusion_payload,
    build_review_exclusion_payload as _build_review_exclusion_payload,
)
from ...trail_sync import read_trail_model_fields
from ...timed_cache import TimedSingleFlightCache
from .imports import _historical_source_payload


# Remote Trail probes are short-lived and single-flight so a burst of page/status
# requests does not repeat the same network read.
_preview_capability_cache = TimedSingleFlightCache[
    tuple[int, str, str, tuple[str, ...]], dict[str, Any]
](ttl_seconds=90, max_entries=256)

# Local Review aggregation has an independent, shorter lifetime than Trail state.
_review_exclusion_candidate_cache = TimedSingleFlightCache[
    tuple[str, tuple[str, ...]], list[dict[str, Any]]
](ttl_seconds=12, max_entries=128)

# Signed comment expectations let the compact status endpoint avoid rebuilding
# the Review candidate payload. Unknown/expired digests still fail closed.
_preview_status_expectation_cache = TimedSingleFlightCache[str, Any](
    ttl_seconds=180,
    max_entries=512,
)

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
            # The shared Trail reader also reports whether the historical
            # model-label field is visible.  This workflow deliberately does
            # not require or write that field, so its diagnostic must not
            # imply an otherwise-ready info-only update is unavailable.
            message = (
                f"Trail view {sync_result.view_id} 已返回 {info_field}；"
                "将仅 deep-merge 排除标记与说明，不改模型 label。"
            )
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
