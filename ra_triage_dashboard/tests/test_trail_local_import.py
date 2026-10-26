import tempfile
from pathlib import Path
from unittest import TestCase

from ra_triage_dashboard.app.db import Database, LabelAnnotationConflictError


class TrailLocalImportTest(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(Path(tmp.name) / "test.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues([{"issue_id":"cn12345678","gt_label":"正确触发"},
                               {"issue_id":"cn23456789","gt_label":"正确触发"}], source="test", replace_gt=True, baseline_scope="scope")
        self.db.set_labeling_scope_state(baseline_scope="scope",status="active",policy_version="test",source_inventory_sha256="a"*64,updated_by="test")

    def vote(self, issue="cn12345678", reason="", **kwargs):
        return self.db.create_label_revision(issue_id=issue,expected_output="正确触发",tags=["test"],evidence_gaps=["video"],
            rationale=reason,is_excluded=False,author="alice",author_source="test",author_verified=True,**kwargs)

    def preview(self, ids=None, reason="Trail reason", **kwargs):
        ids = ids or ["cn12345678"]
        return self.db.preview_trail_local_import(issue_ids=ids,actor="alice",scopes=["scope"],
            remote={issue:{"should_exclude":True,"should_exclude_comment":reason} for issue in ids},**kwargs)

    def commit(self, items, token="a"*64):
        return self.db.commit_trail_local_import(operation_id=token,actor="alice",scopes=["scope"],items=items)

    def test_append_preserves_label_evidence_original_and_gt(self):
        original = self.vote()
        items = self.preview()
        self.assertFalse(self.db.project_issue_exclusions(["cn12345678"])["cn12345678"]["is_excluded"])
        result = self.commit(items)
        self.assertEqual(result["imported_count"],1)
        self.assertEqual(self.commit(items),result)
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM label_revisions ORDER BY id").fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]["id"],original["id"])
            self.assertFalse(rows[0]["is_excluded"])
            for key in ("expected_output","tags_json","evidence_gaps_json"):
                self.assertEqual(rows[0][key],rows[1][key])
            self.assertEqual(rows[1]["author_source"],"trail_import")
            self.assertEqual(rows[1]["rationale"],"Trail reason")
            self.assertEqual(conn.execute("SELECT gt_label FROM issues WHERE issue_id='cn12345678'").fetchone()["gt_label"],"正确触发")
        self.assertTrue(self.db.project_issue_exclusions(["cn12345678"])["cn12345678"]["is_excluded"])
        self.assertEqual(self.commit(self.preview(),"b"*64)["imported_count"],0)

    def test_remote_empty_preserves_local_reason_and_new_case_no_classification(self):
        self.vote(reason="keep local")
        self.assertEqual(self.preview(reason="")[0]["after"]["rationale"],"keep local")
        item = self.preview(["cn23456789"],reason="")[0]
        self.assertEqual(item["expected_output"],"")
        self.commit([item])
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM label_revisions WHERE author_source='trail_import'").fetchone()
            self.assertIsNone(row["expected_output"])

    def test_conflict_and_scope_rejected(self):
        self.vote(reason="local")
        with self.assertRaises(ValueError): self.preview()
        with self.assertRaises(ValueError): self.preview(["cn99999999"])
        with self.assertRaises(ValueError):
            self.db.preview_trail_local_import(issue_ids=["cn23456789"],actor="alice",scopes=["scope"],remote={"cn23456789":{"should_exclude":1}})

    def test_atomic_stale_batch_and_actor_replay(self):
        items = self.preview(["cn12345678","cn23456789"])
        self.vote(issue="cn23456789")
        with self.assertRaises(LabelAnnotationConflictError): self.commit(items)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM label_revisions WHERE author_source='trail_import'").fetchone()["n"],0)
        self.commit(self.preview())
        with self.assertRaises(PermissionError): self.db.trail_local_import_result("a"*64,"bob")

    def test_existing_decision_not_invalidated(self):
        original = self.vote()
        state = self.db.project_issue_label_states("scope",["cn12345678"])["cn12345678"]
        self.db.adjudicate_issue_label(baseline_scope="scope",issue_id="cn12345678",expected_output="正确触发",rationale="decision",
            actor="judge",actor_source="test",actor_verified=True,expected_source_fingerprint=state["source_fingerprint"])
        with self.assertRaises(ValueError): self.preview()

    def test_discovery_includes_unannotated_members_and_paginates_scopes(self):
        self.vote()
        first = self.db.trail_local_import_members(scopes=["scope"], limit=1)
        self.assertEqual(first["total"],2)
        self.assertEqual(first["scanned"],1)
        self.assertIs(first["items"][0]["local_excluded"],False)
        second = self.db.trail_local_import_members(scopes=["scope"],after=first["next_cursor"],limit=1)
        self.assertIsNone(second["next_cursor"])
        self.assertIsNone(second["items"][0]["local_excluded"])
        self.assertEqual(self.db.trail_local_import_members(scopes=["other"])["items"],[])
