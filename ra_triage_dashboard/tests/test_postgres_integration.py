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
            snapshot = database.apply_gt_sync_snapshot(
                scope=scope,
                rows=[{"issue_id": issue_id, "gt_label": "正确触发"}],
                source_name="test", source_view_id=1000, source_field="gt",
                trigger="test", requested_by="pg-test", requested_by_source="test",
                requested_by_verified=True, expected_issue_ids=[issue_id],
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
            with database.connect() as conn:
                before_rollback = {
                    table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
                    for table in ("review_worksets", "run_evaluation_exclusion_snapshots", "run_evaluation_contexts")
                }
            with self.assertRaisesRegex(ValueError, "scoring_policy"):
                database.create_run_evaluation(
                    collection_id=collection["id"], baseline_scopes=[scope],
                    scoring_policy={"version": "unsupported-v9"},
                )
            with database.connect() as conn:
                after_rollback = {
                    table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
                    for table in before_rollback
                }
            self.assertEqual(after_rollback, before_rollback)
            evaluation = database.create_run_evaluation(
                collection_id=collection["id"], baseline_scopes=[scope],
                actor="pg-test", actor_source="test", actor_verified=True,
            )
            self.assertEqual(evaluation["summary"]["reference_denominator"], 1)
            self.assertEqual([row["correct_count"] for row in evaluation["summary"]["runs"]], [1, 0])
            workset_id = evaluation["workset"]["workset_id"]
            references = [{
                "baseline_scope": scope,
                "reference_type": "gt_snapshot",
                "reference_id": snapshot["active_gt_snapshot"]["id"],
            }]
            label_campaign = database.create_campaign(
                spec={
                    "purpose": "labeling", "lifecycle": "draft",
                    "campaign_name": f"S5 shared labels {suffix}",
                    "workset_id": workset_id, "references": references,
                    "members": [{"issue_id": issue_id, "assignees": ["reviewer"]}],
                },
                actor="pg-test", actor_source="test", actor_verified=True,
                idempotency_key=f"pg-label-campaign-{suffix}",
            )
            self.assertEqual(label_campaign["campaign"]["purpose"], "labeling")
            self.assertFalse(label_campaign["campaign"]["evaluation_run_id"])
            group = database.create_campaign_group(
                name=f"S5 Run group {suffix}", purpose="model_review",
                campaigns=[
                    {
                        "purpose": "model_review", "lifecycle": "draft",
                        "campaign_name": f"S5 review {run_id[:8]}",
                        "evaluation_run_id": run_id, "workset_id": workset_id,
                        "references": references,
                        "members": [{"issue_id": issue_id, "assignees": ["reviewer"]}],
                    }
                    for run_id in run_ids
                ],
                actor="pg-test", actor_source="test", actor_verified=True,
                idempotency_key=f"pg-model-review-group-{suffix}",
            )
            self.assertEqual(group["purpose"], "model_review")
            self.assertEqual(len(group["campaigns"]), 2)
            self.assertEqual({item["campaign"]["workset_id"] for item in group["campaigns"]}, {workset_id})

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
            self.assertEqual(int(migration_count), 49)
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
            database.apply_gt_sync_snapshot(
                scope=scope,
                rows=[{"issue_id": issue_id, "gt_label": "正确触发"} for issue_id in issue_ids],
                source_name="test", source_view_id=1000, source_field="gt",
                trigger="test", requested_by="pg-test", requested_by_source="test",
                requested_by_verified=True, expected_issue_ids=issue_ids,
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

    def test_run_collection_pairwise_shadow_and_pg_context_reuse(self) -> None:
        database = Database(
            os.environ["DASHBOARD_TEST_POSTGRES_URL"],
            postgres_migrations_dir=(
                Path(__file__).resolve().parents[1] / "migrations" / "postgres"
            ),
            pool_size=6,
        )
        other = Database(
            os.environ["DASHBOARD_TEST_POSTGRES_URL"],
            postgres_migrations_dir=(
                Path(__file__).resolve().parents[1] / "migrations" / "postgres"
            ),
            pool_size=6,
        )
        suffix = uuid4().hex
        scope = f"pg_shadow_{suffix}"
        issue_rows = [
            {"issue_id": f"pg_shadow_{suffix}_{index}", "gt_label": label}
            for index, label in enumerate(("正确触发", "误触发", "无需协助", "正确触发"))
        ]
        try:
            database.init()
            database.upsert_issues(issue_rows, source="pg-shadow", replace_gt=True, baseline_scope=scope)
            snapshot = database.apply_gt_sync_snapshot(
                scope=scope, rows=issue_rows, source_name="test",
                source_view_id=1000, source_field="gt", trigger="test",
                requested_by="pg-test", requested_by_source="test",
                requested_by_verified=True,
                expected_issue_ids=[item["issue_id"] for item in issue_rows],
            )
            baseline, _ = database.import_model_run(
                name=f"shadow-baseline-{suffix}", source_name=f"shadow-b-{suffix}",
                source_sha256=hashlib.sha256(f"shadow-b-{suffix}".encode()).hexdigest(),
                metadata={}, rows=[
                    {"issue_id": issue_rows[0]["issue_id"], "model_label": "正确触发"},
                    {"issue_id": issue_rows[1]["issue_id"], "model_label": "正确触发"},
                ],
            )
            candidate, _ = database.import_model_run(
                name=f"shadow-candidate-{suffix}", source_name=f"shadow-c-{suffix}",
                source_sha256=hashlib.sha256(f"shadow-c-{suffix}".encode()).hexdigest(),
                metadata={}, rows=[
                    {"issue_id": issue_rows[0]["issue_id"], "model_label": "正确触发"},
                    {"issue_id": issue_rows[2]["issue_id"], "model_label": "无需协助"},
                ],
            )
            collection = database.create_run_collection(
                name=f"PG shadow {suffix}",
                members=[{"run_id": baseline["id"], "is_reference": True}, candidate["id"]],
            )
            kwargs = dict(
                collection_id=collection["id"], baseline_scopes=[scope],
                comparison_reference_run_id=baseline["id"],
                actor="pg-test", actor_source="test", actor_verified=True,
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda db: db.create_run_evaluation(**kwargs), [database, other]))
            self.assertEqual(results[0]["id"], results[1]["id"])
            evaluation = results[0]
            legacy = database.compare_model_runs(
                baseline_run_id=baseline["id"], candidate_run_id=candidate["id"],
                baseline_scopes=[scope], page_size=100,
            )
            self.assertEqual(
                legacy["summary"]["total_count"],
                evaluation["summary"]["pairwise_union_denominator"],
            )
            self.assertEqual(
                legacy["summary"]["transition_counts"],
                evaluation["summary"]["runs"][1]["transitions_vs_reference"],
            )
            with database.connect() as conn:
                duplicate_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM run_evaluation_contexts WHERE context_sha256 = ?",
                    (evaluation["context_sha256"],),
                ).fetchone()["count"]
            self.assertEqual(int(duplicate_count), 1)
            self.assertEqual(snapshot["active_gt_snapshot"]["id"], evaluation["reference"]["id"])
        finally:
            database.close()
            other.close()


if __name__ == "__main__":
    unittest.main()
