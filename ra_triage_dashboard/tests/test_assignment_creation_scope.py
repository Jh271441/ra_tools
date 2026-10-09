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

    def test_assignment_metrics_precede_creation_form_without_scope_card(self):
        html = (ROOT / 'static/index.html').read_text()
        header = html.index('class="review-assignments-header page-card assignment-composer"')
        panel = html.index('id="workSplitPanel"')
        metrics = html.index('id="reviewAssignmentMetrics"')
        self.assertLess(metrics, header)
        self.assertLess(header, panel)
        self.assertNotIn('id="reviewAssignmentCreate"', html)
        self.assertNotIn('<h3>分配范围</h3>', html)
        self.assertNotIn('id="allocationComparison"', html)
        self.assertNotIn('返回图库修改筛选', html)
        self.assertIn('id="reviewAssignmentsGoReview"', html)
        self.assertNotIn('id="workSplitDialogHint"', html)
        self.assertNotIn('id="workSplitSummary"', html)

    def test_case_gallery_groups_existing_label_attributes_without_extra_requests(self):
        script = (ROOT / 'static/js/case-labeling.js').read_text() + r'''
const assert = require('node:assert/strict');
uiText = (zh, en) => zh;
const catalog = {
  intent_straight: {group:'self_intent', label:'直行'},
  close_distance: {group:'true_trigger', label:'距离近'},
  true_unnecessary_lane_change: {group:'true_trigger', label:'多余变道'},
  egress_swag: {group:'ra', label:'SWAG'},
  queue: {group:'false_trigger', label:'排队'},
  lead_vehicle_departed: {group:'no_assist', label:'前车驶离'},
};
reviewTagCatalogItem = key => catalog[key] || null;
tagLabel = key => catalog[key]?.label || key;
const attributes = caseLabelingTagAttributes({label_state:'resolved',label_cases:[
  {resolution:{state:'resolved',method:'consensus',result_revision:{tags:['intent_straight']},heads:[{tags:['intent_straight','close_distance','egress_swag']},{tags:['true_unnecessary_lane_change']}]}},
  {resolution:{state:'resolved',method:'adjudication',result_revision:{tags:['lead_vehicle_departed']},heads:[{tags:['queue']}]}},
  {resolution:{state:'pending',result_revision:{tags:['queue']},heads:[{tags:['queue']}]}}
]});
assert.deepEqual(attributes.map(item => [item.key, item.values]), [
  ['self_intent',['直行']],
  ['true_trigger',['距离近','多余变道']],
  ['ra',['SWAG']],
  ['no_assist',['前车驶离']],
]);
assert.equal(attributes[0].label_zh, '自车意图');
assert.equal(attributes[0].label_en, 'Ego intent');
assert.deepEqual(caseLabelingTagAttributes({label_state:'conflict',label_cases:[{resolution:{state:'conflict',heads:[{tags:['queue']}]}}]}), []);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

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


class AssignmentNavigationRegressionTest(unittest.TestCase):
    def test_batch_links_roundtrip_campaign_id_without_stale_filters(self):
        script = (ROOT / 'static/js/routing.js').read_text() + (ROOT / 'static/js/review-assignments.js').read_text() + r'''
const assert=require('node:assert/strict');
window={location:{origin:'http://localhost'}};
withBase=p=>p;
PAGE_ROUTES={review:{path:'/review'},analysis:{path:'/review-analysis'}};
LABELS=[]; MODEL_LABELS=[]; CASE_PAGE_SIZES=[10,20,50,100]; DEFAULT_CASE_PAGE_SIZE=20;
ISSUE_QUERY_ID_RE=/^[A-Za-z0-9_-]{3,128}$/;
parseFilterList=v=>Array.isArray(v)?v:String(v||'').split(',').filter(Boolean);
joinFilterList=v=>parseFilterList(v).join(',');normalizeBaselineIds=parseFilterList;
selectedBaselineQueryValue=()=> 'wrong-dataset';defaultBaselineIdsFromConfig=()=>['0508'];
comparisonStatusParam=v=>String(v);parseComparisonStatuses=v=>[v];
const stale={labelStates:['conflict'],workAssignee:['old-user'],sceneTag:['old-scene'],triggerTag:['old-trigger'],egressTag:['old-egress'],workAgreement:'conflict',commentState:'with',commentSearch:'stale',casePage:9,page:9,casePageSize:100,pageSize:100};
currentReviewRouteOptions=o=>({...stale,...o}); currentAnalysisRouteOptions=o=>({...stale,...o});
const batch={split_id:'campaign-abc123',model_run_id:'run-a',workflow_mode:'model_review_only',baseline_ids:['0821'],filter_snapshot:{comparison_status:'mismatch',search:'original-search',review_status:'pending'}};
for (const page of ['review','analysis']) {
 const url=new URL(reviewAssignmentBatchHref(batch,page),'http://localhost');
 assert.equal(url.searchParams.get('run'),'run-a');assert.equal(url.searchParams.get('baselines'),'0821');
 assert.equal(url.searchParams.get('work_split'),'campaign-abc123');assert.equal(url.searchParams.get('comparison'),'all');
 for(const key of ['q','status','label_state','work_assignee','scene_tag','trigger_tag','egress_tag','comment_state','comment_search','work_agreement','page']) assert.equal(url.searchParams.has(key),false,key);
 const parsed=page==='review'?normalizedReviewRouteFilters(url.searchParams):normalizedAnalysisRouteFilters(url.searchParams);
 assert.equal(parsed.workSplitId,'campaign-abc123');
 if(page==='review') assert.equal(parsed.workflowMode,'model_review_only');
}
assert.equal(normalizedAnalysisRouteFilters(new URLSearchParams('work_split=split-123')).workSplitId,'split-123');
assert.equal(normalizedAnalysisRouteFilters(new URLSearchParams('work_split=bad/123')).workSplitId,'');
'''
        subprocess.run(['node','-e',script], check=True, capture_output=True)

    def test_detail_button_uses_requested_batch_and_scrolls_to_result(self):
        script = (ROOT / 'static/js/review-assignments.js').read_text() + r'''
const assert=require('node:assert/strict');
state={reviewAssignments:{selectedSplitId:'campaign-old',detail:{split_id:'campaign-old'},detailRequestSeq:0,page:1,pageSize:50,status:'all',assignee:'',query:''}};
let requested,scrolled=false,route='';
api=async path=>{requested=path;return {split_id:'campaign-new'};};
renderReviewAssignmentPage=()=>{};showToast=()=>{};
$=()=>({scrollIntoView:()=>{scrolled=true;}});
withBase=p=>p;window={location:{origin:'http://localhost'},history:{state:{},replaceState:(_s,_t,url)=>{route=url;}}};
(async()=>{
 await loadReviewAssignmentDetail('campaign-new',{updateRoute:true});
 assert.ok(requested.startsWith('/api/cases/work-splits/campaign-new?'));
 assert.equal(state.reviewAssignments.detail.split_id,'campaign-new');
 assert.equal(route,'/review-assignments?split=campaign-new');assert.equal(scrolled,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        subprocess.run(['node','-e',script], check=True, capture_output=True)
