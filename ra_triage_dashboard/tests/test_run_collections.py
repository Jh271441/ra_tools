from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.run_collections import RunCollectionConflictError


class RunCollectionsDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run-collections.sqlite3"
        self.database = Database(self.path)
        self.database.init()

    def issue(self, issue_id: str, label: str) -> dict[str, str]:
        return {"issue_id": issue_id, "gt_label": label}

    def _make_run(self, name: str, rows: list[dict[str, str]]) -> dict[str, str]:
        result, reused = self.database.import_model_run(
            name=name,
            source_name=f"{name}.json",
            source_sha256=hashlib.sha256(f"{name}-{self.temp.name}".encode()).hexdigest(),
            metadata={"test": True},
            rows=rows,
        )
        self.assertFalse(reused)
        return result

    def _freeze_gt_snapshot(self, scope: str) -> str:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT issue_id, gt_label FROM issues WHERE baseline_scope = ? ORDER BY issue_id",
                (scope,),
            ).fetchall()
            snapshot = self.database._create_or_reuse_gt_snapshot_with_conn(
                conn,
                scope=scope,
                gt_mode="strict",
                source_name="test-fixture",
                source_view_id=1,
                source_field="gt_label",
                rows={
                    str(row["issue_id"]): {"gt_label": str(row["gt_label"] or "")}
                    for row in rows
                },
                created_by="test",
                created_by_source="fixture",
                created_by_verified=True,
                activate=True,
                activation_reason="test_fixture",
                mark_change=False,
                scope_lock_held=True,
            )
        return str(snapshot["id"])

    def test_metadata_rename_does_not_create_revision_and_revision_is_append_only(self) -> None:
        first = self._make_run("first", [self.issue("one", "误触发")])
        second = self._make_run("second", [self.issue("one", "误触发")])
        collection = self.database.create_run_collection(
            name="Pair", members=[{"run_id": first["id"], "is_reference": True}, second["id"]],
            idempotency_key="collection-create-once",
        )
        renamed = self.database.rename_run_collection(
            collection_id=collection["id"], expected_revision=1,
            name="Renamed Pair", description="metadata only", actor="test-admin",
        )
        self.assertEqual(renamed["current_revision"], 1)
        self.assertEqual(renamed["metadata_revision"], 1)
        self.assertEqual(len(renamed["history"]), 1)
        with self.assertRaises(RunCollectionConflictError):
            self.database.rename_run_collection(
                collection_id=collection["id"], expected_revision=1,
                expected_metadata_revision=0, name="Stale rename", description="", actor="test-admin",
            )
        revision = self.database.create_run_collection_revision(
            collection_id=collection["id"], expected_revision=1,
            members=[second["id"], {"run_id": first["id"], "is_reference": True}],
            actor="test-admin", idempotency_key="revision-two",
        )
        self.assertEqual(revision["current_revision"], 2)
        self.assertEqual([m["run_id"] for m in revision["current"]["members"]], [second["id"], first["id"]])
        self.assertEqual(
            self.database.create_run_collection_revision(
                collection_id=collection["id"], expected_revision=1,
                members=[second["id"], {"run_id": first["id"], "is_reference": True}],
                actor="test-admin", idempotency_key="revision-two",
            )["current_revision"],
            2,
        )
        with self.assertRaises(RunCollectionConflictError):
            self.database.create_run_collection_revision(
                collection_id=collection["id"], expected_revision=1,
                members=[first["id"]], actor="test-admin", idempotency_key="revision-two",
            )
        with self.database.connect() as conn:
            with self.assertRaisesRegex(Exception, "immutable"):
                conn.execute(
                    "UPDATE run_collection_members SET role = 'mutated' WHERE collection_id = ? AND revision_no = 1",
                    (collection["id"],),
                )
            with self.assertRaisesRegex(Exception, "backwards"):
                conn.execute(
                    "UPDATE run_collections SET current_revision = 1 WHERE id = ?",
                    (collection["id"],),
                )
            audit_count = conn.execute(
                "SELECT COUNT(*) AS count FROM run_collection_audit WHERE collection_id = ?",
                (collection["id"],),
            ).fetchone()["count"]
        self.assertEqual(audit_count, 3)

    def test_concurrent_revisions_use_optimistic_compare_and_swap(self) -> None:
        first = self._make_run("first", [self.issue("one", "误触发")])
        second = self._make_run("second", [self.issue("one", "误触发")])
        collection = self.database.create_run_collection(name="Concurrent", members=[first["id"]])
        other = Database(self.path)

        def append(db: Database, run_id: str):
            try:
                db.create_run_collection_revision(
                    collection_id=collection["id"], expected_revision=1,
                    members=[run_id], actor="test-admin",
                )
                return "created"
            except RunCollectionConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda pair: append(*pair), [(self.database, second["id"]), (other, first["id"])]))
        self.assertCountEqual(outcomes, ["created", "conflict"])
        self.assertEqual(self.database.get_run_collection(collection["id"])["current_revision"], 2)

    def test_concurrent_collection_and_revision_idempotency(self) -> None:
        first = self._make_run("idempotent-first", [self.issue("one", "误触发")])
        second = self._make_run("idempotent-second", [self.issue("one", "误触发")])
        other = Database(self.path)

        def create(db: Database):
            return db.create_run_collection(
                name="Idempotent", members=[first["id"]], idempotency_key="same-create-key"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(create, [self.database, other]))
        self.assertEqual(created[0]["id"], created[1]["id"])
        collection = created[0]

        def append(db: Database):
            return db.create_run_collection_revision(
                collection_id=collection["id"], expected_revision=1,
                members=[first["id"], second["id"]], idempotency_key="same-revision-key",
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            revisions = list(pool.map(append, [self.database, other]))
        self.assertEqual([item["current_revision"] for item in revisions], [2, 2])
        with self.database.connect() as conn:
            revision_count = conn.execute(
                "SELECT COUNT(*) AS count FROM run_collection_revisions WHERE collection_id = ?",
                (collection["id"],),
            ).fetchone()["count"]
            creation_audit_count = conn.execute(
                "SELECT COUNT(*) AS count FROM run_collection_audit WHERE collection_id = ? AND action = 'created'",
                (collection["id"],),
            ).fetchone()["count"]
        self.assertEqual(revision_count, 2)
        self.assertEqual(creation_audit_count, 1)

    def test_failed_evaluation_rolls_back_its_workset_and_exclusion_snapshot(self) -> None:
        scope = "run-collections-rollback"
        self.database.upsert_issues(
            [self.issue("rollback-a", "正确触发")],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        self._freeze_gt_snapshot(scope)
        run = self._make_run("rollback", [{"issue_id": "rollback-a", "model_label": "正确触发"}])
        collection = self.database.create_run_collection(name="Rollback", members=[run["id"]])
        with self.database.connect() as conn:
            before = {
                table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
                for table in ("review_worksets", "run_evaluation_exclusion_snapshots", "run_evaluation_contexts")
            }
        with self.assertRaisesRegex(ValueError, "scoring_policy"):
            self.database.create_run_evaluation(
                collection_id=collection["id"], baseline_scopes=[scope],
                scoring_policy={"version": "unsupported-v9"},
            )
        with self.database.connect() as conn:
            after = {
                table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
                for table in before
            }
        self.assertEqual(after, before)

    def test_gt_reference_fails_closed_without_active_snapshot(self) -> None:
        scope = "run-collections-no-snapshot"
        self.database.upsert_issues(
            [self.issue("no-snapshot", "正确触发")],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        run = self._make_run("no-snapshot-run", [
            {"issue_id": "no-snapshot", "model_label": "正确触发"},
        ])
        collection = self.database.create_run_collection(
            name="No snapshot", members=[run["id"]]
        )
        with self.assertRaisesRegex(ValueError, "active GT snapshot"):
            self.database.create_run_evaluation(
                collection_id=collection["id"], baseline_scopes=[scope],
            )

    def test_evaluation_freezes_reference_collection_and_predictions(self) -> None:
        scope = "run-collections-history"
        self.database.upsert_issues(
            [self.issue("a", "误触发"), self.issue("b", "正确触发"), self.issue("c", "无需协助")],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        self._freeze_gt_snapshot(scope)
        baseline = self._make_run("baseline", [
            {"issue_id": "a", "model_label": "误触发"},
            {"issue_id": "b", "model_label": "误触发"},
        ])
        candidate = self._make_run("candidate", [
            {"issue_id": "a", "model_label": "正确触发"},
            {"issue_id": "c", "model_label": "无需协助"},
        ])
        with self.database.connect() as conn:
            review_revision = conn.execute(
                """
                INSERT INTO model_review_revisions (
                    model_run_id, issue_id, status, reviewer, created_at
                ) VALUES (?, 'a', 'completed', 'reviewer-one', '2026-09-22T00:00:00Z')
                """,
                (baseline["id"],),
            )
            conn.execute(
                """
                INSERT INTO model_review_heads (
                    model_run_id, issue_id, reviewer, revision_id, updated_at
                ) VALUES (?, 'a', 'reviewer-one', ?, '2026-09-22T00:00:00Z')
                """,
                (baseline["id"], review_revision.lastrowid),
            )
        collection = self.database.create_run_collection(
            name="Evaluation", members=[
                {"run_id": baseline["id"], "is_reference": True},
                {"run_id": candidate["id"]},
            ],
        )
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=[scope],
        )
        self.assertEqual(evaluation["summary"]["reference_denominator"], 3)
        self.assertEqual(evaluation["summary"]["runs"][0]["transitions_vs_reference"], None)
        frozen_issue = next(item for item in evaluation["items"] if item["issue_id"] == "a")
        self.assertEqual(frozen_issue["predictions"][baseline["id"]]["model_reviews"][0]["reviewer"], "reviewer-one")
        self.assertEqual(frozen_issue["predictions"][candidate["id"]]["model_reviews"], [])
        self.assertEqual(
            evaluation["summary"]["runs"][1]["transitions_vs_reference"],
            {"P2P": 0, "P2F": 1, "F2P": 1, "F2F": 1},
        )
        with self.database.connect() as conn:
            with self.assertRaisesRegex(Exception, "complete"):
                conn.execute(
                    "INSERT INTO run_collection_members (collection_id, revision_no, ordinal, run_id) VALUES (?, 1, 3, 'late-run')",
                    (collection["id"],),
                )
            with self.assertRaisesRegex(Exception, "complete"):
                conn.execute(
                    "INSERT INTO run_evaluation_items (context_id, ordinal, issue_id) VALUES (?, 4, 'late-issue')",
                    (evaluation["id"],),
                )
            with self.assertRaisesRegex(Exception, "complete"):
                conn.execute(
                    "INSERT INTO run_evaluation_exclusion_items (content_sha256, issue_id, ordinal) VALUES (?, 'late-exclusion', 1)",
                    (evaluation["exclusion"]["sha256"],),
                )
        before = self.database.get_run_evaluation(evaluation["id"])
        self.database.upsert_issues(
            [self.issue("a", "正确触发"), self.issue("b", "误触发"), self.issue("c", "误触发")],
            source="later-gt", replace_gt=True, baseline_scope=scope,
        )
        next_revision = self.database.create_run_collection_revision(
            collection_id=collection["id"], expected_revision=1,
            members=[candidate["id"], {"run_id": baseline["id"], "is_reference": True}],
        )
        after = self.database.get_run_evaluation(evaluation["id"])
        self.assertEqual(before["reference"]["sha256"], after["reference"]["sha256"])
        self.assertEqual(before["summary"], after["summary"])
        self.assertEqual(after["collection_revision"], 1)
        self.assertEqual(next_revision["current_revision"], 2)
        exported = self.database.export_run_evaluation(evaluation["id"])
        self.assertEqual(exported["export_provenance"]["collection_revision"], 1)
        self.assertEqual(exported["export_provenance"]["workset_sha256"], evaluation["workset_sha256"])

    def test_exclusions_and_source_run_selection_are_explicit(self) -> None:
        scope = "run-collections-bias"
        self.database.upsert_issues(
            [self.issue(f"bias-{index}", "正确触发") for index in range(4)],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        self._freeze_gt_snapshot(scope)
        first = self._make_run("source", [{"issue_id": "bias-0", "model_label": "正确触发"}, {"issue_id": "bias-1", "model_label": "正确触发"}])
        second = self._make_run("other", [{"issue_id": f"bias-{index}", "model_label": "正确触发"} for index in range(4)])
        collection = self.database.create_run_collection(name="Bias", members=[first["id"], second["id"]])
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=[scope],
            selection_source_run_id=first["id"], excluded_issue_ids=["bias-0"],
        )
        self.assertEqual(evaluation["summary"]["workset_count"], 2)
        self.assertEqual(evaluation["summary"]["excluded_count"], 1)
        self.assertEqual(evaluation["summary"]["reference_denominator"], 1)
        self.assertIn(first["id"], evaluation["selection_bias_warning"])
        self.assertEqual(len(evaluation["exclusion"]["sha256"]), 64)

    def test_evaluation_workset_binds_shared_labeling_campaign_and_run_group(self) -> None:
        scope = "run-collections-campaign"
        issue_ids = ["campaign-a", "campaign-b"]
        self.database.upsert_issues(
            [self.issue(issue_ids[0], "误触发"), self.issue(issue_ids[1], "正确触发")],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        snapshot_status = self.database.apply_gt_sync_snapshot(
            scope=scope,
            rows=[{"issue_id": issue_ids[0], "gt_label": "误触发"}, {"issue_id": issue_ids[1], "gt_label": "正确触发"}],
            source_name="test", source_view_id=1000, source_field="gt",
            trigger="test", requested_by="admin", requested_by_source="test",
            requested_by_verified=True, expected_issue_ids=issue_ids,
        )
        gt_snapshot_id = snapshot_status["active_gt_snapshot"]["id"]
        first = self._make_run("campaign-first", [{"issue_id": issue_ids[0], "model_label": "误触发"}])
        second = self._make_run("campaign-second", [{"issue_id": issue_ids[1], "model_label": "正确触发"}])
        collection = self.database.create_run_collection(
            name="Campaign Integration", members=[first["id"], second["id"]]
        )
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=[scope],
        )
        workset_id = evaluation["workset"]["workset_id"]
        self.assertTrue(workset_id)
        references = [{
            "baseline_scope": scope,
            "reference_type": "gt_snapshot",
            "reference_id": gt_snapshot_id,
        }]
        labeling = self.database.create_campaign(
            spec={
                "purpose": "labeling", "lifecycle": "draft", "campaign_name": "Shared labels",
                "workset_id": workset_id, "references": references,
                "members": [{"issue_id": issue_id, "assignees": ["reviewer"]} for issue_id in issue_ids],
            },
            actor="admin", actor_source="test", actor_verified=True,
            idempotency_key="evaluation-labeling-campaign",
        )
        self.assertEqual(labeling["campaign"]["purpose"], "labeling")
        self.assertFalse(labeling["campaign"]["evaluation_run_id"])
        group = self.database.create_campaign_group(
            name="Per Run Review", purpose="model_review",
            campaigns=[
                {
                    "purpose": "model_review", "lifecycle": "draft", "campaign_name": f"Review {run_id[:8]}",
                    "evaluation_run_id": run_id, "workset_id": workset_id,
                    "references": references,
                    "members": [{"issue_id": issue_id, "assignees": ["reviewer"]} for issue_id in issue_ids],
                }
                for run_id in (first["id"], second["id"])
            ],
            actor="admin", actor_source="test", actor_verified=True,
            idempotency_key="evaluation-model-review-group",
        )
        self.assertEqual(group["purpose"], "model_review")
        self.assertEqual(len(group["campaigns"]), 2)
        self.assertEqual({item["campaign"]["workset_id"] for item in group["campaigns"]}, {workset_id})
        self.assertEqual({item["campaign"]["evaluation_run_id"] for item in group["campaigns"]}, {first["id"], second["id"]})

    def test_missing_runs_remain_in_history_and_5000_items_are_batched(self) -> None:
        scope = "run-collections-5000"
        issue_rows = [self.issue(f"perf-{index:05d}", "正确触发") for index in range(5000)]
        self.database.upsert_issues(issue_rows, source="test", replace_gt=True, baseline_scope=scope)
        self._freeze_gt_snapshot(scope)
        first = self._make_run("perf-first", [
            {"issue_id": f"perf-{index:05d}", "model_label": "正确触发"}
            for index in range(0, 5000, 2)
        ])
        second = self._make_run("perf-second", [
            {"issue_id": f"perf-{index:05d}", "model_label": "误触发"}
            for index in range(1, 5000, 2)
        ])
        collection = self.database.create_run_collection(
            name="Performance", members=[first["id"], second["id"]]
        )
        started = time.perf_counter()
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=[scope]
        )
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 15.0)
        self.assertEqual(evaluation["summary"]["workset_count"], 5000)
        self.assertEqual(evaluation["summary"]["reference_denominator"], 5000)
        with self.database.connect() as conn:
            plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT model_label FROM model_predictions WHERE model_run_id = ? AND issue_id = ?",
                (first["id"], "perf-00000"),
            ).fetchall()
        self.assertTrue(any("model_run_id" in str(row["detail"]) for row in plan))
        self.database.delete_model_run(second["id"])
        detail = self.database.get_run_collection(collection["id"])
        deleted = next(item for item in detail["current"]["members"] if item["run_id"] == second["id"])
        self.assertFalse(deleted["available_now"])
        historical = self.database.get_run_evaluation(evaluation["id"])
        self.assertEqual(historical["summary"]["runs"][1]["correct_count"], 0)
        self.assertTrue(historical["members"][1]["run"]["available_at_revision"])

    def test_multiscope_workset_campaigns_shared_projection_and_context_reuse(self) -> None:
        scopes = [f"multi-scope-{index}" for index in range(5)]
        issue_rows = []
        for scope in scopes:
            self.database.upsert_issues(
                [{"issue_id": f"{scope}-a", "gt_label": "正确触发"},
                 {"issue_id": f"{scope}-b", "gt_label": "误触发"}],
                source="test", replace_gt=True, baseline_scope=scope,
            )
            issue_rows.extend([
                {"issue_id": f"{scope}-a", "gt_label": "正确触发"},
                {"issue_id": f"{scope}-b", "gt_label": "误触发"},
            ])
            self._freeze_gt_snapshot(scope)
        first = self._make_run("multi-first", [
            {"issue_id": item["issue_id"], "model_label": item["gt_label"]}
            for item in issue_rows
        ])
        second = self._make_run("multi-second", [
            {"issue_id": item["issue_id"], "model_label": "正确触发"}
            for item in issue_rows
        ])
        collection = self.database.create_run_collection(
            name="Multi", members=[first["id"], second["id"]]
        )
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=scopes,
            comparison_reference_run_id=first["id"],
        )
        self.assertEqual(evaluation["workset"]["scope_count"], 5)
        self.assertEqual(evaluation["workset"]["baseline_scopes"], scopes)
        self.assertEqual(evaluation["summary"]["workset_count"], 10)
        self.assertEqual(
            evaluation["items"][0]["shared_label"]["source"]["reference_type"],
            "shared_label_projection",
        )
        self.assertEqual(len(evaluation["items"][0]["shared_label"]["sha256"]), 64)
        self.assertIn("supported_coverage", evaluation["summary"]["runs"][0])
        self.assertLess(len(json.dumps(evaluation, ensure_ascii=False)), 250000)
        task_context = self.database.get_run_evaluation_task_context(evaluation["id"])
        self.assertEqual(len(task_context["workset"]["issue_ids"]), 10)
        references = [
            {
                "baseline_scope": item["baseline_scope"],
                "reference_type": "gt_snapshot",
                "reference_id": item["id"],
            }
            for item in evaluation["reference"]["snapshot"]["scope_snapshots"]
        ]
        labeling = self.database.create_campaign(
            spec={
                "purpose": "labeling", "lifecycle": "draft",
                "campaign_name": "Multi shared labels",
                "workset_id": evaluation["workset"]["workset_id"],
                "references": references,
                "members": [
                    {"issue_id": item["issue_id"], "assignees": ["reviewer"]}
                    for item in issue_rows
                ],
            },
            actor="admin", actor_source="test", actor_verified=True,
            idempotency_key="multi-labeling",
        )
        self.assertEqual(set(labeling["campaign"]["baseline_scopes"]), set(scopes))
        group = self.database.create_campaign_group(
            name="Multi model reviews", purpose="model_review",
            campaigns=[
                {
                    "purpose": "model_review", "lifecycle": "draft",
                    "campaign_name": f"Review {run_id[:8]}",
                    "evaluation_run_id": run_id,
                    "workset_id": evaluation["workset"]["workset_id"],
                    "references": references,
                    "members": [
                        {"issue_id": item["issue_id"], "assignees": ["reviewer"]}
                        for item in issue_rows
                    ],
                }
                for run_id in (first["id"], second["id"])
            ],
            actor="admin", actor_source="test", actor_verified=True,
            idempotency_key="multi-model-review",
        )
        self.assertEqual(len(group["campaigns"]), 2)
        reused = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=scopes,
            comparison_reference_run_id=first["id"],
        )
        self.assertEqual(reused["id"], evaluation["id"])
        for item in issue_rows:
            self.database.create_label_revision(
                issue_id=item["issue_id"],
                expected_output=item["gt_label"],
                tags=[], evidence_gaps=[], rationale="multi-scope snapshot",
                is_excluded=False, author="snapshot-reviewer",
                author_source="test", author_verified=True,
            )
        label_snapshots = {
            scope: self.database.create_label_result_snapshot(
                workset_id=evaluation["workset"]["workset_id"],
                baseline_scope=scope,
                created_by="admin", created_by_source="test",
                created_by_verified=True,
            )
            for scope in scopes
        }
        self.assertEqual(
            {item["member_count"] for item in label_snapshots.values()}, {2}
        )
        label_evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"],
            workset_id=evaluation["workset"]["workset_id"],
            reference_type="label_result",
            reference_ids={
                scope: snapshot["id"] for scope, snapshot in label_snapshots.items()
            },
            comparison_reference_run_id=first["id"],
        )
        self.assertEqual(label_evaluation["reference"]["type"], "label_result")
        self.assertEqual(
            len(label_evaluation["reference"]["snapshot"]["scope_snapshots"]), 5
        )
        with self.assertRaisesRegex(ValueError, "不支持.*reference_type=run"):
            self.database.create_run_evaluation(
                collection_id=collection["id"], baseline_scopes=scopes,
                reference_type="run", reference_id=first["id"],
            )
        with self.database.connect() as conn:
            scope_rows = conn.execute(
                "SELECT COUNT(*) AS count FROM review_workset_scopes WHERE workset_id = ?",
                (evaluation["workset"]["workset_id"],),
            ).fetchone()["count"]
        self.assertEqual(scope_rows, 5)

    def test_label_result_snapshot_is_an_official_frozen_reference(self) -> None:
        scope = "run-collections-label-reference"
        issue_id = "label-reference-issue"
        self.database.upsert_issues(
            [{"issue_id": issue_id, "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        workset = self.database.create_review_workset(
            baseline_scope=scope, issue_ids=[issue_id],
            name="Label reference", created_by="admin",
        )
        self.database.ensure_label_case(issue_id=issue_id)
        self.database.create_label_revision(
            issue_id=issue_id, expected_output="正确触发", tags=[],
            evidence_gaps=[], rationale="snapshot", is_excluded=False,
            author="reviewer", author_source="test", author_verified=True,
        )
        snapshot = self.database.create_label_result_snapshot(
            workset_id=workset["id"], created_by="admin",
            created_by_source="test", created_by_verified=True,
        )
        run = self._make_run("label-reference-run", [
            {"issue_id": issue_id, "model_label": "正确触发"},
        ])
        collection = self.database.create_run_collection(
            name="Label reference collection", members=[run["id"]]
        )
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], workset_id=workset["id"],
            reference_type="label_result", reference_id=snapshot["id"],
        )
        self.assertEqual(evaluation["reference"]["type"], "label_result")
        self.assertEqual(evaluation["reference"]["id"], snapshot["id"])
        self.assertEqual(evaluation["items"][0]["shared_label"]["method"], "single")

    def test_gt_reference_and_shared_human_label_are_distinct_and_frozen(self) -> None:
        scope = "run-collections-divergent-label"
        issue_id = "divergent-label-issue"
        self.database.upsert_issues(
            [{"issue_id": issue_id, "gt_label": "无需协助"}],
            source="test", replace_gt=True, baseline_scope=scope,
        )
        self.database.ensure_label_case(issue_id=issue_id)
        self.database.create_label_revision(
            issue_id=issue_id, expected_output="误触发", tags=[],
            evidence_gaps=[], rationale="human label differs from GT",
            is_excluded=False, author="reviewer", author_source="test",
            author_verified=True,
        )
        self._freeze_gt_snapshot(scope)
        run = self._make_run("divergent-label-run", [
            {"issue_id": issue_id, "model_label": "误触发"},
        ])
        collection = self.database.create_run_collection(
            name="Divergent label", members=[run["id"]]
        )
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=[scope],
        )
        item = evaluation["items"][0]
        self.assertEqual(item["reference_label"], "无需协助")
        self.assertEqual(item["shared_label"]["state"], "resolved")
        self.assertEqual(item["shared_label"]["expected_output"], "误触发")
        self.assertEqual(item["shared_label"]["gt_relation"], "differs_from_gt")
        self.assertTrue(item["shared_label"]["source"]["source_revision_ids"])
        before = self.database.get_run_evaluation(evaluation["id"])
        self.database.create_label_revision(
            issue_id=issue_id, expected_output="正确触发", tags=[],
            evidence_gaps=[], rationale="later human update",
            is_excluded=False, author="reviewer", author_source="test",
            author_verified=True, expected_previous_revision_id=1,
        )
        self.database.upsert_issues(
            [{"issue_id": issue_id, "gt_label": "正确触发"}],
            source="later-gt", replace_gt=True, baseline_scope=scope,
        )
        after = self.database.get_run_evaluation(evaluation["id"])
        self.assertEqual(after["reference"]["sha256"], before["reference"]["sha256"])
        self.assertEqual(after["items"][0]["shared_label"], before["items"][0]["shared_label"])

    def test_pairwise_shadow_reconciles_with_v1_evaluation_union(self) -> None:
        scope = "run-collections-pairwise-shadow"
        rows = [
            self.issue("shadow-a", "正确触发"),
            self.issue("shadow-b", "误触发"),
            self.issue("shadow-c", "无需协助"),
            self.issue("shadow-d", "正确触发"),
        ]
        self.database.upsert_issues(rows, source="test", replace_gt=True, baseline_scope=scope)
        self._freeze_gt_snapshot(scope)
        baseline = self._make_run("shadow-baseline", [
            {"issue_id": "shadow-a", "model_label": "正确触发"},
            {"issue_id": "shadow-b", "model_label": "正确触发"},
        ])
        candidate = self._make_run("shadow-candidate", [
            {"issue_id": "shadow-a", "model_label": "正确触发"},
            {"issue_id": "shadow-c", "model_label": "无需协助"},
        ])
        collection = self.database.create_run_collection(
            name="Pairwise shadow", members=[
                {"run_id": baseline["id"], "is_reference": True},
                candidate["id"],
            ]
        )
        evaluation = self.database.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=[scope],
            comparison_reference_run_id=baseline["id"],
        )
        legacy = self.database.compare_model_runs(
            baseline_run_id=baseline["id"], candidate_run_id=candidate["id"],
            baseline_scopes=[scope], page_size=100,
        )
        self.assertEqual(legacy["summary"]["total_count"], evaluation["summary"]["pairwise_union_denominator"])
        for side, metric in zip(("baseline", "candidate"), evaluation["summary"]["runs"]):
            shadow = legacy["summary"][side]
            self.assertEqual(shadow["correct_count"], metric["correct_count"])
            self.assertEqual(shadow["accuracy"], metric["accuracy"])
            self.assertEqual(shadow["prediction_count"], metric["supported_count"])
        self.assertEqual(
            legacy["summary"]["transition_counts"],
            evaluation["summary"]["runs"][1]["transitions_vs_reference"],
        )
        self.assertEqual(evaluation["summary"]["workset_count"], 4)
        self.assertEqual(evaluation["summary"]["workset_missing_count"], 1)


if __name__ == "__main__":
    unittest.main()
