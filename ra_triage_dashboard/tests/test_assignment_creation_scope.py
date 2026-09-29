from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AssignmentCreationScopeTest(unittest.TestCase):
    def test_draft_submission_ignores_hidden_review_filters(self):
        script = (ROOT / 'static/js/work-split.js').read_text() + r'''
const assert = require('node:assert/strict');
state = {session:{is_admin:true}, selectedRunId:'old-run', caseTotal:999, activePage:'review-assignments', workAssigneeRequestSeq:0};
currentReviewFilterPayload = () => ({model_run_id:'old-run', work_split_id:'old-task', search:'stale'});
workSplitDraft = {filters:{model_run_id:'new-run', baselines:'0522', comparison:'mismatch', work_split_id:'', search:''}, total:12};
const copy = workSplitFilters(); copy.model_run_id='changed';
assert.equal(workSplitFilters().model_run_id,'new-run');
assert.equal(workSplitTotal(),12);
readWorkSplitAssignees=()=>[{name:'alice',count:null}];
workSplitReviewersPerIssue=()=>1; workSplitOverlapRatio=()=>0;
$=()=>null; t=(key)=>key; showToast=()=>{};
acknowledgeLocalChange=()=>{};renderWorkAssigneeFilter=()=>{};saveReviewAllocationDraft=()=>{};
renderWorkSplitResults=()=>{};loadReviewAssignments=async()=>{};
let sent;
api=async(path, options)=>{sent=JSON.parse(options.body);return {work_assignees:[]};};
(async()=>{
 await generateWorkSplit();
 assert.equal(sent.filters.model_run_id,'new-run');
 assert.equal(sent.filters.work_split_id,'');
 assert.equal(sent.filters.baselines,'0522');
 assert.equal(sent.filters.search,'');
 assert.equal(state.selectedRunId,'old-run');
 workSplitDraft=null;
 assert.equal(workSplitFilters().model_run_id,'old-run');
 assert.equal(workSplitTotal(),999);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

    def test_source_link_preserves_full_filter_without_inheriting_ui(self):
        script = 'document={getElementById:()=>null};\n' + (ROOT / 'static/js/review-assignments.js').read_text() + r'''
const assert=require('node:assert/strict');
parseFilterList=v=>String(v).split(',').filter(Boolean);
let route;
pageUrl=(page,options)=>{assert.equal(page,'review');route=options;return '/review?source=ok';};
const filters={model_run_id:'run-a',comparison_status:'mismatch,none',gt_label:'误触发',model_label:'正确触发',annotation_author:'alice',review_status:['completed'],label_state:['conflict'],comment_state:'with',work_assignee:'bob',work_split_id:'old-task',missing_evidence:'camera',exclusion:'excluded',baselines:['0508'],issue_ids:['cn1','cn2'],search:''};
assert.equal(reviewAssignmentSourceHref(filters),'/review?source=ok');
assert.equal(route.runId,'run-a');assert.equal(route.workSplitId,'old-task');
assert.deepEqual(route.issueIds,['cn1','cn2']);assert.deepEqual(route.workAssignee,['bob']);
assert.deepEqual(route.reviewStatus,['completed']);assert.deepEqual(route.labelStates,['conflict']);
assert.equal(route.commentState,'with');assert.equal(route.clusterKey,'camera');
reviewAssignmentSourceHref({model_run_id:'run-b',baselines:['0522']});
assert.equal(route.workSplitId,'');assert.deepEqual(route.issueIds,[]);assert.deepEqual(route.workAssignee,[]);
assert.equal(route.commentState,'all');assert.equal(route.casePage,1);
assert.equal(route.workflowMode,'model_review_and_case_label');
'''
        subprocess.run(['node','-e',script], check=True, capture_output=True)

    def test_assignment_form_is_merged_into_header_without_scope_card(self):
        html = (ROOT / 'static/index.html').read_text()
        header = html.index('class="review-assignments-header page-card"')
        panel = html.index('id="workSplitPanel"')
        metrics = html.index('id="reviewAssignmentMetrics"')
        self.assertLess(header, panel)
        self.assertLess(panel, metrics)
        self.assertNotIn('id="reviewAssignmentCreate"', html)
        self.assertNotIn('<h3>分配范围</h3>', html)
        self.assertNotIn('id="allocationComparison"', html)
        self.assertNotIn('返回图库修改筛选', html)
        self.assertIn('id="reviewAssignmentsGoReview"', html)
        self.assertNotIn('id="workSplitDialogHint"', html)
        self.assertNotIn('id="workSplitSummary"', html)

    def test_all_three_assignment_flows_start_with_explicit_addition(self):
        work_split = (ROOT / 'static/js/work-split.js').read_text()
        case_labeling = (ROOT / 'static/js/case-labeling.js').read_text()
        intent = (ROOT / 'static/js/intent-workspaces.js').read_text()
        self.assertIn('root.innerHTML = "";\n    ensureWorkSplitPeople(1);', work_split)
        self.assertNotIn('users.forEach((user)', work_split)
        self.assertIn('root.innerHTML = "";\n    ensureLabelingTaskPeople(1);', case_labeling)
        self.assertNotIn('users.forEach((user)', case_labeling)
        self.assertIn('intent.experimentDraftMembers = [];', intent)
        self.assertIn('setMultiFilterValues($("#intentExperimentMembers"), []);', intent)

    def test_review_and_new_review_tasks_default_to_combined_mode(self):
        html = (ROOT / 'static/index.html').read_text()
        core = (ROOT / 'static/js/core-base.js').read_text()
        routing = (ROOT / 'static/js/routing.js').read_text()
        work_split = (ROOT / 'static/js/work-split.js').read_text()
        self.assertIn('value="model_review_and_case_label" selected', html)
        self.assertIn('reviewWorkflowMode: "model_review_and_case_label"', core)
        self.assertIn('params.get("workflow") === "model_only"', routing)
        self.assertIn('url.searchParams.set("workflow", "model_only")', routing)
        self.assertIn('$("#workSplitWorkflowMode").value = "model_review_and_case_label"', work_split)
