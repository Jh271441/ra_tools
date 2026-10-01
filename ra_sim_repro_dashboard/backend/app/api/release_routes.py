from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.services import release_workflow as workflow
from app.services import simulation_board

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


@router.get("")
def status(db: Session = Depends(get_db)):
    return workflow.status(db)


@router.get("/issues")
def issues(
    release: str = "@current",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    query: str = "",
    label: str = "",
    db: Session = Depends(get_db),
):
    return guarded(workflow.list_issues, db, release, page, page_size, query, label)


@router.get("/board")
def board(
    tasks: BackgroundTasks,
    release: str = "@current",
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    value = guarded(simulation_board.board, db, release, refresh)
    for job_id in value.pop("refresh_job_ids"):
        tasks.add_task(simulation_board.refresh_progress, job_id, refresh)
    return value


@router.post("/sync", status_code=202)
def sync(tasks: BackgroundTasks):
    tasks.add_task(workflow.tick)
    return {"status": "requested"}


@router.put("/mode")
def mode(payload: Mode, db: Session = Depends(get_db)):
    guarded(workflow.set_mode, db, payload.mode)
    return workflow.status(db)


@router.get("/plan")
def plan(db: Session = Depends(get_db)):
    return guarded(workflow.make_plan, db)


@router.post("/submit", status_code=202)
def submit(payload: Submit, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    batch = guarded(workflow.queue_plan, db, payload.fingerprint)
    tasks.add_task(workflow.process_queued)
    return {
        "fingerprint": batch.fingerprint,
        "status": batch.status,
        "job_id": batch.payload.get("job_id"),
    }


@router.post("/attach", status_code=202)
def attach(payload: Attach, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    batch = guarded(workflow.attach_job, db, payload.fingerprint, payload.job_id)
    tasks.add_task(workflow.process_queued)
    return {
        "fingerprint": batch.fingerprint,
        "status": batch.status,
        "job_id": batch.payload.get("job_id"),
    }
