from pathlib import Path
import shutil,subprocess,unittest

class ExclusionDialogBehaviorTest(unittest.TestCase):
 @unittest.skipUnless(shutil.which('node'),'Node required')
 def test_full_payload_and_draft_ownership(self):
  source=Path(__file__).resolve().parents[1]/'static/js/case-exclusion-decision.js'
  script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let current=true,write=true,fail=false,release,block=false,posts=[];
const n=(value='')=>({value,checked:false,disabled:false,hidden:true,setAttribute(){},removeAttribute(){}});
const nodes={'#caseExclusionTask':n('task-case'),'#caseExclusionReference':n('2'),'#caseExclusionChoice':n('false'),'#caseExclusionRationale':n('no exclusion required'),'#caseExclusionConfirm':n(),'#caseExclusionSubmit':n(),'#caseExclusionDialog .case-label-decision-error':n(),'#caseExclusionDialog':{open:true,querySelectorAll(){return []},close(){this.open=false;rememberCaseExclusionDraft();}}};
const task={id:'task-case',can_adjudicate_exclusion:true,resolution:{heads:[{id:1,expected_output:'',is_excluded:true},{id:2,expected_output:'误触发',tags:['keep'],evidence_gaps:['camera'],is_excluded:false}],adjudication:{id:7}}};
const data={issue_id:'cn1',label_cases:[task],label_state:{state:'pending'}};
Object.assign(global,{$:key=>nodes[key]||null,state:{caseLabeling:{issueId:'cn1',dirty:true,pendingImages:['keep'],caseData:data}},hasDashboardWriteRole:()=>write,isPageContextCurrent:()=>current,selectedBaselineQueryValue:()=> '0508',uiText:(z,e)=>e,showToast(){},acknowledgeLocalChange(){},withBaselineQuery:p=>p,enhanceNativeUiSelect(){},refreshCaseLabelDecisionLanguage(){},api:async(p,o)=>{if(o){posts.push(JSON.parse(o.body));if(block)await new Promise(r=>release=r);if(fail)throw Error('409 source changed');return {change_revision:2}}return {label_cases:[task],label_state:{state:'resolved'},exclusion_summary:{is_excluded:false}}}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
assert.equal(caseExclusionNeedsDecision(data),true);
assert.equal(caseExclusionNeedsDecision({label_cases:[{resolution:{state:'resolved',method:'adjudication',result_revision:{id:3,is_excluded:false},heads:task.resolution.heads}}]}),false);
assert.equal(caseExclusionNeedsDecision({label_cases:[{resolution:{heads:[{id:1,is_excluded:true},{id:2,is_excluded:true}]}}]}),false);
function reset(){caseExclusionUi.context={caseData:data,key:'k',baselines:'0508',pageContext:{},draft:{}};}
(async()=>{
 reset();await saveCaseExclusionDecision();assert.equal(posts.length,0); // explicit confirmation required
 nodes['#caseExclusionConfirm'].checked=true;fail=true;await saveCaseExclusionDecision();
 assert.equal(posts.length,1);assert.deepEqual(posts[0],{expected_output:'误触发',tags:['keep'],evidence_gaps:['camera'],is_excluded:false,rationale:'no exclusion required',source_revision_ids:[1,2],expected_previous_resolution_id:7,adjudication_scope:'exclusion',confirm_full_label:true});
 assert.equal(caseExclusionUi.drafts.get('k').rationale,'no exclusion required');assert.equal(nodes['#caseExclusionDialog'].open,true);
 fail=false;block=true;posts=[];const pending=saveCaseExclusionDecision();await saveCaseExclusionDecision();assert.equal(posts.length,1);
 current=false;state.caseLabeling.issueId='cn2';release();await pending;assert.equal(data.label_state.state,'pending');assert.equal(state.caseLabeling.dirty,true);assert.deepEqual(state.caseLabeling.pendingImages,['keep']);
 block=false;current=true;state.caseLabeling.issueId='cn1';reset();write=false;await saveCaseExclusionDecision();assert.equal(posts.length,1);
 write=true;await saveCaseExclusionDecision();assert.equal(data.label_state.state,'resolved');assert.equal(state.caseLabeling.dirty,true);assert.deepEqual(state.caseLabeling.pendingImages,['keep']);assert.equal(caseExclusionUi.drafts.has('k'),false);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
  result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
