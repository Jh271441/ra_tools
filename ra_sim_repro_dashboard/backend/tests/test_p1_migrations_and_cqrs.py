"""P1 tests: Alembic upgrade/downgrade, KV backfill idempotency, CQRS read models, locks, and worker."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Thread
from unittest.mock import MagicMock

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.domain.hashing import digest, population_identity
from app import evaluation_worker as eval_worker_cli
from app.infra.locks import LockBusyError, advisory_lock
from app.migrate_kv_data import backfill_database, verify_backfill
from app.models import (
    AdminAuditLog,
    DashboardReadModel,
    EvaluationExecution,
    EvaluationRequest,
    EvaluationRevision,
    EvaluationRevisionBlob,
    EvaluationScenarioTag,
    ReleaseIssueSnapshot,
    ReleaseSimulationBatch,
    ReleaseWorkflowState,
    ReproductionTimingEvidence,
)
from app.repositories import read_models_repo, state_store
from app.services import cache as cache_mod
from app.services import evaluation_pipeline as p
from app.services import scenario_label_sets
from app.services.read_views import read_view

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_downgrade_roundtrip_on_legacy_schema(tmp_path):
    db_path = tmp_path / "alembic_test.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    # Seed a pre-P1 legacy schema (64-char KV key, no population_hash or normalized tables)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE release_workflow_state (
                    key VARCHAR(64) PRIMARY KEY,
                    payload JSON NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE release_issue_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_hash VARCHAR(64) NOT NULL,
                    release VARCHAR(128) NOT NULL,
                    payload JSON NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE release_simulation_batches (
                    fingerprint VARCHAR(64) PRIMARY KEY,
                    release VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    payload JSON NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)

    from alembic.script import ScriptDirectory

    script_dir = ScriptDirectory.from_config(cfg)
    for rev in script_dir.walk_revisions():
        assert (
            len(rev.revision) <= 32
        ), f"Alembic revision ID exceeds PG VARCHAR(32): {rev.revision!r}"

    command.upgrade(cfg, "head")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for expected in (
        "evaluation_scenario_tags",
        "evaluation_requests",
        "evaluation_revisions",
        "evaluation_revision_blobs",
        "evaluation_executions",
        "reproduction_timing_evidence",
        "dashboard_read_models",
        "release_data_versions",
        "admin_audit_logs",
    ):
        assert expected in tables

    snap_cols = {c["name"] for c in insp.get_columns("release_issue_snapshots")}
    assert "population_hash" in snap_cols
    batch_cols = {c["name"] for c in insp.get_columns("release_simulation_batches")}
    assert {"population_hash", "is_backfill", "is_primary", "job_id"} <= batch_cols

    # Verify downgrade -> re-upgrade works cleanly
    command.downgrade(cfg, "base")
    insp_down = inspect(engine)
    assert "evaluation_revisions" not in set(insp_down.get_table_names())

    from alembic.script import ScriptDirectory

    script_dir = ScriptDirectory.from_config(cfg)
    for rev in script_dir.walk_revisions():
        assert (
            len(rev.revision) <= 32
        ), f"Alembic revision ID exceeds PG VARCHAR(32): {rev.revision!r}"

    command.upgrade(cfg, "head")
    assert "evaluation_revisions" in set(inspect(engine).get_table_names())
    engine.dispose()


def test_kv_backfill_is_idempotent_and_non_destructive(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    Base.metadata.create_all(engine)

    period = {
        "release": "gen4-release-20261106",
        "case_start": "2026-11-01",
        "case_end_exclusive": "2026-11-08",
        "binary_id": 1001,
    }
    snap_payload = {
        "period": period,
        "issues": [{"issue_id": "cn1", "ra_type": 2, "ra_merge_result": "成功"}],
        "scenarios": [
            {
                "scenario_id": "s1",
                "issue_id": "cn1",
                "scenario_revision": 1,
                "start_timestamp": 10,
                "end_timestamp": 20,
            }
        ],
    }
    expected_pop_hash = population_identity(snap_payload)
    ctx = {
        "release": "gen4-release-20261106",
        "profile_id": "auto_triage_review_v1",
        "date_start": "2026-11-01",
        "date_end": "2026-11-07",
    }
    rev_payload = {
        "revision_key": "evrevision:testrev1",
        "context": ctx,
        "profile": {"id": "auto_triage_review_v1", "config_hash": "cfg1"},
        "metrics": {"precision": 0.9, "recall": 0.8},
        "rows": [{"issue_id": "cn1", "eligible": True}],
        "source": {"dashboard": {"observed_at": "2026-11-07T00:00:00Z"}},
        "payload": snap_payload,
        "lineage": {"s1": {"execution_id": "exec1"}},
        "generated_at": "2026-11-07T00:00:00+00:00",
    }
    exec_payload = {
        "id": "exec1",
        "status": "complete",
        "job_id": 9999,
        "plan": {"release": "gen4-release-20261106", "scenarios": [{"scenario_id": "s1"}]},
        "results": {"s1": {"sim_triggered": True}},
        "export": {"job_id": 9999, "rows": []},
        "audit_hash": "aud1",
    }
    req_payload = {
        "id": "req1",
        "context": ctx,
        "status": "complete",
        "source_mode": "database",
        "requested_at": "2026-11-07T00:00:00+00:00",
    }
    rtime_core = {
        "schema": "reproduction_evidence_v1",
        "release": "gen4-release-20261106",
        "records": [{"binding": {"release": "gen4-release-20261106", "issue_id": "cn1"}}],
    }
    rtime_key = "rtime:" + digest(rtime_core)[:48]

    with Session(engine) as db:
        # Insert directly as legacy rows (bypassing routed put_state)
        snap = ReleaseIssueSnapshot(
            period_hash="p1", release="gen4-release-20261106", payload=snap_payload
        )
        db.add(snap)
        db.flush()
        # Simulate pre-P1 NULL population_hash via raw SQL
        db.execute(text("UPDATE release_issue_snapshots SET population_hash = NULL"))
        orig_batch_ts = datetime(2026, 11, 7, 1, 2, 3)
        db.add(
            ReleaseSimulationBatch(
                fingerprint="fp1",
                release="gen4-release-20261106",
                status="complete",
                updated_at=orig_batch_ts,
                payload={
                    "population_hash": expected_pop_hash,
                    "job_id": 8888,
                    "result_import": {"primary": True},
                },
            )
        )
        db.flush()
        # Simulate pre-P1 NULL indexed columns without changing updated_at
        db.execute(
            text(
                "UPDATE release_simulation_batches "
                "SET population_hash = NULL, is_primary = 0, job_id = NULL, updated_at = :ts "
                "WHERE fingerprint = 'fp1'"
            ),
            {"ts": orig_batch_ts},
        )
        db.add(ReleaseWorkflowState(key="evrevision:testrev1", payload=rev_payload))
        db.add(ReleaseWorkflowState(key="evexecution:exec1", payload=exec_payload))
        db.add(ReleaseWorkflowState(key="evrequest:req1", payload=req_payload))
        db.add(
            ReleaseWorkflowState(
                key=scenario_label_sets.index_key(ctx),
                payload={"id": "plan1", "context": ctx, "namespace": "ns1"},
            )
        )
        db.add(
            ReleaseWorkflowState(
                key=scenario_label_sets.issue_key(ctx, "cn1"),
                payload={
                    "plan_id": "plan1",
                    "revision_key": "evrevision:testrev1",
                    "namespace": "ns1",
                    "checked_at": "2026-11-07T00:00:00+00:00",
                    "items": [{"issue_id": "cn1", "scenario_id": "s1"}],
                },
            )
        )
        db.add(ReleaseWorkflowState(key=rtime_key, payload=rtime_core))
        db.commit()

        first = backfill_database(db)
        assert first["snapshots_hashed"] == 1
        assert first["batches_indexed"] == 1
        assert first["revisions_migrated"] == 1
        assert first["executions_migrated"] == 1
        assert first["requests_migrated"] == 1
        assert first["scenario_tags_migrated"] == 1
        assert first["timing_ledgers_migrated"] == 1

        # Backfill must preserve ReleaseSimulationBatch.updated_at (published_batch orders DESC).
        db.expire_all()
        assert db.get(ReleaseSimulationBatch, "fp1").updated_at == orig_batch_ts

        # Second run is a clean idempotent no-op
        second = backfill_database(db)
        assert all(v == 0 for v in second.values())

        # Legacy KV rows remain intact for rollback safety
        assert db.get(ReleaseWorkflowState, "evrevision:testrev1") is not None
        assert db.get(ReleaseWorkflowState, "evexecution:exec1") is not None

        # Verify summary read does NOT load EvaluationRevisionBlob
        db.expunge_all()
        loaded_types = []

        def track(session, instance):
            loaded_types.append(type(instance))

        event.listen(db, "loaded_as_persistent", track)
        try:
            summary = state_store.get_revision_summary(db, "evrevision:testrev1")
        finally:
            event.remove(db, "loaded_as_persistent", track)
        assert summary["metrics"]["precision"] == 0.9
        assert "rows" not in summary
        assert EvaluationRevisionBlob not in loaded_types

        # Full revision reconstructs losslessly
        assert state_store.get_revision_full(db, "evrevision:testrev1") == rev_payload
        assert state_store.get_execution(db, "exec1", include_heavy=True) == exec_payload
        meta = state_store.get_execution(db, "exec1", include_heavy=False)
        assert meta["status"] == "complete" and "export" not in meta

        counts = verify_backfill(db)
        assert counts["snapshots_missing_hash"] == 0
        assert counts["evaluation_revisions"] == 1
        assert counts["evaluation_executions"] == 1
        assert counts["evaluation_scenario_tags"] == 1
        assert counts["reproduction_timing_evidence"] == 1
    engine.dispose()


def test_fine_grained_release_invalidation_and_cqrs_read_model(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cqrs.db'}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        calls_a, calls_b = [], []

        def load_a():
            calls_a.append(1)
            return {"release": "rel-a", "count": len(calls_a)}

        def load_b():
            calls_b.append(1)
            return {"release": "rel-b", "count": len(calls_b)}

        assert read_view(db, "board-a", load_a, scope_releases=["rel-a"])["count"] == 1
        assert read_view(db, "board-b", load_b, scope_releases=["rel-b"])["count"] == 1

        # Writing to rel-a must invalidate ONLY rel-a, NOT rel-b!
        db.add(
            ReleaseSimulationBatch(
                fingerprint="fp-a", release="rel-a", status="running", payload={}
            )
        )
        db.commit()

        assert read_view(db, "board-a", load_a, scope_releases=["rel-a"])["count"] == 2
        assert read_view(db, "board-b", load_b, scope_releases=["rel-b"])["count"] == 1

        # Upsert & batch-read CQRS read model
        read_models_repo.upsert_read_model(
            db,
            cache_key="eval_cmp:p1:rel-a::",
            scope_release="rel-a",
            profile_id="p1",
            view_type="eval_comparison",
            source_version="r1:g0:cfg1::",
            payload={"release": "rel-a", "revision": {"metrics": {"f1": 0.85}}, "stale": False},
        )
        db.commit()
        batch = read_models_repo.get_read_models_batch(db, ["eval_cmp:p1:rel-a::"])
        assert batch["eval_cmp:p1:rel-a::"].payload["revision"]["metrics"]["f1"] == 0.85
    engine.dispose()


def test_advisory_lock_blocks_concurrent_thread_and_releases_cleanly(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'locks.db'}")
    entered = Barrier(2)
    release = Barrier(2)
    errors: list[Exception] = []

    def holder():
        with advisory_lock("test-contention-key", blocking=False, engine=engine):
            entered.wait(timeout=3)
            release.wait(timeout=3)

    t = Thread(target=holder)
    t.start()
    try:
        entered.wait(timeout=3)
        with pytest.raises(LockBusyError, match="busy"):
            with advisory_lock("test-contention-key", blocking=False, engine=engine):
                pass
    finally:
        release.wait(timeout=3)
        t.join(timeout=3)

    # Immediately reacquirable after release
    with advisory_lock("test-contention-key", blocking=False, engine=engine):
        assert not errors
    engine.dispose()


def test_redis_cache_uses_lua_owner_token_unlock():
    rc = cache_mod.RedisCache.__new__(cache_mod.RedisCache)
    fake = MagicMock()
    fake.set.return_value = True
    rc._client = fake
    rc._last_failed_at = 0.0
    rc._reconnect_backoff = 15.0
    rc._lock_tokens = {}

    assert rc.lock("job:1", ttl=60) is True
    token = rc._lock_tokens["job:1"]
    assert len(token) == 32
    rc.unlock("job:1")
    fake.eval.assert_called_once_with(cache_mod._UNLOCK_LUA, 1, "job:1", token)


def test_standalone_evaluation_worker_guards(monkeypatch):
    monkeypatch.setenv("EVALUATION_WORKER_ENABLED", "0")
    with pytest.raises(RuntimeError, match="disabled"):
        eval_worker_cli.main()

    monkeypatch.setenv("EVALUATION_WORKER_ENABLED", "1")
    monkeypatch.setenv("EVALUATION_WORKER_RUNNER", "api")
    with pytest.raises(RuntimeError, match="EVALUATION_WORKER_RUNNER=worker"):
        eval_worker_cli.main()
