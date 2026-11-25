import subprocess
from pathlib import Path


def test_comparison_media_case_navigation_and_page_boundaries():
    script=Path('ra_triage_dashboard/static/js/media-dialog.js').read_text()+'''
const assert=require('node:assert/strict');
const state={activePage:'comparison',media:{snapshot:{referenceMedia:true,issueId:'a'},kind:'camera'},runComparison:{data:{page:1,page_count:2,items:[{issue_id:'a'},{issue_id:'b'}]}}};
const $=()=>({open:false});
let opened=[];let notices=[];
showToast=(x)=>notices.push(x);
openComparisonMedia=async(id,kind)=>{opened.push([id,kind]);state.media.snapshot.issueId=id;};
loadRunComparison=async()=>{state.runComparison.data={page:2,page_count:2,items:[{issue_id:'c'}]};};
(async()=>{
 await navigateComparisonMediaCase(1);assert.deepEqual(opened[0],['b','camera']);
 await navigateComparisonMediaCase(1);assert.deepEqual(opened[1],['c','camera']);assert.equal(state.runComparison.page,2);
 await navigateComparisonMediaCase(1);assert.equal(opened.length,2);assert.ok(notices.length);
})();
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True)


def test_comparison_case_dialog_shortcuts_queue_and_cross_pages():
    script = Path('ra_triage_dashboard/static/js/run-comparison.js').read_text() + '''
const assert=require('node:assert/strict');
const dialog={open:true,dataset:{issueId:'a',tab:'prompt'}};
const state={activePage:'comparison',runComparison:{page:1,data:{page:1,page_count:2,items:[{issue_id:'a'},{issue_id:'b'},{issue_id:'c'}]}}};
const $=(selector)=>selector==='#comparisonReasonDialog' ? dialog : null;
let opened=[];let notices=[];let pageLoads=0;
showToast=(message)=>notices.push(message);
uiText=(zh)=>zh;
openComparisonReasonDialog=(id,options)=>{opened.push([id,options]);dialog.dataset.issueId=id;};
loadRunComparison=async()=>{pageLoads++;state.runComparison.data=state.runComparison.page===2 ? {page:2,page_count:2,items:[{issue_id:'d'},{issue_id:'e'}]} : {page:1,page_count:2,items:[{issue_id:'a'},{issue_id:'b'},{issue_id:'c'}]};};
(async()=>{
 await Promise.all([navigateComparisonCaseDialog(1),navigateComparisonCaseDialog(1)]);
 assert.deepEqual(opened,[['b',{preserveTab:true}],['c',{preserveTab:true}]]);
 await navigateComparisonCaseDialog(1);
 assert.equal(pageLoads,1);assert.equal(state.runComparison.page,2);
 assert.deepEqual(opened[2],['d',{preserveTab:true}]);
 await navigateComparisonCaseDialog(-1);
 assert.deepEqual(opened[3],['c',{preserveTab:true}]);
 await navigateComparisonCaseDialog(-1);
 assert.deepEqual(opened[4],['b',{preserveTab:true}]);
 await navigateComparisonCaseDialog(-1);
 assert.deepEqual(opened[5],['a',{preserveTab:true}]);
 await navigateComparisonCaseDialog(-1);
 assert.ok(notices.length);
})();
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)


def test_comparison_run_selection_applies_inferred_dataset():
    script = Path('ra_triage_dashboard/static/js/run-comparison.js').read_text() + '''
const assert=require('node:assert/strict');
const state={modelRuns:[
  {id:'run-0508',inferred_baseline_ids:['0508']},
  {id:'run-0821',inferred_baseline_ids:['0821']},
],runComparison:{baselineRunId:'run-0508',candidateRunId:'run-0508',page:9}};
let renders=0;let applied=[];
renderRunComparisonSelectors=()=>{renders++;};
applyInferredBaselinesFromRun=async(run,options)=>{applied.push([run.id,options]);return true;};
(async()=>{
 const switched=await selectRunComparisonRun('candidate','run-0821');
 assert.equal(switched,true);
 assert.equal(state.runComparison.candidateRunId,'run-0821');
 assert.equal(state.runComparison.page,1);
 assert.equal(renders,1);
 assert.deepEqual(applied,[['run-0821',{reason:'run'}]]);
})();
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)


def test_comparison_reason_tooltip_only_exists_for_saved_reason():
    script = Path('ra_triage_dashboard/static/js/run-comparison.js').read_text() + '''
const assert=require('node:assert/strict');
escapeHtml=(value)=>String(value);
uiText=(zh)=>zh;
const missing=comparisonPredictionHtml({model_label:'误触发',correct:false});
assert.match(missing,/comparison-prediction-reason is-empty/);
assert.doesNotMatch(missing,/ title=/);
const saved=comparisonPredictionHtml({model_label:'误触发',model_reason:'完整原因',correct:false});
assert.match(saved,/comparison-prediction-reason has-saved-reason/);
assert.match(saved,/title="完整原因"/);
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)
