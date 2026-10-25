"""False synchronization must use current authoritative Case evidence."""
import tempfile
from pathlib import Path
from unittest import TestCase

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.work_split import distribute_issue_ids


class NonExclusionSourcesTest(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(Path(tmp.name) / "test.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues([{"issue_id": "cn1", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="scope")

    def vote(self, author="alice", excluded=False, output="正确触发", **kwargs):
        return self.db.create_label_revision(issue_id="cn1", expected_output=output,
            tags=[], evidence_gaps=[], rationale="local evidence", is_excluded=excluded,
            author=author, author_source="test", author_verified=True, **kwargs)

    def candidates(self, **kwargs):
        return self.db.trail_non_exclusion_candidates(["cn1"], baseline_scopes=["scope"], **kwargs)

    def decide(self, revision):
        self.db.set_labeling_scope_state(baseline_scope="scope", status="active",
            policy_version="test", source_inventory_sha256="a" * 64, updated_by="test")
        state = self.db.project_issue_label_states("scope", ["cn1"])["cn1"]
        return self.db.adjudicate_issue_label(baseline_scope="scope", issue_id="cn1",
            expected_output="正确触发", rationale="explicit non-exclusion decision",
            actor="judge", actor_source="test", actor_verified=True,
            expected_source_fingerprint=state["source_fingerprint"],
            full_result={"is_excluded": False, "tags": [], "evidence_gaps": [],
                "label_rationale": "final evidence", "adopted_revision_id": revision["id"]})

    def test_unannotated_and_incomplete_never_become_false(self):
        self.assertEqual(self.candidates(), [])
        self.vote(output="")
        self.assertEqual(self.candidates(), [])

    def test_current_false_and_run_membership(self):
        vote = self.vote()
        self.assertEqual(self.candidates()[0]["case_label_source"]["revision_ids"], [vote["id"]])
        self.assertEqual(self.candidates(model_run_id="missing"), [])
        run, _ = self.db.import_model_run(name="run", source_name="test.json",
            source_sha256="a" * 64, metadata={}, rows=[{"issue_id": "cn1", "model_label": "误触发"}])
        self.assertEqual(len(self.candidates(model_run_id=run["id"])), 1)

    def test_other_author_true_cannot_be_hidden(self):
        self.vote()
        self.vote("bob", excluded=True)
        self.assertEqual(self.candidates(), [])

    def test_conflict_requires_resolution(self):
        self.vote()
        self.vote("bob", output="误触发")
        self.assertEqual(self.candidates(), [])

    def test_full_issue_decision_can_override_true_but_stale_decision_cannot(self):
        vote = self.vote(excluded=True)
        decision = self.decide(vote)["decision"]
        self.assertEqual(self.candidates()[0]["case_label_source"]["decision_id"], decision["id"])
        # A new false vote still invalidates the old decision fingerprint.
        self.vote(expected_previous_revision_id=vote["id"])
        self.assertEqual(self.candidates(), [])

    def test_incomplete_task_cannot_be_cancelled_by_single_false_vote(self):
        split = self.db.apply_work_split(assignments=distribute_issue_ids(["cn1"],
            [{"name": "alice"}, {"name": "bob"}], seed=1, reviewers_per_issue=2),
            created_by="admin", reviewers_per_issue=2)
        workset = self.db.create_review_workset(baseline_scope="scope", issue_ids=["cn1"], created_by="admin")
        self.db.bind_labeling_task(task_id=split["split_id"], workset_id=workset["id"])
        self.vote(task_id=split["split_id"])
        self.assertEqual(self.candidates(), [])
        self.vote("bob", task_id=split["split_id"])
        self.assertEqual(len(self.candidates()), 1)

    def test_all_source_heads_pin_the_snapshot_even_when_selected_reason_unchanged(self):
        alice = self.vote()
        self.vote("bob")
        before = self.candidates()[0]
        self.vote(expected_previous_revision_id=alice["id"])
        after = self.candidates()[0]
        self.assertNotEqual(before["case_label_source"]["source_fingerprint"],
                            after["case_label_source"]["source_fingerprint"])

    def test_task_decision_only_replaces_its_own_sources_and_expires(self):
        split = self.db.apply_work_split(assignments=distribute_issue_ids(["cn1"],
            [{"name": "alice"}, {"name": "bob"}], seed=1, reviewers_per_issue=2),
            created_by="admin", reviewers_per_issue=2)
        workset = self.db.create_review_workset(baseline_scope="scope", issue_ids=["cn1"], created_by="admin")
        self.db.bind_labeling_task(task_id=split["split_id"], workset_id=workset["id"])
        alice = self.vote(excluded=True, task_id=split["split_id"])
        bob = self.vote("bob", output="误触发", task_id=split["split_id"])
        self.db.adjudicate_label_case(label_case_id=bob["label_case"]["id"],
            source_revision_ids=[alice["id"], bob["id"]], expected_output="正确触发",
            tags=[], evidence_gaps=[], rationale="task decision", is_excluded=False,
            actor="judge", actor_source="test", actor_verified=True,
            expected_previous_resolution_id=None)
        self.assertEqual(len(self.candidates()), 1)
        other = self.vote("carol", excluded=True)
        self.assertEqual(self.candidates(), [])
        self.vote("carol", expected_previous_revision_id=other["id"])
        self.assertEqual(len(self.candidates()), 1)
        self.vote(expected_previous_revision_id=alice["id"], task_id=split["split_id"])
        self.assertEqual(self.candidates(), [])
