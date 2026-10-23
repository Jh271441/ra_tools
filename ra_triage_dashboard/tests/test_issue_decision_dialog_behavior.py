from pathlib import Path
import shutil
import subprocess
import unittest

class IssueDecisionDialogBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_independent_payload_failures_concurrency_and_navigation(self):
        source=Path(__file__).resolve().parents[1]/'static/js/case-label-decision.js'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let current=true,canWrite=true,fail=false,pendingResolve=null,posts=[];
const node=(value='')=>({value,disabled:false,hidden:true,setAttribute(){},removeAttribute(){},focus(){}});
const nodes={
 '#caseLabelDecisionExpectedOutput':node('误触发'), '#caseLabelDecisionRationale':node('decision rationale'),
 '#caseLabelingExpectedOutput':node('正确触发'), '#caseLabelingRationale':node('unsaved label draft'),
 '#caseLabelDecisionSubmit':node(), '#caseLabelDecisionDialog .case-label-decision-error':node(),
 '#caseLabelDecisionDialog':{open:true,close(){this.open=false;rememberCaseLabelDecisionDraft();}}
};
Object.assign(global,{document:{activeElement:null},$:key=>nodes[key]||null,uiText:(zh,en)=>en,showToast:()=>{},
 state:{activePage:'labeling',caseLabeling:{issueId:'cn1',dirty:true,caseData:{label_state:{state:'conflict'}},pendingImages:['keep']}},
 enhanceNativeUiSelect:()=>{},hasDashboardWriteRole:()=>canWrite,isPageContextCurrent:()=>current,selectedBaselineQueryValue:()=> '0508',
 EXPECTED_OUTPUT_OPTIONS:[{value:'误触发'},{value:'正确触发'}],acknowledgeLocalChange:()=>{},
 withBaselineQuery:p=>p,caseLabelFinalResultMarkup:()=>'',
 api:async(path,opts)=>{if(opts){posts.push(JSON.parse(opts.body));if(pendingResolve)await new Promise(resolve=>pendingResolve(resolve));if(fail)throw Error('409 source changed');return {ok:true};}return {label_state:{state:'resolved'}};}
});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
vm.runInThisContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'case-exclusion-decision.js'),'utf8'));
function context(){caseLabelDecisionUi.context={key:'key',baselines:'0508',pageContext:{},caseData:{issue_id:'cn1',label_state:{source_fingerprint:'fp',sources:[],decision:{id:7}}}};}
(async()=>{
 context();fail=true;await adjudicateIssueLabel();
 assert.equal(posts[0].expected_output,'误触发');assert.equal(posts[0].rationale,'decision rationale');
 assert.equal(posts[0].expected_source_fingerprint,'fp');assert.equal(posts[0].expected_previous_decision_id,7);
 assert.equal(nodes['#caseLabelDecisionDialog'].open,true);assert.match(caseLabelDecisionUi.context.error,/409/);
 assert.equal(caseLabelDecisionUi.drafts.get('key').rationale,'decision rationale');
 assert.equal(state.caseLabeling.dirty,true);assert.deepEqual(state.caseLabeling.pendingImages,['keep']);
 fail=false;let release;pendingResolve=resolve=>release=resolve;posts=[];
 const first=adjudicateIssueLabel();await adjudicateIssueLabel();assert.equal(posts.length,1);
 current=false;state.caseLabeling.issueId='cn2';release();await first;
 assert.equal(state.caseLabeling.caseData.label_state.state,'conflict');
 assert.equal(caseLabelDecisionUi.drafts.has('key'),false);
 assert.equal(nodes['#caseLabelingRationale'].value,'unsaved label draft');
 current=true;pendingResolve=null;state.caseLabeling.issueId='cn1';context();posts=[];
 caseLabelDecisionUi.context.caseData.label_state.sources=[{task_id:'t',state:'conflict'}];
 await adjudicateIssueLabel();assert.equal(posts.length,0);
 context();canWrite=false;await adjudicateIssueLabel();assert.equal(posts.length,0);
 canWrite=true;await adjudicateIssueLabel();assert.equal(posts.length,1);
 assert.equal(state.caseLabeling.caseData.label_state.state,'resolved');assert.equal(state.caseLabeling.dirty,true);
 console.log('Independent decision payload, failure retention, duplicate guard, navigation ownership and main draft preservation passed');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
