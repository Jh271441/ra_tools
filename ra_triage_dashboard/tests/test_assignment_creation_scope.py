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
acknowledgeLocalChange=()=>{};renderWorkAssigneeFilter=()=>{};
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

    def test_creation_previews_explicit_scope_without_writing(self):
        script = (ROOT / 'static/js/review-assignments.js').read_text() + r'''
const assert=require('node:assert/strict');
state={session:{is_admin:true},modelRuns:[{id:'chosen',name:'Chosen Run'}]};
const nodes={
 '#reviewAssignmentCreateRun':{value:'chosen'}, '#reviewAssignmentCreateComparison':{value:'mismatch'},
 '#reviewAssignmentCreateSearch':{value:'cn123'}, '#reviewAssignmentCreateButton':{},
 '#reviewAssignmentCreateStatus':{}, '#workSplitSummary':{},
};
$=(selector)=>nodes[selector];selectedBaselineQueryValue=()=>'0522';
let draft,requested;
api=async(path,options)=>{assert.equal(options,undefined);requested=new URL(path,'https://test');return {total:7};};
openWorkSplitDialog=async(value)=>{draft=value;};showToast=()=>{};
(async()=>{
 await openReviewAssignmentCreate();
 assert.equal(requested.searchParams.get('model_run_id'),'chosen');
 assert.equal(requested.searchParams.get('comparison'),'mismatch');
 assert.equal(requested.searchParams.get('baselines'),'0522');
 assert.equal(requested.searchParams.get('include_thumbnail'),'false');
 assert.equal(draft.total,7);
 assert.equal(draft.filters.search,'cn123');
 assert.equal(nodes['#reviewAssignmentCreateButton'].disabled,false);
 draft=null;api=async()=>({total:0});await openReviewAssignmentCreate();assert.equal(draft,null);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)
