from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TRAIL_RESULT_FIELD = "ra_stuck_auto_result"
TRAIL_INFO_FIELD = "ra_stuck_auto_result_info"


@dataclass(frozen=True)
class TrailSyncResult:
    rows: list[dict[str, Any]]
    queried_issues: int
    returned_issues: int
    fields_visible: tuple[str, ...]
    view_id: int
    message: str


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
        return TrailSyncResult([], 0, 0, (), view_id, "当前 baseline 没有可同步的 issue。")
    root = str(ra_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        importlib.invalidate_caches()
        from utils.get_ra_issue_utils import get_self_issue  # type: ignore[import-not-found]
    except Exception as exc:
        return TrailSyncResult(
            [], len(ids), 0, (), view_id, f"无法加载 ra_auto_triage 的 Trail 只读客户端: {exc}"
        )

    output: dict[str, dict[str, Any]] = {}
    visible: set[str] = set()
    for chunk in _chunks(ids, max(1, chunk_size)):
        condition = [{"attr_id": "issue_id", "val": chunk, "operator": "like"}]
        try:
            frame = get_self_issue(condition, view_id=view_id, size=max(len(chunk), 200))
        except Exception as exc:
            return TrailSyncResult(
                list(output.values()),
                len(ids),
                len(output),
                tuple(sorted(visible)),
                view_id,
                f"Trail 查询失败（view {view_id}）: {exc}",
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
    return TrailSyncResult(list(output.values()), len(ids), len(output), fields, view_id, message)
