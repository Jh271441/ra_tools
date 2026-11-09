from pathlib import Path
import shutil
import subprocess
import unittest


JS = Path(__file__).resolve().parents[1] / "static/js"


@unittest.skipUnless(shutil.which("node"), "Node is required")
class ReviewPredictionSelectionTest(unittest.TestCase):
    def test_selected_run_never_falls_back_to_another_run(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const body=fs.readFileSync(process.argv[1],'utf8');
const fn=body.slice(body.indexOf('function selectedRunPrediction('),body.indexOf('function formatModelConfidence('));
const state={selectedRunId:''},context={state};vm.createContext(context);vm.runInContext(fn,context);
const old={model_run_id:'old',model_label:'误触发'},current={model_run_id:'selected',model_label:'正确触发'};
const issue={predictions:[old,current]};
assert.equal(context.selectedRunPrediction(issue),null);
state.selectedRunId='missing';assert.equal(context.selectedRunPrediction(issue),null);
state.selectedRunId='selected';assert.equal(context.selectedRunPrediction(issue),current);
assert.equal(context.selectedRunPrediction(issue,'old'),old);
assert.equal(context.selectedRunPrediction({predictions:[]}),null);
assert.equal(context.selectedRunPrediction(null),null);
"""
        self.run_node(script, JS / "format-api.js")

    def test_rule_reason_and_history_remain_visible_without_claiming_a_current_run(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let lang='zh';const state={selectedRunId:''};
const context={state,uiText:(zh,en)=>lang==='en'?en:zh,
escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
labelBadge:(label,fallback)=>`<b>${label||fallback}</b>`,formatModelConfidence:v=>String(v),formatTime:()=>'-'};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const rule={model_run_id:'r',run_name:'1016',model_label:'误触发',model_reason:'',model_confidence:.95,
 model_extra:{prediction_source:'pre_rule',confidence_source:'rule_constant',rule_reason:'[pullover] rule <evidence>'}};
assert.equal(context.currentRunOutputMarkup({},rule),'');
const history=context.predictionCards({predictions:[rule]});
assert.ok(history.includes('规则命中'));assert.ok(history.includes('rule &lt;evidence&gt;'));assert.ok(!history.includes('模型未返回'));
state.selectedRunId='other';assert.equal(context.currentRunOutputMarkup({},rule),'');
state.selectedRunId='r';const output=context.currentRunOutputMarkup({},rule);
assert.ok(output.includes('Rule hit'));assert.ok(output.includes('规则常数'));assert.ok(output.includes('rule &lt;evidence&gt;'));
const nested={...rule,model_extra:{ra_stuck_auto_result_info:{daily_auto_triage:rule.model_extra}}};
assert.equal(context.predictionOutputDetails(nested).reason,rule.model_extra.rule_reason);
const model={...rule,model_reason:'model reason',model_extra:{prediction_source:'model'}};
assert.equal(context.predictionOutputDetails(model).isRule,false);
assert.ok(context.currentRunOutputMarkup({},model).includes('model reason'));
lang='en';const english=context.predictionCards({predictions:[rule]});
assert.ok(english.includes('Rule hit'));assert.ok(english.includes('Rule constant'));
assert.ok(context.predictionCards({predictions:[]}).includes('No Run output'));
"""
        self.run_node(script, JS / "review-history.js")

    def test_model_history_relocalizes_without_changing_the_selected_run(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let rendered=0;const data={issue_id:'cn1'};
const dialog={open:true,historyCaseData:data,dataset:{historyKind:'model'}},content={scrollTop:82};
const source=fs.readFileSync(process.argv[1],'utf8');
const fn=source.slice(source.indexOf('function refreshHistoryDialogLanguage('),source.indexOf('function predictionOutputDetails('));
const context={$:s=>s==='#historyDialog'?dialog:content,openHistoryDialog:(kind,d)=>{assert.equal(kind,'model');assert.equal(d,data);rendered++;content.scrollTop=0;}};
vm.createContext(context);vm.runInContext(fn,context);context.refreshHistoryDialogLanguage();
assert.equal(rendered,1);assert.equal(content.scrollTop,82);
dialog.open=false;context.refreshHistoryDialogLanguage();assert.equal(rendered,1);
"""
        self.run_node(script, JS / "review-history.js")

    def run_node(self, script, path):
        result = subprocess.run(["node", "-e", script, str(path)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
