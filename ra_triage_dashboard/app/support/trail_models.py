"""Trail Models HTTP helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..baseline_registry import ids_to_scopes
from ..db import LABELS
from ..import_parsing import normalize_model_row
from ..trail_sync import TRAIL_INFO_FIELD, TRAIL_RESULT_FIELD, read_trail_model_fields
from ..runtime import baseline_registry, database, runtime_state, settings, trail_sync_lock


def sync_trail_model_fields(
    *,
    create_run: bool = False,
    requested_by: str = "",
    identity_source: str = "anonymous",
    identity_verified: bool = False,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Inspect Trail fields and optionally create/reuse an immutable local snapshot.

    This function only calls the Trail query client.  Creating a snapshot writes
    local SQLite rows, but never writes Trail and never changes the shared
    default model run.
    """

    if not trail_sync_lock.acquire(blocking=False):
        return {
            **runtime_state["trail_sync"],
            "status": "running",
            "message": "已有 Trail 字段检查或快照任务在运行。",
        }
    action = "创建只读快照" if create_run else "检查字段"
    runtime_state["trail_sync"] = {
        "status": "running",
        "message": f"正在从 Trail view {settings.trail_view_id} 只读{action}。",
        "run_id": "",
        "can_create": False,
        "default_changed": False,
        "action": "create" if create_run else "preview",
    }
    try:
        issue_ids = database.baseline_issue_ids(
            baseline_scopes=ids_to_scopes(baseline_registry.default_ids(), baseline_registry)
            or [settings.baseline_scope]
        )
        result = read_trail_model_fields(
            ra_root=settings.ra_auto_triage_root,
            issue_ids=issue_ids,
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        state: dict[str, Any] = {
            "status": "unavailable",
            "message": result.message,
            "view_id": result.view_id,
            "queried_issues": result.queried_issues,
            "returned_issues": result.returned_issues,
            "fields_visible": list(result.fields_visible),
            "run_id": "",
            "complete": result.complete,
            "can_create": False,
            "default_changed": False,
            "action": "create" if create_run else "preview",
        }
        if not result.complete or result.returned_issues < result.queried_issues:
            state.update(
                {
                    "status": "failed",
                    "message": (
                        result.message
                        + (
                            f" 仅返回 {result.returned_issues} / {result.queried_issues} 个 baseline issue；"
                            if result.complete
                            else " "
                        )
                        + "为避免部分快照，未创建 Run，团队默认 Run 未变化。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        if TRAIL_RESULT_FIELD not in result.fields_visible:
            state["message"] = result.message + " 未创建 Run，团队默认 Run 未变化。"
            runtime_state["trail_sync"] = state
            return state
        normalized = [row for raw in result.rows if (row := normalize_model_row(raw))]
        # Trail snapshots participate in three-class evaluation, so only the
        # canonical labels are usable. Keep non-standard values out of the
        # snapshot rather than treating placeholders such as "nan" as labels.
        usable = [row for row in normalized if row["model_label"] in LABELS]
        if not usable:
            state.update(
                {
                    "status": "empty",
                    "message": (
                        result.message
                        + " 字段已出现，但当前 baseline 没有非空模型结果；未创建 Run。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        snapshot_rows = sorted(usable, key=lambda row: row["issue_id"])
        state.update(
            {
                "can_create": True,
                "usable_predictions": len(usable),
                "missing_predictions": max(result.queried_issues - len(usable), 0),
            }
        )
        if not create_run:
            state.update(
                {
                    "status": "preview_ready",
                    "message": (
                        result.message
                        + f" 检查完成：{len(usable)} / {result.queried_issues} 条可生成快照。"
                        + " 尚未创建 Run，团队默认 Run 未变化。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        payload = {
            "scope": settings.baseline_scope,
            "view_id": settings.trail_view_id,
            "fields": [TRAIL_RESULT_FIELD, TRAIL_INFO_FIELD],
            "rows": snapshot_rows,
        }
        source_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        run, duplicate = database.import_model_run(
            name=f"Trail view {settings.trail_view_id} · {TRAIL_RESULT_FIELD}",
            source_name=f"Trail view {settings.trail_view_id}",
            source_sha256=source_hash,
            metadata={
                "schema_version": "trail-fields-v1",
                "origin": "trail_readonly_snapshot",
                "baseline_scope": settings.baseline_scope,
                "view_id": settings.trail_view_id,
                "fields_visible": list(result.fields_visible),
                "queried_issues": result.queried_issues,
                "returned_issues": result.returned_issues,
                "usable_predictions": len(usable),
                "trigger": trigger,
            },
            rows=snapshot_rows,
            kind="trail_snapshot",
            make_default=False,
            created_by=requested_by,
            created_by_source=identity_source,
            created_by_verified=identity_verified,
        )
        state.update(
            {
                "status": "ready",
                "run_id": run["id"],
                "usable_predictions": len(usable),
                "duplicate": duplicate,
                "message": (
                    result.message
                    + (
                        f" 内容未变化，已复用现有只读快照（{len(usable)} 条）。"
                        if duplicate
                        else f" 已创建只读快照（{len(usable)} 条）。"
                    )
                    + " Trail、GT、人工复核和团队默认 Run 均未修改。"
                ),
            }
        )
        runtime_state["trail_sync"] = state
        return state
    except Exception as exc:
        state = {
            "status": "failed",
            "message": f"Trail 只读{action}失败: {exc}；未创建 Run，团队默认 Run 未变化。",
            "run_id": "",
            "can_create": False,
            "default_changed": False,
            "action": "create" if create_run else "preview",
        }
        runtime_state["trail_sync"] = state
        return state
    finally:
        trail_sync_lock.release()
