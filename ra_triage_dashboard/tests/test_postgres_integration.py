from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database


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
            self.assertGreater(database.change_revision(), initial_revision)
            overview = database.overview(
                baseline_scope="postgres_test", model_run_id=run["id"]
            )
            self.assertEqual(overview["issues"], 1)
            self.assertEqual(overview["model_failures"], 1)
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
