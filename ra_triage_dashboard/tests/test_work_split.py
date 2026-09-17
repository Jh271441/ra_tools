from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from ra_triage_dashboard.app.db import AnnotationConflictError, Database
from ra_triage_dashboard.app.routers import analysis as analysis_router
from ra_triage_dashboard.app.routers import cases as cases_router
from ra_triage_dashboard.app.support import review_payloads
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class WorkSplitTest(unittest.TestCase):
    def test_analysis_work_split_options_only_returns_current_matching_batches(self) -> None:
        request = Request(
            {"type": "http", "method": "GET", "path": "/api/review-work-splits", "headers": []}
        )
        rows = [
            {
                "split_id": "split-current",
                "model_run_id": "run-1",
                "created_at": "2026-09-17T10:00:00+08:00",
                "created_by": "alice",
                "mode": "blind",
                "reviewers_per_issue": 2,
                "total_count": 10,
                "assignment_count": 20,
                "completed_count": 6,
                "filter_snapshot": {"baselines": ["0508"]},
                "is_current": True,
            },
            {
                "split_id": "split-other-baseline",
                "model_run_id": "run-1",
                "filter_snapshot": {"baselines": ["0821"]},
                "is_current": True,
            },
            {
                "split_id": "split-superseded",
                "model_run_id": "run-1",
                "filter_snapshot": {"baselines": ["0508"]},
                "is_current": False,
            },
        ]
        with patch.object(
            cases_router, "resolve_request_baseline_ids", return_value=["0508"]
        ), patch.object(
            cases_router.database, "list_review_work_splits", return_value=rows
        ):
            result = asyncio.run(
                cases_router.review_work_split_options(
                    request, model_run_id="run-1", baselines="0508"
                )
            )
        self.assertEqual([item["split_id"] for item in result["items"]], ["split-current"])
        self.assertEqual(result["items"][0]["completed_count"], 6)
        self.assertEqual(result["items"][0]["baselines"], ["0508"])

    def test_exact_split_scope_keeps_task_membership_and_new_reviews_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "exact-split-scope.sqlite")
            db.init()
            scope = "scope"
            db.upsert_issues(
                [
                    {"issue_id": "cn1", "gt_label": "误触发"},
                    {"issue_id": "cn2", "gt_label": "误触发"},
                    {"issue_id": "cn3", "gt_label": "误触发"},
                ],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = db.import_model_run(
                name="split-run",
                source_name="split.json",
                source_sha256="6" * 64,
                metadata={},
                rows=[
                    {"issue_id": issue_id, "model_label": "正确触发"}
                    for issue_id in ("cn1", "cn2", "cn3")
                ],
            )
            db.create_annotation(
                issue_id="cn1", model_run_id=run["id"], label="无需协助",
                review_status="needs_gt_review", tags=[], missing_evidence=[],
                note="old ordinary", author="legacy",
            )
            db.create_annotation(
                issue_id="cn2", model_run_id=run["id"], label="无需协助",
                review_status="needs_gt_review", tags=[], missing_evidence=[],
                note="old ordinary", author="legacy",
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
            fresh = db.create_annotation(
                issue_id="cn1", model_run_id=run["id"],
                work_split_id=saved["split_id"], label="正确触发",
                review_status="needs_gt_review", tags=[],
                missing_evidence=["routing_direction"],
                note="new split result", author="alice",
                expected_previous_annotation_id=None,
            )

            gallery = db.list_cases(
                baseline_scopes=[scope], model_run_id=run["id"],
                work_split_id=saved["split_id"], page_size=10,
            )
            self.assertEqual([item["issue_id"] for item in gallery["items"]], ["cn1", "cn2"])
            self.assertEqual(gallery["items"][0]["annotation"]["id"], fresh["id"])
            self.assertIsNone(gallery["items"][1]["annotation"]["id"])
            self.assertEqual(
                db.review_clusters(
                    baseline_scopes=[scope], model_run_id=run["id"],
                    failure_only=False, work_split_id=saved["split_id"],
                ),
                [{"key": "routing_direction", "count": 1}],
            )

            with patch.object(review_payloads, "database", db), patch(
                "ra_triage_dashboard.app.support.catalogs.database", db
            ):
                analysis = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    work_split_id=saved["split_id"],
                    include_multi_reviews=True,
                )

            self.assertEqual(analysis["total"], 1)
            self.assertEqual(analysis["items"][0]["issue_id"], "cn1")
            self.assertEqual(analysis["items"][0]["annotation"]["id"], fresh["id"])
            self.assertEqual(analysis["items"][0]["multi_review"]["agreement"], "pending")
            self.assertEqual(analysis["scope"]["work_split_id"], saved["split_id"])
            self.assertEqual(analysis["filters"]["work_split_id"], saved["split_id"])

    def test_reviewer_endpoint_keeps_cross_review_additive_to_existing_facet(self) -> None:
        request = Request(
            {"type": "http", "method": "GET", "path": "/api/reviewers", "headers": []}
        )
        analysis = [{"name": "alice", "review_count": 1}]
        with patch.object(
            cases_router, "resolve_request_baseline_scopes", return_value=["scope"]
        ), patch.object(
            cases_router.database, "list_analysis_reviewers", return_value=analysis
        ):
            result = asyncio.run(
                cases_router.reviewers(request, model_run_id="run", baselines="0821")
            )
        self.assertEqual(result["items"], analysis)
        self.assertEqual(result["analysis_items"], analysis)

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

    def test_partial_blind_assigns_one_base_reviewer_and_sampled_cross_reviewers(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(100)],
            [{"name": name} for name in ("alice", "bob", "carol", "dora")],
            seed=42,
            reviewers_per_issue=2,
            overlap_ratio=0.2,
        )
        self.assertEqual(sum(item["count"] for item in result), 120)
        self.assertEqual({item["count"] for item in result}, {30})
        owners: dict[str, list[str]] = {}
        for item in result:
            for assignment in item["items"]:
                owners.setdefault(assignment["issue_id"], []).append(
                    assignment["assignment_kind"]
                )
        self.assertEqual(len(owners), 100)
        self.assertEqual(sum(len(names) == 2 for names in owners.values()), 20)
        self.assertEqual(sum(len(names) == 1 for names in owners.values()), 80)
        self.assertTrue(all(names.count("base") == 1 for names in owners.values()))

    def test_partial_blind_honors_fixed_member_quotas(self) -> None:
        result = distribute_issue_ids(
            [f"id{i}" for i in range(100)],
            [
                {"name": "alice", "count": 40},
                {"name": "bob", "count": 30},
                {"name": "carol", "count": 30},
                {"name": "dora", "count": 20},
            ],
            seed=42,
            reviewers_per_issue=2,
            overlap_ratio=0.2,
        )
        self.assertEqual(
            {item["name"]: item["count"] for item in result},
            {"alice": 40, "bob": 30, "carol": 30, "dora": 20},
        )
        owners: dict[str, set[str]] = {}
        for item in result:
            for issue_id in item["issue_ids"]:
                owners.setdefault(issue_id, set()).add(item["name"])
        self.assertEqual(len(owners), 100)
        self.assertEqual(sum(len(names) == 2 for names in owners.values()), 20)
        self.assertTrue(all(len(names) in {1, 2} for names in owners.values()))

    def test_overlap_ratio_must_be_a_finite_fraction(self) -> None:
        for value in (-0.1, 1.1, "nan", True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "overlap_ratio"):
                    distribute_issue_ids(
                        ["a", "b"],
                        [{"name": "alice"}, {"name": "bob"}],
                        reviewers_per_issue=2,
                        overlap_ratio=value,
                    )

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

    def test_work_split_management_reports_progress_and_reassigns_pending_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "work-management.sqlite")
            db.init()
            now = "2026-08-04T00:00:00+00:00"
            with db._write_lock, db.connect() as conn:
                for index in range(4):
                    conn.execute(
                        """
                        INSERT INTO issues (
                            issue_id, trip_id, title, scenario, summary, review_note,
                            trail_url, gt_label, gt_source, source, baseline_scope,
                            extra_json, created_at, updated_at
                        ) VALUES (?, '', ?, '', '', '', '', '误触发', 'test', 'test',
                                  'scope', '{}', ?, ?)
                        """,
                        (f"cn{index}", f"Issue {index}", now, now),
                    )
            assignments = distribute_issue_ids(
                [f"cn{i}" for i in range(4)],
                [{"name": "alice"}, {"name": "bob"}],
                seed=9,
            )
            saved = db.apply_work_split(
                assignments=assignments,
                created_by="admin",
                seed=9,
                model_run_id="",
                filter_snapshot={"baselines": "0821", "comparison_status": "mismatch"},
            )
            completed_issue = assignments[0]["issue_ids"][0]
            db.create_annotation(
                issue_id=completed_issue,
                model_run_id="",
                work_split_id="",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="done",
                author=assignments[0]["name"],
                expected_previous_annotation_id=None,
            )

            batches = db.list_review_work_splits()
            self.assertEqual(len(batches), 1)
            batch = batches[0]
            self.assertEqual(batch["total_count"], 4)
            self.assertEqual(batch["assignment_count"], 4)
            self.assertEqual(batch["completed_count"], 1)
            self.assertEqual(batch["pending_count"], 3)
            self.assertEqual(sum(item["completed_count"] for item in batch["members"]), 1)

            detail = db.get_review_work_split(saved["split_id"], page_size=20)
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["total"], 4)
            self.assertEqual(sum(bool(item["submitted"]) for item in detail["items"]), 1)
            pending = next(item for item in detail["items"] if not item["submitted"])
            old_assignee = pending["assignee"]
            new_assignee = "bob" if old_assignee == "alice" else "alice"
            changed = db.reassign_review_work_assignment(
                split_id=saved["split_id"],
                issue_id=pending["issue_id"],
                assignee=new_assignee,
                changed_by="admin",
            )
            self.assertTrue(changed["changed"])
            updated = db.get_review_work_split(saved["split_id"], page_size=20)
            assert updated is not None
            updated_item = next(item for item in updated["items"] if item["issue_id"] == pending["issue_id"])
            self.assertEqual(updated_item["assignee"], new_assignee)
            self.assertEqual(updated["change_count"], 1)
            with self.assertRaisesRegex(ValueError, "已提交"):
                db.reassign_review_work_assignment(
                    split_id=saved["split_id"],
                    issue_id=completed_issue,
                    assignee=new_assignee,
                    changed_by="admin",
                )
            db.apply_work_split(
                assignments=[{"name": "bob", "issue_ids": [f"cn{i}" for i in range(4)]}],
                created_by="admin",
                model_run_id="",
            )
            history = next(
                item
                for item in db.list_review_work_splits()
                if item["split_id"] == saved["split_id"]
            )
            self.assertFalse(history["is_current"])
            self.assertEqual(history["completed_count"], 1)
            old_detail = db.get_review_work_split(saved["split_id"], page_size=20)
            assert old_detail is not None
            self.assertEqual(old_detail["total"], 4)
            self.assertEqual(sum(bool(item["submitted"]) for item in old_detail["items"]), 1)

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
            self.assertEqual(context["overlap_ratio"], 1.0)
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
            alice_latest = db.create_annotation(
                issue_id="cn1", model_run_id="", work_split_id=saved["split_id"],
                label="无需协助", review_status="needs_gt_review", tags=[],
                missing_evidence=[], note="alice latest", author="alice",
                expected_previous_annotation_id=alice["id"],
            )
            with self.assertRaises(AnnotationConflictError):
                db.create_annotation(
                    issue_id="cn1", model_run_id="", work_split_id=saved["split_id"],
                    label="误触发", review_status="reviewed", tags=[],
                    missing_evidence=[], note="stale", author="alice",
                    expected_previous_annotation_id=None,
                )
            projected = db.list_cases(
                baseline_scope="scope", page_size=10
            )["items"][0]["annotation"]
            self.assertEqual(projected["id"], alice_latest["id"])
            self.assertEqual(projected["author"], "alice")
            own_projected = db.list_cases(
                baseline_scope="scope",
                preferred_annotation_author="bob",
                page_size=10,
            )["items"][0]["annotation"]
            self.assertEqual(own_projected["id"], bob["id"])
            self.assertEqual(own_projected["author"], "bob")
            explicitly_filtered = db.list_cases(
                baseline_scope="scope",
                annotation_author="alice",
                preferred_annotation_author="bob",
                page_size=10,
            )["items"][0]["annotation"]
            self.assertEqual(explicitly_filtered["id"], alice_latest["id"])
            self.assertEqual(explicitly_filtered["author"], "alice")
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
                work_split_id=saved["split_id"], label="正确触发",
                review_status="needs_gt_review", tags=[],
                missing_evidence=["routing_direction"], note="alice result",
                author="alice", expected_previous_annotation_id=None,
            )
            db.create_review_comment(
                issue_id="cn1",
                model_run_id=run["id"],
                body="这里讨论绕行空间",
                author="alice",
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
                no_overlay = review_payloads._review_reason_analysis_payload(
                    model_run_id="",
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
                with_comments = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    include_multi_reviews=True,
                    comment_state="with",
                )
                no_overlay_with_comments = review_payloads._review_reason_analysis_payload(
                    model_run_id="",
                    comparison="all",
                    baseline_scopes=[scope],
                    include_multi_reviews=True,
                    comment_state="with",
                )
                no_overlay_matching_comment = review_payloads._review_reason_analysis_payload(
                    model_run_id="",
                    comparison="all",
                    baseline_scopes=[scope],
                    include_multi_reviews=True,
                    comment_search="绕行空间",
                )
                matching_comment = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    include_multi_reviews=True,
                    comment_search="绕行空间",
                )
                missing_comment = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    include_multi_reviews=True,
                    comment_search="不存在的评论",
                )
                issue_filtered_out = review_payloads._review_reason_analysis_payload(
                    model_run_id="",
                    comparison="all",
                    baseline_scopes=[scope],
                    include_multi_reviews=True,
                    issue_ids="cn404",
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
            # GT-update export shares the current analysis projection: the
            # submitted blind result wins over stale ordinary history even
            # before every assigned reviewer has completed the Issue.
            self.assertEqual(
                analysis_router._trail_expected_output_rows(result),
                [{"issue_id": "cn1", "期望输出": "正确触发"}],
            )
            self.assertEqual(no_overlay["total"], 1)
            self.assertEqual(no_overlay["items"][0]["issue_id"], "cn1")
            self.assertEqual(no_overlay["items"][0]["annotation"]["author"], "alice")
            self.assertEqual(
                no_overlay["items"][0]["annotation"]["model_run_id"], run["id"]
            )
            self.assertEqual(no_overlay["items"][0]["prediction"]["model_run_id"], "")
            self.assertIn(f"run={run['id']}", no_overlay["items"][0]["review_url"])
            self.assertEqual(
                no_overlay["items"][0]["multi_review"]["model_run_id"], run["id"]
            )
            self.assertEqual(no_overlay["scope"]["model_run"], None)
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
            alice_cases = db.list_cases(
                baseline_scopes=[scope],
                model_run_id=run["id"],
                work_assignee="alice",
                page_size=20,
            )
            self.assertEqual(alice_cases["total"], 2)
            self.assertEqual(
                alice_cases["items"][0]["annotation"]["author"], "alice"
            )
            self.assertIsNone(alice_cases["items"][1]["annotation"]["id"])
            with patch.object(cases_router, "database", db), patch.object(
                cases_router, "_review_tag_catalog", return_value=()
            ):
                needs_gt = cases_router._case_result_with_status_filter(
                    filters={
                        "baseline_scopes": [scope],
                        "model_run_id": run["id"],
                        "comparison_status": "all",
                        "work_assignee": "alice",
                    },
                    review_statuses=("needs_gt_review",),
                    page=1,
                    page_size=20,
                )
            self.assertEqual(needs_gt["total"], 1)
            self.assertEqual(needs_gt["items"][0]["issue_id"], "cn1")
            self.assertEqual(
                db.overview(
                    baseline_scopes=[scope], model_run_id=run["id"]
                )["labelled"],
                1,
            )
            # The explicit pending task view still includes untouched cn2;
            # only the default result view suppresses zero-submission tasks.
            self.assertEqual(pending["total"], 2)
            self.assertEqual(with_comments["total"], 1)
            self.assertEqual(no_overlay_with_comments["total"], 1)
            self.assertEqual(no_overlay_matching_comment["total"], 1)
            self.assertEqual(matching_comment["total"], 1)
            self.assertEqual(missing_comment["total"], 0)
            self.assertEqual(issue_filtered_out["total"], 0)
            self.assertEqual(issue_filtered_out["filters"]["issue_ids"], ["cn404"])

    def test_conflict_analysis_display_and_export_use_latest_reviewer_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "blind-conflict-analysis.sqlite")
            db.init()
            scope = "scope"
            db.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "正确触发"}],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = db.import_model_run(
                name="blind-run",
                source_name="blind.json",
                source_sha256="8" * 64,
                metadata={},
                rows=[{"issue_id": "cn1", "model_label": "正确触发"}],
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
                model_run_id=run["id"],
            )
            alice = db.create_annotation(
                issue_id="cn1",
                model_run_id=run["id"],
                work_split_id=saved["split_id"],
                label="正确触发",
                review_status="reviewed",
                tags=["alice-tag"],
                missing_evidence=["alice-evidence"],
                note="alice older",
                author="alice",
                expected_previous_annotation_id=None,
            )
            bob = db.create_annotation(
                issue_id="cn1",
                model_run_id=run["id"],
                work_split_id=saved["split_id"],
                label="误触发",
                review_status="needs_gt_review",
                tags=["bob-tag"],
                missing_evidence=["bob-evidence"],
                note="bob latest",
                author="bob",
                expected_previous_annotation_id=None,
            )
            self.assertGreater(bob["id"], alice["id"])

            with patch.object(review_payloads, "database", db), patch(
                "ra_triage_dashboard.app.support.catalogs.database", db
            ):
                result = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    work_agreement="conflict",
                    annotation_author="alice",
                )

            self.assertEqual(result["total"], 1)
            annotation = result["items"][0]["annotation"]
            self.assertEqual(annotation["id"], bob["id"])
            self.assertEqual(annotation["author"], "bob")
            self.assertEqual(annotation["label"], "误触发")
            self.assertEqual(annotation["note"], "bob latest")
            self.assertEqual(annotation["tags"], ["bob-tag"])
            self.assertEqual(annotation["missing_evidence"], ["bob-evidence"])

            with patch.object(analysis_router, "_review_tag_catalog", return_value=[]), patch.object(
                analysis_router, "_missing_evidence_catalog", return_value=[]
            ):
                exported = analysis_router._review_analysis_export_rows(result)
            self.assertEqual(exported[0]["expected_output"], "误触发")
            self.assertEqual(exported[0]["review_reason"], "bob latest")
            self.assertEqual(exported[0]["reviewer"], "bob")
            self.assertEqual(exported[0]["tags"], "bob-tag")
            self.assertEqual(exported[0]["missing_evidence"], "bob-evidence")

    def test_agreed_analysis_display_uses_latest_reviewer_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "blind-agreed-analysis.sqlite")
            db.init()
            scope = "scope"
            db.upsert_issues(
                [{"issue_id": "cn1", "gt_label": "正确触发"}],
                source="test",
                replace_gt=True,
                baseline_scope=scope,
            )
            run, _ = db.import_model_run(
                name="blind-run",
                source_name="blind.json",
                source_sha256="9" * 64,
                metadata={},
                rows=[{"issue_id": "cn1", "model_label": "正确触发"}],
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
                model_run_id=run["id"],
            )
            alice = db.create_annotation(
                issue_id="cn1",
                model_run_id=run["id"],
                work_split_id=saved["split_id"],
                label="误触发",
                review_status="needs_gt_review",
                tags=["alice-tag"],
                missing_evidence=["alice-evidence"],
                note="alice older",
                author="alice",
                expected_previous_annotation_id=None,
            )
            bob = db.create_annotation(
                issue_id="cn1",
                model_run_id=run["id"],
                work_split_id=saved["split_id"],
                label="误触发",
                review_status="needs_gt_review",
                tags=["bob-tag"],
                missing_evidence=["bob-evidence"],
                note="bob latest",
                author="bob",
                expected_previous_annotation_id=None,
            )
            self.assertGreater(bob["id"], alice["id"])

            with patch.object(review_payloads, "database", db), patch(
                "ra_triage_dashboard.app.support.catalogs.database", db
            ):
                result = review_payloads._review_reason_analysis_payload(
                    model_run_id=run["id"],
                    comparison="all",
                    baseline_scopes=[scope],
                    work_agreement="all",
                    include_multi_reviews=True,
                )

            self.assertEqual(result["total"], 1)
            item = result["items"][0]
            self.assertEqual(item["multi_review"]["agreement"], "agreed")
            self.assertEqual(item["annotation"]["id"], bob["id"])
            self.assertEqual(item["annotation"]["author"], "bob")
            self.assertEqual(item["annotation"]["note"], "bob latest")
            self.assertEqual(item["annotation"]["tags"], ["bob-tag"])
            self.assertEqual(
                item["annotation"]["missing_evidence"], ["bob-evidence"]
            )

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
