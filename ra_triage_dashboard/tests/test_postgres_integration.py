from __future__ import annotations

import hashlib
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.run_collections import RunCollectionConflictError


@unittest.skipUnless(
    os.getenv("DASHBOARD_TEST_POSTGRES_URL", "").startswith("postgresql://"),
    "set DASHBOARD_TEST_POSTGRES_URL to an empty disposable database",
)
class PostgresDatabaseIntegrationTest(unittest.TestCase):
    def test_review_run_batch_and_revision_contract(self) -> None:
        database = Database(
            os.environ["DASHBOARD_TEST_POSTGRES_URL"],
            postgres_migrations_dir=(
                Path(__file__).resolve().parents[1] / "migrations" / "postgres"
            ),
            pool_size=3,
        )
        try:
            database.init()
            initial_revision = database.change_revision()
            database.upsert_issues(
                [{"issue_id": "cn_pg_1001", "gt_label": "正确触发"}],
                source="postgres_integration",
                replace_gt=True,
                baseline_scope="postgres_test",
            )
            run, reused = database.import_model_run(
                name="postgres integration",
                source_name="integration.json",
                source_sha256=hashlib.sha256(b"postgres-integration").hexdigest(),
                metadata={"schema_version": "v1"},
                rows=[
                    {
                        "issue_id": "cn_pg_1001",
                        "model_label": "误触发",
                        "model_reason": "integration mismatch",
                        "raw": {"source": "test"},
                    }
                ],
                make_default=True,
                created_by="integration",
            )
            self.assertFalse(reused)
            self.assertEqual(database.default_model_run_id(), run["id"])
            cases = database.list_cases(
                baseline_scope="postgres_test",
                model_run_id=run["id"],
                comparison_status="mismatch",
            )
            self.assertEqual(cases["total"], 1)
            annotation = database.create_annotation(
                issue_id="cn_pg_1001",
                label="正确触发",
                review_status="reviewed",
                tags=["queue"],
                missing_evidence=["routing_direction"],
                note="postgres review",
                author="integration",
                author_verified=False,
            )
            self.assertGreater(annotation["id"], 0)
            job = database.create_batch_prediction_job(
                name="postgres queue",
                issue_ids=["cn_pg_1001"],
                requested_by="integration",
                requested_model_id="profile",
                resolved_model_id="Qwen3.5/base",
                model_source="integration",
                catalog_sha256="a" * 64,
                prompt_version="integration",
                prompt_template="误触发、正确触发、无需协助",
                prompt_template_sha256="b" * 64,
                prompt_mode="custom",
                input_profile="camera_ra_event",
                input_config={"use_ra_event": True},
            )
            self.assertEqual(database.next_queued_batch_prediction_job()["id"], job["id"])
            batch_jobs = database.list_batch_prediction_jobs(page_size=20)
            self.assertEqual(batch_jobs["total"], 1)
            self.assertEqual(
                {item["id"] for item in batch_jobs["facets"]["models"]},
                {"profile", "Qwen3.5/base"},
            )
            self.assertGreater(database.change_revision(), initial_revision)
            overview = database.overview(
                baseline_scope="postgres_test", model_run_id=run["id"]
            )
            self.assertEqual(overview["issues"], 1)
            self.assertEqual(overview["model_failures"], 1)
        finally:
            database.close()

    def test_run_collection_revision_concurrency_and_frozen_evaluation(self) -> None:
        database = Database(
            os.environ["DASHBOARD_TEST_POSTGRES_URL"],
            postgres_migrations_dir=(
                Path(__file__).resolve().parents[1] / "migrations" / "postgres"
            ),
            pool_size=4,
        )
        other = Database(
            os.environ["DASHBOARD_TEST_POSTGRES_URL"],
            postgres_migrations_dir=(
                Path(__file__).resolve().parents[1] / "migrations" / "postgres"
            ),
            pool_size=3,
        )
        suffix = uuid4().hex
        scope = f"pg_run_collection_{suffix}"
        issue_id = f"pg_rc_{suffix}"
        try:
            database.init()
            database.upsert_issues(
                [{"issue_id": issue_id, "gt_label": "正确触发"}],
                source="run_collection_pg_test", replace_gt=True, baseline_scope=scope,
            )
            run_ids = []
            for name, label in (("first", "正确触发"), ("second", "误触发")):
                run, reused = database.import_model_run(
                    name=f"{name}-{suffix}", source_name=f"{name}-{suffix}.json",
                    source_sha256=hashlib.sha256(f"{name}-{suffix}".encode()).hexdigest(),
                    metadata={}, rows=[{"issue_id": issue_id, "model_label": label}],
                )
                self.assertFalse(reused)
                run_ids.append(run["id"])
            collection = database.create_run_collection(
                name=f"Postgres collection {suffix}",
                members=[{"run_id": run_ids[0], "is_reference": True}, run_ids[1]],
                actor="pg-test", actor_source="test", actor_verified=True,
                idempotency_key=f"pg-create-{suffix}",
            )
            evaluation = database.create_run_evaluation(
                collection_id=collection["id"], baseline_scopes=[scope],
                actor="pg-test", actor_source="test", actor_verified=True,
            )
            self.assertEqual(evaluation["summary"]["reference_denominator"], 1)
            self.assertEqual([row["correct_count"] for row in evaluation["summary"]["runs"]], [1, 0])

            def append(db: Database, member_id: str) -> str:
                try:
                    db.create_run_collection_revision(
                        collection_id=collection["id"], expected_revision=1,
                        members=[member_id], actor="pg-test", actor_source="test",
                        actor_verified=True,
                    )
                    return "created"
                except RunCollectionConflictError:
                    return "conflict"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(
                    lambda pair: append(*pair),
                    [(database, run_ids[1]), (other, run_ids[0])],
                ))
            self.assertCountEqual(outcomes, ["created", "conflict"])
            self.assertEqual(database.get_run_collection(collection["id"])["current_revision"], 2)
            committed = database.create_run_collection_revision(
                collection_id=collection["id"], expected_revision=2,
                members=[run_ids[0]], actor="pg-test", actor_source="test",
                actor_verified=True, idempotency_key=f"pg-revision-{suffix}",
            )
            replay = other.create_run_collection_revision(
                collection_id=collection["id"], expected_revision=2,
                members=[run_ids[0]], actor="pg-test", actor_source="test",
                actor_verified=True, idempotency_key=f"pg-revision-{suffix}",
            )
            self.assertEqual(committed["current_revision"], 3)
            self.assertEqual(replay["current_revision"], 3)
            with database.connect() as conn:
                migration_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM dashboard_schema_migrations"
                ).fetchone()["count"]
            self.assertEqual(int(migration_count), 47)
        finally:
            database.close()
            other.close()

    def test_run_collection_5000_issue_batch_performance_and_query_plan(self) -> None:
        database = Database(
            os.environ["DASHBOARD_TEST_POSTGRES_URL"],
            postgres_migrations_dir=(
                Path(__file__).resolve().parents[1] / "migrations" / "postgres"
            ),
            pool_size=4,
        )
        suffix = uuid4().hex
        scope = f"pg_run_collection_perf_{suffix}"
        try:
            database.init()
            issue_ids = [f"pg_rc_perf_{suffix}_{index:05d}" for index in range(5000)]
            database.upsert_issues(
                [{"issue_id": issue_id, "gt_label": "正确触发"} for issue_id in issue_ids],
                source="run_collection_pg_perf", replace_gt=True, baseline_scope=scope,
            )
            first, _ = database.import_model_run(
                name=f"perf-first-{suffix}", source_name=f"perf-first-{suffix}.json",
                source_sha256=hashlib.sha256(f"perf-first-{suffix}".encode()).hexdigest(),
                metadata={}, rows=[
                    {"issue_id": issue_ids[index], "model_label": "正确触发"}
                    for index in range(0, 5000, 2)
                ],
            )
            second, _ = database.import_model_run(
                name=f"perf-second-{suffix}", source_name=f"perf-second-{suffix}.json",
                source_sha256=hashlib.sha256(f"perf-second-{suffix}".encode()).hexdigest(),
                metadata={}, rows=[
                    {"issue_id": issue_ids[index], "model_label": "误触发"}
                    for index in range(1, 5000, 2)
                ],
            )
            collection = database.create_run_collection(
                name=f"Postgres performance {suffix}",
                members=[{"run_id": first["id"], "is_reference": True}, second["id"]],
            )
            started = time.perf_counter()
            evaluation = database.create_run_evaluation(
                collection_id=collection["id"], baseline_scopes=[scope],
            )
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 30.0)
            self.assertEqual(evaluation["summary"]["workset_count"], 5000)
            self.assertEqual(evaluation["summary"]["reference_denominator"], 5000)
            with database.connect() as conn:
                plan = conn.execute(
                    "EXPLAIN (ANALYZE, BUFFERS) SELECT model_label FROM model_predictions "
                    "WHERE model_run_id = ? AND issue_id = ?",
                    (first["id"], issue_ids[0]),
                ).fetchall()
            plan_text = "\n".join(str(row["QUERY PLAN"]) for row in plan)
            self.assertTrue("Index Scan" in plan_text or "Bitmap Index Scan" in plan_text, plan_text)
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
