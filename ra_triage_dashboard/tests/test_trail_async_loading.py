"""Delayed metadata/status must not block local rows or reclaim navigation."""
from pathlib import Path
import shutil
import subprocess
import unittest


class TrailAsyncLoadingTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_independent_first_paint_scope_and_late_responses(self):
        root = Path(__file__).resolve().parents[1] / "static/js"
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
let baseline='0508';
let epoch=1,active='trail-update',search='',routes=[],renders=[],patches=[],calls=[],metadata=deferred(),local=deferred(),remote=deferred();
Object.assign(global,{
 state:{trailUpdate:{runId:'explicit-run',tab:'review',filters:{},requestSeq:0,data:null}},
 $:()=>null,document:{querySelectorAll:()=>[]},uiText:(zh,en)=>en,
 selectedBaselineQueryValue:()=> baseline,
 capturePageContext:()=>({epoch,page:active}),
 isPageContextCurrent:c=>c.epoch===epoch&&c.page===active,
 loadRuns:()=>{calls.push('runs');return metadata.promise},
 loadOverview:()=>metadata.promise,loadReviewers:()=>metadata.promise,loadWorkAssignees:()=>metadata.promise,
 settleInitialRequests:promises=>Promise.allSettled(promises),showToast(){},
 api:url=>{calls.push(url);return url.includes('/status?')?remote.promise:local.promise}
});
for(const name of ['trail-update-state.js','trail-update-preview.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
renderTrailAttributeRunPicker=()=>{};
renderTrailAttributePreview=data=>renders.push(data);
syncTrailAttributeActions=()=>{};
trailUpdatePersistRoute=()=>routes.push({active,search});
patchTrailAttributeStatus=data=>patches.push(data);
setTrailAttributeStatus=()=>{};
const payload={items:[{issue_id:'cn1'}],draft:{},write_ready:false};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 startTrailAttributePage();
 assert.equal(calls.includes('runs'),false);assert.doesNotMatch(calls[0],/model_run_id/);assert.match(calls[0],/probe_trail=false/);assert.equal(state.trailUpdate.runId,'');assert.equal(trailUpdatePreviewKey('old-run'),trailUpdatePreviewKey('other-run'));
 search='typed while loading';local.resolve(payload);await tick();
 assert.equal(renders.length,1);assert.equal(state.trailUpdate.loading,false);
 assert.equal(routes[0].search,search);assert.equal(calls.filter(u=>u.includes('/status?')).length,1);
 // Neither pending remote status nor metadata prevents local completion.
 assert.equal(state.trailUpdate.data,payload);assert.equal(patches.length,0);
 active='labeling';epoch++;remote.resolve({write_ready:true});metadata.resolve();await tick();assert.equal(patches.length,0);assert.equal(routes.length,1);
 // Leaving and returning to the same URL also makes the old local result stale.
 active='trail-update';epoch++;local=deferred();remote=deferred();
 const stale=loadTrailAttributePreview(true);epoch+=2;local.resolve(payload);await stale;
 assert.equal(renders.length,1);assert.equal(routes.length,1);assert.equal(state.trailUpdate.loading,false);
 // A late response cannot apply to a newer dataset scope.
 local=deferred();const oldRun=loadTrailAttributePreview(true);baseline='0821';local.resolve(payload);await oldRun;
 assert.equal(renders.length,1);assert.equal(routes.length,1);
 // Current-scope failures keep the local rows usable and fail the write gate.
 remote=deferred();const currentKey=trailUpdatePreviewKey();
 const failed=refreshTrailAttributeStatus({requestSeq:state.trailUpdate.requestSeq,previewKey:currentKey});remote.reject(Error('offline'));await assert.rejects(failed,/offline/);
 assert.equal(patches.length,1);assert.equal(patches[0].write_ready,false);assert.equal(patches[0].trail_update_statuses.cn1,'query_failed');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run(["node", "-e", script, str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_selected_issue_preview_never_inherits_stale_run(self):
        root = Path(__file__).resolve().parents[1] / "static/js"
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const requests=[];
Object.assign(global, {
 state:{trailUpdate:{runId:'old-run',data:{selected_run:{id:'old-run'},baselines:['0508']},selectionIntent:'exclude'}},
 trailSelectionReady:()=>true,trailUpdatePreviewKey:()=> 'issues|0508|local',
 trailSelectedIssues:()=>new Set(['cn1']),syncTrailAttributeActions(){},
 syncTrailSelectionControls(){},setTrailAttributeStatus(){},uiText:(zh,en)=>en,
 api:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {mode:'selected_exclusions',items:[]}}
});
vm.runInThisContext(fs.readFileSync(process.argv[1]+'/trail-update-commit.js','utf8'));
openTrailUpdateConfirm=async()=>false;
(async()=>{
 await commitTrailAttributeUpdate();
 assert.equal(requests.length,1);
 assert.equal(requests[0].url,'/api/trail-attribute-update/selection-preview');
 assert.deepEqual(requests[0].body,{issue_ids:['cn1'],intent:'exclude',baselines:['0508']});
 assert.equal(state.trailUpdate.selectionBusy,false);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run(["node", "-e", script, str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
