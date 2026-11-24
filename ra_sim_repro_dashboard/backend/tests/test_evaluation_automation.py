from copy import deepcopy
import asyncio
import pytest
from app.services import (
    evaluation_pipeline as p,
    evaluation_worker as worker,
    release_workflow as w,
)
from app.services import auto_triage_warehouse as warehouse, auto_triage_metrics as at
from test_auto_triage_metrics import db, prepared, RELEASE
from test_evaluation_pipeline import executable, seed


def test_hourly_pause_does_not_pause_authorized_work(monkeypatch):
    monkeypatch.setenv("EVALUATION_CRON_ENABLED", "0")
    monkeypatch.delenv("EVALUATION_WORKER_ENABLED", raising=False)
    assert worker.enabled() and not worker.scheduling_enabled()
    calls = []

    def tick(*, schedule):
        calls.append(schedule)
        if len(calls) == 1:
            raise RuntimeError("temporary failure")

    async def to_thread(fn, **kwargs):
        return fn(**kwargs)

    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(p, "tick", tick)
    monkeypatch.setattr(worker.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.monitor())
    assert calls == [False, False] and sleeps == [worker.POLL_SECONDS] * 2
    monkeypatch.setenv("EVALUATION_WORKER_ENABLED", "0")
    assert not worker.enabled() and not worker.scheduling_enabled()


