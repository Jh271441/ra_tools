from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from contextlib import contextmanager
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Response
from starlette.requests import Request

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.routers import analysis as analysis_router
from ra_triage_dashboard.app.routers import cases as cases_router
from ra_triage_dashboard.app.support import filter_parsing


class IssueLabelStateProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Database(Path(self.temp.name) / "label-state.sqlite")
        self.database.init()

    def add_issues(self, rows: list[dict], scope: str) -> None:
        self.database.upsert_issues(
            rows,
            source="label-state-test",
            replace_gt=True,
            baseline_scope=scope,
        )
        with self.database.connect() as conn:
            current = conn.execute(
                "SELECT issue_id, gt_label, gt_source FROM issues WHERE baseline_scope = ? ORDER BY issue_id",
                (scope,),
            ).fetchall()
            labels = [
                {"issue_id": str(row["issue_id"]), "gt_label": str(row["gt_label"] or ""),
                 "source_updated_by": str(row["gt_source"] or "")}
                for row in current
            ]
            content_sha = hashlib.sha256(
                json.dumps(labels, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            member_sha = hashlib.sha256(
                "\n".join(sorted(item["issue_id"] for item in labels)).encode("utf-8")
            ).hexdigest()
            snapshot_id = f"projection-{scope}-{content_sha[:16]}"
            now = "2026-09-21T00:00:00Z"
            valid_count = sum(item["gt_label"] in {"误触发", "正确触发", "无需协助"} for item in labels)
            gt_mode = "strict" if valid_count == len(labels) else "sparse"
            conn.execute(
                """
                INSERT INTO gt_snapshots (
                    id, baseline_scope, gt_mode, content_sha256, membership_sha256,
                    member_count, valid_label_count, created_by, created_by_source,
                    created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', 'test', 0, ?)
                ON CONFLICT(baseline_scope, content_sha256) DO NOTHING
                """,
                (snapshot_id, scope, gt_mode, content_sha, member_sha, len(labels), valid_count, now),
            )
            snapshot_id = str(conn.execute(
                "SELECT id FROM gt_snapshots WHERE baseline_scope = ? AND content_sha256 = ?",
                (scope, content_sha),
            ).fetchone()["id"])
            conn.executemany(
                """
                INSERT INTO gt_snapshot_items (
                    snapshot_id, baseline_scope, issue_id, ordinal, gt_label, source_updated_by
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id, issue_id) DO NOTHING
                """,
                [(snapshot_id, scope, item["issue_id"], ordinal, item["gt_label"], item["source_updated_by"])
                 for ordinal, item in enumerate(labels, 1)],
            )
            conn.execute(
                """
                INSERT INTO gt_snapshot_active (baseline_scope, snapshot_id, activated_at, activation_reason)
                VALUES (?, ?, ?, 'test_fixture')
                ON CONFLICT(baseline_scope) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    activated_at = excluded.activated_at,
                    activation_reason = excluded.activation_reason
                """,
                (scope, snapshot_id, now),
            )

    def create_revision(
        self,
        *,
        issue_id: str,
        expected_output: str,
        author: str,
        task_id: str = "",
        source_run_id: str = "",
        expected_previous_revision_id: int | None = None,
    ) -> dict:
        return self.database.create_label_revision(
            issue_id=issue_id,
            task_id=task_id,
            source_run_id=source_run_id,
            expected_output=expected_output,
            tags=[],
            evidence_gaps=[],
            rationale="fixture",
            is_excluded=False,
            author=author,
            author_source="test",
            author_verified=False,
            expected_previous_revision_id=expected_previous_revision_id,
        )

    def create_task(
        self,
        *,
        workset_id: str,
        issue_id: str,
        assignees: tuple[str, ...],
    ) -> dict:
        assignments = [
            {"name": assignee, "issue_ids": [issue_id]}
            for assignee in assignees
        ]
        reviewer_count = len(assignees)
        return self.database.create_labeling_task(
            workset_id=workset_id,
            assignments=assignments,
            created_by="admin",
            seed=17,
            reviewers_per_issue=reviewer_count,
            overlap_ratio=1.0 if reviewer_count > 1 else 0.0,
        )

    def test_cross_task_aggregation_is_conservative_and_uses_current_gt(self) -> None:
        rows = [
            {"issue_id": "same-label", "gt_label": "正确触发"},
            {"issue_id": "different-label", "gt_label": "误触发"},
            {"issue_id": "missing-submission", "gt_label": "正确触发"},
            {"issue_id": "stale-adjudication", "gt_label": "误触发"},
            {"issue_id": "gt-differs", "gt_label": "误触发"},
            {"issue_id": "gt-missing", "gt_label": ""},
        ]
        self.add_issues(rows, "scope-a")
        workset = self.database.create_review_workset(
            baseline_scope="scope-a",
            issue_ids=[item["issue_id"] for item in rows],
            name="projection fixture",
            created_by="admin",
        )

        same_tasks = [
            self.create_task(workset_id=workset["id"], issue_id="same-label", assignees=(name,))
            for name in ("alice", "bob")
        ]
        same_revisions = [
            self.create_revision(
                issue_id="same-label",
                task_id=task["id"],
                expected_output="正确触发",
                author=author,
            )
            for task, author in zip(same_tasks, ("alice", "bob"))
        ]

        conflict_tasks = [
            self.create_task(workset_id=workset["id"], issue_id="different-label", assignees=(name,))
            for name in ("carol", "dave")
        ]
        for task, author, label in zip(
            conflict_tasks, ("carol", "dave"), ("误触发", "正确触发")
        ):
            self.create_revision(
                issue_id="different-label",
                task_id=task["id"],
                expected_output=label,
                author=author,
            )

        resolved_task = self.create_task(
            workset_id=workset["id"],
            issue_id="missing-submission",
            assignees=("erin",),
        )
        self.create_revision(
            issue_id="missing-submission",
            task_id=resolved_task["id"],
            expected_output="正确触发",
            author="erin",
        )
        pending_task = self.create_task(
            workset_id=workset["id"],
            issue_id="missing-submission",
            assignees=("frank",),
        )
        self.database.ensure_label_case(
            issue_id="missing-submission", task_id=pending_task["id"]
        )

        stale_task = self.create_task(
            workset_id=workset["id"],
            issue_id="stale-adjudication",
            assignees=("grace", "heidi"),
        )
        grace = self.create_revision(
            issue_id="stale-adjudication",
            task_id=stale_task["id"],
            expected_output="误触发",
            author="grace",
        )
        heidi = self.create_revision(
            issue_id="stale-adjudication",
            task_id=stale_task["id"],
            expected_output="正确触发",
            author="heidi",
        )
        current_case = self.database.get_label_case(grace["label_case"]["id"])
        heads = current_case["resolution"]["heads"]
        self.database.adjudicate_label_case(
            label_case_id=grace["label_case"]["id"],
            source_revision_ids=[item["id"] for item in heads],
            expected_output="误触发",
            tags=[],
            evidence_gaps=[],
            rationale="fixture adjudication",
            is_excluded=False,
            actor="judge",
            actor_source="test",
            actor_verified=False,
            expected_previous_resolution_id=None,
        )
        other_stale_task = self.create_task(
            workset_id=workset["id"],
            issue_id="stale-adjudication",
            assignees=("ivan",),
        )
        self.create_revision(
            issue_id="stale-adjudication",
            task_id=other_stale_task["id"],
            expected_output="误触发",
            author="ivan",
        )
        self.create_revision(
            issue_id="stale-adjudication",
            task_id=stale_task["id"],
            expected_output="无需协助",
            author="grace",
            expected_previous_revision_id=grace["id"],
        )

        self.create_revision(
            issue_id="gt-differs", expected_output="正确触发", author="judy"
        )
        self.create_revision(
            issue_id="gt-missing", expected_output="无需协助", author="mallory"
        )

        states = self.database.project_issue_label_states(
            "scope-a", [item["issue_id"] for item in rows]
        )
        self.assertEqual(states["same-label"]["state"], "resolved")
        self.assertEqual(states["same-label"]["method"], "consensus")
        self.assertEqual(states["same-label"]["expected_output"], "正确触发")
        self.assertEqual(states["same-label"]["gt_relation"], "matches_gt")
        self.assertEqual(
            set(states["same-label"]["source_task_ids"]),
            {item["id"] for item in same_tasks},
        )
        self.assertEqual(
            set(states["same-label"]["source_revision_ids"]),
            {item["id"] for item in same_revisions},
        )

        self.assertEqual(states["different-label"]["state"], "conflict")
        self.assertEqual(states["different-label"]["expected_output"], "")
        self.assertEqual(states["different-label"]["gt_relation"], "unknown")
        self.assertEqual(states["missing-submission"]["state"], "pending")
        self.assertEqual(states["missing-submission"]["expected_output"], "")
        self.assertEqual(states["stale-adjudication"]["state"], "stale")
        self.assertEqual(states["stale-adjudication"]["expected_output"], "")
        self.assertEqual(states["gt-differs"]["gt_relation"], "differs_from_gt")
        self.assertEqual(states["gt-missing"]["gt_relation"], "fills_missing_gt")

    def test_run_projection_shares_labels_without_sharing_review_completion(self) -> None:
        issue_id = "0821-overlap"
        self.add_issues([{"issue_id": issue_id, "gt_label": "正确触发"}], "scope-0821")
        old_run_id = "d4b519b7-ea35-4589-9139-9e1631403a8b"
        rand10_run_id = "95dc9002-16cc-46b5-aa13-84dcf0e5db5a"
        with self.database.connect() as conn:
            for run_id, name, digest, model_label in (
                (old_run_id, "old", "d" * 64, "误触发"),
                (rand10_run_id, "rand10", "9" * 64, "正确触发"),
            ):
                conn.execute(
                    """INSERT INTO model_runs (id, name, source_name, source_sha256, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (run_id, name, f"{name}.csv", digest, "2026-09-20T00:00:00+00:00"),
                )
                conn.execute(
                    """INSERT INTO model_predictions (
                           model_run_id, issue_id, model_label, model_reason, created_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (run_id, issue_id, model_label, f"reason-{name}", "2026-09-20T00:00:00+00:00"),
                )
        old_label = self.create_revision(
            issue_id=issue_id,
            source_run_id=old_run_id,
            expected_output="正确触发",
            author="labeler-old",
        )
        rand10_label = self.create_revision(
            issue_id=issue_id,
            source_run_id=rand10_run_id,
            expected_output="正确触发",
            author="labeler-rand10",
        )
        filters = {
            "baseline_scopes": ["scope-0821"],
            "model_run_id": old_run_id,
            "comparison_status": "all",
        }
        with patch.object(cases_router, "database", self.database), patch.object(
            cases_router, "_review_tag_catalog", return_value=()
        ):
            old_page = cases_router._case_result_with_status_filter(
                filters=filters,
                review_statuses=(),
                label_states=(),
                page=1,
                page_size=10,
            )
            rand10_page = cases_router._case_result_with_status_filter(
                filters={**filters, "model_run_id": rand10_run_id},
                review_statuses=(),
                label_states=(),
                page=1,
                page_size=10,
            )

        old_item = old_page["items"][0]
        rand10_item = rand10_page["items"][0]
        self.assertEqual(old_item["label_state"], rand10_item["label_state"])
        self.assertEqual(old_item["label_state"]["state"], "resolved")
        self.assertEqual(
            set(old_item["label_state"]["source_revision_ids"]),
            {old_label["id"], rand10_label["id"]},
        )
        self.assertIsNone(old_item["annotation"]["id"])
        self.assertIsNone(rand10_item["annotation"]["id"])
        old_overview = self.database.overview(
            baseline_scopes=["scope-0821"], model_run_id=old_run_id
        )
        rand10_overview = self.database.overview(
            baseline_scopes=["scope-0821"], model_run_id=rand10_run_id
        )
        self.assertEqual(old_overview["labelled"], 0)
        self.assertEqual(rand10_overview["labelled"], 0)
        self.assertEqual(
            old_overview["label_state_counts"], rand10_overview["label_state_counts"]
        )
        self.assertEqual(old_overview["label_state_counts"]["resolved"], 1)

    def test_full_multiscope_filter_scans_over_5000_before_paging(self) -> None:
        now = "2026-09-20T00:00:00+00:00"
        scope_a = [
            {
                "issue_id": f"a-{index:05d}",
                "gt_label": "正确触发",
                "baseline_scope": "scope-a",
            }
            for index in range(2600)
        ]
        scope_b = [
            {
                "issue_id": f"b-{index:05d}",
                "gt_label": "误触发" if index == 0 else "正确触发",
                "baseline_scope": "scope-b",
            }
            for index in range(2605)
        ]
        scope_b[1]["gt_label"] = ""
        with self.database.connect() as conn:
            conn.executemany(
                """INSERT INTO issues (
                       issue_id, gt_label, source, baseline_scope, created_at, updated_at
                   ) VALUES (?, ?, 'test', ?, ?, ?)""",
                [
                    (row["issue_id"], row["gt_label"] or None, row["baseline_scope"], now, now)
                    for row in (*scope_a, *scope_b)
                ],
            )
        a_match = self.create_revision(
            issue_id="a-00000", expected_output="正确触发", author="alice"
        )
        b_differs = self.create_revision(
            issue_id="b-00000", expected_output="正确触发", author="bob"
        )
        b_missing = self.create_revision(
            issue_id="b-00001", expected_output="无需协助", author="carol"
        )

        statements: list[str] = []
        original_connect = self.database.connect

        @contextmanager
        def traced_connect():
            with original_connect() as connection:
                connection.set_trace_callback(statements.append)
                yield connection

        self.database.connect = traced_connect
        filters = {
            "baseline_scope": "",
            "baseline_scopes": ["scope-a", "scope-b"],
            "model_run_id": "",
            "comparison_status": "all",
        }
        with patch.object(cases_router, "database", self.database), patch.object(
            cases_router, "_review_tag_catalog", return_value=()
        ):
            last_page = cases_router._case_result_with_status_filter(
                filters=filters,
                review_statuses=(),
                label_states=("none",),
                page=53,
                page_size=100,
            )
            first_scan_statements = list(statements)
            statements.clear()
            matches = cases_router._case_result_with_status_filter(
                filters=filters,
                review_statuses=(),
                label_states=("matches_gt",),
                page=1,
                page_size=100,
            )
            needs_gt_review = cases_router._case_result_with_status_filter(
                filters=filters,
                review_statuses=(),
                label_states=("needs_gt_review",),
                page=1,
                page_size=100,
            )
        candidate_queries = [
            statement
            for statement in first_scan_statements
            if "SELECT DISTINCT i.issue_id, i.baseline_scope, i.gt_label" in statement
        ]
        self.assertEqual(len(candidate_queries), 14)
        self.assertLess(len(first_scan_statements), 100)
        self.assertEqual(last_page["total"], 5202)
        self.assertEqual(last_page["items"][0]["issue_id"], "b-02603")
        self.assertEqual(last_page["items"][1]["issue_id"], "b-02604")
        self.assertEqual(matches["total"], 1)
        self.assertEqual(matches["items"][0]["issue_id"], "a-00000")
        self.assertEqual(matches["items"][0]["label_state"]["gt_relation"], "matches_gt")
        self.assertEqual(needs_gt_review["total"], 2)
        self.assertEqual(
            {item["issue_id"] for item in needs_gt_review["items"]},
            {"b-00000", "b-00001"},
        )
        self.assertEqual(
            self.database.project_issue_label_states("scope-a", ["b-00000"])[
                "b-00000"
            ]["state"],
            "none",
        )
        self.assertEqual(a_match["label_case"]["baseline_scope"], "scope-a")
        self.assertEqual(b_differs["label_case"]["baseline_scope"], "scope-b")
        self.assertEqual(b_missing["label_case"]["baseline_scope"], "scope-b")

        with patch.object(cases_router, "database", self.database), patch.object(
            cases_router, "_review_tag_catalog", return_value=()
        ):
            matching_ids = cases_router._case_issue_ids_with_status_filter(
                filters=filters,
                review_statuses=(),
                label_states=("none",),
            )
        self.assertEqual(len(matching_ids), 5202)
        self.assertEqual(
            self.database.list_work_assignees(
                issue_ids=matching_ids, model_run_id=""
            ),
            [],
        )
        self.assertEqual(
            self.database.review_reason_rows(
                baseline_scopes=["scope-a", "scope-b"],
                issue_ids=matching_ids,
                include_unbound_fallback=True,
                include_bound_history_fallback=True,
            ),
            [],
        )
        self.assertEqual(
            self.database.review_multi_rows(
                baseline_scopes=["scope-a", "scope-b"],
                issue_ids=matching_ids,
            ),
            [],
        )
        self.assertEqual(
            self.database.review_comment_issue_ids(
                issue_ids=matching_ids, model_run_id=""
            ),
            set(),
        )

        export_state: dict[str, object] = {}
        case_batches: list[int] = []
        original_list_cases = self.database.list_cases

        def capture_list_cases(**kwargs):
            case_batches.append(len(kwargs.get("issue_ids") or []))
            return original_list_cases(**kwargs)

        self.database.list_cases = capture_list_cases

        def capture_reason_payload(**kwargs):
            export_state["selected_ids"] = kwargs.get("issue_ids")
            return {"items": []}

        def capture_export_response(payload, export_format):
            export_state["exported_items"] = len(payload.get("items") or [])
            export_state["format"] = export_format
            return Response(content=b"ok", media_type="text/plain")

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/review-reason-analysis/export",
                "headers": [],
                "query_string": b"",
            }
        )
        with patch.object(analysis_router, "database", self.database), patch.object(
            cases_router, "database", self.database
        ), patch.object(
            analysis_router, "resolve_request_baseline_scopes", return_value=["scope-a", "scope-b"]
        ), patch.object(
            filter_parsing, "resolve_request_baseline_scopes", return_value=["scope-a", "scope-b"]
        ), patch.object(
            analysis_router, "resolve_request_baseline_ids", return_value=["scope-a", "scope-b"]
        ), patch.object(
            analysis_router,
            "request_identity",
            return_value=SimpleNamespace(username="tester", verified=True),
        ), patch.object(
            cases_router, "_review_tag_catalog", return_value=()
        ), patch.object(
            analysis_router, "_review_reason_analysis_payload", side_effect=capture_reason_payload
        ), patch.object(
            analysis_router, "_review_analysis_export_response", side_effect=capture_export_response
        ):
            response = asyncio.run(
                analysis_router.export_review_reason_analysis(
                    request,
                    format="csv",
                    label_state="none",
                    baselines="scope-a,scope-b",
                    gallery_scope=True,
                )
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(export_state["selected_ids"]), 5202)
        self.assertEqual(export_state["exported_items"], 5202)
        self.assertEqual(export_state["format"], "csv")
        self.assertEqual(case_batches, [400] * 13 + [2])
