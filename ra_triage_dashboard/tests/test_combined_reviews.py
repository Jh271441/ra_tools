from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import AnnotationConflictError, Database, LabelAnnotationConflictError


class CombinedReviewWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "combined.sqlite")
        self.db.init()
        self.addCleanup(self.db.close)
        self.db.upsert_issues(
            [{"issue_id": "cn1", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="scope",
        )
        self.db.apply_gt_sync_snapshot(
            scope="scope", rows=[{"issue_id": "cn1", "gt_label": "正确触发"}],
            source_name="Trail", source_view_id=1000, source_field="gt",
            trigger="test", requested_by="tester", requested_by_source="test",
            requested_by_verified=True, expected_issue_ids=["cn1"],
        )
        self.db.set_labeling_scope_state(
            baseline_scope="scope", status="active", policy_version="test",
            source_inventory_sha256="a" * 64, updated_by="tester",
        )
        self.db.set_access_user(username="alice", role="admin", actor="tester")
        self.db.set_access_user(username="bob", role="admin", actor="tester")
        self.db.set_access_user(username="viewer", role="writer", actor="tester")
        self.runs = []
        for index in range(2):
            run, _ = self.db.import_model_run(
                name=f"run-{index}", source_name=f"run-{index}.json",
                source_sha256=str(index + 1) * 64, metadata={},
                rows=[{"issue_id": "cn1", "model_label": "误触发"}],
            )
            self.runs.append(run)
        self.workset = self.db.create_review_workset(
            baseline_scope="scope", issue_ids=["cn1"], name="combined",
            selection_source_run_id=self.runs[0]["id"], created_by="tester",
        )

    def campaign(self, run_index: int, *, workflow: str = "model_review_and_case_label", assignees=None):
        return self.db.create_campaign(
            spec={
                "purpose": "model_review", "workflow_mode": workflow,
                "evaluation_run_id": self.runs[run_index]["id"],
                "workset_id": self.workset["id"], "name": f"campaign-{run_index}-{workflow}",
                "members": [{"issue_id": "cn1", "assignees": assignees or ["alice"]}],
            },
            actor="tester", actor_source="test", actor_verified=True,
            idempotency_key=f"campaign-{run_index}-{workflow}-{','.join(assignees or ['alice'])}",
        )["campaign"]

    def submit(self, campaign, context, *, label="误触发", reviewer="alice", key="submit-1", status="completed", excluded=None, attachments=(), tags=()):
        return self.db.submit_combined_review(
            issue_id="cn1", campaign_id=campaign["id"],
            model_run_id=campaign["evaluation_run_id"], reviewer=reviewer,
            reviewer_source="test", reviewer_verified=True,
            model_review_status=status, reason="model reason",
            missing_evidence=["camera"], expected_output=label,
            tags=list(tags), rationale="case rationale",
            expected_model_review_storage_id=context["model_review_storage_id"],
            expected_case_revision_id=context["case_revision_id"],
            expected_label_state_fingerprint=context["label_state_fingerprint"],
            idempotency_key=key, is_excluded=excluded, attachments=attachments,
        )

    def test_cross_page_combined_filters_and_fresh_exclusion_preview(self):
        from unittest.mock import patch
        from ra_triage_dashboard.app.routers import cases as gallery, analysis as exports
        from ra_triage_dashboard.app.routers.trail_update import preview
        from ra_triage_dashboard.app.support import review_payloads as analysis
        from ra_triage_dashboard.app.trail_exclusion_payloads import build_review_exclusion_payload
        task = self.campaign(0)
        def context():
            return self.db.combined_review_context(issue_id="cn1", campaign_id=task["id"], model_run_id=self.runs[0]["id"], reviewer="alice")
        self.submit(task, context(), excluded=True, tags=["queue"])
        self.db.create_review_comment(issue_id="cn1", body="Case discussion", author="alice", baseline_scope="scope", discussion_channel="case")
        catalog = [{"key": "queue", "label": "排队", "section": "scene", "group": "environment"}]
        query = dict(baseline_scopes=["scope"], model_run_id=self.runs[0]["id"], work_split_id=task["id"], include_multi_reviews=True)
        with patch.object(analysis, "database", self.db), patch.object(analysis, "_review_tag_catalog", return_value=catalog), patch.object(analysis, "_missing_evidence_catalog", return_value=[]):
            result = analysis._review_reason_analysis_payload(**query, annotation_author="alice", review_status="completed", scene_tag="queue", exclusion="excluded", comment_state="with", search="cn1")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["annotation"]["tags"], [])
            self.assertEqual(result["items"][0]["case_label_context"]["tags"], ["queue"])
            with patch.object(exports, "_review_tag_catalog", return_value=catalog), patch.object(exports, "_missing_evidence_catalog", return_value=[]):
                exported = exports._review_analysis_export_rows(result)[0]
                self.assertEqual(exported["tag_keys"], "queue")
                self.assertEqual(exported["is_excluded"], "是")
            self.assertEqual(result["summary"]["model_review_status_counts"]["completed"], 1)
            self.assertEqual(analysis._review_reason_analysis_payload(**query, search="排队")["total"], 1)
            for extra in ({"review_status": "pending"}, {"exclusion": "included"}, {"comment_state": "without"}, {"annotation_author": "bob"}):
                self.assertEqual(analysis._review_reason_analysis_payload(**query, **extra)["total"], 0, extra)
        filters = dict(baseline_scopes=["scope"], model_run_id=self.runs[0]["id"], work_split_id=task["id"], work_assignee="alice", model_review_status="completed", is_excluded=True, comment_state="with")
        with patch.object(gallery, "database", self.db), patch.object(gallery, "_review_tag_catalog", return_value=catalog):
            result = gallery._case_result_with_status_filter(filters=filters, review_statuses=(), label_states=("resolved",), page=1, page_size=1)
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["issue_id"], "cn1")
            self.assertEqual(gallery._case_issue_ids_with_status_filter(filters=filters, review_statuses=(), label_states=("resolved",)), ["cn1"])
            self.assertEqual(gallery._case_result_with_status_filter(filters=filters, review_statuses=(), label_states=("none",), page=1, page_size=20)["total"], 0)
        summary_filters = dict(baseline_scopes=["scope"], task_id=task["id"], author="alice", assignee="alice", status="resolved", expected_output="误触发", gt_label="正确触发", comment_state="with", exclusion="excluded")
        self.assertEqual(len(self.db._project_labeling_cases(**summary_filters)[0]), 1)
        self.assertEqual(len(self.db._project_labeling_cases(**{**summary_filters, "author": "bob"})[0]), 0)
        with patch.object(preview, "database", self.db):
            def payload():
                rows = preview._load_review_exclusion_candidate_rows(selected_run_id=self.runs[0]["id"], baseline_scopes=["scope"])
                return build_review_exclusion_payload(rows, run=self.runs[0], baseline_ids=["test"], baseline_scopes=["scope"], write_mode="info_only")
            before = payload()
            self.assertEqual(len(before["items"]), 1)
            self.submit(task, context(), excluded=False, key="include-again")
            after = payload()
            self.assertEqual(after["items"], [])
            self.assertNotEqual(before["payload_sha256"], after["payload_sha256"])

    def test_gallery_status_projection_keeps_task_run_and_reviewer_boundaries(self):
        task = self.campaign(0)
        other = self.campaign(0, assignees=["bob"])
        query = dict(baseline_scopes=["scope"], model_run_id=self.runs[0]["id"], work_split_id=task["id"], work_assignee="alice")
        def selected(status):
            return self.db.list_cases(**query, model_review_status=status)
        self.assertEqual(selected("pending")["total"], 1)
        self.assertEqual(self.db.list_cases(**{**query, "work_assignee": "bob"})["total"], 0)
        self.assertEqual(selected("completed")["total"], 0)
        other_context = self.db.combined_review_context(issue_id="cn1", campaign_id=other["id"], reviewer="bob")
        self.submit(other, other_context, reviewer="bob", key="bob-done")
        self.assertEqual(selected("pending")["total"], 1)  # another task/reviewer cannot complete ours
        ctx = self.db.combined_review_context(issue_id="cn1", campaign_id=task["id"], reviewer="alice")
        first = self.submit(task, ctx, status="pending")
        self.assertEqual(selected("pending")["total"], 0)
        self.assertEqual(selected("in_progress")["total"], 1)
        ctx = self.db.combined_review_context(issue_id="cn1", campaign_id=task["id"], reviewer="alice")
        completed = self.submit(task, ctx, key="done")
        result = selected("completed")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["annotation"]["id"], completed["model_review"]["id"])
        self.assertEqual(selected("pending,in_progress")["total"], 0)
        self.assertEqual(selected("pending,in_progress,completed")["total"], 1)
        self.assertEqual(self.db.list_case_issue_ids(**query, model_review_status="completed"), ["cn1"])
        self.assertEqual(self.db.list_cases(**{**query, "model_run_id": self.runs[1]["id"]})["total"], 0)

    def test_case_exclusion_filters_summary_and_preview_use_current_vote(self):
        from ra_triage_dashboard.app.labeling_summary import summarize_labeling_cases
        from ra_triage_dashboard.app.trail_exclusion_payloads import build_review_exclusion_payload
        task = self.campaign(0)
        context = lambda: self.db.combined_review_context(issue_id="cn1", campaign_id=task["id"], reviewer="alice")
        excluded = self.submit(task, context(), excluded=True)
        scopes = ["scope"]
        selected, _ = self.db._project_labeling_cases(baseline_scopes=scopes, exclusion="excluded")
        self.assertEqual([item["issue_id"] for item in selected], ["cn1"])
        self.assertTrue(summarize_labeling_cases(selected)["items"][0]["is_excluded"])
        self.assertEqual(self.db._project_labeling_cases(baseline_scopes=scopes, exclusion="active")[0], [])
        rows = self.db.case_exclusion_candidate_rows(baseline_scopes=scopes, model_run_id=self.runs[0]["id"])
        payload = build_review_exclusion_payload(rows, run=self.runs[0], baseline_ids=["test"], baseline_scopes=scopes, write_mode="info_only")
        self.assertEqual(payload["items"][0]["case_label_source"]["revision_ids"], [excluded["case_revision_id"]])
        self.assertEqual(payload["items"][0]["comment"], "case rationale")
        self.submit(task, context(), excluded=False, key="restore")
        self.assertFalse(self.db.project_issue_exclusions(["cn1"])["cn1"]["is_excluded"])
        self.assertEqual(self.db._project_labeling_cases(baseline_scopes=scopes, exclusion="excluded")[0], [])
        rows = self.db.case_exclusion_candidate_rows(baseline_scopes=scopes)
        self.assertEqual(build_review_exclusion_payload(rows, run={}, baseline_ids=["test"], baseline_scopes=scopes, write_mode="info_only")["items"], [])

    def test_case_images_are_atomic_versioned_and_content_idempotent(self):
        from unittest.mock import patch
        campaign = self.campaign(0)
        context = lambda: self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        initial = context()
        item = {"id": "image-1", "original_name": "evidence.png", "stored_name": "image-1.png",
                "media_type": "image/png", "size_bytes": 68, "width": 1, "height": 1, "sha256": "f" * 64}
        first = self.submit(campaign, initial, attachments=[item])
        self.assertEqual([a["id"] for a in first["case_attachments"]], ["image-1"])
        # A retry stores a new temporary object but reuses the original label/review.
        replay = self.submit(campaign, initial, attachments=[{**item, "id": "retry", "stored_name": "retry.png"}])
        self.assertTrue(replay["duplicate"])
        self.assertIsNone(self.db.get_label_attachment("retry"))
        self.assertEqual(replay["case_revision_id"], first["case_revision_id"])
        with self.assertRaises(AnnotationConflictError):
            self.submit(campaign, initial, attachments=[{**item, "sha256": "a" * 64}])
        before = context()
        # An image-only edit must append a Case revision rather than acknowledge.
        second = self.submit(campaign, before, key="new-image", attachments=[{**item, "id": "image-2", "stored_name": "image-2.png"}])
        self.assertEqual(second["case_action"], "submitted")
        self.assertNotEqual(second["case_revision_id"], first["case_revision_id"])
        self.assertIsNotNone(self.db.get_label_attachment("image-1"))
        # Display-only metadata must not alter the label fingerprint.
        detail = self.db.get_case("cn1")
        self.assertEqual(detail["label_state"], second["label_state"])
        source = detail["label_state"]["sources"][0]
        images = detail["label_source_contexts"][source["label_case_id"]]["revision_attachments"]
        self.assertEqual(images[str(second["case_revision_id"])][0]["id"], "image-2")
        self.assertNotIn("stored_name", str(images))
        # A failure after image insertion rolls back images and both review halves.
        current = context()
        with patch("ra_triage_dashboard.app.db_parts.combined_reviews.append_label_mention_event", side_effect=RuntimeError("outbox failure")):
            with self.assertRaises(RuntimeError):
                self.submit(campaign, current, key="rollback", attachments=[{**item, "id": "failed"}])
        self.assertIsNone(self.db.get_label_attachment("failed"))
        self.assertEqual(context()["case_revision_id"], current["case_revision_id"])
        self.assertEqual(context()["model_review_storage_id"], current["model_review_storage_id"])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM combined_review_progress").fetchone()["n"], 1)

    def test_no_run_case_images_append_without_model_review(self):
        context = self.db.combined_review_context(issue_id="cn1", campaign_id="", reviewer="alice")
        item = {"id": "no-run-image", "original_name": "evidence.png", "stored_name": "image.png",
                "media_type": "image/png", "size_bytes": 68, "width": 1, "height": 1, "sha256": "f" * 64}
        result = self.db.submit_review_case_label(issue_id="cn1", reviewer="alice", reviewer_source="test", reviewer_verified=True,
            expected_output="误触发", tags=[], rationale="evidence", expected_case_revision_id=None,
            expected_label_state_fingerprint=context["label_state_fingerprint"], attachments=[item])
        self.assertEqual(self.db.get_label_attachment(item["id"])["revision_id"], result["case_revision"]["id"])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM model_review_revisions").fetchone()["n"], 0)

    def test_source_contexts_follow_exact_submissions_without_changing_label_state(self) -> None:
        campaign_a = self.campaign(0)
        campaign_b = self.campaign(1)
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign_a["id"], reviewer="alice")
        first = self.submit(campaign_a, context)
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign_b["id"], reviewer="alice")
        self.submit(campaign_b, context, key="other-task")
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign_a["id"], reviewer="alice")
        self.submit(campaign_a, context, key="repeat-task")
        before = self.db.project_issue_label_states("scope", ["cn1"])["cn1"]
        detail = self.db.get_case("cn1")
        self.assertEqual(detail["label_state"], before)
        source = detail["label_state"]["sources"][0]
        self.assertEqual(source["task_id"], "")  # Shared Issue vote remains independent.
        provenance = detail["label_source_contexts"][source["label_case_id"]]["combined_reviews"]
        self.assertEqual({item["task_id"] for item in provenance}, {campaign_a["id"], campaign_b["id"]})
        self.assertEqual(len(provenance), 2)  # Repeated submissions do not duplicate a task.
        self.assertTrue(all(item["task_name"] and item["run_name"] for item in provenance))
        self.assertEqual({item["revision_id"] for item in provenance}, {first["case_revision"]["id"]})
        # A later independent label edit must not inherit earlier tasks by membership.
        self.db.create_label_revision(issue_id="cn1", is_excluded=False, expected_output="误触发",
            tags=[], evidence_gaps=[], rationale="independent edit", author="alice", author_source="test",
            author_verified=True, expected_previous_revision_id=first["case_revision"]["id"])
        detail = self.db.get_case("cn1")
        self.assertEqual(detail["label_source_contexts"][source["label_case_id"]]["combined_reviews"], [])

    def test_existing_campaign_defaults_to_model_review_only_and_combined_allows_writers(self) -> None:
        ordinary = self.campaign(0, workflow="model_review_only")
        self.assertEqual(ordinary["workflow_mode"], "model_review_only")
        combined = self.campaign(0, assignees=["viewer"])
        self.assertEqual(combined["workflow_mode"], "model_review_and_case_label")
        context = self.db.combined_review_context(
            issue_id="cn1", campaign_id=combined["id"], reviewer="viewer"
        )
        result = self.submit(
            combined, context, reviewer="viewer", key="writer-submit"
        )
        self.assertEqual(result["model_review"]["reviewer"], "viewer")

    def test_atomic_combined_submission_reuses_vote_across_runs_and_tracks_progress(self) -> None:
        campaign_a = self.campaign(0)
        with self.db.connect() as conn:
            before_annotations = conn.execute("SELECT COUNT(*) n FROM annotations").fetchone()["n"]
        context_a = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign_a["id"], reviewer="alice"
        )
        first = self.submit(campaign_a, context_a)
        self.assertEqual(first["case_action"], "submitted")
        self.assertEqual(first["model_review"]["model_review_status"], "completed")
        self.assertTrue(first["progress"]["model_review_submitted"])
        self.assertTrue(first["progress"]["case_label_acknowledged"])
        with self.db.connect() as conn:
            first_label_count = int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"])
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM annotations").fetchone()["n"]), before_annotations)

        campaign_b = self.campaign(1)
        context_b = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign_b["id"], reviewer="alice"
        )
        second = self.submit(campaign_b, context_b, key="submit-run-b")
        self.assertEqual(second["case_action"], "acknowledged")
        with self.db.connect() as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"]), first_label_count)
            heads = conn.execute("SELECT model_run_id FROM model_review_heads ORDER BY model_run_id").fetchall()
        self.assertEqual({row["model_run_id"] for row in heads}, {self.runs[0]["id"], self.runs[1]["id"]})

        replay = self.submit(campaign_b, context_b, key="submit-run-b")
        self.assertTrue(replay["duplicate"])

    def test_vote_change_conflict_does_not_block_completed_model_review(self) -> None:
        campaign = self.campaign(0, assignees=["alice", "bob"])
        alice_context = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="alice"
        )
        self.submit(campaign, alice_context, label="误触发", reviewer="alice", key="alice")
        bob_context = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="bob"
        )
        bob = self.submit(campaign, bob_context, label="正确触发", reviewer="bob", key="bob")
        self.assertEqual(bob["label_state"]["state"], "conflict")
        self.assertEqual(bob["model_review"]["model_review_status"], "completed")
        alice_after = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="alice"
        )
        changed = self.submit(
            campaign, alice_after, label="正确触发", reviewer="alice", key="alice-change"
        )
        self.assertEqual(changed["case_action"], "submitted")
        with self.db.connect() as conn:
            bob_heads = conn.execute(
                "SELECT COUNT(*) n FROM label_revisions WHERE lower(author)='bob'"
            ).fetchone()["n"]
        self.assertEqual(int(bob_heads), 1)

    def test_stale_case_version_rolls_back_model_half(self) -> None:
        campaign = self.campaign(0)
        stale = self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer="alice"
        )
        self.db.submit_review_case_label(
            issue_id="cn1", reviewer="alice", reviewer_source="test",
            reviewer_verified=True, expected_output="误触发", tags=[], rationale="external",
            expected_case_revision_id=None,
            expected_label_state_fingerprint=stale["label_state_fingerprint"],
        )
        with self.db.connect() as conn:
            before_models = int(conn.execute("SELECT COUNT(*) n FROM model_review_revisions").fetchone()["n"])
            before_labels = int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"])
        with self.assertRaises((LabelAnnotationConflictError, AnnotationConflictError)):
            self.submit(campaign, stale, key="stale")
        with self.db.connect() as conn:
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM model_review_revisions").fetchone()["n"]), before_models)
            self.assertEqual(int(conn.execute("SELECT COUNT(*) n FROM label_revisions").fetchone()["n"]), before_labels)


    def test_exclusion_changes_case_vote_only_and_replays_without_extra_progress(self) -> None:
        campaign = self.campaign(0)
        context = lambda: self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        first = self.submit(campaign, context(), excluded=False)
        before = context()
        excluded = self.submit(campaign, before, key="exclude", excluded=True)
        self.assertEqual(excluded["case_action"], "submitted")
        self.assertTrue(context()["case_revision"]["is_excluded"])
        self.assertFalse(excluded["model_review"]["is_excluded"])
        replay = self.submit(campaign, before, key="exclude", excluded=True)
        self.assertTrue(replay["duplicate"])
        with self.assertRaises(AnnotationConflictError):
            self.submit(campaign, before, key="exclude", excluded=False)
        same = self.submit(campaign, context(), key="ack-exclusion", excluded=True)
        self.assertEqual(same["case_action"], "acknowledged")
        # Older clients omit this field: they must not silently undo an exclusion.
        old_client = self.submit(campaign, context(), key="old-client")
        self.assertEqual(old_client["case_action"], "acknowledged")
        self.assertTrue(context()["case_revision"]["is_excluded"])
        with self.db.connect() as conn:
            original = conn.execute("SELECT is_excluded FROM label_revisions WHERE id=?", (first["case_revision_id"],)).fetchone()
            self.assertFalse(original["is_excluded"])
            self.assertEqual(conn.execute("SELECT count(*) n FROM label_revisions").fetchone()["n"], 2)
            self.assertEqual(conn.execute("SELECT count(*) n FROM combined_review_progress").fetchone()["n"], 1)
        restored = self.submit(campaign, context(), key="include-again", excluded=False)
        self.assertEqual(restored["case_action"], "submitted")
        self.assertFalse(context()["case_revision"]["is_excluded"])
        self.assertEqual(self.db.labeling_task_progress(["scope"], [campaign["id"]])[campaign["id"]]["resolved"], 1)

    def test_case_only_submission_can_change_exclusion_without_changing_label(self) -> None:
        def save(excluded=None):
            ctx = self.db.combined_review_context(issue_id="cn1", campaign_id="", reviewer="alice")
            return self.db.submit_review_case_label(
                issue_id="cn1", reviewer="alice", reviewer_source="test", reviewer_verified=True,
                expected_output="误触发", tags=[], rationale="case exclusion",
                expected_case_revision_id=ctx["case_revision_id"],
                expected_label_state_fingerprint=ctx["label_state_fingerprint"], is_excluded=excluded,
            )
        initial = save(False)
        changed = save(True)
        self.assertNotEqual(initial["case_revision"]["id"], changed["case_revision"]["id"])
        self.assertTrue(changed["case_revision"]["is_excluded"])
        self.assertEqual(save()["case_action"], "acknowledged")
        self.assertFalse(save(False)["case_revision"]["is_excluded"])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) n FROM model_review_revisions").fetchone()["n"], 0)


    def test_explicit_rationale_edits_append_and_queue_mentions_once(self) -> None:
        campaign = self.campaign(0)
        initial = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        def submit(context, key, reason):
            return self.db.submit_combined_review(
                issue_id="cn1", campaign_id=campaign["id"], model_run_id=self.runs[0]["id"],
                reviewer="alice", reviewer_source="test", reviewer_verified=True,
                model_review_status="completed", reason="model reason", missing_evidence=[],
                expected_output="误触发", tags=[], rationale=reason,
                expected_model_review_storage_id=context["model_review_storage_id"],
                expected_case_revision_id=context["case_revision_id"],
                expected_label_state_fingerprint=context["label_state_fingerprint"],
                idempotency_key=key, update_case_details=True, mention_recipients=["bob"],
            )
        first = submit(initial, "mention-1", "Issue reason @bob")
        self.assertEqual(first["notification"]["queued"], ["bob"])
        self.assertTrue(submit(initial, "mention-1", "Issue reason @bob")["duplicate"])
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        same = submit(context, "mention-2", "Issue reason @bob")
        self.assertEqual(same["case_action"], "acknowledged")
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        changed = submit(context, "mention-3", "Edited Issue reason @bob")
        self.assertEqual(changed["case_action"], "submitted")
        self.assertEqual(changed["case_revision"]["rationale"], "Edited Issue reason @bob")
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM comment_notifications").fetchone()["n"], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM combined_review_progress").fetchone()["n"], 1)
            comments = conn.execute("SELECT discussion_channel, evaluation_run_id FROM review_comments").fetchall()
            self.assertTrue(all(row["discussion_channel"] == "case" and not row["evaluation_run_id"] for row in comments))

    def test_label_mention_failure_rolls_back_both_combined_halves(self) -> None:
        from unittest.mock import patch
        campaign = self.campaign(0)
        context = self.db.combined_review_context(issue_id="cn1", campaign_id=campaign["id"], reviewer="alice")
        with patch("ra_triage_dashboard.app.db_parts.combined_reviews.append_label_mention_event", side_effect=RuntimeError("outbox failure")):
            with self.assertRaises(RuntimeError):
                self.submit(campaign, context)
        with self.db.connect() as conn:
            for table in ("label_revisions", "model_review_revisions", "combined_review_progress", "comment_notifications"):
                self.assertEqual(conn.execute("SELECT COUNT(*) n FROM " + table).fetchone()["n"], 0)

    def test_case_only_mentions_keep_original_revision_and_do_not_resend_ack(self) -> None:
        def save(text, recipients=()):
            context = self.db.combined_review_context(issue_id="cn1", campaign_id="", reviewer="alice")
            return self.db.submit_review_case_label(
                issue_id="cn1", reviewer="alice", reviewer_source="test", reviewer_verified=True,
                expected_output="误触发", tags=[], rationale=text,
                expected_case_revision_id=context["case_revision_id"],
                expected_label_state_fingerprint=context["label_state_fingerprint"],
                update_case_details=True, mention_recipients=recipients,
            )
        first = save("Original saved reason")
        changed = save("Updated reason @bob", ["bob"])
        self.assertNotEqual(first["case_revision"]["id"], changed["case_revision"]["id"])
        self.assertEqual(save("Updated reason @bob", ["bob"])["case_action"], "acknowledged")
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT rationale FROM label_revisions WHERE id=?", (first["case_revision"]["id"],)).fetchone()["rationale"], "Original saved reason")
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM comment_notifications").fetchone()["n"], 1)


    def test_labeling_revision_mentions_and_stale_retry_share_one_outbox_record(self) -> None:
        kwargs = dict(issue_id="cn1", expected_output="误触发", tags=[], evidence_gaps=[],
                      rationale="Label rationale @bob", is_excluded=False, author="alice",
                      author_source="test", author_verified=True, expected_previous_revision_id=None,
                      mention_recipients=["bob"])
        revision = self.db.create_label_revision(**kwargs)
        self.assertEqual(revision["notification"]["queued"], ["bob"])
        with self.assertRaises(LabelAnnotationConflictError):
            self.db.create_label_revision(**kwargs)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) n FROM comment_notifications").fetchone()["n"], 1)
