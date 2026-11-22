"""Behavior checks for shared components after extraction from work-split.js."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'static/js'


class AssignmentComponentTest(unittest.TestCase):
    def test_manual_edit_and_new_request_win_over_old_name_response(self):
        script = (ROOT / 'assignment-naming.js').read_text() + r'''
const assert=require('node:assert/strict');
let queued, pending=[], requests=0;
const input={value:'',dataset:{}}, handlers={}, refresh={disabled:false,addEventListener:(name,cb)=>handlers.refresh=cb};
input.addEventListener=(name,cb)=>handlers.input=cb;
state={session:{is_admin:true}};
window={clearTimeout:()=>{},setTimeout:cb=>{queued=cb;return 1;}};
assignmentNameElements=()=>({input,refresh,status:{}});
assignmentNameContext=()=>({datasetLabels:['0508'],baselineIds:['0508'],caseCount:10,memberCount:1,reviewersPerIssue:1,overlapRatio:0,assignmentKind:'case_labeling',workflowMode:'',modelRunId:'',comparison:'all'});
renderAssignmentNameStatus=()=>{};
api=()=>{requests++;return new Promise(resolve=>pending.push(resolve));};
(async()=>{
 bindAssignmentNameInput('labeling');
 updateAssignmentNameSuggestion('labeling',{immediate:true});
 assert.match(input.value,/0508.*10 Case/);
 const first=queued();
 input.value='my manual name';handlers.input();
 pending.shift()({source:'llm',suggestion:'late model name'});await first;
 assert.equal(input.value,'my manual name');
 handlers.refresh();const second=queued();
 assert.equal(input.dataset.manualEdited,'false');
 pending.shift()({source:'llm',suggestion:'new model name'});await second;
 assert.equal(input.value,'new model name');
 updateAssignmentNameSuggestion('labeling');assert.equal(requests,2);
 handlers.refresh();const third=queued();pending.shift()({source:'rule',reason:'timeout'});await third;
 assert.equal(input.dataset.suggestionSource,'rule');assert.equal(input.dataset.suggestionReason,'timeout');
 assert.match(input.value,/0508.*10 Case/);assert.equal(requests,3);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

    def test_group_shares_keep_zero_distinct_from_missing_input(self):
        script = (ROOT / 'allocation-groups.js').read_text() + r'''
const assert=require('node:assert/strict');
const input=value=>({value:String(value??''),valueAsNumber:value??NaN});
const people=[['alice',100],['bob',0],['carol',null]].map(([name,share])=>({
  querySelector:match=>match==='[data-group-member]'?{value:name}:input(share)
}));
const card={dataset:{setupGroup:'rd'},querySelector:match=>
  match==='[data-group-strategy]'?{value:'overlap'}:input(100),querySelectorAll:()=>people};
const root={querySelector:()=>null,querySelectorAll:match=>match==='[data-setup-group]'?[card]:[]};
const draft=readAllocationGroupSetup(root);
assert.deepEqual(draft.groups,[{group_id:'rd',coverage_percent:100,coverage_strategy:'overlap',
  members:[{name:'alice',review_percent:100},{name:'bob',review_percent:0},{name:'carol',review_percent:null}]}]);
apiResponseError=(zh,en)=>({messages:{zh,en}});
assert.ok(groupAllocationSetupError(draft));
draft.groups[0].members.pop();
assert.equal(groupAllocationSetupError(draft),null);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)
