from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.snapshots import _snapshot_membership_sha
from ra_triage_dashboard.scripts import backfill_gt_label_snapshots as backfill


class GtLabelSnapshotBackfillTest(unittest.TestCase):
    def test_dry_run_is_read_only_and_apply_reuses_snapshot_without_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "backfill.sqlite3"
            db = Database(path)
            db.init()
            db.upsert_issues(
                [{"issue_id": "a", "gt_label": "正确触发"}],
                source="test",
                replace_gt=True,
                baseline_scope="scope",
            )
            db.apply_gt_sync_snapshot(
                scope="scope",
                rows=[{"issue_id": "a", "gt_label": "正确触发"}],
                source_name="Trail",
                source_view_id=1000,
                source_field="ra_merge_result",
                trigger="test",
                requested_by="tester",
                requested_by_source="test",
                requested_by_verified=False,
                expected_issue_ids=["a"],
            )
            # Model an upgraded legacy database whose sync state is ready but
            # whose S2 active reference has not yet been backfilled.
            with db.connect() as conn:
                conn.execute("DELETE FROM gt_snapshot_active WHERE baseline_scope = 'scope'")
                conn.execute("DELETE FROM gt_snapshot_items")
                conn.execute("DELETE FROM gt_snapshots")
            self.assertIsNone(db.get_active_gt_snapshot("scope"))
            revision_before = db.change_revision()

            url = f"sqlite:///{path}"
            settings = SimpleNamespace(database_url=url, postgres_migrations_dir=None)
            entry = SimpleNamespace(
                scope="scope",
                gt_mode="strict",
                expected_count=1,
                members_sha256=_snapshot_membership_sha(["a"]),
            )
            args = argparse.Namespace(
                database_url=url,
                scopes=["scope"],
                apply=False,
                created_by="tester",
                created_by_source="migration",
            )

            def run(current_args):
                output = io.StringIO()
                with patch.object(backfill.Settings, "from_env", return_value=settings):
                    with patch.object(backfill, "Database", return_value=db):
                        with patch.object(backfill, "parse_args", return_value=current_args):
                            with patch.object(
                                backfill,
                                "baseline_registry",
                                SimpleNamespace(entries=[entry]),
                            ):
                                with patch.object(
                                    db, "init", side_effect=AssertionError("init must not run")
                                ):
                                    with redirect_stdout(output):
                                        status = backfill.main()
                return status, json.loads(output.getvalue())

            dry_status, dry_report = run(args)
            self.assertEqual(dry_status, 0)
            self.assertEqual(dry_report["scopes"][0]["action"], "dry_run")
            self.assertIsNone(db.get_active_gt_snapshot("scope"))
            self.assertEqual(db.change_revision(), revision_before)

            args.apply = True
            first_status, first_report = run(args)
            second_status, second_report = run(args)
            self.assertEqual((first_status, second_status), (0, 0))
            first_id = first_report["scopes"][0]["snapshot"]["id"]
            second_id = second_report["scopes"][0]["snapshot"]["id"]
            self.assertEqual(first_id, second_id)
            self.assertEqual(db.get_active_gt_snapshot("scope")["id"], first_id)
            db.close()


if __name__ == "__main__":
    unittest.main()
