from pathlib import Path
import shutil
import subprocess
import unittest


class IssueDecisionDialogBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_complete_payload_conflict_duplicate_guard_and_draft_isolation(self):
        source=Path(__file__).resolve().parents[1]/'static/js/case-label-decision.js'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let current=true,write=true,fail=true,posts=[],release,hold=false;
const input={value:'judge explanation',checked:true,attributes:{},setAttribute(k,v){this.attributes[k]=v},focus(){this.focused=true}};const error={textContent:''},confirmError={textContent:''};
const form={querySelectorAll(){return []}};
Object.assign(global,{document:{},$:key=>key==='#caseLabelingForm'?form:key==='#caseDecisionEditorError'?error:key==='#caseDecisionConfirmError'?confirmError:input,
 state:{caseLabeling:{issueId:'cn1',pendingImages:[],dirty:true,caseData:{label_state:{state:'conflict'}}}},
 uiText:(z,e)=>e,caseExclusionErrorMessage:e=>e.message,hasDashboardWriteRole:()=>write,isPageContextCurrent:()=>current,
 selectedBaselineQueryValue:()=> '0508',enhanceDashboardSelects(){},showToast(){},acknowledgeLocalChange(){},
 caseLabelingFormPayload:()=>({expected_output:'误触发',tags:['tag'],evidence_gaps:[],rationale:'label evidence',is_excluded:false}),
 caseLabelingOutputValidation:()=>({conflict:false}),
 api:async(path,opts)=>{posts.push(JSON.parse(opts.body));if(hold)await new Promise(r=>release=r);if(fail)throw Error('409 sources changed');return {decision:{id:8}}}
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
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
