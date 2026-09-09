from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from ra_triage_dashboard.app.db import AnnotationConflictError, Database
from ra_triage_dashboard.app.routers import cases as cases_router
from ra_triage_dashboard.app.support import review_payloads
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class WorkSplitTest(unittest.TestCase):
    def test_reviewer_endpoint_separates_admin_analysis_facet(self) -> None:
        request = Request(
            {"type": "http", "method": "GET", "path": "/api/reviewers", "headers": []}
        )
        ordinary = [{"name": "legacy", "review_count": 1}]
        analysis = [{"name": "alice", "review_count": 1}]
        with patch.object(
            cases_router, "resolve_request_baseline_scopes", return_value=["scope"]
        ), patch.object(
            cases_router, "_is_dashboard_admin", return_value=True
        ), patch.object(
            cases_router.database, "list_reviewers", return_value=ordinary
        ), patch.object(
            cases_router.database, "list_analysis_reviewers", return_value=analysis
        ):
            result = asyncio.run(
                cases_router.reviewers(request, model_run_id="run", baselines="0821")
            )
        self.assertEqual(result["items"], ordinary)
        self.assertEqual(result["analysis_items"], analysis)

        with patch.object(
            cases_router, "resolve_request_baseline_scopes", return_value=["scope"]
        ), patch.object(
            cases_router, "_is_dashboard_admin", return_value=False
        ), patch.object(
            cases_router.database, "list_reviewers", return_value=ordinary
        ), patch.object(
            cases_router.database, "list_analysis_reviewers"
        ) as blind_facet:
            result = asyncio.run(
                cases_router.reviewers(request, model_run_id="run", baselines="0821")
            )
        self.assertEqual(result["analysis_items"], ordinary)
        blind_facet.assert_not_called()

    def test_even_share_when_no_fixed_counts(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(10)],
            [{"name": "a"}, {"name": "b"}],
            seed=1,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(sum(item["count"] for item in result), 10)
        self.assertEqual(result[0]["count"], 5)
        self.assertEqual(result[1]["count"], 5)
        self.assertEqual(result[0]["mode"], "share")

    def test_fixed_plus_remaining_share(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(10)],
            [
                {"name": "alice", "count": 3},
                {"name": "bob"},
                {"name": "carol"},
            ],
            seed=7,
        )
        by_name = {item["name"]: item for item in result}
        self.assertEqual(by_name["alice"]["count"], 3)
        self.assertEqual(by_name["alice"]["mode"], "fixed")
        self.assertEqual(by_name["bob"]["count"] + by_name["carol"]["count"], 7)
        self.assertTrue(abs(by_name["bob"]["count"] - by_name["carol"]["count"]) <= 1)
        all_ids = []
        for item in result:
            all_ids.extend(item["issue_ids"])
        self.assertEqual(sorted(all_ids), sorted([f"id{i}" for i in range(10)]))

    def test_rejects_over_allocated_fixed_counts(self) -> None:
        with self.assertRaises(ValueError):
            distribute_issue_ids(
                ["a", "b", "c"],
                [{"name": "x", "count": 2}, {"name": "y", "count": 2}],
                seed=1,
            )

    def test_double_blind_reuses_balanced_assignment_shape(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(200)],
            [{"name": name} for name in ("alice", "bob", "carol", "dora")],
            seed=42,
            reviewers_per_issue=2,
        )
        self.assertEqual(sum(item["count"] for item in result), 400)
        self.assertEqual({item["count"] for item in result}, {100})
        owners: dict[str, set[str]] = {}
        for item in result:
            for issue_id in item["issue_ids"]:
                owners.setdefault(issue_id, set()).add(item["name"])
        self.assertEqual(len(owners), 200)
        self.assertTrue(all(len(names) == 2 for names in owners.values()))

    def test_double_blind_supports_fixed_and_automatic_member_quotas(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(200)],
            [
                {"name": "alice", "count": 120},
                {"name": "bob"},
                {"name": "carol"},
                {"name": "dora"},
                {"name": "erin"},
            ],
            seed=42,
            reviewers_per_issue=2,
        )
        by_name = {item["name"]: item["count"] for item in result}
        self.assertEqual(
            by_name,
            {"alice": 120, "bob": 70, "carol": 70, "dora": 70, "erin": 70},
        )
        owners: dict[str, set[str]] = {}
        for item in result:
            for issue_id in item["issue_ids"]:
                owners.setdefault(issue_id, set()).add(item["name"])
        self.assertEqual(len(owners), 200)
        self.assertTrue(all(len(names) == 2 for names in owners.values()))

    def test_double_blind_rejects_impossible_member_quota(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能超过 Issue 数"):
            distribute_issue_ids(
                [f"id{i}" for i in range(10)],
                [
                    {"name": "alice", "count": 11},
                    {"name": "bob"},
                    {"name": "carol"},
                ],
                seed=42,
                reviewers_per_issue=2,
            )
        with self.assertRaisesRegex(ValueError, "必须是整数"):
            distribute_issue_ids(
                [f"id{i}" for i in range(10)],
                [
                    {"name": "alice", "count": 4.5},
                    {"name": "bob"},
                    {"name": "carol"},
                ],
                seed=42,
                reviewers_per_issue=2,
            )

    def test_apply_work_split_persists_filterable_assignee(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "work-split.sqlite")
            db.init()
            now = "2026-08-04T00:00:00+00:00"
            with db._write_lock, db.connect() as conn:
                for index in range(5):
                    conn.execute(
                        """
                        INSERT INTO issues (
                            issue_id, trip_id, title, scenario, summary, review_note,
                            trail_url, gt_label, gt_source, source, baseline_scope,
                            extra_json, created_at, updated_at
                        ) VALUES (?, '', '', '', '', '', '', '误触发', 'test', 'test',
                                  'scope', '{}', ?, ?)
                        """,
                        (f"cn{index}", now, now),
                    )
            assignments = distribute_issue_ids(
                [f"cn{i}" for i in range(4)],
                [{"name": "alice", "count": 1}, {"name": "bob"}],
                seed=3,
            )
            saved = db.apply_work_split(
                assignments=assignments,
                created_by="admin.user",
                seed=3,
                filter_snapshot={"gt_label": "误触发"},
            )
            db.apply_work_split(
                assignments=[
                    {
                        "name": "carol",
                        "count": 1,
                        "requested_count": 1,
                        "mode": "fixed",
                        "issue_ids": ["cn4"],
                    }
                ],
                created_by="admin.user",
            )
            self.assertTrue(saved["split_id"].startswith("split-"))
            alice = db.list_cases(
                baseline_scope="scope", work_assignee="alice", page_size=20
            )
            bob = db.list_cases(
                baseline_scope="scope", work_assignee="bob", page_size=20
            )
            none = db.list_cases(
                baseline_scope="scope", work_assignee="__none__", page_size=20
            )
            self.assertEqual(alice["total"], 1)
            self.assertEqual(bob["total"], 3)
            self.assertEqual(none["total"], 0)
            self.assertEqual(alice["items"][0]["work_assignee"], "alice")
            names = {item["username"] for item in db.list_work_assignees()}
            self.assertEqual(names, {"alice", "bob", "carol"})
            scoped = db.list_work_assignees(
                issue_ids=[f"cn{i}" for i in range(4)]
            )
            self.assertEqual(
                {item["username"] for item in scoped}, {"alice", "bob"}
            )
            self.assertEqual(sum(item["issue_count"] for item in scoped), 4)
            self.assertEqual(db.list_work_assignees(issue_ids=[]), [])

    def test_multi_assignment_and_reviews_are_scoped_per_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "blind.sqlite")
            db.init()
            now = "2026-09-09T00:00:00+00:00"
            with db._write_lock, db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO issues (
                        issue_id, trip_id, title, scenario, summary, review_note,
                        trail_url, gt_label, gt_source, source, baseline_scope,
                        extra_json, created_at, updated_at
                    ) VALUES ('cn1', '', '', '', '', '', '', '误触发', 'test',
                              'test', 'scope', '{}', ?, ?)
                    """,
                    (now, now),
                )
            assignments = distribute_issue_ids(
                ["cn1"],
                [{"name": "alice"}, {"name": "bob"}],
                seed=1,
                reviewers_per_issue=2,
            )
            saved = db.apply_work_split(
                assignments=assignments,
                created_by="admin",
                reviewers_per_issue=2,
            )
            context = db.review_assignment_context("cn1", username="alice")
            self.assertEqual(context["assigned_count"], 2)
            self.assertTrue(context["assigned"])
            alice = db.create_annotation(
                issue_id="cn1", model_run_id="", work_split_id=saved["split_id"],
                label="误触发", review_status="reviewed", tags=[],
                missing_evidence=[], note="alice", author="alice",
                expected_previous_annotation_id=None,
            )
            bob = db.create_annotation(
                issue_id="cn1", model_run_id="", work_split_id=saved["split_id"],
                label="正确触发", review_status="needs_gt_review", tags=[],
                missing_evidence=[], note="bob", author="bob",
                expected_previous_annotation_id=None,
            )
            self.assertNotEqual(alice["id"], bob["id"])
            with self.assertRaises(AnnotationConflictError):
                db.create_annotation(
                    issue_id="cn1", model_run_id="", work_split_id=saved["split_id"],
                    label="误触发", review_status="reviewed", tags=[],
                    missing_evidence=[], note="stale", author="alice",
                    expected_previous_annotation_id=None,
                )
            self.assertIsNone(
                db.list_cases(baseline_scope="scope", page_size=10)["items"][0]["annotation"]["id"]
            )
            self.assertEqual(len(db.review_multi_rows(baseline_scopes=["scope"])), 2)

    def test_default_analysis_includes_submitted_partial_blind_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "blind-analysis.sqlite")
            db.init()
            scope = "scope"
            db.upsert_issues(
                [
                    {"issue_id": "cn1", "gt_label": "误触发"},
                    {"issue_id": "cn2", "gt_label": "误触发"},
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = db.import_model_run(
                name="blind-run",
                source_name="blind.json",
                source_sha256="7" * 64,
                metadata={},
                rows=[
                    {"issue_id": "cn1", "model_label": "正确触发"},
                    {"issue_id": "cn2", "model_label": "正确触发"},
                ],
            )
            assignments = distribute_issue_ids(
                ["cn1", "cn2"],
                [{"name": "alice"}, {"name": "bob"}],
                seed=1,
                reviewers_per_issue=2,
            )
            saved = db.apply_work_split(
                assignments=assignments,
                created_by="admin",
                reviewers_per_issue=2,
                model_run_id=run["id"],
            )
            # An ordinary Review for the same Issue must not duplicate the
            # active blind-task result in the default analysis projection.
            db.create_annotation(
                issue_id="cn1", model_run_id=run["id"],
                label="无需协助", review_status="needs_gt_review", tags=[],
                missing_evidence=[], note="ordinary", author="legacy",
            )
            db.create_annotation(
                issue_id="cn1", model_run_id=run["id"],
                work_split_id=saved["split_id"], label="误触发",
                review_status="reviewed", tags=["queue"],
                missing_evidence=["routing_direction"], note="alice result",
                author="alice", expected_previous_annotation_id=None,
            )
            with patch.object(review_payloads, "database", db), patch(
                "ra_triage_dashboard.app.support.catalogs.database", db
            ):
                ordinary_only = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    work_agreement="all",
                )
                result = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    work_agreement="all",
                    include_multi_reviews=True,
                )
                pending = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    work_agreement="pending",
                )

            self.assertEqual(ordinary_only["total"], 1)
            self.assertEqual(ordinary_only["items"][0]["annotation"]["author"], "legacy")
            self.assertNotIn("multi_review", ordinary_only["items"][0])
            self.assertEqual(result["total"], 1)
            item = result["items"][0]
            self.assertEqual(item["issue_id"], "cn1")
            self.assertEqual(item["annotation"]["author"], "alice")
            self.assertEqual(item["annotation"]["note"], "alice result")
            self.assertEqual(item["multi_review"]["agreement"], "pending")
            self.assertEqual(item["multi_review"]["completed_count"], 1)
            self.assertEqual(item["multi_review"]["assigned_count"], 2)
            self.assertEqual(
                result["evidence_clusters"][0]["key"], "routing_direction"
            )
            self.assertEqual(
                [
                    item["name"]
                    for item in db.list_reviewers(
                        baseline_scopes=[scope], model_run_id=run["id"]
                    )
                ],
                ["legacy"],
            )
            self.assertEqual(
                db.list_analysis_reviewers(
                    baseline_scopes=[scope], model_run_id=run["id"]
                ),
                [
                    {
                        "name": "alice",
                        "verified": False,
                        "verified_count": 0,
                        "unverified_count": 1,
                        "review_count": 1,
                    }
                ],
            )
            # The explicit pending task view still includes untouched cn2;
            # only the default result view suppresses zero-submission tasks.
            self.assertEqual(pending["total"], 2)

    def test_case_comparison_filter_accepts_multiple_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "comparison.sqlite")
            db.init()
            result = db.list_cases(
                comparison_status="mismatch,match",
                model_run_id="run-placeholder",
                page_size=10,
            )
            self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
