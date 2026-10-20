"""Regression coverage for single-reviewer Campaign entry, summary and repair."""
import subprocess
import unittest
from pathlib import Path

import test_combined_reviews as workflow
from ra_triage_dashboard.app.db import AnnotationConflictError
from ra_triage_dashboard.app.db_parts.combined_review_repair import repair_association


class CombinedReviewLinkageTest(unittest.TestCase):
    setUp = workflow.CombinedReviewWorkflowTest.setUp
    campaign = workflow.CombinedReviewWorkflowTest.campaign
    submit = workflow.CombinedReviewWorkflowTest.submit

    def context(self, campaign, reviewer="alice"):
        return self.db.combined_review_context(
            issue_id="cn1", campaign_id=campaign["id"], reviewer=reviewer,
            model_run_id=campaign["evaluation_run_id"],
        )

    def test_single_assignment_exposes_purpose_and_summary_uses_acknowledged_vote(self):
        campaign = self.campaign(0)
        assignment = self.db.review_assignment_context(
            "cn1", model_run_id=campaign["evaluation_run_id"], username="alice", work_split_id=campaign["id"],
        )
        self.assertEqual(assignment["mode"], "single")
        self.assertEqual(assignment["purpose"], "model_review")
        self.assertTrue(assignment["assigned"])
        self.assertIn(campaign["id"], {row["id"] for row in self.db.list_labeling_tasks(["scope"])})
        self.assertEqual(self.db.list_labeling_tasks(["other"]), [])
        before = self.db.list_labeling_cases(baseline_scopes=["scope"], task_id=campaign["id"])
        self.assertEqual(before["total"], 1)
        self.assertEqual(before["items"][0]["label_state"], "pending")
        self.assertEqual(before["assignees"], ["alice"])
        first = self.submit(campaign, self.context(campaign))
        self.submit(campaign, self.context(campaign), key="again")
        after = self.db.list_labeling_cases(baseline_scopes=["scope"], task_id=campaign["id"])
        self.assertEqual(after["labelers"], ["alice"])
        self.assertEqual(after["items"][0]["expected_output"], "误触发")
        self.assertEqual(after["items"][0]["label_cases"][0]["resolution"]["submitted_count"], 1)
        self.assertEqual(self.db.labeling_task_progress(["scope"], [campaign["id"]])[campaign["id"]]["assignees"],
                         [{"name": "alice", "total": 1, "labeled": 1}])
        self.assertEqual(self.db.list_labeling_cases(
            baseline_scopes=["scope"], task_id=campaign["id"], assignee="bob",
        )["total"], 0)
        with self.assertRaises(PermissionError):
            self.submit(campaign, self.context(campaign, "bob"), reviewer="bob", key="wrong-person")
        free = {"id": "", "evaluation_run_id": campaign["evaluation_run_id"]}
        self.submit(free, self.context(free), label="正确触发", key="later-free")
        # A later free vote must not rewrite the version acknowledged in this task.
        pinned = self.db.list_labeling_cases(baseline_scopes=["scope"], task_id=campaign["id"])
        self.assertEqual(pinned["items"][0]["expected_output"], "误触发")
        self.assertEqual(pinned["items"][0]["label_cases"][0]["resolution"]["heads"][0]["id"],
                         first["case_revision_id"])

    def test_free_submission_remains_free_then_explicit_repair_is_append_only_idempotent(self):
        campaign = self.campaign(0)
        free = {"id": "", "evaluation_run_id": campaign["evaluation_run_id"]}
        result = self.submit(free, self.context(free))
        with self.db.connect() as conn:
            original = dict(conn.execute("SELECT * FROM combined_review_submissions WHERE id=?",
                                        (result["submission_group_id"],)).fetchone())
        self.assertEqual(self.db.labeling_task_progress(["scope"], [campaign["id"]])[campaign["id"]]["resolved"], 0)
        args = dict(submission_id=result["submission_group_id"], campaign_id=campaign["id"],
                    label_revision_id=result["case_revision_id"], model_review_revision_id=result["model_review_storage_id"],
                    actor="operator", reason="confirmed missing navigation context")
        plan = repair_association(self.db, **args)
        self.assertFalse(plan["applied"])
        with self.assertRaises(AnnotationConflictError):
            repair_association(self.db, **args, apply=True, expected_fingerprint="wrong")
        applied = repair_association(self.db, **args, apply=True, expected_fingerprint=plan["fingerprint"])
        replay = repair_association(self.db, **args, apply=True, expected_fingerprint=plan["fingerprint"])
        self.assertTrue(replay["duplicate"])
        self.assertEqual(applied["submission_group_id"], replay["submission_group_id"])
        with self.db.connect() as conn:
            self.assertEqual(dict(conn.execute("SELECT * FROM combined_review_submissions WHERE id=?",
                                              (result["submission_group_id"],)).fetchone()), original)
            self.assertEqual(conn.execute("SELECT count(*) n FROM label_revisions").fetchone()["n"], 1)
            self.assertEqual(conn.execute("SELECT count(*) n FROM combined_review_progress").fetchone()["n"], 1)
        self.assertEqual(self.db.labeling_task_progress(["scope"], [campaign["id"]])[campaign["id"]]["resolved"], 1)
        self.assertEqual(self.context(campaign)["model_review_storage_id"], applied["new_model_review_revision_id"])

    def test_repair_rejects_wrong_assignment_run_revision_and_existing_target(self):
        campaign = self.campaign(0, assignees=["bob"])
        # Repair requires assignment before the source submission. Create the
        # valid target up front so this case reaches the existing-head guard
        # regardless of whether fixture operations cross a clock second.
        own = self.campaign(0)
        free = {"id": "", "evaluation_run_id": campaign["evaluation_run_id"]}
        result = self.submit(free, self.context(free))
        args = dict(submission_id=result["submission_group_id"], campaign_id=campaign["id"],
                    label_revision_id=result["case_revision_id"], model_review_revision_id=result["model_review_storage_id"],
                    actor="operator", reason="test")
        with self.assertRaises(ValueError):
            repair_association(self.db, **args)
        args["campaign_id"] = self.campaign(1)["id"]
        with self.assertRaises(ValueError):
            repair_association(self.db, **args)
        args["campaign_id"] = own["id"]
        with self.assertRaises(ValueError):
            repair_association(self.db, **{**args, "label_revision_id": 999})
        self.submit(own, self.context(own), key="task-save")
        with self.assertRaises(AnnotationConflictError):
            repair_association(self.db, **args)

    def test_disjoint_jasperchen_and_liangxianghui_assignments(self):
        for name in ("jasperchen", "liangxianghui"):
            self.db.set_access_user(username=name, role="writer", actor="tester")
        self.db.upsert_issues([{"issue_id": "cn2", "gt_label": "正确触发"}],
                              source="test", replace_gt=True, baseline_scope="scope")
        workset = self.db.create_review_workset(
            baseline_scope="scope", issue_ids=["cn1", "cn2"], name="disjoint",
            selection_source_run_id=self.runs[0]["id"], created_by="tester",
        )
        campaign = self.db.create_campaign(spec={
            "purpose": "model_review", "workflow_mode": "model_review_and_case_label",
            "evaluation_run_id": self.runs[0]["id"], "workset_id": workset["id"], "name": "disjoint",
            "members": [{"issue_id": "cn1", "assignees": ["jasperchen"]},
                        {"issue_id": "cn2", "assignees": ["liangxianghui"]}],
        }, actor="tester", actor_source="test", actor_verified=True, idempotency_key="disjoint")["campaign"]
        for issue, owner, other in (("cn1", "jasperchen", "liangxianghui"),
                                    ("cn2", "liangxianghui", "jasperchen")):
            for name in (owner, other):
                context = self.db.combined_review_context(issue_id=issue, campaign_id=campaign["id"],
                                                         reviewer=name)
                self.assertEqual(context["assigned"], name == owner)
        first = self.context(campaign, "jasperchen")
        self.submit(campaign, first, reviewer="jasperchen", key="jasper")
        self.submit(campaign, first, reviewer="jasperchen", key="jasper")
        progress = self.db.labeling_task_progress(["scope"], [campaign["id"]])[campaign["id"]]
        self.assertEqual(progress["assignees"], [
            {"name": "jasperchen", "total": 1, "labeled": 1},
            {"name": "liangxianghui", "total": 1, "labeled": 0},
        ])

    def test_multiscope_campaign_summary_respects_selected_datasets(self):
        self.db.upsert_issues([{"issue_id": "cn2", "gt_label": "正确触发"}],
                              source="test", replace_gt=True, baseline_scope="extra")
        self.db.set_labeling_scope_state(
            baseline_scope="extra", status="active", policy_version="test",
            source_inventory_sha256="b" * 64, updated_by="tester",
        )
        self.db.apply_gt_sync_snapshot(
            scope="extra", rows=[{"issue_id": "cn2", "gt_label": "正确触发"}],
            source_name="Trail", source_view_id=1000, source_field="gt", trigger="test",
            requested_by="tester", requested_by_source="test", requested_by_verified=True,
            expected_issue_ids=["cn2"],
        )
        run, _ = self.db.import_model_run(
            name="multiscope", source_name="multi.json", source_sha256="c" * 64, metadata={},
            rows=[{"issue_id": issue, "model_label": "误触发"} for issue in ("cn1", "cn2")],
        )
        collection = self.db.create_run_collection(name="multi", members=[self.runs[0]["id"], run["id"]])
        evaluation = self.db.create_run_evaluation(
            collection_id=collection["id"], baseline_scopes=["scope", "extra"],
            comparison_reference_run_id=run["id"],
        )
        campaign = self.db.create_campaign(spec={
            "name": "multiscope", "purpose": "model_review", "workflow_mode": "model_review_and_case_label",
            "evaluation_run_id": run["id"], "workset_id": evaluation["workset"]["workset_id"],
            "members": [{"issue_id": "cn1", "assignees": ["alice"]},
                        {"issue_id": "cn2", "assignees": ["bob"]}],
        }, actor="tester", actor_source="test", actor_verified=True, idempotency_key="multi")["campaign"]
        self.assertEqual(self.db.list_labeling_tasks(["scope", "extra"])[0]["member_count"], 2)
        self.assertEqual(self.db.list_labeling_tasks(["scope"])[0]["member_count"], 1)
        scoped = self.db.labeling_task_progress(["scope"], [campaign["id"]])[campaign["id"]]
        self.assertEqual(scoped["total"], 1)
        self.assertEqual(scoped["assignees"], [{"name": "alice", "total": 1, "labeled": 0}])
        self.assertEqual(self.db.list_labeling_cases(
            baseline_scopes=["scope", "extra"], task_id=campaign["id"],
        )["total"], 2)


