"""Assignment links preserve a task's view across users and reloads."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'static/js/routing.js').read_text() + (ROOT / 'static/js/review-assignments.js').read_text()
SETUP = r'''
const assert = require('node:assert/strict');
global.document = {getElementById:()=>null,querySelectorAll:()=>[]};
$ = () => null;
global.window = {location:{origin:'https://triage.test', search:''},history:{state:{},replaceState:()=>{}}};
global.state = {activePage:'review-assignments',session:{},modelRuns:[{id:'run'}],reviewAssignments:{
 lifecycle:'current',assignedToMe:true,selectedSplitId:'campaign-a',detail:null,detailRequestSeq:0,
 requestSeq:0,splits:[],page:3,pageSize:20,status:'pending',assignee:'liangxianghui',query:'转向 & lane',
}};
withBase = p => '/manual'+p;
uiText = (zh,en) => zh;
'''


class AssignmentShareTest(unittest.TestCase):
    def run_js(self, body):
        result = subprocess.run(['node','-e',SOURCE+SETUP+body],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_detail_link_roundtrips_filters_and_shared_router(self):
        self.run_js(r'''
const url=new URL(reviewAssignmentShareUrl());
assert.equal(url.pathname,'/manual/review-assignments');
assert.equal(url.searchParams.get('split'),'campaign-a');
assert.equal(url.searchParams.get('assignee'),'liangxianghui');
assert.equal(url.searchParams.get('q'),'转向 & lane');
assert.equal(url.searchParams.get('page'),'3');
assert.equal(url.searchParams.get('page_size'),'20');
assert.equal(url.searchParams.get('status'),'pending');
restoreReviewAssignmentDetailRoute(url.searchParams);
assert.equal(state.reviewAssignments.page,3);
assert.equal(state.reviewAssignments.pageSize,20);
assert.equal(state.reviewAssignments.query,'转向 & lane');
const routed=new URL('https://triage.test/manual/review-assignments');
setReviewAssignmentRouteParams(routed,'campaign-a');
assert.equal(routed.search,url.search);
''')

    def test_card_link_does_not_inherit_sender_or_detail_filters(self):
        self.run_js(r'''
for(const task of ['campaign-a','campaign-b','version:release-20261009-odd2']){
 const url=new URL(reviewAssignmentShareUrl(task,{taskOnly:true}));
 assert.equal(url.searchParams.get('split'),task);
 for(const key of ['assignee','status','q','page','page_size','assigned_to_me'])assert.equal(url.searchParams.has(key),false,key);
}
const list=new URL(reviewAssignmentShareUrl(''));
assert.equal(list.searchParams.get('assigned_to_me'),'true');
for(const key of ['split','assignee','status','q','page','page_size'])assert.equal(list.searchParams.has(key),false);
''')

    def test_invalid_and_empty_filters_restore_safe_defaults(self):
        self.run_js(r'''
restoreReviewAssignmentDetailRoute(new URLSearchParams('page=-1&page_size=999&status=oops&q='+encodeURIComponent('x'.repeat(140))));
assert.equal(state.reviewAssignments.page,1);assert.equal(state.reviewAssignments.pageSize,50);
assert.equal(state.reviewAssignments.status,'all');assert.equal(state.reviewAssignments.query.length,128);
restoreReviewAssignmentDetailRoute(new URLSearchParams());
assert.equal(state.reviewAssignments.assignee,'');assert.equal(state.reviewAssignments.query,'');
''')

    def test_reload_requests_shared_page_and_owner_without_resetting(self):
        self.run_js(r'''
window.location.search='?lifecycle=current&split=campaign-a&assignee=liangxianghui&status=completed&page=4&page_size=10&q=cn37';
renderReviewAssignmentPage=()=>{};restoreReviewAllocationDraft=async()=>{};
let requests=[];
api=async path=>{requests.push(path);return path.includes('/campaign-a?')?{split_id:'campaign-a'}:{items:[]}};
(async()=>{
 await loadReviewAssignments({splitId:'campaign-a'});
 const url=new URL(requests.find(p=>p.includes('/campaign-a?')),'https://triage.test');
 for(const [key,value] of Object.entries({page:'4',page_size:'10',assignee:'liangxianghui',status:'completed',q:'cn37'}))assert.equal(url.searchParams.get(key),value,key);
 assert.equal(state.reviewAssignments.page,4);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_clipboard_success_and_denial_have_truthful_feedback(self):
        self.run_js(r'''
Object.defineProperty(globalThis,'navigator',{value:{clipboard:{}},configurable:true});
const messages=[],prompts=[];showToast=text=>messages.push(text);window.prompt=(...args)=>prompts.push(args);
(async()=>{
 let copied='';navigator.clipboard.writeText=async value=>{copied=value};
 await copyReviewAssignmentLink();assert.equal(copied,reviewAssignmentShareUrl());assert.equal(messages.length,1);assert.equal(prompts.length,0);
 navigator.clipboard.writeText=async()=>{throw Error('permission denied')};
 await copyReviewAssignmentLink();assert.equal(messages.length,1);assert.equal(prompts.length,1);assert.equal(prompts[0][1],copied);
 navigator.clipboard={};await copyReviewAssignmentLink();assert.equal(messages.length,1);assert.equal(prompts.length,2);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_list_and_detail_paint_while_optional_metadata_is_pending(self):
        self.run_js(r'''
state.modelRuns=[];state.accessUsers=[];state.session.is_admin=true;
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const runs=deferred(),users=deferred(),detail=deferred();
loadRuns=()=>runs.promise;loadAccessUsers=()=>users.promise;
let paints=0,enrichments=0,restored=0,requests=[];
renderReviewAssignmentPage=()=>paints++;
renderReviewAssignmentList=()=>enrichments++;
renderReviewAssignmentRowPersonPickers=()=>enrichments++;
restoreReviewAllocationDraft=async()=>{restored++};showToast=message=>{throw Error(message)};
api=async path=>{requests.push(path);return path.includes('/campaign-a?')?detail.promise:{items:[{split_id:'campaign-a'}]};};
(async()=>{
 const loading=loadReviewAssignments({splitId:'campaign-a'});
 await new Promise(setImmediate);
 assert.equal(state.reviewAssignments.splits[0]?.split_id,'campaign-a','list cannot wait for Run/user metadata');
 assert.equal(state.reviewAssignments.loading,false);
 assert.ok(requests.some(path=>path.includes('/campaign-a?')),'selected detail also starts before metadata');
 detail.resolve({split_id:'campaign-a'});await new Promise(setImmediate);
 assert.equal(state.reviewAssignments.detail?.split_id,'campaign-a');
 const before=paints;runs.resolve();users.resolve();await loading;
 assert.equal(paints,before,'late metadata must not rebuild detail rows/unsaved picks');
 assert.equal(enrichments,2);assert.equal(restored,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_optional_metadata_failure_keeps_list_and_newer_load_owns_results(self):
        self.run_js(r'''
state.modelRuns=[];state.session.is_admin=true;state.accessUsers=[];
let finishFirst;const first=new Promise(r=>finishFirst=r),messages=[];
loadRuns=async()=>{throw Error('Run catalog unavailable')};loadAccessUsers=async()=>{};
renderReviewAssignmentPage=()=>{};renderReviewAssignmentList=()=>{};
renderReviewAssignmentRowPersonPickers=()=>{};restoreReviewAllocationDraft=async()=>{};
showToast=message=>messages.push(message);
api=async path=>path.includes('lifecycle=current')?first:{items:[{split_id:'new'}]};
(async()=>{
 const stale=loadReviewAssignments({reloadDetail:false});
 window.location.search='?lifecycle=history';
 await loadReviewAssignments({force:true,reloadDetail:false});
 finishFirst({items:[{split_id:'old'}]});await stale;
 assert.equal(state.reviewAssignments.splits[0].split_id,'new');
 assert.equal(state.reviewAssignments.loading,false);
 assert.deepEqual(messages,['Run catalog unavailable']);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')


if __name__ == '__main__':
    unittest.main()
