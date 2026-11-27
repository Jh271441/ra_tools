from pathlib import Path
import shutil
import subprocess
import unittest


class IssueDecisionDialogBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_case_labeling_decision_reconciles_the_filtered_queue(self):
        source = Path(__file__).resolve().parents[1] / 'static/js'
        script = r'''
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('node:assert/strict');
async function scenario(before, after, {pendingImages = [], race = false, failList = false} = {}) {
  const issue = 'cn34021313', calls = [], toasts = [];
  const form = {querySelectorAll:()=>[]}, error = {textContent:''}, confirmation = {checked:true};
  const data = {issue_id:issue, label_state:{state:'conflict',source_fingerprint:'original'}};
  const labeling = {
    issueId:issue, caseData:data, page:2, pageSize:10, chartGt:'blocked',
    detailSeq:1, requestSeq:0, pendingImages:[], dirty:false,
    data:{queue_issue_ids:before,total:before.length},
  };
  const s = {
    state:{activePage:'labeling',caseLabeling:labeling,session:{username:'alice'}},
    URLSearchParams, AbortController, DEFAULT_CASE_PAGE_SIZE:20,
    $:selector=>({'#caseLabelingForm':form,'#caseDecisionEditorError':error,'#caseDecisionConfirmExclusion':confirmation})[selector]||null,
    hasDashboardWriteRole:()=>true, isPageContextCurrent:()=>true, selectedBaselineQueryValue:()=> '0626',
    withBaselineQuery:p=>p, joinFilterList:values=>(values||[]).join(','),
    enhanceDashboardSelects(){}, acknowledgeLocalChange(){}, hasFocusedTextInput:()=>false,
    uiText:(zh,en)=>en, showToast:message=>toasts.push(message),
    caseExclusionErrorMessage:error=>error.message,
    api:async(url, options={})=>{
      calls.push({url,options});
      if (options.method==='POST') return {decision:{id:294}};
      if (url.startsWith('/api/labeling/cases?')) {
        if (race) labeling.detailSeq++;
        if (failList) throw Error('list unavailable');
        return {queue_issue_ids:after,total:after.length,page:1};
      }
      return {...data,label_state:{state:'resolved',decision:{id:294}}};
    },
  };
  vm.createContext(s);
  for (const file of ['case-labeling.js','case-label-decision.js']) {
    vm.runInContext(fs.readFileSync(path.join(process.env.DECISION_QUEUE_SOURCE || process.argv[1],file),'utf8'),s);
  }
  Object.assign(s,{
    renderCaseLabelingList(){}, refreshCaseLabelDecisionLanguage(){},
    caseLabelingFormPayload:()=>({expected_output:'正确触发',tags:[],rationale:'evidence',is_excluded:true}),
    caseLabelingOutputValidation:()=>({conflict:false}),
    exitCaseDecisionEditor:()=>{
      vm.runInContext('caseLabelDecisionUi.editor=null',s);
      labeling.pendingImages=pendingImages;
    },
    selectCaseLabelingIssue:async(id,options)=>{labeling.issueId=id;labeling.historyMode=options.historyMode;},
    closeCaseLabelingDetail:options=>{labeling.issueId='';labeling.historyMode=options.historyMode;},
  });
  vm.runInContext(`caseLabelDecisionUi.editor={key:'draft',baselines:'0626',pageContext:{},actor:'alice',
    data:${JSON.stringify(data)}, excludedConfirmed:true, images:[],retained:[],
    ordinary:{}, rationale:''}`,s);
  await s.adjudicateIssueLabel();
  assert.equal(calls.filter(call=>call.options.method==='POST').length,1,error.textContent);
  const request=calls.find(call=>call.url.startsWith('/api/labeling/cases?'));
  assert(request, 'a saved decision must read the fresh filtered queue');
  assert.equal(request.options.cache,'no-store');
  const params=new URL(request.url,'http://test').searchParams;
  assert.equal(params.get('chart_gt'),'blocked');
  assert.equal(params.get('baselines'),'0626');
  assert.equal(params.get('page'),'2');
  assert.equal(params.get('page_size'),'10');
  return {labeling,calls,toasts};
}
(async()=>{
  const issue='cn34021313', next='cn34026417', last='cn34029999';
  let f=await scenario([issue,next,last],[next,last]);
  assert.equal(f.labeling.issueId,next);
  assert.equal(f.labeling.data.total,2);
  assert.equal(f.labeling.historyMode,'replace');
  assert.equal(f.calls.length,2,'do not refetch the detail just left');
  f=await scenario([next,issue],[next]);
  assert.equal(f.labeling.issueId,next,'fall back to the previous Issue at the end');
  f=await scenario([issue],[]);
  assert.equal(f.labeling.issueId,'','return to the gallery when the queue is empty');
  f=await scenario([issue,next],[issue,next]);
  assert.equal(f.labeling.issueId,issue);
  assert.equal(f.labeling.caseData.label_state.decision.id,294);
  f=await scenario([issue,next],[next],{pendingImages:[{id:'image'}]});
  assert.equal(f.labeling.issueId,issue);
  assert.equal(f.labeling.pendingImages.length,1);
  f=await scenario([issue,next],[next],{race:true});
  assert.equal(f.labeling.issueId,issue);
  assert.equal(f.labeling.data.total,2,'ignore a refresh after the user starts navigating');
  f=await scenario([issue,next],[next],{failList:true});
  assert.match(f.toasts.at(-1),/Decision saved.*filtered results/);
  assert.equal(f.labeling.caseData.label_state.decision.id,294);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_complete_payload_conflict_duplicate_guard_and_draft_isolation(self):
        source=Path(__file__).resolve().parents[1]/'static/js/case-label-decision.js'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let current=true,write=true,fail=true,posts=[],paths=[],release,hold=false;
const input={value:'judge explanation',checked:true,attributes:{},setAttribute(k,v){this.attributes[k]=v},focus(){this.focused=true}};const error={textContent:''},confirmError={textContent:''};
const form={querySelectorAll(){return []}};
Object.assign(global,{document:{},$:key=>key==='#caseLabelingForm'?form:key==='#caseDecisionEditorError'?error:key==='#caseDecisionConfirmError'?confirmError:input,
 state:{caseLabeling:{issueId:'cn1',pendingImages:[],dirty:true,caseData:{label_state:{state:'conflict'}}}},
 uiText:(z,e)=>e,caseExclusionErrorMessage:e=>e.message,hasDashboardWriteRole:()=>write,isPageContextCurrent:()=>current,
 selectedBaselineQueryValue:()=> '0508',enhanceDashboardSelects(){},showToast(){},acknowledgeLocalChange(){},
 caseLabelingFormPayload:()=>({expected_output:'误触发',tags:['tag'],evidence_gaps:[],rationale:'label evidence',is_excluded:false}),
 caseLabelingOutputValidation:()=>({conflict:false}),
 api:async(path,opts)=>{paths.push(path);posts.push(JSON.parse(opts.body));if(hold)await new Promise(r=>release=r);if(fail)throw Error('409 sources changed');return {decision:{id:8}}}
});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
function reset(){caseLabelDecisionUi.editor={key:'draft',baselines:'0508',pageContext:{},data:{issue_id:'cn1',label_state:{source_fingerprint:'fp',decision:{id:7}}},adoptedId:2,retained:[],images:[],rationale:'judge explanation',ordinary:{images:['ordinary image'],dirty:true}};}
let exits=0,refreshes=0;
exitCaseDecisionEditor=()=>{exits++;caseLabelDecisionUi.editor=null};
refreshCaseDecisionResult=async()=>{refreshes++};
(async()=>{
 reset();await adjudicateIssueLabel();
 assert.equal(posts[0].full_result,true);assert.equal(posts[0].is_excluded,false);
 assert.equal(posts[0].label_rationale,'label evidence');assert.equal(posts[0].rationale,'judge explanation');
 assert.equal(posts[0].adopted_revision_id,2);assert.equal(posts[0].expected_source_fingerprint,'fp');assert.equal(posts[0].expected_previous_decision_id,7);
 assert.match(error.textContent,/409/);assert.equal(exits,0);assert.equal(caseLabelDecisionUi.drafts.get('draft').rationale,'judge explanation');
 assert.deepEqual(caseLabelDecisionUi.editor.ordinary.images,['ordinary image']);
 fail=false;hold=true;posts=[];const first=adjudicateIssueLabel();await adjudicateIssueLabel();assert.equal(posts.length,1);release();await first;
 assert.equal(exits,1);assert.equal(refreshes,1);assert.equal(caseLabelDecisionUi.drafts.has('draft'),false);
 hold=false;reset();write=false;posts=[];await adjudicateIssueLabel();assert.equal(posts.length,0);
 write=true;current=false;await adjudicateIssueLabel();assert.equal(posts.length,0);
 current=true;input.checked=false;await adjudicateIssueLabel();assert.equal(posts.length,0);
 assert.match(confirmError.textContent,/Confirm the exclusion/);assert.equal(input.attributes['aria-invalid'],'true');assert.equal(input.focused,true);
 input.checked=true;updateCaseDecisionConfirmation();assert.equal(confirmError.textContent,'');assert.equal(input.attributes['aria-invalid'],'false');
 input.checked=true;input.value='';await adjudicateIssueLabel();assert.equal(posts.length,1);
 assert.equal(posts[0].rationale,'');assert.equal(posts[0].label_rationale,'label evidence');
 state.activePage='review';state.selectedId='cn1';state.selectedRunId='model-run';state.reviewWorkSplitId='campaign';
 reviewSaveNavigationContext=async()=>({issueId:'cn1'});reviewSaveNavigationIsCurrent=()=>true;
 reset();posts=[];paths=[];await adjudicateIssueLabel();assert.equal(paths[0],'/api/labeling/issues/cn1/decisions');
 assert.equal(posts[0].model_run_id,undefined);assert.equal(posts[0].campaign_id,undefined);assert.equal(posts[0].is_excluded,false);assert.equal(posts[0].adopted_revision_id,2);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
