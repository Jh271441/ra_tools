"""History rendering keeps statuses, permissions and exact adoption targets."""
from pathlib import Path
import shutil
import subprocess
import unittest


class HistoryRecordBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_history_status_permissions_escaping_and_adoption(self):
        root=Path(__file__).resolve().parents[1]/'static/js'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
Object.assign(global,{
 escapeHtml:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
 uiText:(z,e)=>e,formatTime:v=>v||'—',state:{session:{username:'alice'}},
 hasDashboardWriteRole:()=>true,annotationExpectedOutput:a=>a.expected_output,
 reviewRunLabel:v=>v,reviewStatusLabel:v=>v,expectedOutputDisplayText:v=>v,
 labelBadge:v=>`<span>${v}</span>`,tagLabel:v=>v,evidenceLabel:v=>v,
 caseExclusionText:v=>v?'Excluded':'Included'
});
for(const file of ['review-history.js','case-label-decision.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+file,'utf8'));
const row={id:42,author:'alice',review_domain:'model_review',model_review_status:'completed',review_status:'completed',model_run_id:'<untrusted-run>',note:'<untrusted-note>'};
const markup=annotationHistory([row]);
assert.equal((markup.match(/completed/g)||[]).length,1);
assert.ok(markup.includes('data-delete-annotation="42"'));
assert.ok(markup.includes('&lt;untrusted-run>'));assert.ok(markup.includes('&lt;untrusted-note>'));
assert.ok(!annotationHistory([{...row,legacy_read_only:true}]).includes('data-delete-annotation'));
assert.ok(!annotationHistory([{...row,author:'bob'}]).includes('data-delete-annotation'));
const adopted=caseDecisionRecordMarkup({id:17,author:'alice',rationale:'original',expected_output:'label',is_excluded:false},'source','',true);
assert.ok(adopted.includes('data-adopt-decision="17"'));
const decision=caseDecisionRecordMarkup({id:18,rationale:'',label_rationale:'final evidence',full_result:{adopted_revision:{author:'alice'},adopted_revision_id:17}},'source');
assert.ok(decision.includes('final evidence'));assert.ok(!decision.includes('Decision review rationale'));
const fields=caseDecisionEditorFields({source:{},rationale:'',retained:[],excludedConfirmed:false});
const confirmation=fields.match(/<input[^>]*id="caseDecisionConfirmExclusion"[^>]*>/)[0];
assert.ok(!/\srequired(?:\s|=|\/|>)/.test(confirmation));
assert.ok(confirmation.includes('aria-required="true"'));
assert.ok(confirmation.includes('aria-describedby="caseDecisionConfirmError"'));

'''
        result=subprocess.run(['node','-e',script,str(root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
