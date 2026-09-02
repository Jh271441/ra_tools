from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import config_hash, load_versions_config, settings
from app.database import get_db
from app.metrics import summarize_rows
from app.models import Issue, RefreshJob, Scenario, ScenarioVersionResult, Version
from app.schemas import (
    IssueDetailResponse,
    IssueListItem,
    PaginatedIssuesResponse,
    RefreshJobOut,
    RefreshRequest,
    ScenarioDetailResponse,
    SummaryResponse,
    SystemStatusResponse,
    VersionComparisonItem,
    VersionOut,
    VersionsResponse,
)
from app.services.refresh import build_snapshot, create_refresh_job, refresh_dashboard, sync_versions_from_config
from app.services.system_status import collect_system_status


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


DbSession = Annotated[Session, Depends(get_db)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/status", response_model=SystemStatusResponse)
def system_status(db: DbSession) -> SystemStatusResponse:
    return SystemStatusResponse(**collect_system_status(db))


@router.get("/dashboard/versions", response_model=VersionsResponse)
def versions(db: DbSession) -> VersionsResponse:
    payload = load_versions_config()
    sync_versions_from_config(db, payload)
    configured_keys = _configured_version_keys(payload)
    stmt = select(Version)
    if configured_keys:
        stmt = stmt.where(Version.version_key.in_(configured_keys))
    rows = db.execute(stmt.order_by(Version.sort_order)).scalars().all()
    return VersionsResponse(
        current_version=str(payload.get("current_version") or ""),
        compare_versions=[str(item) for item in payload.get("compare_versions", [])],
        config_hash=config_hash(payload),
        versions=[
            VersionOut.model_validate(row).model_copy(
                update={"metadata_json": _public_version_metadata(row.metadata_json)}
            )
            for row in rows
        ],
    )


@router.get("/dashboard/summary", response_model=SummaryResponse)
def summary(db: DbSession) -> SummaryResponse:
    snapshot = build_snapshot(db)
    current = snapshot.get("current")
    if not current:
        raise HTTPException(status_code=404, detail="No dashboard data. Run refresh first.")
    return SummaryResponse(
        current=current,
        previous=snapshot.get("previous"),
        deltas=snapshot.get("deltas", {}),
        generated_at=datetime.fromisoformat(snapshot["generated_at"]),
    )


@router.get("/dashboard/version-comparison", response_model=list[VersionComparisonItem])
def version_comparison(db: DbSession) -> list[VersionComparisonItem]:
    snapshot = build_snapshot(db)
    return [VersionComparisonItem(**item) for item in snapshot.get("comparison", [])]


@router.get("/dashboard/issues", response_model=PaginatedIssuesResponse)
def issues(
    db: DbSession,
    version: str | None = None,
    root_cause: str | None = None,
    trigger_type: str | None = None,
    precision_label: str | None = None,
    reproduced: bool | None = None,
    issue_id: str | None = None,
    scenario_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> PaginatedIssuesResponse:
    configured_keys = _configured_version_keys()
    stmt = (
        select(ScenarioVersionResult, Scenario, Issue)
        .join(Scenario, Scenario.scenario_id == ScenarioVersionResult.scenario_id)
        .outerjoin(Issue, Issue.issue_id == ScenarioVersionResult.issue_id)
    )
    count_stmt = select(func.count()).select_from(ScenarioVersionResult)

    conditions = []
    if configured_keys:
        conditions.append(ScenarioVersionResult.version_key.in_(configured_keys))
    if version:
        conditions.append(ScenarioVersionResult.version_key == version)
    if root_cause:
        conditions.append(ScenarioVersionResult.root_cause == root_cause)
    if trigger_type:
        conditions.append(ScenarioVersionResult.trigger_type == trigger_type)
    if precision_label:
        conditions.append(ScenarioVersionResult.precision_label == precision_label)
    if reproduced is not None:
        conditions.append(ScenarioVersionResult.reproduced == reproduced)
    if issue_id:
        conditions.append(ScenarioVersionResult.issue_id == issue_id)
    if scenario_id:
        conditions.append(ScenarioVersionResult.scenario_id == scenario_id)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(
        stmt.order_by(ScenarioVersionResult.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = []
    for result, scenario, issue in rows:
        items.append(
            IssueListItem(
                issue_id=result.issue_id,
                scenario_id=result.scenario_id,
                scenario_name=scenario.scenario_name,
                version_key=result.version_key,
                issue_topic=issue.issue_topic if issue else "",
                status=issue.status if issue else "",
                priority=issue.priority if issue else "",
                poi=issue.poi if issue else "",
                road_triggered=result.road_triggered,
                sim_triggered=result.sim_triggered,
                reproduced=result.reproduced,
                precision_label=result.precision_label,
                trigger_type=result.trigger_type,
                root_cause=result.root_cause,
                model_score_max=result.model_score_max,
                threshold=result.threshold,
                unstuck_status=result.unstuck_status,
                fp_reasons=result.fp_reasons,
                fn_reasons=result.fn_reasons,
            )
        )
    return PaginatedIssuesResponse(page=page, page_size=page_size, total=total, items=items)


@router.get("/dashboard/issues/{issue_id}", response_model=IssueDetailResponse)
def issue_detail(issue_id: str, db: DbSession) -> IssueDetailResponse:
    configured_keys = _configured_version_keys()
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    scenarios = db.execute(select(Scenario).where(Scenario.issue_id == issue_id)).scalars().all()
    payload = []
    for scenario in scenarios:
        results_stmt = select(ScenarioVersionResult).where(
            ScenarioVersionResult.scenario_id == scenario.scenario_id
        )
        if configured_keys:
            results_stmt = results_stmt.where(ScenarioVersionResult.version_key.in_(configured_keys))
        results = db.execute(results_stmt.order_by(ScenarioVersionResult.version_key)).scalars().all()
        payload.append(
            {
                "scenario": {
                    "scenario_id": scenario.scenario_id,
                    "scenario_name": scenario.scenario_name,
                    "signature": scenario.signature,
                },
                "results": [_result_dict(row) for row in results],
            }
        )
    return IssueDetailResponse(
        issue_id=issue_id,
        issue={
            "issue_id": issue.issue_id,
            "issue_topic": issue.issue_topic,
            "status": issue.status,
            "priority": issue.priority,
            "poi": issue.poi,
            "issue_time": issue.issue_time,
            "url": issue.url,
            "raw_issue": issue.raw_issue,
        },
        scenarios=payload,
    )


@router.get("/dashboard/scenarios/{scenario_id}", response_model=ScenarioDetailResponse)
def scenario_detail(scenario_id: str, db: DbSession) -> ScenarioDetailResponse:
    configured_keys = _configured_version_keys()
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    results_stmt = select(ScenarioVersionResult).where(ScenarioVersionResult.scenario_id == scenario_id)
    if configured_keys:
        results_stmt = results_stmt.where(ScenarioVersionResult.version_key.in_(configured_keys))
    results = db.execute(results_stmt.order_by(ScenarioVersionResult.version_key)).scalars().all()
    return ScenarioDetailResponse(
        scenario_id=scenario_id,
        scenario={
            "scenario_id": scenario.scenario_id,
            "scenario_name": scenario.scenario_name,
            "issue_id": scenario.issue_id,
            "signature": scenario.signature,
            "raw_info": scenario.raw_info,
        },
        results=results,
    )


@router.post("/dashboard/refresh", response_model=RefreshJobOut, status_code=202)
def refresh(
    payload: RefreshRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
) -> RefreshJobOut:
    _ = payload.force
    job = create_refresh_job(db)
    if settings.enable_rq:
        try:
            import redis
            from rq import Queue

            queue = Queue("ra_dashboard_refresh", connection=redis.from_url(settings.redis_url))
            queue.enqueue("app.worker.run_refresh_job", job.job_id, job_timeout=1800)
        except Exception as exc:
            logger.warning("Failed to enqueue refresh job in RQ; using FastAPI background task.", exc_info=True)
            job.message = f"RQ enqueue failed; using local background task: {exc}"
            db.add(job)
            db.commit()
            background_tasks.add_task(refresh_dashboard, job.job_id)
    else:
        background_tasks.add_task(refresh_dashboard, job.job_id)
    return RefreshJobOut.model_validate(job)


@router.get("/dashboard/refresh/{job_id}", response_model=RefreshJobOut)
def refresh_status(job_id: str, db: DbSession) -> RefreshJobOut:
    job = db.get(RefreshJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Refresh job not found")
    return RefreshJobOut.model_validate(job)


@router.get("/dashboard/root-causes")
def root_causes(db: DbSession) -> dict[str, int]:
    configured_keys = _configured_version_keys()
    stmt = select(ScenarioVersionResult)
    if configured_keys:
        stmt = stmt.where(ScenarioVersionResult.version_key.in_(configured_keys))
    rows = db.execute(stmt).scalars().all()
    return summarize_rows(rows)["root_causes"]


def _result_dict(row: ScenarioVersionResult) -> dict[str, object]:
    return {
        "version_key": row.version_key,
        "scenario_id": row.scenario_id,
        "issue_id": row.issue_id,
        "road_triggered": row.road_triggered,
        "sim_triggered": row.sim_triggered,
        "reproduced": row.reproduced,
        "precision_label": row.precision_label,
        "trigger_type": row.trigger_type,
        "root_cause": row.root_cause,
        "model_score_max": row.model_score_max,
        "threshold": row.threshold,
        "unstuck_status": row.unstuck_status,
        "fp_reasons": row.fp_reasons,
        "fn_reasons": row.fn_reasons,
        "raw_metrics": row.raw_metrics,
    }


def _configured_version_keys(payload: dict[str, object] | None = None) -> list[str]:
    data = payload or load_versions_config()
    current = str(data.get("current_version") or "")
    keys = [str(key) for key in data.get("compare_versions", []) if key]
    if current:
        keys.append(current)
    return list(dict.fromkeys(keys))


def _public_version_metadata(metadata: dict[str, object] | None) -> dict[str, object]:
    """Hide refresh-runtime blobs from the lightweight versions endpoint."""
    return {
        str(key): value
        for key, value in (metadata or {}).items()
        if not str(key).startswith("_")
    }
