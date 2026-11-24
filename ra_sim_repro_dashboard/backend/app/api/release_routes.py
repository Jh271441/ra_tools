from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    CollectionInventoryResponse,
    ScenarioLabelGroupsResponse,
    SimulationBoardResponse,
    WorkflowBatchReceiptResponse,
    WorkflowIssuesPageResponse,
    WorkflowPlanResponse,
    WorkflowResumeResponse,
    WorkflowStatusResponse,
    WorkflowSyncResponse,
)
from app.services import (
    release_inventory,
    release_label_groups,
    release_resume,
    release_workflow as workflow,
    simulation_board,
    workflow_orchestrator as orchestrator,
)
from app.services.read_views import read_view
from app.services.release_presentation import workflow_status

router = APIRouter(prefix="/api/dashboard/workflow")


class Mode(BaseModel):
    mode: str


class Attach(BaseModel):
    fingerprint: str
    job_id: int


class Submit(BaseModel):
    fingerprint: str


def guarded(fn, *args):
    try:
        return fn(*args)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("", response_model=WorkflowStatusResponse)
def status(db: Session = Depends(get_db)):
    return workflow_status(db)


@router.get("/issues", response_model=WorkflowIssuesPageResponse)
def issues(
    release: str = "@current",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    query: str = "",
    label: str = "",
    view: str = Query("collection", pattern="^(simulation|collection)$"),
    db: Session = Depends(get_db),
):
    return read_view(
        db,
        ("source-issues", release, page, page_size, query, label, view),
        lambda: guarded(orchestrator.list_issues, db, release, page, page_size, query, label, view),
        max_age=10,
    )


@router.get("/scenario-label-groups", response_model=ScenarioLabelGroupsResponse)
def scenario_label_groups(
    release: str = Query(pattern=r"^gen4-release-[0-9]{8}$"), db: Session = Depends(get_db)
):
    return read_view(
        db,
        ("scenario-label-groups", release),
        lambda: guarded(release_label_groups.for_release, db, release),
    )


@router.get("/versions", response_model=CollectionInventoryResponse)
def collection_versions(db: Session = Depends(get_db)):
    return read_view(
        db, "collection-inventory", lambda: release_inventory.inventory(db), max_age=10
    )


@router.get("/board", response_model=SimulationBoardResponse)
def board(
    tasks: BackgroundTasks,
    release: str = "@current",
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    scope_releases = [release] if release and not release.startswith("@") else None
    value = (
        guarded(simulation_board.board, db, release, True)
        if refresh
        else read_view(
            db,
            ("simulation-board", release),
            lambda: guarded(simulation_board.board, db, release, False),
            max_age=2,
            scope_releases=scope_releases,
        )
    )
    for job_id in value.pop("refresh_job_ids"):
        tasks.add_task(simulation_board.refresh_progress, job_id, refresh)
    return value


@router.post("/sync", status_code=202, response_model=WorkflowSyncResponse)
def sync(tasks: BackgroundTasks):
    tasks.add_task(orchestrator.tick)
    return {"status": "requested"}


@router.put("/mode", response_model=WorkflowStatusResponse)
def mode(payload: Mode, db: Session = Depends(get_db)):
    guarded(orchestrator.set_mode, db, payload.mode)
    return orchestrator.status(db)


@router.get("/plan", response_model=WorkflowPlanResponse)
def plan(db: Session = Depends(get_db)):
    return guarded(workflow.make_plan, db)


@router.post("/submit", status_code=202, response_model=WorkflowBatchReceiptResponse)
def submit(payload: Submit, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    batch = guarded(workflow.queue_plan, db, payload.fingerprint)
    tasks.add_task(orchestrator.process_queued)
    return {
        "fingerprint": batch.fingerprint,
        "status": batch.status,
        "job_id": batch.payload.get("job_id"),
    }


@router.post("/attach", status_code=202, response_model=WorkflowBatchReceiptResponse)
def attach(payload: Attach, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    batch = guarded(workflow.attach_job, db, payload.fingerprint, payload.job_id)
    tasks.add_task(orchestrator.process_queued)
    return {
        "fingerprint": batch.fingerprint,
        "status": batch.status,
        "job_id": batch.payload.get("job_id"),
    }


class Resume(BaseModel):
    release: str
    fingerprint: str | None = None


@router.post("/resume", status_code=202, response_model=WorkflowResumeResponse)
def resume(payload: Resume, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    value = guarded(release_resume.request, db, payload.release, payload.fingerprint)
    tasks.add_task(orchestrator.process_queued)
    return value
