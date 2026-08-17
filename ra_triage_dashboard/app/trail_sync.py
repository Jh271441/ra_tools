from __future__ import annotations

import importlib
import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TRAIL_RESULT_FIELD = "ra_stuck_auto_result"
TRAIL_INFO_FIELD = "ra_stuck_auto_result_info"
TRAIL_COMMENT_FIELD = "more_comment"

# These are display-only fields.  They are deliberately kept separate from
# the model-result contract above: Trail sync still reads only the two model
# fields, while the Issue detail view may use this small allow-list to build
# external RA links without copying the whole Trail row into the dashboard.
TRAIL_DETAIL_FIELDS = (
    "ra_id",
    "ra_event",
    "car_id",
    "trip_id",
    "ra_start_timestamp",
    "ra_end_timestamp",
)
_detail_cache: dict[tuple[str, int, str], tuple[float, dict[str, Any]]] = {}
_detail_cache_lock = threading.Lock()


@dataclass(frozen=True)
class TrailSyncResult:
    rows: list[dict[str, Any]]
    queried_issues: int
    returned_issues: int
    fields_visible: tuple[str, ...]
    view_id: int
    complete: bool
    message: str


@dataclass(frozen=True)
class TrailCommentMarkerResult:
    """Minimal result of a read-only Comment marker lookup.

    The dashboard never returns Trail Comment bodies to the browser.  It only
    needs to know whether the deterministic operation marker already exists so
    retrying the same write cannot append a duplicate Comment.
    """

    matched_issue_ids: frozenset[str]
    queried_issues: int
    returned_issues: int
    fields_visible: tuple[str, ...]
    complete: bool
    message: str


def _safe_detail_value(field: str, value: Any) -> Any:
    """Return a small JSON-safe subset of Trail detail metadata."""

    if value is None:
        return None
    if isinstance(value, float) and value != value:  # pandas NaN
        return None
    if field == "ra_event":
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
        elif hasattr(value, "tolist"):
            try:
                value = value.tolist()
            except (TypeError, ValueError):
                return []
        if not isinstance(value, (list, tuple)):
            return []
        events: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            event = str(item.get("event") or "").strip()[:128]
            if not event:
                continue
            raw_timestamp = item.get("timestamp")
            try:
                timestamp = int(raw_timestamp) if raw_timestamp is not None else None
            except (TypeError, ValueError, OverflowError):
                timestamp = None
            raw_value = item.get("value")
            if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
                safe_value = raw_value
            else:
                safe_value = str(raw_value)[:256]
            events.append(
                {"event": event, "value": safe_value, "timestamp": timestamp}
            )
        return events[:64]
    if field in {"ra_start_timestamp", "ra_end_timestamp"}:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    return str(value).strip()[:256]


