from __future__ import annotations

import tempfile
import threading
import unittest
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app.batch_prediction_runner import BatchPredictionRunner


class _QueueDatabase:
    def __init__(self) -> None:
        self.jobs = {
            "job-1": {"id": "job-1", "status": "queued"},
            "job-2": {"id": "job-2", "status": "queued"},
        }

    def update_batch_prediction_job(self, job_id: str, **values):
        self.jobs[job_id].update(values)
        return dict(self.jobs[job_id])

    def next_queued_batch_prediction_job(self):
        return next(
            (dict(job) for job in self.jobs.values() if job["status"] == "queued"),
            None,
        )


class BatchQueueRunnerTest(unittest.TestCase):
    def test_worker_uses_server_runtime_override_without_inheriting_secrets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "batch-bags",
                app_root=root / "app",
                jobs_dir=root / "jobs",
            )
            runner = BatchPredictionRunner(settings, _QueueDatabase())
            for override in ("", str(root / "worker-venv/bin/python3")):
                with self.subTest(override=override), patch.dict(
                    os.environ,
                    {
                        "DASHBOARD_BATCH_PYTHON_BIN": override,
                        "VOYAGER_SETUP_SCRIPT": str(root / "worker-setup.sh"),
                        "RA_CODE_MANIFEST_SHA256": "a" * 64,
                        "UNRELATED_SECRET": "must-not-reach-child",
                        "HTTPS_PROXY": "http://wrong-proxy.invalid",
                    },
                ), patch(
                    "ra_triage_dashboard.app.batch_prediction_runner.subprocess.Popen",
                    side_effect=RuntimeError("captured worker spawn"),
                ) as spawn:
                    with self.assertRaisesRegex(RuntimeError, "captured worker spawn"):
                        runner._run_worker(job_id="probe", action="publish", payload={})
                    env = spawn.call_args.kwargs["env"]
                    self.assertEqual(
                        env["DASHBOARD_PYTHON_BIN"], override or sys.executable
                    )
                    self.assertEqual(
                        env["VOYAGER_SETUP_SCRIPT"], str(root / "worker-setup.sh")
                    )
                    self.assertEqual(env["RA_CODE_MANIFEST_SHA256"], "a" * 64)
                    self.assertNotIn("UNRELATED_SECRET", env)
                    self.assertEqual(env["HTTPS_PROXY"], "")

    def test_busy_runner_keeps_next_prediction_queued_then_starts_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
            )
            database = _QueueDatabase()
            runner = BatchPredictionRunner(settings, database)
            first_started = threading.Event()
            release_first = threading.Event()
            second_started = threading.Event()
            release_second = threading.Event()

            def predict(job_id: str) -> None:
                if job_id == "job-1":
                    first_started.set()
                    release_first.wait(timeout=2)
                else:
                    second_started.set()
                    release_second.wait(timeout=2)

            runner._predict = predict
            self.assertTrue(runner.launch_prediction(database.jobs["job-1"]))
            self.assertTrue(first_started.wait(timeout=1))
            self.assertTrue(runner.launch_prediction(database.jobs["job-2"]))
            self.assertEqual(database.jobs["job-2"]["status"], "queued")
            release_first.set()
            self.assertTrue(second_started.wait(timeout=1))
            self.assertEqual(database.jobs["job-2"]["status"], "running")
            release_second.set()
            runner.shutdown()

    def test_standby_init_preserves_running_batch_jobs_until_leased_recovery(self) -> None:
        from ra_triage_dashboard.app.db import Database

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "triage.sqlite3"
            primary = Database(db_path)
            primary.init()
            primary.upsert_issues(
                [{"issue_id": "cn1", "baseline_scope": "scope"}],
                source="test",
                replace_gt=False,
            )
            job = primary.create_batch_prediction_job(
                name="live-blue-job",
                issue_ids=["cn1"],
                requested_by="alice",
                requested_by_source="sso",
                requested_by_verified=True,
                provider_id="kylin",
                requested_model_id="m1",
                resolved_model_id="m1",
                model_source="ra_model_gateway",
                catalog_sha256="a" * 64,
                model_validation_status="ok",
                prompt_version="v1",
                prompt_template="prompt",
                prompt_template_sha256="b" * 64,
                prompt_mode="default",
                input_profile="p1",
                input_config={},
            )
            primary.update_batch_prediction_job(
                job["id"],
                status="running",
                publish_status="running",
            )
            with primary.connect() as conn:
                conn.execute(
                    "UPDATE batch_prediction_items SET status = 'running' WHERE job_id = ?",
                    (job["id"],),
                )

            # Standby blue-green slot starts with recover_interrupted_jobs=False:
            # live running job, running item, and running publish must remain intact.
            standby = Database(db_path)
            standby.init(recover_interrupted_jobs=False)
            after_standby = standby.get_batch_prediction_job(job["id"])
            self.assertEqual(after_standby["status"], "running")
            self.assertEqual(after_standby["publish_status"], "running")
            self.assertEqual(after_standby["items"][0]["status"], "running")

            # Excluding an actively owned local job also preserves it.
            standby.recover_interrupted_jobs(exclude_job_ids={job["id"]})
            still_running = standby.get_batch_prediction_job(job["id"])
            self.assertEqual(still_running["status"], "running")
            self.assertEqual(still_running["publish_status"], "running")

            # Once the old executor exits and the new leader acquires the lease,
            # explicit recover_interrupted_jobs() marks truly orphaned jobs failed.
            standby.recover_interrupted_jobs()
            recovered = standby.get_batch_prediction_job(job["id"])
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["publish_status"], "failed")
            self.assertEqual(recovered["items"][0]["status"], "failed")

    def test_lease_gated_runner_defers_execution_until_lease_acquired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
                autotriage_push_enabled=True,
            )
            database = _QueueDatabase()
            runner = BatchPredictionRunner(settings, database)
            runner.set_lease_gating(True, held=False)
            started = threading.Event()
            runner._predict = lambda job_id: started.set()

            # Without lease, prediction stays durably queued and confirmed publish
            # is accepted for the lease-holding worker rather than failing with 409.
            self.assertTrue(runner.launch_prediction(database.jobs["job-1"]))
            self.assertEqual(database.jobs["job-1"]["status"], "queued")
            self.assertTrue(runner.launch_publish(database.jobs["job-1"]))
            self.assertFalse(runner.resume_queued_work())

            # After acquiring lease, queued prediction starts cleanly.
            runner.set_lease_held(True)
            self.assertTrue(runner.resume_queued_work())
            self.assertTrue(started.wait(timeout=1))
            runner.shutdown()

    def test_run_with_lease_cancels_inner_leader_and_reacquires_after_renew_exception(self) -> None:
        import asyncio
        from ra_triage_dashboard.app.workers.leases import run_with_lease

        events: list[str] = []

        class _FlakyLeaseManager:
            owner_id = "test-owner"

            def __init__(self) -> None:
                self.calls = 0

            def try_acquire_or_renew(self, lease_key: str, *, ttl_seconds: float = 60.0) -> bool:
                self.calls += 1
                if self.calls == 1:
                    events.append("acquire_1")
                    return True
                if self.calls == 2:
                    events.append("renew_error")
                    raise RuntimeError("transient db connection error")
                events.append("acquire_2")
                return True

            def release(self, lease_key: str) -> bool:
                events.append("release")
                return True

        async def _scenario() -> None:
            manager = _FlakyLeaseManager()
            second_leader_started = asyncio.Event()

            async def _leader() -> None:
                run_no = 1 if "leader_1_start" not in events else 2
                events.append(f"leader_{run_no}_start")
                if run_no == 2:
                    second_leader_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    events.append(f"leader_{run_no}_cleanup")

            orig_sleep = asyncio.sleep

            async def _fast_sleep(_seconds: float) -> None:
                await orig_sleep(0.01)

            with patch("ra_triage_dashboard.app.workers.leases.asyncio.sleep", side_effect=_fast_sleep):
                task = asyncio.create_task(
                    run_with_lease(
                        manager,
                        "batch-prediction-runner",
                        _leader,
                        ttl_seconds=15.0,
                        retry_seconds=0.01,
                        renew_interval=0.01,
                    )
                )
                await asyncio.wait_for(second_leader_started.wait(), timeout=2.0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        asyncio.run(_scenario())
        self.assertIn("leader_1_cleanup", events)
        self.assertLess(events.index("renew_error"), events.index("leader_1_cleanup"))
        self.assertLess(events.index("leader_1_cleanup"), events.index("acquire_2"))
        self.assertIn("leader_2_cleanup", events)

    def _seed_completed_batch_job(self, db, *, name: str = "publish-job") -> dict:
        db.upsert_issues([{"issue_id": "cn1"}], baseline_scope="scope", source="test", replace_gt=False)
        imported = db.import_model_run(
            name=f"{name}-run",
            source_name=f"{name}.json",
            source_sha256=f"{abs(hash(name)):064x}"[:64],
            rows=[{"issue_id": "cn1", "model_label": "误触发"}],
            metadata={"kind": "manual_batch"},
            kind="manual_batch",
        )
        run = imported[0] if isinstance(imported, tuple) else imported
        job = db.create_batch_prediction_job(
            name=name,
            issue_ids=["cn1"],
            requested_by="alice",
            requested_by_source="sso",
            requested_by_verified=True,
            provider_id="kylin",
            requested_model_id="m1",
            resolved_model_id="m1",
            model_source="ra_model_gateway",
            catalog_sha256="a" * 64,
            model_validation_status="ok",
            prompt_version="v1",
            prompt_template="prompt",
            prompt_template_sha256="b" * 64,
            prompt_mode="default",
            input_profile="p1",
            input_config={},
        )
        return db.update_batch_prediction_job(
            job["id"],
            status="succeeded",
            completed_count=1,
            success_count=1,
            model_run_id=run["id"],
            config_sha256="c" * 64,
        )

    def test_standalone_worker_publish_api_persists_request_and_leased_worker_executes(self) -> None:
        import asyncio
        from ra_triage_dashboard.app.db import Database
        from ra_triage_dashboard.app.routers import core as core_router
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "triage.sqlite3")
            db.init()
            job = self._seed_completed_batch_job(db, name="standalone-publish")

            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
                autotriage_push_enabled=True,
                auto_triage_record_base_url="http://autotriage.invalid",
            )
            web_runner = BatchPredictionRunner(settings, db)
            web_runner.set_lease_gating(True, held=False)

            worker_runner = BatchPredictionRunner(settings, db)
            worker_runner.set_lease_gating(True, held=True)
            published = threading.Event()
            publish_calls: list[str] = []

            def fake_publish(job_id: str) -> None:
                publish_calls.append(job_id)
                db.update_batch_prediction_job(
                    job_id,
                    publish_status="succeeded",
                    autotriage_batch_id="at-batch-1",
                )
                published.set()

            worker_runner._publish = fake_publish

            class _FakeRequest:
                headers = {"x-ra-triage-request": "publish-v1"}

                async def json(self):
                    return {"confirm": "publish-autotriage"}

            fake_publisher = SimpleNamespace(username="alice", source="sso", verified=True)

            async def _exercise_api() -> dict:
                with patch.object(core_router, "database", db), patch.object(
                    core_router, "batch_prediction_runner", web_runner
                ), patch.object(core_router, "settings", settings), patch.object(
                    core_router, "request_identity", return_value=fake_publisher
                ):
                    res = await core_router.publish_batch_prediction(job["id"], _FakeRequest())
                    with self.assertRaises(HTTPException) as ctx:
                        await core_router.publish_batch_prediction(job["id"], _FakeRequest())
                    self.assertEqual(ctx.exception.status_code, 409)
                    return res

            response = asyncio.run(_exercise_api())
            self.assertTrue(response["accepted"])
            self.assertTrue(worker_runner.resume_queued_work())
            self.assertTrue(published.wait(timeout=2))
            self.assertEqual(publish_calls, [job["id"]])
            final_job = db.get_batch_prediction_job(job["id"])
            self.assertEqual(final_job["publish_status"], "succeeded")
            self.assertFalse(final_job["publish_queued"])
            self.assertEqual(final_job["autotriage_batch_id"], "at-batch-1")
            self.assertFalse(final_job["summary"]["autotriage_publish_request"]["queued"])
            worker_runner.shutdown()
            web_runner.shutdown()

    def test_single_publish_request_never_invokes_publish_twice_under_api_and_worker_race(self) -> None:
        import asyncio
        from ra_triage_dashboard.app.db import Database
        from ra_triage_dashboard.app.routers import core as core_router

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "triage.sqlite3")
            db.init()
            job = self._seed_completed_batch_job(db, name="race-publish")
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
                autotriage_push_enabled=True,
                auto_triage_record_base_url="http://autotriage.invalid",
            )
            api_runner = BatchPredictionRunner(settings, db)
            poller_runner = BatchPredictionRunner(settings, db)
            publish_calls: list[str] = []
            poller_done = threading.Event()

            def record_publish(job_id: str) -> None:
                publish_calls.append(job_id)
                db.update_batch_prediction_job(
                    job_id,
                    publish_status="succeeded",
                    autotriage_batch_id="at-race-1",
                )
                poller_done.set()

            api_runner._publish = record_publish
            poller_runner._publish = record_publish

            # Simulate the polling worker claiming and completing the queued job
            # right after API enqueue, before the API handler wakes its local runner.
            original_resume = api_runner.resume_queued_publishes

            def racing_resume() -> bool:
                self.assertTrue(poller_runner.resume_queued_publishes())
                self.assertTrue(poller_done.wait(timeout=2))
                return original_resume()

            api_runner.resume_queued_publishes = racing_resume

            class _FakeRequest:
                headers = {"x-ra-triage-request": "publish-v1"}

                async def json(self):
                    return {"confirm": "publish-autotriage"}

            fake_publisher = SimpleNamespace(username="alice", source="sso", verified=True)

            async def _run_race() -> dict:
                with patch.object(core_router, "database", db), patch.object(
                    core_router, "batch_prediction_runner", api_runner
                ), patch.object(core_router, "settings", settings), patch.object(
                    core_router, "request_identity", return_value=fake_publisher
                ):
                    return await core_router.publish_batch_prediction(job["id"], _FakeRequest())

            res = asyncio.run(_run_race())
            self.assertTrue(res["accepted"])
            self.assertEqual(publish_calls, [job["id"]])
            # Direct conditional claim must also reject any second claim attempt.
            self.assertIsNone(db.claim_queued_batch_prediction_publish(job["id"]))
            api_runner.shutdown()
            poller_runner.shutdown()

    def test_disabled_autotriage_push_keeps_queued_request_unexecuted_until_reenabled(self) -> None:
        from ra_triage_dashboard.app.db import Database

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "triage.sqlite3")
            db.init()
            job = self._seed_completed_batch_job(db, name="push-switch-job")
            enqueued = db.enqueue_batch_prediction_publish(
                job["id"], requested_by="alice", identity_source="sso"
            )
            self.assertIsNotNone(enqueued)
            self.assertTrue(enqueued["publish_queued"])

            disabled_settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
                autotriage_push_enabled=False,
            )
            worker = BatchPredictionRunner(disabled_settings, db)
            worker.set_lease_gating(True, held=True)
            calls: list[str] = []
            done = threading.Event()

            def fake_publish(job_id: str) -> None:
                calls.append(job_id)
                db.update_batch_prediction_job(job_id, publish_status="succeeded", autotriage_batch_id="at-2")
                done.set()

            worker._publish = fake_publish
            self.assertFalse(worker.resume_queued_work())
            self.assertFalse(worker.launch_publish(enqueued))
            self.assertEqual(calls, [])
            still_queued = db.get_batch_prediction_job(job["id"])
            self.assertTrue(still_queued["publish_queued"])
            self.assertEqual(still_queued["publish_status"], "not_requested")

            # Re-enabling autotriage_push_enabled lets the worker consume the preserved request.
            disabled_settings.autotriage_push_enabled = True
            self.assertTrue(worker.resume_queued_work())
            self.assertTrue(done.wait(timeout=2))
            self.assertEqual(calls, [job["id"]])
            worker.shutdown()

    def test_revoked_lease_fences_paused_worker_thread_before_subprocess_popen(self) -> None:
        from ra_triage_dashboard.app.db import Database

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "triage.sqlite3")
            db.init()
            db.upsert_issues([{"issue_id": "cn1"}], baseline_scope="scope", source="test", replace_gt=False)
            job = db.create_batch_prediction_job(
                name="fenced-job",
                issue_ids=["cn1"],
                requested_by="alice",
                requested_by_source="sso",
                requested_by_verified=True,
                provider_id="kylin",
                requested_model_id="m1",
                resolved_model_id="m1",
                model_source="ra_model_gateway",
                catalog_sha256="a" * 64,
                model_validation_status="ok",
                prompt_version="v1",
                prompt_template="prompt",
                prompt_template_sha256="b" * 64,
                prompt_mode="default",
                input_profile="p1",
                input_config={},
            )
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
                app_root=root / "app",
                jobs_dir=root / "jobs",
                batch_job_timeout_seconds=30,
            )
            runner = BatchPredictionRunner(settings, db)
            runner.set_lease_gating(True, held=True)

            entered_prep = threading.Event()
            release_prep = threading.Event()

            def paused_key_read(_settings, _provider_id):
                entered_prep.set()
                release_prep.wait(timeout=5)
                return "fake-key"

            with patch(
                "ra_triage_dashboard.app.batch_prediction_runner.read_provider_api_key",
                side_effect=paused_key_read,
            ), patch(
                "ra_triage_dashboard.app.batch_prediction_runner.model_gateway_chat_url",
                return_value="http://gateway.invalid",
            ), patch(
                "ra_triage_dashboard.app.batch_prediction_runner.subprocess.Popen",
            ) as popen_mock:
                self.assertTrue(runner.launch_prediction(job))
                self.assertTrue(entered_prep.wait(timeout=2))
                worker_thread = runner._active_thread
                # Simulate lease revocation returning even while old thread is paused in prep
                # (short join timeout), followed by a new lease epoch being granted.
                with patch.object(threading.Thread, "join", return_value=None):
                    runner.revoke_lease()
                runner.set_lease_held(True)
                release_prep.set()
                if worker_thread is not None:
                    worker_thread.join(timeout=3)
                popen_mock.assert_not_called()
            # Fenced thread must not overwrite DB job state as failed either.
            self.assertEqual(db.get_batch_prediction_job(job["id"])["status"], "running")
            runner.shutdown()

    def test_next_queued_batch_publish_job_uses_partial_index_without_scanning_history(self) -> None:
        from ra_triage_dashboard.app.db import Database

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "triage.sqlite3")
            db.init()
            for idx in range(5):
                self._seed_completed_batch_job(db, name=f"history-{idx}")
            self.assertIsNone(db.next_queued_batch_publish_job())
            target = self._seed_completed_batch_job(db, name="queued-target")
            db.enqueue_batch_prediction_publish(
                target["id"], requested_by="alice", identity_source="sso"
            )
            found = db.next_queued_batch_publish_job()
            self.assertIsNotNone(found)
            self.assertEqual(found["id"], target["id"])
            with db.connect() as conn:
                plan_rows = conn.execute(
                    """
                    EXPLAIN QUERY PLAN
                    SELECT id
                    FROM batch_prediction_jobs
                    WHERE publish_queued = 1
                      AND status IN ('succeeded', 'partial')
                      AND publish_status IN ('not_requested', 'failed')
                      AND TRIM(COALESCE(autotriage_batch_id, '')) = ''
                    ORDER BY created_at ASC, rowid ASC
                    LIMIT 1
                    """
                ).fetchall()
            plan_text = " ".join(str(row["detail"]) for row in plan_rows)
            self.assertIn("idx_batch_prediction_jobs_publish_queue", plan_text)

    def test_graceful_drain_completes_active_batch_while_holding_lease_then_new_slot_takes_queued(self) -> None:
        import asyncio
        from ra_triage_dashboard.app.db import Database
        from ra_triage_dashboard.app.workers.leases import WorkerLeaseManager, run_with_lease

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "triage.sqlite3")
            db.init()
            db.upsert_issues([{"issue_id": "cn1"}], baseline_scope="scope", source="test", replace_gt=False)

            def create_job(name: str) -> dict:
                return db.create_batch_prediction_job(
                    name=name,
                    issue_ids=["cn1"],
                    requested_by="alice",
                    requested_by_source="sso",
                    requested_by_verified=True,
                    provider_id="kylin",
                    requested_model_id="m1",
                    resolved_model_id="m1",
                    model_source="ra_model_gateway",
                    catalog_sha256="a" * 64,
                    model_validation_status="ok",
                    prompt_version="v1",
                    prompt_template="prompt",
                    prompt_template_sha256="b" * 64,
                    prompt_mode="default",
                    input_profile="p1",
                    input_config={},
                )

            job1 = create_job("long-running-before-cutover")
            job2 = create_job("queued-for-new-slot")
            settings = SimpleNamespace(
                ra_auto_triage_root=root / "ra-source",
                batch_bag_cache_dir=root / "dashboard-data" / "batch-bags",
                autotriage_push_enabled=True,
            )

            blue_runner = BatchPredictionRunner(settings, db)
            green_runner = BatchPredictionRunner(settings, db)
            blue_runner.set_lease_gating(True, held=False)
            green_runner.set_lease_gating(True, held=False)

            job1_started = threading.Event()
            release_job1 = threading.Event()
            job2_done = threading.Event()
            executed: list[tuple[str, str]] = []

            def make_predict(slot_name: str):
                def _predict(job_id: str) -> None:
                    executed.append((slot_name, job_id))
                    if job_id == job1["id"]:
                        job1_started.set()
                        assert release_job1.wait(timeout=5)
                    db.update_batch_prediction_job(
                        job_id, status="succeeded", completed_count=1, success_count=1
                    )
                    if job_id == job2["id"]:
                        job2_done.set()
                return _predict

            blue_runner._predict = make_predict("blue")
            green_runner._predict = make_predict("green")

            blue_leases = WorkerLeaseManager(db, owner_id="slot-blue")
            green_leases = WorkerLeaseManager(db, owner_id="slot-green")

            def make_leader(runner: BatchPredictionRunner, drain_event: asyncio.Event):
                async def _leader() -> None:
                    await asyncio.to_thread(
                        db.recover_interrupted_jobs,
                        exclude_job_ids=runner.active_job_ids(),
                    )
                    runner.set_lease_held(True)
                    gracefully_drained = False
                    try:
                        while not drain_event.is_set():
                            await asyncio.to_thread(runner.resume_queued_work)
                            try:
                                await asyncio.wait_for(drain_event.wait(), timeout=0.05)
                            except asyncio.TimeoutError:
                                pass
                        await asyncio.to_thread(runner.begin_graceful_drain)
                        while await asyncio.to_thread(runner.has_active_work):
                            await asyncio.sleep(0.02)
                        gracefully_drained = True
                    finally:
                        if gracefully_drained:
                            runner.set_lease_held(False)
                        else:
                            await asyncio.to_thread(runner.revoke_lease)
                return _leader

            async def _scenario() -> None:
                blue_drain = asyncio.Event()
                green_drain = asyncio.Event()
                blue_task = asyncio.create_task(
                    run_with_lease(
                        blue_leases,
                        "batch-prediction-runner",
                        make_leader(blue_runner, blue_drain),
                        ttl_seconds=1.5,
                        retry_seconds=0.05,
                        renew_interval=0.1,
                        stop_event=blue_drain,
                    )
                )
                # Wait until blue has claimed and started job1.
                for _ in range(100):
                    if job1_started.is_set():
                        break
                    await asyncio.sleep(0.02)
                self.assertTrue(job1_started.is_set())

                # Start standby green slot while blue is running job1.
                green_task = asyncio.create_task(
                    run_with_lease(
                        green_leases,
                        "batch-prediction-runner",
                        make_leader(green_runner, green_drain),
                        ttl_seconds=1.5,
                        retry_seconds=0.05,
                        renew_interval=0.1,
                        stop_event=green_drain,
                    )
                )

                # Simulate blue-green cutover SIGTERM on blue while job1 is still running.
                blue_drain.set()
                await asyncio.to_thread(blue_runner.begin_graceful_drain)

                # Hold job1 open across multiple lease renewal cycles (> 0.35s) to prove
                # blue keeps renewing the lease, green never preempts or fails job1,
                # and job2 stays queued until blue finishes.
                await asyncio.sleep(0.35)
                self.assertFalse(blue_task.done())
                self.assertEqual(db.get_batch_prediction_job(job1["id"])["status"], "running")
                self.assertEqual(db.get_batch_prediction_job(job2["id"])["status"], "queued")

                # Let job1 complete; blue must NOT claim job2 and must hand off lease to green.
                release_job1.set()
                await asyncio.wait_for(blue_task, timeout=3.0)
                self.assertEqual(db.get_batch_prediction_job(job1["id"])["status"], "succeeded")

                # Green acquires the released lease and completes job2.
                for _ in range(150):
                    if job2_done.is_set():
                        break
                    await asyncio.sleep(0.02)
                self.assertTrue(job2_done.is_set())

                green_drain.set()
                await asyncio.to_thread(green_runner.begin_graceful_drain)
                await asyncio.wait_for(green_task, timeout=3.0)

            asyncio.run(_scenario())
            self.assertEqual(executed, [("blue", job1["id"]), ("green", job2["id"])])
            self.assertEqual(db.get_batch_prediction_job(job1["id"])["status"], "succeeded")
            self.assertEqual(db.get_batch_prediction_job(job2["id"])["status"], "succeeded")
            blue_runner.shutdown()
            green_runner.shutdown()


if __name__ == "__main__":
    unittest.main()
