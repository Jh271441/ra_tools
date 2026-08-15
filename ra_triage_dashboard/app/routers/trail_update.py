"""Safe Trail attribute update drafts.

The dashboard deliberately stops at an immutable, auditable preview.  This
module does not call Trail write APIs.  It groups the latest Review rows for a
single immutable Model Run and emits a namespaced deep-merge patch that can be
reviewed or handed to a future, separately-gated writer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from fastapi import APIRouter, Request

from ..http_support import (
    _as_text,
    _detail,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
)
from ..runtime import database

router = APIRouter()

TRAIL_TARGET_FIELD = "ra_stuck_auto_result_info"
TRAIL_TARGET_PATH = "ra_triage_dashboard.should_exclude"
TRAIL_DRAFT_SCHEMA = "trail-attribute-update-draft-v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_trail_attribute_update_payload(
    rows: list[dict[str, Any]],
    *,
    run: dict[str, Any],
    baseline_ids: list[str],
    baseline_scopes: list[str],
) -> dict[str, Any]:
    """Build a deterministic, write-disabled Trail patch draft.

    The selected Run is carried into every patch so a future writer cannot
    accidentally apply a review from another Run.  The namespace is unique to
    this dashboard and the patch strategy is explicitly deep-merge.
    """

    run_id = _as_text(run.get("id"))
    items: list[dict[str, Any]] = []
    for row in rows:
        annotation = row.get("annotation") or {}
        prediction = row.get("prediction") or {}
        issue_id = _as_text(row.get("issue_id"))
        if not issue_id or not bool(annotation.get("is_excluded")):
            continue
        review_id = annotation.get("id")
        patch = {
            "ra_triage_dashboard": {
                "schema_version": 1,
                "should_exclude": True,
                "model_run_id": run_id,
                "review_id": review_id,
                "reviewer": _as_text(annotation.get("author")),
                "reviewed_at": _as_text(annotation.get("created_at")),
            }
        }
        items.append(
            {
                "issue_id": issue_id,
                "title": _as_text(row.get("title")),
                "scenario": _as_text(row.get("scenario")),
                "gt_label": _as_text(row.get("gt_label")),
                "model": {
                    "run_id": _as_text(prediction.get("model_run_id") or run_id),
                    "label": _as_text(prediction.get("label")),
                    "reason": _as_text(prediction.get("reason")),
                    "confidence": prediction.get("confidence"),
                },
                "review": {
                    "id": review_id,
                    "model_run_id": _as_text(annotation.get("model_run_id") or run_id),
                    "status": _as_text(annotation.get("review_status")),
                    "reviewer": _as_text(annotation.get("author")),
                    "reviewed_at": _as_text(annotation.get("created_at")),
                    "note": _as_text(annotation.get("note")),
                    "tags": list(annotation.get("tags") or []),
                    "missing_evidence": list(annotation.get("missing_evidence") or []),
                    "is_excluded": True,
                },
                "target": {
                    "field": TRAIL_TARGET_FIELD,
                    "path": TRAIL_TARGET_PATH,
                    "merge_strategy": "deep_merge",
                    "patch": patch,
                },
            }
        )
    items.sort(key=lambda item: item["issue_id"])
    draft: dict[str, Any] = {
        "schema_version": TRAIL_DRAFT_SCHEMA,
        "mode": "preview",
        "trail_write_enabled": False,
        "target_field": TRAIL_TARGET_FIELD,
        "target_path": TRAIL_TARGET_PATH,
        "merge_strategy": "deep_merge",
        "model_run_id": run_id,
        "model_run_name": _as_text(run.get("name")),
        "baseline_ids": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "items": items,
    }
    digest = hashlib.sha256(_canonical_json(draft).encode("utf-8")).hexdigest()
    draft["payload_sha256"] = digest
    return {
        "schema_version": TRAIL_DRAFT_SCHEMA,
        "mode": "preview",
        "trail_write_enabled": False,
        "write_status": "draft_only",
        "target_field": TRAIL_TARGET_FIELD,
        "target_path": TRAIL_TARGET_PATH,
        "merge_strategy": "deep_merge",
        "selected_run": {
            "id": run_id,
            "name": _as_text(run.get("name")),
            "source_name": _as_text(run.get("source_name")),
            "created_at": _as_text(run.get("created_at")),
        },
        "baselines": list(baseline_ids),
        "baseline_scopes": list(baseline_scopes),
        "count": len(items),
        "payload_sha256": digest,
        "items": items,
        "draft": draft,
    }


@router.get("/api/trail-attribute-update/preview")
async def trail_attribute_update_preview(
    request: Request,
    model_run_id: str = "",
    baselines: str = "",
) -> dict[str, Any]:
    """Return should-exclude rows for exactly one Run as a draft payload."""

    selected_run_id = _as_text(model_run_id)
    if not selected_run_id:
        raise _detail(400, "请选择一个模型 Run 后再生成 Trail 属性更新草稿。")
    baseline_ids = resolve_request_baseline_ids(baselines, request=request)
    baseline_scopes = resolve_request_baseline_scopes(baselines, request=request)
    run = await asyncio.to_thread(database.get_model_run, selected_run_id)
    if run is None:
        raise _detail(404, "模型 Run 不存在，无法生成 Trail 属性更新草稿。")
    rows = await asyncio.to_thread(
        database.review_reason_rows,
        baseline_scopes=baseline_scopes,
        model_run_id=selected_run_id,
        comparison_status="all",
        is_excluded=True,
    )
    return await asyncio.to_thread(
        build_trail_attribute_update_payload,
        rows,
        run=run,
        baseline_ids=baseline_ids,
        baseline_scopes=baseline_scopes,
    )
