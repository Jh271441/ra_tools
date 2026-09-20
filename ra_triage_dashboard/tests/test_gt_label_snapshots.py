from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.snapshots import SnapshotConflictError


class GtLabelSnapshotsTest(unittest.TestCase):
    def make_db(self) -> Database:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = Database(Path(temp.name) / "snapshots.sqlite")
        db.init()
        return db

    def add_scope(self, db: Database, scope: str, rows: list[tuple[str, str]]) -> None:
        db.upsert_issues(
            [{"issue_id": issue_id, "gt_label": label} for issue_id, label in rows],
            source="snapshot-test",
            replace_gt=True,
            baseline_scope=scope,
        )

    def sync(self, db: Database, scope: str, rows: list[dict], sparse: bool = False) -> dict:
        ids = db.baseline_issue_ids(scope=scope)
        return db.apply_gt_sync_snapshot(
            scope=scope,
            rows=rows,
            source_name="Trail",
            source_view_id=1000,
            source_field="ra_merge_result",
            trigger="test",
            requested_by="tester",
            requested_by_source="test",
            requested_by_verified=False,
            expected_issue_ids=ids,
            allow_sparse=sparse,
        )

    def test_strict_snapshot_reuses_identical_content_and_changed_content_is_new(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发"), ("b", "误触发")])
        rows = [
            {"issue_id": "a", "gt_label": "正确触发"},
            {"issue_id": "b", "gt_label": "误触发"},
        ]
        first = self.sync(db, "scope", rows)
        second = self.sync(db, "scope", rows)
        self.assertEqual(first["active_gt_snapshot"]["id"], second["active_gt_snapshot"]["id"])
        self.assertEqual(first["active_gt_snapshot"]["member_count"], 2)
        self.assertEqual(first["active_gt_snapshot"]["valid_label_count"], 2)
        changed = self.sync(
            db,
            "scope",
            [
                {"issue_id": "a", "gt_label": "无需协助"},
                {"issue_id": "b", "gt_label": "误触发"},
            ],
        )
        self.assertNotEqual(first["active_gt_snapshot"]["id"], changed["active_gt_snapshot"]["id"])
        self.assertEqual(db.get_active_gt_snapshot("scope")["id"], changed["active_gt_snapshot"]["id"])
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM gt_snapshots").fetchone()["count"]
        self.assertEqual(count, 2)

    def test_sparse_snapshot_keeps_full_membership_and_clears_valid_label(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发"), ("b", "误触发")])
        self.sync(
            db,
            "scope",
            [
                {"issue_id": "a", "gt_label": "正确触发"},
                {"issue_id": "b", "gt_label": "误触发"},
            ],
            sparse=True,
        )
        next_snapshot = self.sync(
            db,
            "scope",
            [{"issue_id": "a", "gt_label": "正确触发"}],
            sparse=True,
        )["active_gt_snapshot"]
        self.assertEqual(next_snapshot["member_count"], 2)
        self.assertEqual(next_snapshot["valid_label_count"], 1)
        detail = db.get_gt_snapshot(next_snapshot["id"], include_items=True, item_limit=10)
        self.assertEqual({item["issue_id"] for item in detail["items"]}, {"a", "b"})
        self.assertEqual(
            {item["issue_id"]: item["gt_label"] for item in detail["items"]},
            {"a": "正确触发", "b": ""},
        )
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT gt_label FROM issues WHERE issue_id='b'").fetchone()["gt_label"], None)

    def test_membership_and_strict_empty_label_are_rejected_without_mutation(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发"), ("b", "误触发")])
        first = self.sync(
            db,
            "scope",
            [{"issue_id": "a", "gt_label": "正确触发"}, {"issue_id": "b", "gt_label": "误触发"}],
        )
        with self.assertRaises(ValueError):
            self.sync(db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}])
        with self.assertRaises(ValueError):
            self.sync(
                db,
                "scope",
                [{"issue_id": "a", "gt_label": ""}, {"issue_id": "b", "gt_label": "误触发"}],
            )
        self.assertEqual(db.get_active_gt_snapshot("scope")["id"], first["active_gt_snapshot"]["id"])

    def test_active_snapshot_optimistic_conflict(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        first = self.sync(db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}])["active_gt_snapshot"]
        second = self.sync(db, "scope", [{"issue_id": "a", "gt_label": "误触发"}])["active_gt_snapshot"]
        with self.assertRaises(SnapshotConflictError):
            db.activate_gt_snapshot(
                baseline_scope="scope",
                snapshot_id=first["id"],
                expected_previous_snapshot_id=first["id"],
                activated_by="tester",
            )
        self.assertEqual(db.get_active_gt_snapshot("scope")["id"], second["id"])

    def test_label_result_snapshot_is_complete_reusable_and_immutable(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        workset = db.create_review_workset(
            baseline_scope="scope", issue_ids=["a"], created_by="admin"
        )
        db.create_label_revision(
            issue_id="a", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="first", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
        )
        first = db.create_label_result_snapshot(workset_id=workset["id"], created_by="admin")
        reused = db.create_label_result_snapshot(workset_id=workset["id"], created_by="admin")
        self.assertEqual(first["id"], reused["id"])
        self.assertEqual(first["coverage_status"], "complete")
        self.assertEqual(first["resolved_count"], 1)
        db.create_label_revision(
            issue_id="a", expected_output="误触发", tags=[], evidence_gaps=[],
            rationale="second", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
            expected_previous_revision_id=1,
        )
        changed = db.create_label_result_snapshot(workset_id=workset["id"], created_by="admin")
        self.assertNotEqual(first["id"], changed["id"])
        self.assertEqual(db.get_label_result_snapshot(first["id"], include_items=True)["items"][0]["expected_output"], "正确触发")

    def test_label_result_partial_requires_explicit_flag(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        workset = db.create_review_workset(baseline_scope="scope", issue_ids=["a"], created_by="admin")
        with self.assertRaises(ValueError):
            db.create_label_result_snapshot(workset_id=workset["id"], created_by="admin")
        snapshot = db.create_label_result_snapshot(
            workset_id=workset["id"], created_by="admin", allow_partial=True
        )
        self.assertEqual(snapshot["coverage_status"], "partial")
        self.assertEqual(snapshot["unknown_count"], 1)

    def test_legacy_database_without_active_snapshot_is_readable(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        self.assertIsNone(db.get_active_gt_snapshot("scope"))
        self.assertEqual(db.active_gt_snapshots(["scope"]), [])

    def test_gt_export_binds_source_snapshot_and_reconciles_against_new_active_snapshot(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "误触发")])
        self.sync(db, "scope", [{"issue_id": "a", "gt_label": "误触发"}])
        db.create_label_revision(
            issue_id="a", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="needs GT update", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
        )
        preview = db.create_label_gt_export_preview(
            baseline_scopes=["scope"], created_by="alice",
            created_by_source="test", created_by_verified=False,
        )
        self.assertTrue(preview["source_gt_snapshot_id"])
        self.assertEqual(preview["source_gt_snapshot_ids"]["scope"], preview["source_gt_snapshot_id"])
        db.mark_label_gt_exported(batch_id=preview["id"], file_sha256="f" * 64)
        self.sync(db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}])
        reconciled = db.reconcile_label_gt_export_batch(preview["id"])
        self.assertEqual(reconciled["reconcile_status"], "matched")
        self.assertEqual(reconciled["reconcile_counts"]["matched"], 1)

        db.create_label_revision(
            issue_id="a", expected_output="无需协助", tags=[], evidence_gaps=[],
            rationale="second GT update", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
            expected_previous_revision_id=1,
        )
        preview_again = db.create_label_gt_export_preview(
            baseline_scopes=["scope"], created_by="alice",
            created_by_source="test", created_by_verified=False,
        )
        db.mark_label_gt_exported(batch_id=preview_again["id"], file_sha256="e" * 64)
        self.sync(db, "scope", [{"issue_id": "a", "gt_label": "误触发"}])
        changed = db.reconcile_label_gt_export_batch(preview_again["id"])
        self.assertEqual(changed["reconcile_status"], "changed_again")
        self.assertEqual(changed["reconcile_counts"]["changed_again"], 1)

    def test_large_membership_is_batch_safe(self) -> None:
        db = self.make_db()
        rows = [(f"issue-{index:05d}", "正确触发") for index in range(5205)]
        self.add_scope(db, "scope", rows)
        statements: list[str] = []
        original = db.connect

        @contextmanager
        def traced_connect():
            with original() as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        db.connect = traced_connect
        snapshot = self.sync(
            db,
            "scope",
            [{"issue_id": issue_id, "gt_label": label} for issue_id, label in rows],
        )["active_gt_snapshot"]
        self.assertEqual(snapshot["member_count"], 5205)
        self.assertEqual(snapshot["valid_label_count"], 5205)
        select_statements = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
        ]
        self.assertLess(len(select_statements), 20)
