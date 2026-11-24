import os
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.config import load_versions_config, config_hash
from app.database import get_db
from app.models import ReleaseIssueSnapshot, Version
from app.services import (
    metric_profiles as profiles,
    evaluation_pipeline as pipeline,
    scenario_label_sets,
)
from app.services.read_views import read_view

router = APIRouter(prefix="/api/dashboard/evaluation")


def guarded(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            409, str(exc) if isinstance(exc, ValueError) else "invalid_configuration"
        ) from exc


class Context(BaseModel):
    release: str = "@current"
    profile_id: str | None = None
    date_start: str | None = None
    date_end: str | None = None


class Refresh(Context):
    refresh_labels: bool = False


class Draft(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    config: dict
    parent: str | None = None


class Publish(BaseModel):
    preview_hash: str
    activate: bool | None = None


class Activate(BaseModel):
    expected_active: str
    contexts: list[Context] = Field(min_length=1, max_length=100)


class Cron(Context):
    enabled: bool


@router.get("/profiles")
def catalogue(db: Session = Depends(get_db)):
    return profiles.catalogue(db)


@router.get("/versions")
def versions(db: Session = Depends(get_db)):
    """Navigation metadata only; no ordinary KPI calculation or write-on-read."""

    def load():
        config = load_versions_config()
        releases = list(
            db.scalars(
                select(ReleaseIssueSnapshot.release)
                .group_by(ReleaseIssueSnapshot.release)
                .order_by(ReleaseIssueSnapshot.release)
            )
        )
        saved = {
            v.version_key: v
            for v in db.scalars(select(Version).where(Version.version_key.in_(releases)))
        }
        current = releases[-1] if releases else ""
        items = []
        for index, release in enumerate(releases):
            record = saved.get(release)
            configured = config.get("versions", {}).get(release, {})
            metadata = {
                str(k): v
                for k, v in {**configured, **(record.metadata_json if record else {})}.items()
                if not str(k).startswith("_")
            }
            metadata.setdefault("platform_gen", "GEN4_PT")
            if pipeline.at.RELEASE.fullmatch(release):
                metadata.setdefault(
                    "release_date", release[-8:-4] + "-" + release[-4:-2] + "-" + release[-2:]
                )
            items.append(
                {
                    "version_key": release,
                    "label": record.label if record else configured.get("label", release),
                    "sim_job_id": None,
                    "baseline_job_id": None,
                    "sort_order": index,
                    "is_current": release == current,
                    "metadata_json": metadata,
                    "last_refreshed_at": None,
                }
            )
        return {
            "current_version": current,
            "compare_versions": releases,
            "config_hash": config_hash(config),
            "versions": items,
        }

    return read_view(db, "evaluation-navigation-versions", load, max_age=30)


@router.post("/profiles/drafts", status_code=201)
def draft(body: Draft, db: Session = Depends(get_db)):
    return guarded(profiles.draft, db, **body.model_dump())


@router.post("/profiles/{version}/preview")
def preview(version: str, body: Context, db: Session = Depends(get_db)):
    return guarded(pipeline.preview, db, version, **body.model_dump())


@router.post("/profiles/{version}/publish")
def publish(version: str, body: Publish, db: Session = Depends(get_db)):
    return guarded(profiles.publish, db, version, body.preview_hash, activate=body.activate)


@router.post("/profiles/{version}/activate")
def activate(version: str, body: Activate, db: Session = Depends(get_db)):
    return guarded(
        profiles.activate,
        db,
        version,
        [ctx.model_dump() for ctx in body.contexts],
        body.expected_active,
    )


@router.get("/board")
def board(
    ctx: Context = Depends(),
    view: Literal["full", "metrics"] = "full",
    db: Session = Depends(get_db),
):
    # Metric pages/settings navigate the source catalogue; simulation pages keep
    # the full legacy publication metadata. Every revision audit is shared.
    def load():
        catalogue = pipeline.navigation_versions(db) if view == "metrics" else None
        return guarded(pipeline.board, db, **ctx.model_dump(), catalogue=catalogue)

    scope_releases = [ctx.release] if ctx.release and not ctx.release.startswith("@") else None
    return read_view(
        db,
        ("evaluation-board", view, *ctx.model_dump().values()),
        load,
        max_age=30,
        scope_releases=scope_releases,
    )


@router.get("/comparison")
def comparison(
    profile_id: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    db: Session = Depends(get_db),
):
    selected = guarded(profiles.get, db, profile_id)["id"]
    return read_view(
        db,
        ("evaluation-comparison", selected, date_start, date_end),
        lambda: guarded(pipeline.comparison, db, selected, date_start, date_end),
        max_age=30,
    )


@router.get("/issues")
def issues(
    ctx: Context = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    query: str = Query("", max_length=200),
    coverage: str = "",
    changed_only: bool = False,
    db: Session = Depends(get_db),
):
    return read_view(
        db,
        (
            "evaluation-issues",
            *ctx.model_dump().values(),
            page,
            page_size,
            query,
            coverage,
            changed_only,
        ),
        lambda: guarded(
            pipeline.issue_page,
            db,
            **ctx.model_dump(),
            page=page,
            page_size=page_size,
            query=query,
            coverage=coverage,
            changed_only=changed_only,
        ),
        max_age=30,
    )


@router.post("/runs", status_code=202)
def refresh(body: Refresh, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    value = guarded(pipeline.queue, db, **body.model_dump())
    if os.getenv("EVALUATION_WORKER_RUNNER", "api") == "api":
        tasks.add_task(pipeline.process, value["id"])
    return value


@router.post("/plans/{identifier}/start", status_code=202)
def start(identifier: str, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    value = guarded(pipeline.start, db, identifier)
    if os.getenv("EVALUATION_WORKER_RUNNER", "api") == "api":
        tasks.add_task(pipeline.tick, schedule=False)
    return value


@router.put("/cron")
def cron(body: Cron, db: Session = Depends(get_db)):
    return guarded(pipeline.set_cron, db, **body.model_dump())


@router.get("/scenario-labels")
def scenario_labels(
    issue_id: str = Query(min_length=1, max_length=100),
    ctx: Context = Depends(),
    db: Session = Depends(get_db),
):
    def read():
        canonical, _, _, key = pipeline.context(db, **ctx.model_dump())
        pointer = pipeline.w.get_state(db, key)
        current = (
            pipeline.current_revision(db, **canonical)
            if pipeline.w.get_state(db, scenario_label_sets.index_key(canonical))
            else None
        )
        label_plan_id = scenario_label_sets.build_plan(current)["id"] if current else None
        return scenario_label_sets.issue_labels(
            db, canonical, issue_id, pointer.get("revision_key"), label_plan_id
        )

    return guarded(read)


@router.get("/scenario-label-summary")
def scenario_label_summary(
    ctx: Context = Depends(),
    revision: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
):
    from app.services import evaluation_label_summary

    return guarded(evaluation_label_summary.read, db, ctx.model_dump(), revision)
