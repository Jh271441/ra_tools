from __future__ import annotations

import importlib
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .baseline import normalize_gt_label


TRAIL_GT_FIELD = "ra_merge_result"
TRAIL_GT_UPDATED_AT_FIELD = "last_modify_time"
TRAIL_GT_UPDATED_BY_FIELD = "last_modificator"


@dataclass(frozen=True)
class TrailGtSyncResult:
    rows: list[dict[str, str]]
    queried_issues: int
    returned_issues: int
    fields_visible: tuple[str, ...]
    view_id: int
    complete: bool
    message: str


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _source_timestamp(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        if not text:
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    if not math.isfinite(number) or number <= 0:
        return ""
    seconds = number / 1000 if number > 10_000_000_000 else number
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (OverflowError, OSError, ValueError):
        return ""


def read_trail_gt_labels(
    *,
    ra_root: Path,
    issue_ids: Iterable[str],
    view_id: int,
    chunk_size: int,
) -> TrailGtSyncResult:
    """Read the fixed authoritative Trail GT field for an exact workset."""

    ids = sorted(
        {str(issue_id).strip() for issue_id in issue_ids if str(issue_id).strip()}
    )
    if not ids:
        return TrailGtSyncResult(
            rows=[],
            queried_issues=0,
            returned_issues=0,
            fields_visible=(),
            view_id=view_id,
            complete=False,
            message="当前 baseline 没有可同步的 issue。",
        )
    root = str(ra_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        importlib.invalidate_caches()
        from utils.get_ra_issue_utils import get_self_issue  # type: ignore[import-not-found]
    except Exception as exc:
        return TrailGtSyncResult(
            rows=[],
            queried_issues=len(ids),
            returned_issues=0,
            fields_visible=(),
            view_id=view_id,
            complete=False,
            message=f"无法加载 ra_auto_triage 的 Trail 只读客户端: {exc}",
        )

    requested = set(ids)
    output: dict[str, dict[str, str]] = {}
    visible: set[str] = set()
    for chunk in _chunks(ids, max(1, int(chunk_size))):
        condition = [{"attr_id": "issue_id", "val": chunk, "operator": "like"}]
        try:
            frame = get_self_issue(
                condition,
                view_id=int(view_id),
                size=max(200, len(chunk)),
            )
        except Exception as exc:
            return TrailGtSyncResult(
                rows=list(output.values()),
                queried_issues=len(ids),
                returned_issues=len(output),
                fields_visible=tuple(sorted(visible)),
                view_id=view_id,
                complete=False,
                message=f"Trail GT 查询失败（view {view_id}）: {exc}",
            )
        if frame is None or len(frame) == 0:
            continue
        lower_columns = {str(column).lower(): str(column) for column in frame.columns}
        issue_column = lower_columns.get("issue_id")
        label_column = lower_columns.get(TRAIL_GT_FIELD)
        updated_column = lower_columns.get(TRAIL_GT_UPDATED_AT_FIELD)
        modifier_column = lower_columns.get(TRAIL_GT_UPDATED_BY_FIELD)
        if label_column:
            visible.add(TRAIL_GT_FIELD)
        if updated_column:
            visible.add(TRAIL_GT_UPDATED_AT_FIELD)
        if modifier_column:
            visible.add(TRAIL_GT_UPDATED_BY_FIELD)
        if not issue_column or not label_column:
            continue
        for raw in frame.to_dict(orient="records"):
            issue_id = str(raw.get(issue_column) or "").strip()
            if issue_id not in requested:
                continue
            if issue_id in output:
                return TrailGtSyncResult(
                    rows=list(output.values()),
                    queried_issues=len(ids),
                    returned_issues=len(output),
                    fields_visible=tuple(sorted(visible)),
                    view_id=view_id,
                    complete=False,
                    message=f"Trail GT 查询返回重复 issue: {issue_id}",
                )
            label = normalize_gt_label(raw.get(label_column))
            if not label:
                return TrailGtSyncResult(
                    rows=list(output.values()),
                    queried_issues=len(ids),
                    returned_issues=len(output),
                    fields_visible=tuple(sorted(visible)),
                    view_id=view_id,
                    complete=False,
                    message=(
                        f"Trail GT 包含空值或非三分类标签: {issue_id}="
                        f"{raw.get(label_column)!r}"
                    ),
                )
            output[issue_id] = {
                "issue_id": issue_id,
                "gt_label": label,
                "source_updated_at": _source_timestamp(
                    raw.get(updated_column) if updated_column else None
                ),
                "source_updated_by": str(
                    raw.get(modifier_column) if modifier_column else ""
                ).strip(),
            }

    returned = len(output)
    complete = returned == len(ids) and TRAIL_GT_FIELD in visible
    message = (
        f"Trail view {view_id} 已完整读取 {returned}/{len(ids)} 条 {TRAIL_GT_FIELD}。"
        if complete
        else (
            f"Trail view {view_id} 仅返回 {returned}/{len(ids)} 条完整 GT；"
            "为避免部分快照，本次不会更新。"
        )
    )
    return TrailGtSyncResult(
        rows=[output[issue_id] for issue_id in sorted(output)],
        queried_issues=len(ids),
        returned_issues=returned,
        fields_visible=tuple(sorted(visible)),
        view_id=view_id,
        complete=complete,
        message=message,
    )
