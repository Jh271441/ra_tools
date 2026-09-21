from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from ra_triage_dashboard.app.auth import SessionIdentity
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import labeling as labeling_router


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

    def test_active_gt_reference_contains_activation_and_latest_observation(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        active = self.sync(
            db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}]
        )["active_gt_snapshot"]
        self.assertTrue(active["activation"]["activated_at"])
        self.assertEqual(active["activation"]["activation_reason"], "gt_sync")
        self.assertEqual(active["observation"]["status"], "ready")
        self.assertEqual(active["observation"]["source_sha256"], active["content_sha256"])
        by_id = db.get_gt_snapshot(active["id"])
        self.assertEqual(by_id["activation"], active["activation"])
        self.assertEqual(by_id["observation"]["last_checked_at"], active["observation"]["last_checked_at"])

    def test_metadata_only_gt_sync_reuses_content_and_refreshes_observation(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        with patch(
            "ra_triage_dashboard.app.db_parts.gt_sync.utc_now",
            return_value="2026-09-20T10:00:00+00:00",
        ):
            first = self.sync(
                db,
                "scope",
                [{
                    "issue_id": "a",
                    "gt_label": "正确触发",
                    "source_updated_at": "2026-09-01T10:00:00Z",
                    "source_updated_by": "alice",
                }],
            )["active_gt_snapshot"]
        first_item = db.get_gt_snapshot(first["id"], include_items=True)["items"][0]

        with patch(
            "ra_triage_dashboard.app.db_parts.gt_sync.utc_now",
            return_value="2026-09-20T10:00:01+00:00",
        ):
            second = self.sync(
                db,
                "scope",
                [{
                    "issue_id": "a",
                    "gt_label": "正确触发",
                    "source_updated_at": "2026-09-02T11:00:00Z",
                    "source_updated_by": "bob",
                }],
            )["active_gt_snapshot"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(
            first["observation"]["last_checked_at"],
            second["observation"]["last_checked_at"],
        )
        self.assertEqual(
            second["observation"]["source_updated_at"], "2026-09-02T11:00:00Z"
        )
        self.assertEqual(second["observation"]["source_updated_by"], "bob")
        second_item = db.get_gt_snapshot(second["id"], include_items=True)["items"][0]
        self.assertEqual(second_item["source_updated_at"], first_item["source_updated_at"])
        self.assertEqual(second_item["source_updated_by"], first_item["source_updated_by"])
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM gt_snapshots").fetchone()["count"]
        self.assertEqual(count, 1)

    def test_gt_snapshot_identity_changes_for_contract_or_membership_changes(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发"), ("b", "误触发")])
        first = self.sync(
            db,
            "scope",
            [
                {"issue_id": "a", "gt_label": "正确触发"},
                {"issue_id": "b", "gt_label": "误触发"},
            ],
        )["active_gt_snapshot"]
        contract_changed = db.apply_gt_sync_snapshot(
            scope="scope",
            rows=[
                {"issue_id": "a", "gt_label": "正确触发"},
                {"issue_id": "b", "gt_label": "误触发"},
            ],
            source_name="Trail",
            source_view_id=1001,
            source_field="ra_merge_result",
            trigger="test",
            requested_by="tester",
            requested_by_source="test",
            requested_by_verified=False,
            expected_issue_ids=["a", "b"],
        )["active_gt_snapshot"]
        self.assertNotEqual(first["id"], contract_changed["id"])

        db.upsert_issues(
            [{"issue_id": "c", "gt_label": "无需协助"}],
            source="snapshot-test-membership-change",
            replace_gt=True,
            baseline_scope="scope",
        )
        membership_changed = self.sync(
            db,
            "scope",
            [
                {"issue_id": "a", "gt_label": "正确触发"},
                {"issue_id": "b", "gt_label": "误触发"},
                {"issue_id": "c", "gt_label": "无需协助"},
            ],
        )["active_gt_snapshot"]
        self.assertNotEqual(contract_changed["id"], membership_changed["id"])
        self.assertEqual(membership_changed["member_count"], 3)

    def test_postgres_scope_lock_and_active_pointer_both_use_for_update(self) -> None:
        db = self.make_db()
        db.backend = "postgresql"

        class Cursor:
            @staticmethod
            def fetchone():
                return {"baseline_scope": "scope", "snapshot_id": "snapshot"}

        class RecordingConnection:
            def __init__(self):
                self.statements = []

            def execute(self, sql, params):
                self.statements.append((sql, params))
                return Cursor()

        connection = RecordingConnection()
        db._ensure_gt_sync_scope_lock_with_conn(connection, "scope")
        db._lock_gt_snapshot_active_with_conn(connection, "scope")
        self.assertEqual(len(connection.statements), 3)
        self.assertIn("INSERT INTO gt_sync_state", connection.statements[0][0])
        self.assertIn("FROM gt_sync_state", connection.statements[1][0])
        self.assertIn("FOR UPDATE", connection.statements[1][0])
        self.assertIn("FROM gt_snapshot_active", connection.statements[2][0])
        self.assertIn("FOR UPDATE", connection.statements[2][0])

    def test_gt_sync_and_cutover_lock_scope_before_reading_issue_membership(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        statements: list[str] = []
        original_connect = db.connect

        @contextmanager
        def traced_connect():
            with original_connect() as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        db.connect = traced_connect
        self.sync(db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}])
        lock_index = next(
            index
            for index, sql in enumerate(statements)
            if "SELECT baseline_scope FROM gt_sync_state" in sql
        )
        issue_read_index = next(
            index
            for index, sql in enumerate(statements)
            if "SELECT issue_id, gt_label" in sql and "FROM issues" in sql
        )
        self.assertLess(lock_index, issue_read_index)

        statements.clear()
        db.create_gt_snapshot_from_current(
            scope="scope",
            gt_mode="strict",
            source_name="Trail",
            source_view_id=1000,
            source_field="ra_merge_result",
        )
        lock_index = next(
            index
            for index, sql in enumerate(statements)
            if "SELECT baseline_scope FROM gt_sync_state" in sql
        )
        issue_read_index = next(
            index
            for index, sql in enumerate(statements)
            if "SELECT issue_id, gt_label, gt_source" in sql and "FROM issues" in sql
        )
        self.assertLess(lock_index, issue_read_index)

    def test_gt_sync_rolls_back_active_pointer_overlay_and_state_together(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        first = self.sync(
            db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}]
        )["active_gt_snapshot"]
        previous_state = db.gt_sync_status("scope")
        with db.connect() as conn:
            conn.execute(
                """
                CREATE TRIGGER reject_snapshot_state_update
                BEFORE UPDATE ON gt_sync_state
                WHEN NEW.baseline_scope = 'scope'
                 AND NEW.source_sha256 <> OLD.source_sha256
                BEGIN
                    SELECT RAISE(ABORT, 'snapshot rollback fixture');
                END
                """
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.sync(db, "scope", [{"issue_id": "a", "gt_label": "误触发"}])
        self.assertEqual(db.get_active_gt_snapshot("scope")["id"], first["id"])
        self.assertEqual(db.get_issue("a")["gt_label"], "正确触发")
        self.assertEqual(db.gt_sync_status("scope")["source_sha256"], previous_state["source_sha256"])
        self.assertEqual(db.gt_sync_overlay("scope")["a"]["gt_label"], "正确触发")

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

    def test_label_snapshot_hash_tracks_resolution_and_new_pending_source_provenance(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发")])
        self.sync(db, "scope", [{"issue_id": "a", "gt_label": "正确触发"}])
        workset = db.create_review_workset(
            baseline_scope="scope", issue_ids=["a"], created_by="admin"
        )
        task = db.create_labeling_task(
            workset_id=workset["id"],
            assignments=[{"name": "alice", "issue_ids": ["a"]}],
            created_by="admin",
            seed=1,
            reviewers_per_issue=1,
            overlap_ratio=0,
        )
        revision = db.create_label_revision(
            issue_id="a", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="same label", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
            task_id=task["id"],
        )
        revision_id = int(revision["id"])
        case_id = str(revision["label_case_id"])
        source_sha = hashlib.sha256(str(revision_id).encode("utf-8")).hexdigest()
        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO label_resolutions (
                    label_case_id, method, result_revision_id,
                    source_revision_ids_json, source_fingerprint, supersedes_id,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, 'adjudication', ?, ?, ?, NULL, 'admin', 'test', 0, '2026-01-01T00:00:00Z')
                """,
                (case_id, revision_id, json.dumps([revision_id]), source_sha),
            )
            first_resolution_id = int(cursor.lastrowid)
        first = db.create_label_result_snapshot(workset_id=workset["id"], created_by="admin")
        first_saved = db.get_label_result_snapshot(first["id"], include_items=True, include_sources=True)

        with db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO label_resolutions (
                    label_case_id, method, result_revision_id,
                    source_revision_ids_json, source_fingerprint, supersedes_id,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, 'adjudication', ?, ?, ?, ?, 'admin', 'test', 0, '2026-01-02T00:00:00Z')
                """,
                (case_id, revision_id, json.dumps([revision_id]), source_sha, first_resolution_id),
            )
            second_resolution_id = int(cursor.lastrowid)
        second = db.create_label_result_snapshot(workset_id=workset["id"], created_by="admin")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["resolved_count"], second["resolved_count"])
        self.assertEqual(first_saved["items"], db.get_label_result_snapshot(first["id"], include_items=True)["items"])
        self.assertEqual(
            {item["resolution_id"] for item in first_saved["sources"] if item["resolution_id"]},
            {first_resolution_id},
        )
        self.assertEqual(
            {item["task_id"] for item in first_saved["sources"]},
            {task["id"]},
        )
        self.assertEqual(
            {item["source_role"] for item in first_saved["sources"]},
            {"case", "resolution_input", "resolution_result"},
        )
        second_sources = db.get_label_result_snapshot(second["id"], include_sources=True)["sources"]
        self.assertIn(second_resolution_id, {item["resolution_id"] for item in second_sources})

        db.ensure_label_case(
            issue_id="a", source_run_id="empty-pending-source", allow_missing_source_run=True
        )
        partial = db.create_label_result_snapshot(
            workset_id=workset["id"], created_by="admin", allow_partial=True
        )
        self.assertNotEqual(second["id"], partial["id"])
        self.assertEqual(partial["pending_count"], 1)
        self.assertEqual(db.get_label_result_snapshot(first["id"], include_items=True)["items"], first_saved["items"])

    def test_label_snapshot_service_rejects_source_case_from_another_issue_atomically(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发"), ("b", "正确触发")])
        workset = db.create_review_workset(
            baseline_scope="scope", issue_ids=["a"], created_by="admin"
        )
        wrong_revision = db.create_label_revision(
            issue_id="b", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="source for b", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
        )
        wrong_case_id = wrong_revision["label_case_id"]
        tampered_projection = {
            "a": {
                "state": "resolved",
                "expected_output": "正确触发",
                "method": "single",
                "gt_relation": "matches_gt",
                "source_revision_ids": [wrong_revision["id"]],
                "sources": [{
                    "label_case_id": wrong_case_id,
                    "task_id": "",
                    "source_revision_ids": [wrong_revision["id"]],
                    "adjudication": None,
                    "resolution_id": None,
                }],
            }
        }
        with patch.object(db, "project_issue_label_states", return_value=tampered_projection):
            with self.assertRaisesRegex(ValueError, "does not match issue/scope/task"):
                db.create_label_result_snapshot(
                    workset_id=workset["id"], created_by="admin"
                )
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS n FROM label_result_snapshots").fetchone()["n"],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) AS n FROM label_result_snapshot_sources").fetchone()["n"],
                0,
            )

    def test_label_snapshot_service_rejects_resolution_from_another_case(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "正确触发"), ("b", "正确触发")])
        workset = db.create_review_workset(
            baseline_scope="scope", issue_ids=["a"], created_by="admin"
        )
        case_a = db.ensure_label_case(issue_id="a")
        revision_b = db.create_label_revision(
            issue_id="b", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="source for b", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
        )
        with db.connect() as conn:
            resolution = conn.execute(
                """
                INSERT INTO label_resolutions (
                    label_case_id, method, result_revision_id,
                    source_revision_ids_json, source_fingerprint, supersedes_id,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, 'adjudication', ?, '[]', 'fixture', NULL,
                          'admin', 'test', 0, '2026-09-20T00:00:00Z')
                """,
                (revision_b["label_case_id"], revision_b["id"]),
            )
            resolution_id = int(resolution.lastrowid)
        tampered_projection = {
            "a": {
                "state": "resolved",
                "expected_output": "正确触发",
                "method": "adjudication",
                "gt_relation": "matches_gt",
                "source_revision_ids": [revision_b["id"]],
                "sources": [{
                    "label_case_id": case_a["id"],
                    "task_id": "",
                    "source_revision_ids": [revision_b["id"]],
                    "adjudication": {
                        "id": resolution_id,
                        "result_revision_id": revision_b["id"],
                        "source_revision_ids": [],
                    },
                    "resolution_id": resolution_id,
                }],
            }
        }
        with patch.object(db, "project_issue_label_states", return_value=tampered_projection):
            with self.assertRaisesRegex(ValueError, "resolution does not belong"):
                db.create_label_result_snapshot(
                    workset_id=workset["id"], created_by="admin"
                )

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

    def test_snapshot_actor_allows_writer_and_admin_but_denies_viewer(self) -> None:
        request = object()
        for role in ("writer", "admin"):
            identity = SessionIdentity(username="person", source="test-sso", verified=True)
            with patch.object(labeling_router, "request_identity", return_value=identity):
                with patch.object(labeling_router.database, "access_role", return_value=role):
                    self.assertEqual(
                        labeling_router._labeling_snapshot_actor(request),
                        ("person", "test-sso", True),
                    )
        identity = SessionIdentity(username="person", source="test-sso", verified=True)
        with patch.object(labeling_router, "request_identity", return_value=identity):
            with patch.object(labeling_router.database, "access_role", return_value="viewer"):
                with self.assertRaises(HTTPException) as raised:
                    labeling_router._labeling_snapshot_actor(request)
        self.assertEqual(raised.exception.status_code, 403)

    def test_partial_flag_parser_requires_json_boolean(self) -> None:
        self.assertFalse(labeling_router._snapshot_allow_partial({}))
        self.assertTrue(labeling_router._snapshot_allow_partial({"allow_partial": True}))
        for value in ("false", 0, 1, None):
            with self.subTest(value=value):
                with self.assertRaises(HTTPException) as raised:
                    labeling_router._snapshot_allow_partial({"allow_partial": value})
                self.assertEqual(raised.exception.status_code, 400)

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

    def test_gt_export_records_each_scope_snapshot_and_enforces_association_foreign_keys(self) -> None:
        db = self.make_db()
        for scope, issue_id, label, expected in (
            ("scope-a", "a", "误触发", "正确触发"),
            ("scope-b", "b", "正确触发", "无需协助"),
        ):
            self.add_scope(db, scope, [(issue_id, label)])
            self.sync(db, scope, [{"issue_id": issue_id, "gt_label": label}])
            db.create_label_revision(
                issue_id=issue_id, expected_output=expected, tags=[], evidence_gaps=[],
                rationale="export candidate", is_excluded=False, author="alice",
                author_source="test", author_verified=False,
            )
        preview = db.create_label_gt_export_preview(
            baseline_scopes=["scope-a", "scope-b"], created_by="alice",
            created_by_source="test", created_by_verified=False,
        )
        self.assertEqual(
            {item["baseline_scope"] for item in preview["source_gt_snapshots"]},
            {"scope-a", "scope-b"},
        )
        batch = db.get_label_gt_export_batch(preview["id"])
        self.assertEqual(
            {item["baseline_scope"] for item in batch["source_gt_snapshots"]},
            {"scope-a", "scope-b"},
        )
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO label_gt_export_source_snapshots (
                        batch_id, baseline_scope, snapshot_id, content_sha256
                    ) VALUES (?, 'scope-a', 'missing-snapshot', 'x')
                    """,
                    (preview["id"],),
                )

    def test_gt_export_without_active_snapshot_is_rejected(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "误触发")])
        db.create_label_revision(
            issue_id="a", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="export candidate", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
        )
        with self.assertRaisesRegex(ValueError, "正式 GT snapshot"):
            db.create_label_gt_export_preview(
                baseline_scopes=["scope"], created_by="alice",
                created_by_source="test", created_by_verified=False,
            )

    def test_gt_export_reconciliation_reports_not_applied_and_missing_snapshot_as_error(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "误触发")])
        self.sync(db, "scope", [{"issue_id": "a", "gt_label": "误触发"}])
        db.create_label_revision(
            issue_id="a", expected_output="正确触发", tags=[], evidence_gaps=[],
            rationale="export candidate", is_excluded=False, author="alice",
            author_source="test", author_verified=False,
        )
        preview = db.create_label_gt_export_preview(
            baseline_scopes=["scope"], created_by="alice",
            created_by_source="test", created_by_verified=False,
        )
        db.mark_label_gt_exported(batch_id=preview["id"], file_sha256="f" * 64)
        not_applied = db.reconcile_label_gt_export_batch(preview["id"])
        self.assertEqual(not_applied["reconcile_status"], "not_applied")
        self.assertEqual(not_applied["items"][0]["reconcile_status"], "not_applied")

        with db.connect() as conn:
            conn.execute("DELETE FROM gt_snapshot_active WHERE baseline_scope = 'scope'")
        missing = db.reconcile_label_gt_export_batch(preview["id"])
        self.assertEqual(missing["reconcile_status"], "error")
        self.assertIn("no active GT snapshot", missing["reconcile_error"])
        self.assertEqual(missing["items"][0]["reconcile_status"], "error")

    def test_bulk_reconciliation_retries_error_and_finishes_after_successful_sync(self) -> None:
        db = self.make_db()
        self.add_scope(db, "scope", [("a", "误触发"), ("b", "正确触发")])
        old_rows = [
            {"issue_id": "a", "gt_label": "误触发"},
            {"issue_id": "b", "gt_label": "正确触发"},
        ]
        self.sync(db, "scope", old_rows)
        for issue_id, expected in (("a", "正确触发"), ("b", "无需协助")):
            db.create_label_revision(
                issue_id=issue_id, expected_output=expected, tags=[], evidence_gaps=[],
                rationale="batch reconcile", is_excluded=False, author="alice",
                author_source="test", author_verified=False,
            )
        preview = db.create_label_gt_export_preview(
            baseline_scopes=["scope"], created_by="alice",
            created_by_source="test", created_by_verified=False,
        )
        db.mark_label_gt_exported(batch_id=preview["id"], file_sha256="a" * 64)

        with db.connect() as conn:
            conn.execute("DELETE FROM gt_snapshot_active WHERE baseline_scope = 'scope'")
        failed = db.reconcile_label_gt_export_batches_for_scope("scope")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reconcile_status"], "error")

        self.sync(db, "scope", old_rows)
        retried = db.reconcile_label_gt_export_batches_for_scope("scope")
        self.assertEqual(retried[0]["reconcile_status"], "not_applied")
        self.sync(
            db,
            "scope",
            [
                {"issue_id": "a", "gt_label": "正确触发"},
                {"issue_id": "b", "gt_label": "无需协助"},
            ],
        )
        matched = db.reconcile_label_gt_export_batches_for_scope("scope")
        self.assertEqual(matched[0]["reconcile_status"], "matched")
        self.assertEqual(matched[0]["reconcile_counts"]["matched"], 2)
        self.assertEqual(db.reconcile_label_gt_export_batches_for_scope("scope"), [])

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
        collected = []
        page = 1
        while True:
            detail = db.get_gt_snapshot(
                snapshot["id"], include_items=True, page=page, page_size=1000
            )
            self.assertEqual(detail["items_total"], 5205)
            collected.extend(detail["items"])
            if detail["items_next_page"] is None:
                break
            page = detail["items_next_page"]
        self.assertEqual(len(collected), 5205)
        self.assertEqual(len({item["issue_id"] for item in collected}), 5205)

    def test_label_result_snapshot_items_are_fully_pageable(self) -> None:
        db = self.make_db()
        rows = [(f"label-{index:04d}", "正确触发") for index in range(1105)]
        self.add_scope(db, "scope", rows)
        workset = db.create_review_workset(
            baseline_scope="scope",
            issue_ids=[issue_id for issue_id, _label in rows],
            created_by="admin",
        )
        snapshot = db.create_label_result_snapshot(
            workset_id=workset["id"], created_by="admin", allow_partial=True
        )
        collected = []
        page = 1
        while True:
            detail = db.get_label_result_snapshot(
                snapshot["id"], include_items=True, page=page, page_size=400
            )
            self.assertEqual(detail["items_total"], 1105)
            collected.extend(detail["items"])
            if detail["items_next_page"] is None:
                break
            page = detail["items_next_page"]
        self.assertEqual(len(collected), 1105)
        self.assertEqual(len({item["issue_id"] for item in collected}), 1105)
