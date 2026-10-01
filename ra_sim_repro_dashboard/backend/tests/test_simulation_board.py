from contextlib import contextmanager
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import DashboardSnapshot, ReleaseSimulationBatch
from app.config import config_hash
from app.services import simulation_board as board, release_workflow as workflow


@pytest.fixture
def setup(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    archive = {
        "versions": {"old": {"sim_job_id": 42, "binary_id": 99}},
        "compare_versions": ["old"],
    }
    config = {
        "periods": [
            {"release": "new", "status": "completed", "binary_id": 100},
            {"release": "next", "status": "running"},
        ]
    }
    current = {
        "current_version": "new",
        "mode": "manual",
        "driver_ready": True,
        "scheduler_enabled": True,
        "status": "ready",
        "issue_count": 20,
        "scenario_count": 25,
        "source_metrics": {"eligible": 23},
        "metrics": {"available": False},
        "population_complete": True,
        "last_sync": {},
        "synced_at": None,
    }
    monkeypatch.setattr(board, "load_versions_config", lambda: archive)
    monkeypatch.setattr(workflow, "effective_config", lambda _: config)
    monkeypatch.setattr(workflow, "status", lambda *_: current)
    monkeypatch.setenv("RELEASE_WORKFLOW_LOCK", str(tmp_path / "workflow.lock"))
    db.add(
        ReleaseSimulationBatch(
            fingerprint="new-plan",
            release="new",
            status="running",
            payload={"job_id": 50, "scenarios": [{}] * 23},
        )
    )
    db.add(
        DashboardSnapshot(
            config_hash=config_hash(archive),
            current_version="old",
            snapshot={
                "comparison": [
                    {
                        "version_key": "old",
                        "total_cases": 12,
                        "evaluated_cases": 11,
                        "quality_gate_passed": True,
                        "precision": 0.8,
                        "recall": 0.7,
                        "sim_repro_rate": 0.9,
                        "source_gt": {"online_precision": 0.82, "online_recall": 0.75},
                    }
                ]
            },
        )
    )
    db.commit()

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(board, "SessionLocal", session)
    yield db
    db.close()


def test_versions_show_only_their_jobs_and_metrics(setup):
    db = setup
    current = board.board(db)
    assert current["selected"]["release"] == "new" and current["refresh_job_ids"] == [
        50
    ]
    assert not current["selected"]["metrics"]["available"]
    old = board.board(db, "old")
    assert old["selected"]["metrics"]["precision"] == 0.8 and old[
        "refresh_job_ids"
    ] == [42]
    assert (
        old["selected"]["jobs"][0]["job_id"] == 42 and not old["selected"]["is_current"]
    )
    pending = board.board(db, "next")
    assert (
        not pending["selected"]["jobs"]
        and not pending["selected"]["metrics"]["available"]
    )
    with pytest.raises(ValueError):
        board.board(db, "unknown")


def test_progress_failure_preserves_counts_and_never_submits(setup, monkeypatch):
    db = setup
    calls = []
    value = {
        "job_id": 50,
        "state": "RUNNING",
        "total": 23,
        "completed": 3,
        "running": 1,
        "queued": 19,
        "failed": 0,
        "cancelled": 0,
        "unknown": 0,
    }

    def driver(config, action, payload):
        calls.append((action, payload))
        return value

    monkeypatch.setattr(workflow, "driver_call", driver)
    board.refresh_progress(50)
    board.refresh_progress(50)
    board.refresh_progress(999)
    assert calls == [("progress", {"job_id": 50})]
    assert board.board(db)["selected"]["jobs"][0]["progress"]["completed"] == 3
    workflow.put_state(db, "job-progress:50", {"value": value, "attempt_at": 0})
    monkeypatch.setattr(
        workflow, "driver_call", lambda *_: {"error": "upstream timeout"}
    )
    board.refresh_progress(50)
    result = board.board(db)["selected"]["jobs"][0]
    assert (
        result["progress"] == value and result["progress_error"] == "upstream timeout"
    )


def test_invalid_counts_do_not_replace_last_progress(setup, monkeypatch):
    monkeypatch.setattr(
        workflow,
        "driver_call",
        lambda *_: {
            "job_id": 50,
            "total": 100,
            "completed": 1,
            "running": 1,
            "queued": 1,
            "failed": 0,
            "cancelled": 0,
            "unknown": 0,
        },
    )
    board.refresh_progress(50)
    result = board.board(setup)["selected"]["jobs"][0]
    assert result["progress"] is None and "inconsistent" in result["progress_error"]


def test_archived_values_remain_visible_with_separate_quality_status(setup):
    row = setup.scalars(select(DashboardSnapshot)).one()
    item = {**row.snapshot["comparison"][0], "quality_gate_passed": False}
    row.snapshot = {"comparison": [item]}
    setup.commit()
    metrics = board.board(setup, "old")["selected"]["metrics"]
    assert metrics["available"] and metrics["precision"] == 0.8
    assert metrics["archived"] and not metrics["quality_gate_passed"]
