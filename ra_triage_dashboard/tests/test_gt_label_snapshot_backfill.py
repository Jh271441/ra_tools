from __future__ import annotations

import argparse
import hashlib
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
    @staticmethod
    def _source_file(path: Path, issue_id: str = "cn123") -> tuple[str, str]:
        path.write_text(
            json.dumps({
                "schema_version": "capture-workset-v1",
                "expected_count": 1,
                "rows": [{"issue_id": issue_id, "gt_label": "正确触发"}],
            }),
            encoding="utf-8",
        )
        return hashlib.sha256(path.read_bytes()).hexdigest(), issue_id

    def _database(self, path: Path, issue_id: str) -> Database:
        db = Database(path)
        db.init()
        db.upsert_issues(
            [{"issue_id": issue_id, "gt_label": "正确触发"}],
            source="test",
            replace_gt=True,
            baseline_scope="scope",
        )
        db.apply_gt_sync_snapshot(
            scope="scope",
            rows=[{"issue_id": issue_id, "gt_label": "正确触发"}],
            source_name="Trail",
            source_view_id=1000,
            source_field="ra_merge_result",
            trigger="test",
            requested_by="tester",
            requested_by_source="test",
            requested_by_verified=False,
            expected_issue_ids=[issue_id],
        )
        with db.connect() as conn:
            conn.execute("DELETE FROM gt_snapshot_active WHERE baseline_scope = 'scope'")
            conn.execute("DELETE FROM gt_snapshot_items")
            conn.execute("DELETE FROM gt_snapshots")
        return db

    @staticmethod
    def _entry(path: Path, source_sha: str, *, configured_sha: str | None = None):
        return SimpleNamespace(
            scope="scope",
            gt_mode="strict",
            expected_count=1,
            members_sha256=(configured_sha if configured_sha is not None else source_sha),
            loader="capture_workset",
            xlsx=path,
            dataset="",
        )

    def _run_main(self, db: Database, url: str, args, entries):
        output = io.StringIO()
        settings = SimpleNamespace(database_url=url, postgres_migrations_dir=None)
        with patch.object(backfill.Settings, "from_env", return_value=settings):
            with patch.object(backfill, "Database", return_value=db):
                with patch.object(backfill, "parse_args", return_value=args):
                    with patch.object(backfill, "baseline_registry", SimpleNamespace(entries=entries)):
                        with patch.object(db, "init", side_effect=AssertionError("init must not run")):
                            with redirect_stdout(output):
                                status = backfill.main()
        return status, json.loads(output.getvalue())

    @staticmethod
    def _args(url: str, *, apply: bool) -> argparse.Namespace:
        return argparse.Namespace(
            database_url=url,
            scopes=["scope"],
            apply=apply,
            created_by="tester",
            created_by_source="migration",
        )

    def test_source_file_and_membership_hashes_are_separate_and_apply_reuses_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "backfill.sqlite3"
            source_path = root / "capture-workset.json"
            source_sha, issue_id = self._source_file(source_path)
            expected_membership_sha = _snapshot_membership_sha([issue_id])
            self.assertNotEqual(source_sha, expected_membership_sha)
            db = self._database(db_path, issue_id)
            self.addCleanup(db.close)
            url = f"sqlite:///{db_path}"
            entry = self._entry(source_path, source_sha)
            revision_before = db.change_revision()

            dry_status, dry_report = self._run_main(
                db, url, self._args(url, apply=False), [entry]
            )
            self.assertEqual(dry_status, 0)
            scope_report = dry_report["scopes"][0]
            self.assertTrue(scope_report["source_file_sha_matches"])
            self.assertEqual(scope_report["configured_source_file_sha256"], source_sha)
            self.assertEqual(scope_report["actual_source_file_sha256"], source_sha)
            self.assertEqual(scope_report["expected_membership_sha256"], expected_membership_sha)
            self.assertEqual(scope_report["actual_membership_sha256"], expected_membership_sha)
            self.assertTrue(scope_report["membership_matches"])
            self.assertEqual(scope_report["missing_issue_count"], 0)
            self.assertEqual(scope_report["extra_issue_count"], 0)
            self.assertIsNone(db.get_active_gt_snapshot("scope"))
            self.assertEqual(db.change_revision(), revision_before)

            bad_hash_entry = self._entry(source_path, source_sha, configured_sha="0" * 64)
            bad_hash_status, bad_hash_report = self._run_main(
                db, url, self._args(url, apply=True), [bad_hash_entry]
            )
            self.assertEqual(bad_hash_status, 2)
            self.assertFalse(bad_hash_report["scopes"][0]["source_file_sha_matches"])
            self.assertIsNone(db.get_active_gt_snapshot("scope"))

            db.upsert_issues(
                [{"issue_id": "cn999", "gt_label": "正确触发"}],
                source="membership-mismatch-fixture",
                replace_gt=True,
                baseline_scope="scope",
            )
            mismatch_status, mismatch_report = self._run_main(
                db, url, self._args(url, apply=True), [entry]
            )
            report = mismatch_report["scopes"][0]
            self.assertEqual(mismatch_status, 2)
            self.assertFalse(report["membership_matches"])
            self.assertEqual(report["missing_issue_count"], 0)
            self.assertEqual(report["extra_issue_count"], 1)
            self.assertEqual(report["extra_issue_ids_sample"], ["cn999"])
            self.assertIsNone(db.get_active_gt_snapshot("scope"))
            with db.connect() as conn:
                conn.execute("DELETE FROM issues WHERE issue_id = 'cn999'")

            first_status, first_report = self._run_main(
                db, url, self._args(url, apply=True), [entry]
            )
            second_status, second_report = self._run_main(
                db, url, self._args(url, apply=True), [entry]
            )
            self.assertEqual((first_status, second_status), (0, 0))
            first_id = first_report["scopes"][0]["snapshot_id"]
            second_id = second_report["scopes"][0]["snapshot_id"]
            self.assertEqual(first_id, second_id)
            self.assertEqual(db.get_active_gt_snapshot("scope")["id"], first_id)

    def test_missing_loader_members_refuse_backfill_even_when_counts_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "missing-member.sqlite3"
            source_path = root / "capture-workset.json"
            source_sha, _ = self._source_file(source_path, "cn123")
            db = self._database(db_path, "cn999")
            self.addCleanup(db.close)
            url = f"sqlite:///{db_path}"
            entry = self._entry(source_path, source_sha)
            for apply in (False, True):
                status, payload = self._run_main(db, url, self._args(url, apply=apply), [entry])
                report = payload["scopes"][0]
                self.assertEqual(status, 2)
                self.assertEqual(report["missing_issue_count"], 1)
                self.assertEqual(report["extra_issue_count"], 1)
                self.assertEqual(report["missing_issue_ids_sample"], ["cn123"])
                self.assertEqual(report["extra_issue_ids_sample"], ["cn999"])
                self.assertIsNone(db.get_active_gt_snapshot("scope"))


if __name__ == "__main__":
    unittest.main()
