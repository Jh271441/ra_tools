from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import Database, LabelAnnotationConflictError
from ra_triage_dashboard.app.labeling_migration import (
    legacy_labeling_inventory,
    migrate_legacy_labeling,
    reconcile_legacy_labeling,
)
from ra_triage_dashboard.app.routers.labeling import _public_label_attachment
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class CaseLabelingTest(unittest.TestCase):
    def make_db(self, root: str) -> Database:
        database = Database(Path(root) / "labeling.sqlite")
        database.init()
        database.upsert_issues(
            [
                {"issue_id": "cn1", "gt_label": "正确触发"},
                {"issue_id": "cn2", "gt_label": ""},
            ],
            source="test",
            replace_gt=True,
            baseline_scope="scope",
        )
        return database

    def test_free_label_revision_is_independent_gt_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            saved = database.create_label_revision(
                issue_id="cn1",
                expected_output="误触发",
                tags=["traffic_light"],
                evidence_gaps=[],
                rationale="GT 应为误触发",
                is_excluded=False,
                author="alice",
                author_source="kylin_ticket",
                author_verified=True,
                expected_previous_revision_id=None,
                attachments=[{
                    "id": "22222222-2222-4222-8222-222222222222",
                    "original_name": "new.png", "stored_name": "new.png",
                    "media_type": "image/png", "size_bytes": 20,
                    "width": 4, "height": 4, "sha256": "b" * 64,
                }],
            )
            label_case = saved["label_case"]
            self.assertEqual(label_case["resolution"]["state"], "resolved")
            self.assertEqual(label_case["resolution"]["method"], "single")
            detail = database.get_label_case(label_case["id"])
            self.assertEqual(len(detail["revisions"][0]["attachments"]), 1)
            self.assertEqual(
                database.get_label_attachment("22222222-2222-4222-8222-222222222222")["stored_name"],
                "new.png",
            )
            candidates = database.label_gt_candidates(["scope"])
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["issue_id"], "cn1")
            self.assertEqual(candidates[0]["expected_output"], "误触发")

    def test_public_label_attachment_exposes_only_opaque_url(self) -> None:
        public = _public_label_attachment({
            "id": "asset-1", "original_name": "private.png",
            "stored_name": "server-path.png", "media_type": "image/png",
            "size_bytes": 10, "width": 2, "height": 2, "sha256": "a" * 64,
        })
        self.assertNotIn("stored_name", public)
        self.assertNotIn("sha256", public)
        self.assertNotIn("original_name", public)
        self.assertTrue(public["url"].endswith("/api/labeling/attachments/asset-1"))

    def test_task_conflict_requires_adjudication_and_stales_on_new_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            assignments = distribute_issue_ids(
                ["cn1"],
                [{"name": "alice"}, {"name": "bob"}],
                seed=1,
                reviewers_per_issue=2,
            )
            split = database.apply_work_split(
                assignments=assignments,
                created_by="admin",
                reviewers_per_issue=2,
            )
            workset = database.create_review_workset(
                baseline_scope="scope",
                issue_ids=["cn1"],
                name="double label",
                created_by="admin",
            )
            database.bind_labeling_task(task_id=split["split_id"], workset_id=workset["id"])
            alice = database.create_label_revision(
                issue_id="cn1", task_id=split["split_id"],
                expected_output="误触发", tags=[], evidence_gaps=[], rationale="a",
                is_excluded=False, author="alice", author_source="kylin_ticket",
                author_verified=True, expected_previous_revision_id=None,
            )
            bob = database.create_label_revision(
                issue_id="cn1", task_id=split["split_id"],
                expected_output="正确触发", tags=[], evidence_gaps=[], rationale="b",
                is_excluded=False, author="bob", author_source="kylin_ticket",
                author_verified=True, expected_previous_revision_id=None,
            )
            label_case = bob["label_case"]
            self.assertEqual(label_case["resolution"]["state"], "conflict")
            blocked = database.label_gt_candidates(["scope"])
            self.assertEqual(blocked[0]["status"], "unresolved")
            self.assertEqual(blocked[0]["blocked_sources"][0]["state"], "conflict")
            source_ids = [item["id"] for item in label_case["resolution"]["heads"]]
            adjudicated = database.adjudicate_label_case(
                label_case_id=label_case["id"],
                source_revision_ids=source_ids,
                expected_output="误触发",
                tags=[], evidence_gaps=[], rationale="裁决采用误触发",
                is_excluded=False, actor="carol", actor_source="kylin_ticket",
                actor_verified=True, expected_previous_resolution_id=None,
            )
            self.assertEqual(adjudicated["resolution"]["method"], "adjudication")
            self.assertEqual(adjudicated["resolution"]["expected_output"], "误触发")
            alice_next = database.create_label_revision(
                issue_id="cn1", task_id=split["split_id"],
                expected_output="正确触发", tags=[], evidence_gaps=[], rationale="a2",
                is_excluded=False, author="alice", author_source="kylin_ticket",
                author_verified=True,
                expected_previous_revision_id=alice["id"],
            )
            self.assertEqual(alice_next["label_case"]["resolution"]["state"], "stale")
            blocked = database.label_gt_candidates(["scope"])
            self.assertEqual(blocked[0]["status"], "unresolved")
            self.assertEqual(blocked[0]["blocked_sources"][0]["state"], "stale")

    def test_free_label_cannot_be_adjudicated_as_task_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            first = database.create_label_revision(
                issue_id="cn1", expected_output="误触发", tags=[], evidence_gaps=[],
                rationale="first", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=None,
            )
            database.create_label_revision(
                issue_id="cn1", expected_output="正确触发", tags=[], evidence_gaps=[],
                rationale="second", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=first["id"],
            )
            with self.assertRaisesRegex(ValueError, "自由标注"):
                database.adjudicate_label_case(
                    label_case_id=first["label_case"]["id"],
                    source_revision_ids=[first["id"]],
                    expected_output="误触发", tags=[], evidence_gaps=[], rationale="stale",
                    is_excluded=False, actor="writer", actor_source="kylin_ticket",
                    actor_verified=True, expected_previous_resolution_id=None,
                )

    def test_gt_export_preview_detects_source_or_gt_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            first = database.create_label_revision(
                issue_id="cn1", expected_output="误触发", tags=[], evidence_gaps=[],
                rationale="candidate", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=None,
            )
            preview = database.create_label_gt_export_preview(
                baseline_scopes=["scope"], created_by="alice",
                created_by_source="kylin_ticket", created_by_verified=True,
            )
            self.assertEqual(preview["item_count"], 1)
            self.assertEqual(database.validate_label_gt_export_batch(preview["id"])["stale_issue_ids"], [])
            database.create_label_revision(
                issue_id="cn1", expected_output="无需协助", tags=[], evidence_gaps=[],
                rationale="changed", is_excluded=False, author="alice",
                author_source="kylin_ticket", author_verified=True,
                expected_previous_revision_id=first["id"],
            )
            stale = database.validate_label_gt_export_batch(preview["id"])
            self.assertEqual(stale["status"], "stale")
            self.assertEqual(stale["stale_issue_ids"], ["cn1"])

    def test_legacy_labeling_migration_preserves_rationale_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            legacy = database.create_annotation(
                issue_id="cn1", model_run_id="", work_split_id="",
                label="误触发", review_status="needs_gt_review",
                tags=["traffic_light"], missing_evidence=["missing_camera"],
                note="原始标注依据", author="alice",
                author_source="kylin_ticket", author_verified=True,
                attachments=[{
                    "id": "11111111-1111-4111-8111-111111111111",
                    "original_name": "evidence.png",
                    "stored_name": "evidence.png",
                    "media_type": "image/png",
                    "size_bytes": 10,
                    "width": 2,
                    "height": 2,
                    "sha256": "a" * 64,
                }],
                expected_previous_annotation_id=None,
            )
            comment = database.create_review_comment(
                issue_id="cn1", model_run_id="", body="原始标注讨论",
                author="alice", author_source="kylin_ticket", author_verified=True,
            )
            inventory = legacy_labeling_inventory(database, scopes=["scope"])
            self.assertEqual(inventory["datasets"][0]["issue_count"], 2)
            self.assertEqual(inventory["datasets"][0]["annotated_issue_count"], 1)
            first = migrate_legacy_labeling(
                database,
                scopes=["scope"],
                tag_catalog=[],
                policy_version="test-v1",
            )
            second = migrate_legacy_labeling(
                database,
                scopes=["scope"],
                tag_catalog=[],
                policy_version="test-v1",
            )
            self.assertEqual(first["revision_count"], 1)
            self.assertEqual(second["revision_count"], 1)
            cases = database.label_cases_for_issue("cn1")
            self.assertEqual(len(cases), 1)
            detail = database.get_label_case(cases[0]["id"])
            self.assertEqual(len(detail["revisions"]), 1)
            self.assertEqual(detail["revisions"][0]["source_annotation_id"], legacy["id"])
            self.assertEqual(detail["revisions"][0]["rationale"], "原始标注依据")
            self.assertEqual(detail["revisions"][0]["evidence_gaps"], ["missing_camera"])
            self.assertEqual(len(detail["revisions"][0]["attachments"]), 1)
            self.assertEqual(
                detail["revisions"][0]["attachments"][0]["source_review_attachment_id"],
                "11111111-1111-4111-8111-111111111111",
            )
            comments = database.list_label_comments(issue_id="cn1")
            self.assertEqual([item["id"] for item in comments], [comment["id"]])
            self.assertEqual(comments[0]["body"], "原始标注讨论")
            with self.assertRaisesRegex(ValueError, "迁移后的标注来源"):
                database.delete_annotation(issue_id="cn1", annotation_id=legacy["id"])
            reconciliation = reconcile_legacy_labeling(
                database, scopes=["scope"], policy_version="test-v1"
            )
            self.assertTrue(reconciliation["passed"], reconciliation["errors"])
            shadow = database.labeling_scope_states(["scope"])[0]
            self.assertEqual(shadow["status"], "shadow")
            active = database.set_labeling_scope_state(
                baseline_scope="scope", status="active",
                policy_version="test-v1",
                source_inventory_sha256=reconciliation["source_inventory_sha256"],
                updated_by="admin", expected_epoch=0,
            )
            self.assertEqual(active["status"], "active")
            self.assertEqual(active["epoch"], 1)
            self.assertEqual(database.active_labeling_scopes(), ("scope",))
            database.create_annotation(
                issue_id="cn2", model_run_id="", work_split_id="",
                label="正确触发", review_status="pending", tags=[],
                missing_evidence=[], note="cutover 后的新 Review",
                author="bob", author_source="kylin_ticket",
                author_verified=True, expected_previous_annotation_id=None,
            )
            with self.assertRaisesRegex(ValueError, "不能直接重新回填"):
                migrate_legacy_labeling(
                    database, scopes=["scope"], tag_catalog=[],
                    policy_version="test-v1",
                )
            self.assertEqual(
                database.labeling_scope_states(["scope"])[0]["status"],
                "active",
            )

    def test_multi_scope_backfill_reconciles_and_activates_independently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            database.upsert_issues(
                [{"issue_id": "cn3", "gt_label": "无需协助"}],
                source="test", replace_gt=True, baseline_scope="scope-two",
            )
            for issue_id, label in (("cn1", "误触发"), ("cn3", "无需协助")):
                database.create_annotation(
                    issue_id=issue_id, model_run_id="", work_split_id="",
                    label=label, review_status="pending", tags=[],
                    missing_evidence=[], note=f"label {issue_id}",
                    author="alice", author_source="kylin_ticket",
                    author_verified=True, expected_previous_annotation_id=None,
                )
                database.create_review_comment(
                    issue_id=issue_id, model_run_id="", body=f"comment {issue_id}",
                    author="alice", author_source="kylin_ticket",
                    author_verified=True,
                )
            migrated = migrate_legacy_labeling(
                database, scopes=["scope", "scope-two"], tag_catalog=[],
                policy_version="test-multi-v1",
            )
            fingerprints = migrated["source_inventory_sha256_by_scope"]
            self.assertEqual(set(fingerprints), {"scope", "scope-two"})
            self.assertNotEqual(fingerprints["scope"], fingerprints["scope-two"])
            for scope in ("scope", "scope-two"):
                reconciliation = reconcile_legacy_labeling(
                    database, scopes=[scope], policy_version="test-multi-v1"
                )
                self.assertTrue(reconciliation["passed"], reconciliation["errors"])
                self.assertEqual(
                    reconciliation["source_inventory_sha256"], fingerprints[scope]
                )

    def test_legacy_blind_task_migrates_as_labeling_workset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            assignments = distribute_issue_ids(
                ["cn1"], [{"name": "alice"}, {"name": "bob"}],
                seed=2, reviewers_per_issue=2,
            )
            split = database.apply_work_split(
                assignments=assignments, created_by="admin",
                reviewers_per_issue=2,
            )
            for author, label in (("alice", "误触发"), ("bob", "正确触发")):
                database.create_annotation(
                    issue_id="cn1", model_run_id="",
                    work_split_id=split["split_id"], label=label,
                    review_status="needs_gt_review", tags=[], missing_evidence=[],
                    note=f"{author} rationale", author=author,
                    author_source="kylin_ticket", author_verified=True,
                    expected_previous_annotation_id=None,
                )
            migrated = migrate_legacy_labeling(
                database, scopes=["scope"], tag_catalog=[], policy_version="test-task-v1"
            )
            self.assertEqual(migrated["task_count"], 1)
            tasks = database.list_labeling_tasks(["scope"])
            self.assertEqual([item["id"] for item in tasks], [split["split_id"]])
            cases = database.label_cases_for_issue("cn1", split["split_id"])
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["resolution"]["state"], "conflict")
            self.assertEqual(cases[0]["resolution"]["submitted_count"], 2)

    def test_list_label_comments_includes_task_threads_in_case_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            workset = database.create_review_workset(
                baseline_scope="scope", issue_ids=["cn1"], created_by="admin",
            )
            task = database.create_labeling_task(
                workset_id=workset["id"],
                assignments=[{"name": "alice", "issue_ids": ["cn1"]}],
                created_by="admin", seed=1, reviewers_per_issue=1, overlap_ratio=0,
            )
            case_comment = database.create_review_comment(
                issue_id="cn1", model_run_id="", body="Case 历史讨论",
                author="alice", author_source="kylin_ticket", author_verified=True,
            )
            task_comment = database.create_review_comment(
                issue_id="cn1", model_run_id="", body="任务讨论",
                author="bob", author_source="kylin_ticket", author_verified=True,
            )
            database.link_label_comment(
                comment_id=case_comment["id"], task_id="",
                source_run_id="", policy_version="test-v1",
            )
            database.link_label_comment(
                comment_id=task_comment["id"], task_id=task["id"],
                source_run_id="", policy_version="test-v1",
            )
            unscoped = database.list_label_comments(issue_id="cn1")
            self.assertEqual(
                [item["id"] for item in unscoped],
                [case_comment["id"], task_comment["id"]],
            )
            scoped = database.list_label_comments(issue_id="cn1", task_id=task["id"])
            self.assertEqual(
                [item["id"] for item in scoped],
                [case_comment["id"], task_comment["id"]],
            )

    def test_labeling_task_progress_aggregates_per_task_and_assignee(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            database.upsert_issues(
                [{"issue_id": "cn3", "gt_label": ""}],
                source="test", replace_gt=True, baseline_scope="scope",
            )
            workset = database.create_review_workset(
                baseline_scope="scope", issue_ids=["cn1", "cn2", "cn3"],
                name="progress task", created_by="admin",
            )
            task = database.create_labeling_task(
                workset_id=workset["id"],
                assignments=[
                    {"name": "alice", "issue_ids": ["cn1", "cn2"]},
                    {"name": "bob", "issue_ids": ["cn3"]},
                ],
                created_by="admin", seed=1, reviewers_per_issue=1, overlap_ratio=0,
            )
            task_id = task["id"]
            for issue_id, author, output in (
                ("cn1", "alice", "误触发"),
                ("cn3", "bob", "正确触发"),
            ):
                database.create_label_revision(
                    issue_id=issue_id, task_id=task_id, expected_output=output,
                    tags=[], evidence_gaps=[], rationale="r", is_excluded=False,
                    author=author, author_source="kylin_ticket", author_verified=True,
                    expected_previous_revision_id=None,
                )
            progress = database.labeling_task_progress(["scope"], [task_id])[task_id]
            self.assertEqual(progress["total"], 3)
            self.assertEqual(progress["resolved"], 2)
            self.assertEqual(progress["conflict"], 0)
            self.assertEqual(progress["pending"], 1)
            by_name = {item["name"]: item for item in progress["assignees"]}
            self.assertEqual(by_name["alice"], {"name": "alice", "total": 2, "labeled": 1})
            self.assertEqual(by_name["bob"], {"name": "bob", "total": 1, "labeled": 1})
            self.assertEqual(database.labeling_task_progress([], [task_id]), {})
            self.assertEqual(database.labeling_task_progress(["scope"], []), {})

    def test_assignee_filter_scopes_labeling_cases_to_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            database.upsert_issues(
                [{"issue_id": "cn3", "gt_label": ""}],
                source="test", replace_gt=True, baseline_scope="scope",
            )
            workset = database.create_review_workset(
                baseline_scope="scope", issue_ids=["cn1", "cn2", "cn3"],
                name="queue task", created_by="admin",
            )
            task = database.create_labeling_task(
                workset_id=workset["id"],
                assignments=[
                    {"name": "Alice", "issue_ids": ["cn1", "cn2"]},
                    {"name": "bob", "issue_ids": ["cn3"]},
                ],
                created_by="admin", seed=1, reviewers_per_issue=1, overlap_ratio=0,
            )
            task_id = task["id"]
            self.assertEqual(
                database.labeling_assignees(["scope"], task_id), ["alice", "bob"]
            )
            alice_ids = [
                item["issue_id"]
                for item in database.list_labeling_cases(
                    baseline_scopes=["scope"], task_id=task_id, assignee="alice",
                )["items"]
            ]
            self.assertEqual(alice_ids, ["cn1", "cn2"])
            bob_ids = [
                item["issue_id"]
                for item in database.list_labeling_cases(
                    baseline_scopes=["scope"], task_id=task_id, assignee="bob",
                )["items"]
            ]
            self.assertEqual(bob_ids, ["cn3"])
            all_ids = [
                item["issue_id"]
                for item in database.list_labeling_cases(
                    baseline_scopes=["scope"], task_id=task_id,
                )["items"]
            ]
            self.assertEqual(all_ids, ["cn1", "cn2", "cn3"])

    def test_labeling_clusters_and_cluster_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            database.upsert_issues(
                [
                    {"issue_id": "cn1", "gt_label": "正确触发", "scenario": "路口左转"},
                    {"issue_id": "cn2", "gt_label": "正确触发", "scenario": "路口左转"},
                    {"issue_id": "cn3", "gt_label": "误触发", "scenario": "直行"},
                ],
                source="test", replace_gt=True, baseline_scope="scope",
            )
            for issue_id in ("cn1", "cn2", "cn3"):
                database.create_label_revision(
                    issue_id=issue_id, expected_output="误触发",
                    tags=[], evidence_gaps=[], rationale="r", is_excluded=False,
                    author="alice", author_source="kylin_ticket", author_verified=True,
                    expected_previous_revision_id=None,
                )
            clusters = database.labeling_clusters(baseline_scopes=["scope"])
            self.assertEqual(
                [item["key"] for item in clusters],
                [
                    "pair:正确触发|误触发",
                    "pair:误触发|误触发",
                    "scenario:路口左转",
                    "scenario:直行",
                ],
            )
            self.assertEqual(clusters[0]["count"], 2)
            self.assertEqual(clusters[0]["label"], "正确触发 → 误触发")
            pair_ids = [
                item["issue_id"]
                for item in database.list_labeling_cases(
                    baseline_scopes=["scope"], cluster="pair:正确触发|误触发",
                )["items"]
            ]
            self.assertEqual(pair_ids, ["cn1", "cn2"])
            scenario_ids = [
                item["issue_id"]
                for item in database.list_labeling_cases(
                    baseline_scopes=["scope"], cluster="scenario:直行",
                )["items"]
            ]
            self.assertEqual(scenario_ids, ["cn3"])
            with self.assertRaises(ValueError):
                database.list_labeling_cases(baseline_scopes=["scope"], cluster="bogus")

    def test_labeling_splits_do_not_leak_into_review_work_splits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = self.make_db(tmp)
            workset = database.create_review_workset(
                baseline_scope="scope", issue_ids=["cn1"], created_by="admin",
            )
            task = database.create_labeling_task(
                workset_id=workset["id"],
                assignments=[{"name": "alice", "issue_ids": ["cn1"]}],
                created_by="admin", seed=1, reviewers_per_issue=1, overlap_ratio=0,
            )
            review_split = database.apply_work_split(
                assignments=distribute_issue_ids(
                    ["cn1"], [{"name": "carol"}], seed=2, reviewers_per_issue=1,
                ),
                created_by="admin", reviewers_per_issue=1, model_run_id="run-1",
            )
            review_ids = {row["split_id"] for row in database.list_review_work_splits()}
            self.assertIn(review_split["split_id"], review_ids)
            self.assertNotIn(task["id"], review_ids)


if __name__ == "__main__":
    unittest.main()
