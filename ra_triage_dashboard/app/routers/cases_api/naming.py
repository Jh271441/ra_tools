"""Assignment name suggestion endpoint (rule-based + resilient LLM naming)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from ...core.dataset_label_config import (
    PARTITION_DISPLAY_LABELS,
    collapse_dataset_labels,
)
from ...core.deps import get_baseline_registry, get_db, get_settings, resolve_dep
from ...intent_name_suggestion import (
    IntentNameSuggestionError,
    rule_based_assignment_name,
    suggest_assignment_name_with_llm,
)
from ...model_catalog import ModelCatalogError
from ...runtime import baseline_registry, database, model_catalog, settings
from ...schemas import AssignmentNameSuggestionResponse
from ...support.common import _as_text, _detail
from ...support.identity import _admin_identity
from ...work_split import normalize_overlap_ratio

router = APIRouter()


@router.post(
    "/api/assignment-name-suggestion",
    responses={200: {"model": AssignmentNameSuggestionResponse}},
)
async def suggest_assignment_name(
    request: Request,
    db: Any = Depends(get_db),
    cfg: Any = Depends(get_settings),
    baselines_reg: Any = Depends(get_baseline_registry),
) -> dict[str, Any]:
    """Return a rule name immediately or a validated server-owned LLM name."""

    db = resolve_dep(db, lambda: database)
    cfg = resolve_dep(cfg, lambda: settings)
    baselines_reg = resolve_dep(baselines_reg, lambda: baseline_registry)
    await asyncio.to_thread(_admin_identity, request)
    raw = await request.body()
    if len(raw) > 8 * 1024:
        raise _detail(413, "实验名称推荐请求过大。")
    try:
        body = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise _detail(400, "实验名称推荐请求必须是 JSON。") from exc
    if not isinstance(body, dict):
        raise _detail(400, "实验名称推荐请求必须是 JSON 对象。")
    assignment_kind = _as_text(body.get("assignment_kind")).strip().lower()
    if assignment_kind not in {"case_labeling", "model_review"}:
        raise _detail(400, "实验名称推荐类型不合法。")
    raw_baseline_ids = body.get("baseline_ids")
    if not isinstance(raw_baseline_ids, list):
        raise _detail(400, "baseline_ids 必须是数组。")
    baseline_ids = list(
        dict.fromkeys(_as_text(value).strip() for value in raw_baseline_ids)
    )
    baseline_ids = [value for value in baseline_ids if value]
    if not baseline_ids or len(baseline_ids) > 8:
        raise _detail(400, "请为名称推荐选择 1 到 8 个数据集。")
    version_labels: dict[str, str] = {}
    if any(value.startswith("version-") for value in baseline_ids):
        for row in await asyncio.to_thread(db.list_version_datasets):
            fam = str(row.get("release_family") or "").strip()
            if fam:
                version_labels["version-" + fam] = str(
                    row.get("name") or (fam[4:] + " 复核集")
                )
    raw_labels_by_id: dict[str, str] = {}
    for value in baseline_ids:
        entry = baselines_reg.by_id(value)
        if entry is not None:
            raw_labels_by_id[value] = str(entry.label or entry.id)
        elif value in PARTITION_DISPLAY_LABELS:
            raw_labels_by_id[value] = PARTITION_DISPLAY_LABELS[value]
        elif value in version_labels:
            raw_labels_by_id[value] = version_labels[value]
        else:
            raise _detail(400, "名称推荐包含未知数据集。")
    dataset_labels = collapse_dataset_labels(baseline_ids, raw_labels_by_id)
    try:
        case_count = max(1, min(100_000, int(body.get("case_count") or 1)))
        reviewers_per_issue = max(
            1, min(100, int(body.get("reviewers_per_issue") or 1))
        )
        member_count = max(0, min(100, int(body.get("member_count") or 0)))
        overlap_ratio = normalize_overlap_ratio(
            body.get("overlap_ratio"),
            reviewers_per_issue=reviewers_per_issue,
        )
    except (TypeError, ValueError) as exc:
        raise _detail(400, "实验名称推荐参数不合法。") from exc
    workflow_mode = _as_text(body.get("workflow_mode")).strip()
    if workflow_mode not in {"", "model_review_only", "model_review_and_case_label"}:
        raise _detail(400, "实验名称推荐工作流不合法。")
    comparison = " ".join(_as_text(body.get("comparison") or "all").split())[:128]
    draft_name = " ".join(
        _as_text(body.get("draft_name")).replace("\u0000", "").split()
    )[:80]
    run_name = ""
    if assignment_kind == "model_review":
        run_id = _as_text(body.get("model_run_id")).strip()
        run = await asyncio.to_thread(db.get_model_run, run_id)
        if not run:
            raise _detail(404, "名称推荐对应的 Model Run 不存在。")
        run_name = _as_text(run.get("name") or run_id)
    fallback = rule_based_assignment_name(
        dataset_labels,
        assignment_kind=assignment_kind,
        case_count=case_count,
        reviewers_per_issue=reviewers_per_issue,
        overlap_ratio=overlap_ratio,
        member_count=member_count,
        workflow_mode=workflow_mode,
        run_name=run_name,
        comparison=comparison,
    )
    catalog_status = await asyncio.to_thread(model_catalog.status)
    if not catalog_status.get("configured"):
        return {"suggestion": fallback, "source": "rule", "reason": "not_configured"}
    llm_kwargs: dict[str, Any] = {
        "fallback": fallback,
        "dataset_labels": dataset_labels,
        "assignment_kind": assignment_kind,
        "case_count": case_count,
        "reviewers_per_issue": reviewers_per_issue,
        "overlap_ratio": overlap_ratio,
        "member_count": member_count,
        "workflow_mode": workflow_mode,
        "run_name": run_name,
        "comparison": comparison,
        "draft_name": draft_name,
    }
    if bool(body.get("force_refresh", False)):
        llm_kwargs["bypass_cache"] = True
    try:
        suggestion = await asyncio.to_thread(
            suggest_assignment_name_with_llm,
            cfg,
            model_catalog,
            **llm_kwargs,
        )
    except IntentNameSuggestionError as exc:
        return {"suggestion": fallback, "source": "rule", "reason": exc.reason}
    except ModelCatalogError:
        return {"suggestion": fallback, "source": "rule", "reason": "unavailable"}
    return {"suggestion": suggestion, "source": "llm"}