@pytest.mark.parametrize("projection_failure", [False, True])
def test_manual_job_automatically_imports_projects_and_updates_its_receipt(
    prepared, monkeypatch, tmp_path, projection_failure
):
    db, snap, batch, labels, revision = executable(prepared, monkeypatch)
    original_batch, original_snapshot = deepcopy(batch.payload), deepcopy(snap.payload)
    batch_id, snapshot_id = batch.fingerprint, snap.id
    monkeypatch.setenv("RELEASE_WORKFLOW_LOCK", str(tmp_path / "workflow.lock"))
    monkeypatch.setenv("EVALUATION_CRON_ENABLED", "0")
    monkeypatch.setattr(p, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        warehouse,
        "fetch",
        lambda *a, **kw: pytest.fail("Automatic evaluation queried upstream samples"),
    )
    monkeypatch.setattr(
        at,
        "fetch_labels",
        lambda *a, **kw: pytest.fail("Automatic evaluation queried upstream labels"),
    )
    p.set_cron(db, True, **revision["context"])
    assert not p.board(db, RELEASE)["cron"]["effective"]
    plan = p.board(db, RELEASE)["plan"]
    p.start(db, plan["id"])
    calls = []
    polls = 0

    def driver(config, action, body):
        nonlocal polls
        calls.append(action)
        if action == "prepare_scenes":
            return {
                "ready": True,
                "prepared": 1,
                "failed": 0,
                "failures": [],
                "scenarios": [
                    {
                        "scenario_id": "999",
                        "issue_id": "c",
                        "scenario_revision": 0,
                        "start_timestamp": 0,
                        "end_timestamp": 10000,
                    }
                ],
            }
        if action == "preflight":
            return {
                "ready": True,
                "fingerprint": body["fingerprint"],
                "execution_contract_hash": "runtime",
            }
        if action == "submit":
            return {"fingerprint": body["fingerprint"], "job_id": 9999}
        if action == "progress":
            return {
                "state": "RUNNING" if polls == 0 else "COMPLETED",
                "total": 1,
                "completed": polls,
                "running": 1 - polls,
                "queued": 0,
                "failed": 0,
            }
        if action == "poll":
            polls += 1
            if polls == 1:
                return {"status": "running"}
            return {
                "execution_export": {
                    "job_id": 9999,
                    "release": RELEASE,
                    "binary_id": 456,
                    "population_hash": body["population_hash"],
                    "execution_contract_hash": "runtime",
                    "progress": {
                        "job_id": 9999,
                        "state": "COMPLETED",
                        "total": 1,
                        "completed": 1,
                        "failed": 0,
                        "cancelled": 0,
                    },
                    "rows": [
                        {
                            "scenario_id": 999,
                            "issue_id": "c",
                            "cohort": "source_manual",
                            "task_id": "task-999",
                            "argument_hash": "hash",
                            "task_status": 3,
                            "task_outcome": "Done",
                            "simulator_cache_hit": False,
                            "inference_log_count": 1,
                            "dpe_output_count": 1,
                            "output_bag_count": 1,
                            "failed_evaluation_count": 0,
                            "unexpected_warning_count": 0,
                            p.TRIGGER: 1,
                        }
                    ],
                }
            }
        pytest.fail(action)

    monkeypatch.setattr(w, "driver_call", driver)
    requests = deepcopy(p.rows(db, "evrequest:"))
    p.tick(schedule=False)
    running = p.rows(db, "evexecution:")[0]
    assert running["status"] == "running" and running["simulation_submitted"]
    assert p.rows(db, "evstart:")[0]["simulation_submitted"] is True
    assert (
        p.rows(db, "evrequest:") == requests
    )  # Paused hourly scheduling created no extra requests.
    calculate = p.recalculate
    if projection_failure:
        monkeypatch.setattr(
            p, "recalculate", lambda *a, **kw: (_ for _ in ()).throw(ValueError("pipeline_busy"))
        )
    p.tick(schedule=False)
    finished = p.rows(db, "evexecution:")[0]
    assert finished["status"] == "complete" and len(finished["results"]) == 1
    assert p.rows(db, "evstart:")[0]["status"] == "complete"
    if projection_failure:
        assert (
            finished["metrics_status"] == "pending" and finished["metrics_error"] == "pipeline_busy"
        )
        assert (
            p.current_revision(db, RELEASE)["metrics"]["covered"] == revision["metrics"]["covered"]
        )
        prior_calls = list(calls)
        p.tick(schedule=False)  # Retry is bounded and never re-submits.
        assert calls == prior_calls
        finished["metrics_retry_at"] = "2000-01-01T00:00:00+00:00"
        w.put_state(db, "evexecution:" + finished["id"], finished)
        monkeypatch.setattr(p, "recalculate", calculate)
        p.tick(schedule=False)
        assert calls == prior_calls
    after = p.current_revision(db, RELEASE)
    assert (
        after["metrics"]["available"]
        and after["metrics"]["covered"] == after["metrics"]["eligible"]
    )
    assert p.board(db, RELEASE)["plan"]["gap_count"] == 0
    assert p.rows(db, "evexecution:")[0]["metrics_status"] == "complete"
    assert calls.count("submit") == 1
    p.tick(schedule=False)
    assert calls.count("submit") == 1 and len(p.rows(db, "evexecution:")) == 1
    assert db.get(type(batch), batch_id).payload == original_batch
    assert db.get(type(snap), snapshot_id).payload == original_snapshot


def test_hourly_metric_check_only_replans_and_never_launches(prepared, monkeypatch, tmp_path):
    db, _, _, _, revision = seed(prepared, monkeypatch)
    monkeypatch.setenv("RELEASE_WORKFLOW_LOCK", str(tmp_path / "workflow.lock"))
    monkeypatch.setattr(p, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        warehouse, "fetch", lambda *a, **kw: pytest.fail("Hourly check queried upstream")
    )
    monkeypatch.setattr(
        w,
        "driver_call",
        lambda *a, **kw: pytest.fail("Hourly check submitted or polled simulation"),
    )
    p.set_cron(db, True, **revision["context"])
    p.tick(schedule=False)
    assert not p.rows(db, "evrequest:")
    p.tick(schedule=True)
    requests = p.rows(db, "evrequest:")
    assert (
        len(requests) == 1
        and requests[0]["status"] == "complete"
        and requests[0]["source_mode"] == "database"
    )
    assert not p.rows(db, "evexecution:") and not p.rows(db, "evstart:")
    assert p.current_revision(db, RELEASE)["metrics"] == revision["metrics"]
