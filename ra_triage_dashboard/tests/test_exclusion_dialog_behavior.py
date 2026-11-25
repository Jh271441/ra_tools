from pathlib import Path
import shutil,subprocess,unittest

class ExclusionDialogBehaviorTest(unittest.TestCase):
 @unittest.skipUnless(shutil.which('node'),'Node required')
 def test_complete_decision_overrides_votes_and_keeps_stale_disagreement_visible(self):
  source=Path(__file__).resolve().parents[1]/'static/js/case-exclusion-decision.js'
  script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let language='en';global.uiText=(zh,en)=>language==='en'?en:zh;
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const translated=caseExclusionErrorMessage({message:'标注来源已变化，请刷新后重新裁决。'});
assert.match(translated,/Label sources changed/);language='zh';
assert.equal(caseExclusionErrorMessage({message:translated}),'标注来源已变化，请刷新后重新裁决。');
language='en';assert.equal(caseExclusionErrorMessage({message:'截图引用不合法。 / Invalid attachment references.'}),'Invalid attachment references.');
const data={label_cases:[{resolution:{heads:[{id:1,is_excluded:true},{id:2,is_excluded:false}]}}]};
assert.equal(caseExclusionNeedsDecision(data),true);
data.label_state={decision:{id:1,full_result:{is_excluded:false},stale:false}};
assert.equal(caseExclusionNeedsDecision(data),false);
data.label_state.decision.stale=true;assert.equal(caseExclusionNeedsDecision(data),true);
data.label_state.decision={id:1,full_result:null,stale:false};assert.equal(caseExclusionNeedsDecision(data),true);
assert.equal(caseExclusionNeedsDecision({label_cases:[{resolution:{state:'resolved',method:'adjudication',result_revision:{id:3,is_excluded:false},heads:data.label_cases[0].resolution.heads}}]}),false);
'''
  result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
