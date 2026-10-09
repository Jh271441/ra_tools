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

    def test_people_quotas_keep_zero_distinct_from_even_split(self):
        script = (ROOT / 'assignment-people.js').read_text() + r'''
const assert=require('node:assert/strict');
const row=(name,count)=>({querySelector:selector=>({value:selector.includes('name')?name:count})});
document={querySelectorAll:()=>[row('alice',''),row('bob','0'),row('carol','12'),row('','5')]};
assert.deepEqual(readWorkSplitAssignees('#labelingTaskPeople'),[
 {name:'alice',count:null},{name:'bob',count:0},{name:'carol',count:12}]);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)