def ares_playback_metadata(
    metadata: dict[str, Any], events: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    """Return the minimal identifiers needed for read-only Ares playback.

    Older Trail rows may omit ``ra_start_timestamp`` while still exposing the
    canonical ``start`` event.  Keep this compatibility logic independent of
    FastAPI so it is reusable and covered by the lightweight Trail tests.
    """

    trip_id = str(metadata.get("trip_id") or "").strip()[:256]
    raw_timestamp = metadata.get("ra_start_timestamp")
    if raw_timestamp in (None, ""):
        raw_timestamp = next(
            (
                item.get("timestamp")
                for item in events
                if isinstance(item, dict)
                and item.get("event") == "start"
                and item.get("timestamp") is not None
            ),
            None,
        )
    try:
        timestamp_ms = int(raw_timestamp) if raw_timestamp is not None else None
    except (TypeError, ValueError, OverflowError):
        timestamp_ms = None
    return {"ares_trip_id": trip_id, "ares_timestamp_ms": timestamp_ms}


def read_trail_issue_metadata(
    *,
    ra_root: Path,
    issue_id: str,
    view_id: int,
    cache_seconds: int = 300,
) -> dict[str, Any]:
    """Read the minimal Trail metadata needed for external detail links.

    This is a read-only, single-Issue lookup.  It is intentionally not used
    when creating model Runs, and never returns unrelated Trail columns.
    Failure is represented by an empty mapping so an unavailable Trail service
    cannot make the Issue detail page fail.
    """

    normalized_issue_id = str(issue_id).strip()
    if not normalized_issue_id:
        return {}
    cache_key = (str(ra_root.resolve()), int(view_id), normalized_issue_id)
    now = time.monotonic()
    ttl = max(0, int(cache_seconds))
    with _detail_cache_lock:
        cached = _detail_cache.get(cache_key)
        if ttl > 0 and cached and now - cached[0] < ttl:
            return dict(cached[1])

    root = str(ra_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        importlib.invalidate_caches()
        from utils.get_ra_issue_utils import get_self_issue  # type: ignore[import-not-found]

        frame = get_self_issue(
            [{"attr_id": "issue_id", "val": [normalized_issue_id], "operator": "like"}],
            view_id=view_id,
            size=1,
        )
    except Exception:
        return {}
    if frame is None or len(frame) == 0:
        return {}

    lower_columns = {str(column).lower(): str(column) for column in frame.columns}
    issue_column = lower_columns.get("issue_id")
    if not issue_column:
        return {}
    row = next(
        (
            item
            for item in frame.to_dict(orient="records")
            if str(item.get(issue_column) or "").strip() == normalized_issue_id
        ),
        None,
    )
    if row is None:
        return {}
    metadata: dict[str, Any] = {"issue_id": normalized_issue_id}
    for field in TRAIL_DETAIL_FIELDS:
        column = lower_columns.get(field.lower())
        if not column:
            continue
        safe_value = _safe_detail_value(field, row.get(column))
        if safe_value not in (None, "", []):
            metadata[field] = safe_value
    if len(metadata) == 1:
        return {}
    if ttl > 0:
        with _detail_cache_lock:
            _detail_cache[cache_key] = (time.monotonic(), dict(metadata))
    return metadata


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def read_trail_model_fields(
    *,
    ra_root: Path,
    issue_ids: Iterable[str],
    view_id: int,
    chunk_size: int,
) -> TrailSyncResult:
    """Read only the two Trail fields selected for dashboard comparison.

    Trail returns columns configured in the supplied view.  We intentionally do
    not fall back to a write API or fabricate an empty model run: if the view
    does not expose Zhang Yang's fields, the caller gets an actionable message
    and can use the import contract instead.
    """

    ids = sorted({str(issue_id).strip() for issue_id in issue_ids if str(issue_id).strip()})
    if not ids:
        return TrailSyncResult(
            rows=[],
            queried_issues=0,
            returned_issues=0,
            fields_visible=(),
            view_id=view_id,
            complete=True,
            message="当前 baseline 没有可同步的 issue。",
        )
    root = str(ra_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        importlib.invalidate_caches()
        from utils.get_ra_issue_utils import get_self_issue  # type: ignore[import-not-found]
    except Exception as exc:
        return TrailSyncResult(
            rows=[],
            queried_issues=len(ids),
            returned_issues=0,
            fields_visible=(),
            view_id=view_id,
            complete=False,
            message=f"无法加载 ra_auto_triage 的 Trail 只读客户端: {exc}",
        )

    output: dict[str, dict[str, Any]] = {}
    visible: set[str] = set()
    for chunk in _chunks(ids, max(1, chunk_size)):
        condition = [{"attr_id": "issue_id", "val": chunk, "operator": "like"}]
        try:
            frame = get_self_issue(condition, view_id=view_id, size=max(len(chunk), 200))
        except Exception as exc:
            return TrailSyncResult(
                rows=list(output.values()),
                queried_issues=len(ids),
                returned_issues=len(output),
                fields_visible=tuple(sorted(visible)),
                view_id=view_id,
                complete=False,
                message=f"Trail 查询失败（view {view_id}）；为避免部分快照，本次不会创建 Run: {exc}",
            )
        if frame is None or len(frame) == 0:
            continue
        lower_columns = {str(column).lower(): str(column) for column in frame.columns}
        result_column = lower_columns.get(TRAIL_RESULT_FIELD)
        info_column = lower_columns.get(TRAIL_INFO_FIELD)
        if result_column:
            visible.add(TRAIL_RESULT_FIELD)
        if info_column:
            visible.add(TRAIL_INFO_FIELD)
        issue_column = lower_columns.get("issue_id")
        if not issue_column:
            continue
        for raw in frame.to_dict(orient="records"):
            issue_id = str(raw.get(issue_column) or "").strip()
            if issue_id not in ids:
                continue
            row = {"issue_id": issue_id}
            if result_column:
                row[TRAIL_RESULT_FIELD] = raw.get(result_column)
            if info_column:
                row[TRAIL_INFO_FIELD] = raw.get(info_column)
            # Keep the exact source fields for troubleshooting, but never log
            # the complete Trail row (it may contain unrelated PII fields).
            output[issue_id] = row

    fields = tuple(sorted(visible))
    if TRAIL_RESULT_FIELD not in visible:
        message = (
            f"Trail view {view_id} 未返回 {TRAIL_RESULT_FIELD}；请把 "
            f"{TRAIL_RESULT_FIELD} 和 {TRAIL_INFO_FIELD} 加入该 view，或上传 CSV/JSON/XLSX。"
        )
    else:
        message = (
            f"Trail view {view_id} 已读取 {len(output)} 条，"
            f"可见字段: {', '.join(fields)}。"
        )
    return TrailSyncResult(
        rows=list(output.values()),
        queried_issues=len(ids),
        returned_issues=len(output),
        fields_visible=fields,
        view_id=view_id,
        complete=True,
        message=message,
    )


def _comment_texts(value: Any) -> list[str]:
    """Flatten the common Trail ``more_comment`` encodings for marker checks."""

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [text]
        # JSON-encoded comments are common in dataframe exports.  If the
        # value is a JSON scalar, keeping its textual form is sufficient.
        if parsed == value:
            return [text]
        return _comment_texts(parsed)
    if isinstance(value, dict):
        output: list[str] = []
        # Trail has used several names for the visible body over time.  Only
        # inspect those fields; do not stringify the whole row or leak IDs.
        for key in ("content", "comment", "text", "body", "message"):
            if key in value:
                output.extend(_comment_texts(value.get(key)))
        if output:
            return output
        return []
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_comment_texts(item))
        return output
    return [str(value).strip()] if str(value).strip() else []


def read_trail_comment_markers(
    *,
    ra_root: Path,
    issue_ids: Iterable[str],
    view_id: int,
    chunk_size: int,
    marker: str,
) -> TrailCommentMarkerResult:
    """Read only enough Trail Comment data to make retries idempotent.

    This is deliberately separate from :func:`read_trail_model_fields` so
    normal previews do not fetch Comment bodies.  A commit carrying a Comment
    must call this helper first; if ``more_comment`` is not exposed by the
    configured view, the caller fails closed before changing any field.
    """

    ids = sorted({str(issue_id).strip() for issue_id in issue_ids if str(issue_id).strip()})
    if not ids:
        return TrailCommentMarkerResult(
            matched_issue_ids=frozenset(),
            queried_issues=0,
            returned_issues=0,
            fields_visible=(),
            complete=True,
            message="没有需要检查 Comment 的 Issue。",
        )
    root = str(ra_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        importlib.invalidate_caches()
        from utils.get_ra_issue_utils import get_self_issue  # type: ignore[import-not-found]
    except Exception as exc:
        return TrailCommentMarkerResult(
            matched_issue_ids=frozenset(),
            queried_issues=len(ids),
            returned_issues=0,
            fields_visible=(),
            complete=False,
            message=f"无法加载 Trail 只读客户端检查 Comment: {exc}",
        )

    matched: set[str] = set()
    visible: set[str] = set()
    returned = 0
    for chunk in _chunks(ids, max(1, chunk_size)):
        condition = [{"attr_id": "issue_id", "val": chunk, "operator": "like"}]
        try:
            frame = get_self_issue(condition, view_id=view_id, size=max(len(chunk), 200))
        except Exception as exc:
            return TrailCommentMarkerResult(
                matched_issue_ids=frozenset(matched),
                queried_issues=len(ids),
                returned_issues=returned,
                fields_visible=tuple(sorted(visible)),
                complete=False,
                message=f"Trail Comment 查询失败（view {view_id}）: {exc}",
            )
        if frame is None or len(frame) == 0:
            continue
        lower_columns = {str(column).lower(): str(column) for column in frame.columns}
        issue_column = lower_columns.get("issue_id")
        comment_column = lower_columns.get(TRAIL_COMMENT_FIELD)
        if comment_column:
            visible.add(TRAIL_COMMENT_FIELD)
        if not issue_column:
            continue
        for raw in frame.to_dict(orient="records"):
            issue_id = str(raw.get(issue_column) or "").strip()
            if issue_id not in ids:
                continue
            returned += 1
            if comment_column and any(marker in text for text in _comment_texts(raw.get(comment_column))):
                matched.add(issue_id)

    if TRAIL_COMMENT_FIELD not in visible:
        return TrailCommentMarkerResult(
            matched_issue_ids=frozenset(matched),
            queried_issues=len(ids),
            returned_issues=returned,
            fields_visible=tuple(sorted(visible)),
            complete=False,
            message=(
                f"Trail view {view_id} 未返回 {TRAIL_COMMENT_FIELD}；"
                "为避免重复 Comment，本次提交已停止。"
            ),
        )
    return TrailCommentMarkerResult(
        matched_issue_ids=frozenset(matched),
        queried_issues=len(ids),
        returned_issues=returned,
        fields_visible=tuple(sorted(visible)),
        complete=True,
        message=f"Trail view {view_id} 已完成 Comment 幂等检查。",
    )
