from __future__ import annotations

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from ra_triage_dashboard.app.db import Database


DISPOSABLE_POSTGRES_URL = os.getenv("DASHBOARD_TEST_DISPOSABLE_POSTGRES_URL", "").strip()


@unittest.skipUnless(
    DISPOSABLE_POSTGRES_URL,
    "set DASHBOARD_TEST_DISPOSABLE_POSTGRES_URL to a disposable PostgreSQL database",
)
class GtSnapshotPostgresConcurrencyTest(unittest.TestCase):
    def test_same_scope_writers_serialize_pointer_overlay_and_sync_state(self) -> None:
        migrations = Path(__file__).resolve().parents[1] / "migrations" / "postgres"
        db_a = Database(
            DISPOSABLE_POSTGRES_URL,
            postgres_migrations_dir=migrations,
            pool_size=2,
        )
        db_b = Database(
            DISPOSABLE_POSTGRES_URL,
            postgres_migrations_dir=migrations,
            pool_size=2,
        )
        self.addCleanup(db_a.close)
        self.addCleanup(db_b.close)
        db_a.init()

        token = uuid4().hex
        scope = f"snapshot-lock-{token}"
        issue_id = f"snapshot-lock-issue-{token}"
        db_a.upsert_issues(
            [{"issue_id": issue_id, "gt_label": "正确触发"}],
            source="disposable-postgres-concurrency-test",
            replace_gt=True,
            baseline_scope=scope,
        )
        barrier = threading.Barrier(2)

        def apply(database: Database, label: str, source_name: str) -> dict:
            barrier.wait(timeout=20)
            return database.apply_gt_sync_snapshot(
                scope=scope,
                rows=[{"issue_id": issue_id, "gt_label": label}],
                source_name=source_name,
                source_view_id=1000,
                source_field="ra_merge_result",
                trigger="disposable-concurrency-test",
                requested_by="test",
                requested_by_source="test",
                requested_by_verified=False,
                expected_issue_ids=[issue_id],
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(apply, db_a, "正确触发", "test-a"),
                pool.submit(apply, db_b, "误触发", "test-b"),
            ]
            for future in futures:
                future.result(timeout=60)

        active = db_a.get_active_gt_snapshot(scope)
        self.assertIsNotNone(active)
        item = db_a.get_gt_snapshot(active["id"], include_items=True)["items"][0]
        with db_a.connect() as conn:
            issue = conn.execute(
                "SELECT gt_label FROM issues WHERE issue_id = ?",
                (issue_id,),
            ).fetchone()
        overlay = db_a.gt_sync_overlay(scope)[issue_id]
        sync_state = db_a.gt_sync_status(scope)
        self.assertEqual(item["gt_label"], issue["gt_label"])
        self.assertEqual(item["gt_label"], overlay["gt_label"])
        self.assertEqual(active["content_sha256"], sync_state["source_sha256"])
        self.assertIn(item["gt_label"], {"正确触发", "误触发"})


if __name__ == "__main__":
    unittest.main()