def test_browser_binding_cache_and_stale_context():
    root = Path(__file__).resolve().parents[1] / "static/js"
    script = "global.document={getElementById(){return null}};\n" + (root / "review-draft.js").read_text() + (root / "review-form.js").read_text() + (root / "labeling-summary.js").read_text() + (root / "review-assignments.js").read_text() + r"""
const assert = require('node:assert/strict');
capturePageContext=()=>({});isPageContextCurrent=()=>true;$=()=>null;
state = {activePage:"review", selectedRunId:'run1', reviewWorkSplitId:'campaign1', caseDetailPrefetch:new Map(), selectedId:'current'};
const assigned = {issue_id:'cn1', review_assignment:{assigned:true, purpose:'model_review', split_id:'campaign1',
  workflow_mode:'model_review_and_case_label', model_run_id:'run1', mode:'single'}};
assert.equal(combinedReviewCampaignBinding(assigned), 'campaign1');
assert.equal(reviewWorkSplitBinding(assigned), 'campaign1');
state.selectedBaselineIds=['scope'];
labelSummaryFilters.taskId='campaign1';
labelSummaryTasks=[{id:'campaign1', workflow_mode:'model_review_and_case_label', selection_source_run_id:'run1'}];
pageUrl=(page,options)=>({page,options});
const link=labelSummaryCaseUrl({issue:'cn1'});
assert.equal(link.page,'review');
assert.equal(link.options.workSplitId,'campaign1');
assert.equal(link.options.runId,'run1');
assert.equal(link.options.issue,'cn1');
assert.throws(()=>combinedReviewCampaignBinding({issue_id:'cn1'}), /上下文/);
assert.throws(()=>combinedReviewCampaignBinding({...assigned, review_assignment:{...assigned.review_assignment, assigned:false}}), /上下文/);
state.reviewWorkSplitId='';
assert.equal(combinedReviewCampaignBinding(assigned), '');
assert.equal(reviewWorkSplitBinding(assigned), '');
state.reviewWorkSplitId='campaign1';
let calls=[];
api=async path => {calls.push(path);return {path}};
(async()=>{
 prefetchCaseCore('cn2');
 state.reviewWorkSplitId='campaign2';
 const other=await loadCaseCore('cn2');
 assert.match(other.path,/work_split_id=campaign2/);
 state.selectedRunId='run2';
 const run=await loadCaseCore('cn2');
 assert.match(run.path,/model_run_id=run2/);
 state.selectedRunId='run1';state.reviewWorkSplitId='campaign1';state.selectedCase=assigned;
 let resolve;api=()=>new Promise(r=>resolve=r);
 let populated=false;populateCombinedCaseLabel=()=>{populated=true};
 const pending=loadCombinedReviewContext(assigned);
 state.reviewWorkSplitId='campaign2';
 resolve({context:{}});await pending;
 assert.equal(populated,false);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(["node"], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_combined_context_loading_error_retry_and_draft_preservation():
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("combined_review_context_ui.cjs"))],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
