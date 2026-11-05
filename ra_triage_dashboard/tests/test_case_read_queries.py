"""Guard filter equivalence and bounded public / complete internal ID reads."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import cases as cases_router


class CaseReadQueriesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "queries.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues([
            {"issue_id": "cn1", "gt_label": "正确触发"},
            {"issue_id": "cn2", "gt_label": "误触发"},
            {"issue_id": "cn3", "gt_label": ""},
            {"issue_id": "cn4", "gt_label": "无需协助"},
        ], source="test", replace_gt=True, baseline_scope="scope")
        self.run, _ = self.db.import_model_run(
            name="query test", source_name="query.json", source_sha256=hashlib.sha256(b"query").hexdigest(),
            metadata={}, rows=[
                {"issue_id": "cn1", "model_label": "误触发"},
                {"issue_id": "cn2", "model_label": "误触发"},
                {"issue_id": "cn3", "model_label": "无需协助"},
            ],
        )
        self.db.create_annotation(
            issue_id="cn1", model_run_id=self.run["id"], label="正确触发", review_status="reviewed",
            tags=[], missing_evidence=["routing_direction"], note="review", author="alice", is_excluded=True,
        )

    def test_count_page_and_id_reads_keep_all_filter_bindings(self):
        for filters, expected in [
            ({}, ["cn1", "cn2", "cn3", "cn4"]),
            ({"gt_label": "正确触发"}, ["cn1"]),
            ({"model_label": "误触发"}, ["cn1", "cn2"]),
            ({"comparison_status": "mismatch"}, ["cn1"]),
            ({"annotation_author": "alice"}, ["cn1"]),
            ({"annotation_label": "正确触发"}, ["cn1"]),
            ({"model_review_status": "completed"}, ["cn1"]),
            ({"missing_evidence": "routing_direction"}, ["cn1"]),
            ({"is_excluded": False}, ["cn2", "cn3", "cn4"]),
            ({"model_label": "误触发", "annotation_author": "alice"}, ["cn1"]),
            ({"search": "cn4"}, ["cn4"]),
        ]:
            with self.subTest(filters=filters):
                kwargs = {"baseline_scope": "scope", "model_run_id": self.run["id"], **filters}
                page = self.db.list_cases(**kwargs, page=1, page_size=1)
                self.assertEqual(page["total"], len(expected))
                self.assertEqual([item["issue_id"] for item in page["items"]], expected[:1])
                self.assertEqual(self.db.list_case_issue_ids(**kwargs), expected)

    def test_plain_count_does_not_resolve_review_or_prediction_rows(self):
        statements = []
        connect = self.db.connect
        @contextmanager
        def trace():
            with connect() as conn:
                conn.set_trace_callback(statements.append)
                yield conn
        with patch.object(self.db, "connect", trace):
            result = self.db.list_cases(baseline_scope="scope", model_run_id=self.run["id"], page_size=1)
        self.assertEqual(result["total"], 4)
        counts = [sql for sql in statements if sql.startswith("SELECT COUNT(DISTINCT i.issue_id)")]
        self.assertEqual(len(counts), 1)
        self.assertNotIn("review_records", counts[0])
        self.assertNotIn("model_predictions", counts[0])

    def test_internal_assignee_scope_is_complete_beyond_public_id_cap(self):
        self.db.upsert_issues(
            [{"issue_id": f"wide-{index:05}"} for index in range(5001)],
            source="test", replace_gt=False, baseline_scope="wide",
        )
        self.assertEqual(len(self.db.list_case_issue_ids(baseline_scope="wide", limit=10000)), 5000)
        with patch.object(cases_router, "database", self.db):
            ids = cases_router._case_issue_ids_with_status_filter(
                filters={"baseline_scope": "wide", "gt_relation": (), "issue_tag_groups": (), "is_excluded": None},
                review_statuses=(),
            )
        self.assertEqual(len(ids), 5001)
        self.assertEqual(ids[-1], "wide-05000")


if __name__ == "__main__":
    unittest.main()
