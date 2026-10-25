"""Execute the real UI workflow without any production/Trail connection."""
from pathlib import Path
import shutil
import subprocess
import unittest


class NonExclusionFrontendTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_preview_confirmation_cancel_stale_error_and_language(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
let lang='zh',scope='0508',pageEpoch=1,allowed=true,calls=[],reply=null,confirm=false,confirmationCalls=0;
const nodes=new Map();
function node(id){if(!nodes.has(id)) nodes.set(id,{value:'',dataset:{},open:false,disabled:false,textContent:'',innerHTML:'',scrollTop:0,
 classList:{add(){},toggle(){}},toggleAttribute(key,value){this[key]=value},setAttribute(){},focus(){},querySelectorAll(){return []},
 showModal(){this.open=true},close(){this.open=false;if(id==='#trailNonExclusionDialog')trailNonExclusion.epoch++}});return nodes.get(id)}
Object.assign(global,{state:{session:{username:'alice',can_write:true},trailUpdate:{selectionBusy:false}},
 $:node,uiText:(zh,en)=>lang==='zh'?zh:en,escapeHtml:s=>String(s).replaceAll('<','&lt;'),
 selectedBaselineQueryValue:()=>scope,capturePageContext:()=>({epoch:pageEpoch}),isPageContextCurrent:c=>c?.epoch===pageEpoch,
 hasDashboardWriteRole:()=>allowed,document:{querySelectorAll:()=>[]},showToast(){},
 syncTrailAttributeActions(){},setTrailAttributeStatus(){},trailUpdatePreviewKey:()=>scope,refreshTrailAttributeStatus:async()=>{},
 trailUpdateTargetSpec:()=>({fullPath:'info.ra_triage_dashboard.should_exclude'}),
 api:async(url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});return reply instanceof Error?Promise.reject(reply):typeof reply==='function'?reply(url):reply}});
for(const name of ['issue-query.js','trail-update-commit.js','trail-update-non-exclusion.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
const realConfirm=openTrailUpdateConfirm;
openTrailUpdateProgress=()=>{};trailUpdateProgressSetStage=()=>{};finishTrailUpdateProgress=()=>{};
const preview={intent:'unexclude',mode:'selected_exclusions',write_ready:true,payload_sha256:'receipt',baselines:['0508'],write_mode:'info_only',items:[
 {issue_id:'cn12345678',trail_update_status:'pending',before:{should_exclude:true,should_exclude_comment:'<original>'},reason_source:{kind:'issue_decision',rationale:'local evidence',author:'alice'}}]};
const tick=()=>new Promise(r=>setImmediate(r));
function reset(){calls=[];reply=preview;allowed=true;scope='0508';state.session.username='alice';
 node('#trailNonExclusionDialog').close();node('#trailNonExclusionInput').value='cn12345678,cn12345678';openTrailNonExclusion();}
(async()=>{
 allowed=false;openTrailNonExclusion();assert.equal(node('#trailNonExclusionDialog').open,false);assert.equal(calls.length,0);
 reset();assert.equal(calls.length,0);assert.equal(node('#trailNonExclusionPreview').disabled,false);
 openTrailUpdateConfirm=async()=>{confirmationCalls++;return false};await previewTrailNonExclusion();
 assert.equal(calls.length,1);assert.deepEqual(calls[0].body,{issue_ids:['cn12345678'],baselines:'0508'});
 assert.equal(node('#trailNonExclusionInput').value,'cn12345678,cn12345678');assert.equal(state.trailUpdate.selectionBusy,false);
 reset();const pending=deferred();reply=pending.promise;const running=previewTrailNonExclusion();await previewTrailNonExclusion();
 assert.equal(calls.length,1);node('#trailNonExclusionDialog').close();pending.resolve(preview);await running;
 assert.equal(confirmationCalls,1);assert.equal(calls.length,1);
 reset();const delayed=deferred();reply=delayed.promise;const stale=previewTrailNonExclusion();pageEpoch++;delayed.resolve(preview);await stale;
 assert.equal(confirmationCalls,1);assert.equal(calls.length,1);
 reset();openTrailUpdateConfirm=async()=>{scope='0821';return true};await previewTrailNonExclusion();assert.equal(calls.length,1);
 reset();openTrailUpdateConfirm=async()=>{state.session.username='bob';return true};await previewTrailNonExclusion();assert.equal(calls.length,1);
 reset();reply=Error('stale local source');await previewTrailNonExclusion();assert.match(node('#trailNonExclusionFeedback').textContent,/stale local/);
 assert.equal(node('#trailNonExclusionInput').value,'cn12345678,cn12345678');assert.equal(trailNonExclusion.busy,false);
 reset();node('#trailNonExclusionInput').value='!bad';await previewTrailNonExclusion();assert.equal(calls.length,0);
 reset();node('#trailNonExclusionInput').value=Array.from({length:201},(_,i)=>'cn'+(10000000+i)).join(',');await previewTrailNonExclusion();assert.equal(calls.length,0);
 reset();openTrailUpdateConfirm=async()=>true;reply=url=>url.endsWith('-preview')?preview:{ok:true,payload_sha256:'receipt',readback:{verified_count:1}};
 await previewTrailNonExclusion();assert.equal(calls.length,2);assert.match(calls[1].url,/non-exclusion-commit$/);
 assert.deepEqual(calls[1].body,{confirm:true,payload_sha256:'receipt'});assert.equal(node('#trailNonExclusionInput').value,'');
 reset();reply=url=>url.endsWith('-preview')?preview:Promise.reject(Error('lost response'));await previewTrailNonExclusion();
 assert.notEqual(node('#trailNonExclusionInput').value,'');assert.equal(calls.length,2);
 // The actual confirmation renderer must say false and preserve its promise on locale changes.
 openTrailUpdateConfirm=realConfirm;let resolved=false;
 const result=realConfirm({data:preview}).then(v=>{resolved=true;assert.equal(v,false)});
 assert.match(node('#trailUpdateConfirmBannerText').textContent,/false/);assert.match(node('#trailUpdateConfirmList').innerHTML,/不排除/);
 assert.match(node('#trailUpdateConfirmList').innerHTML,/&lt;original>/);
 lang='en';realConfirm({data:preview,renderOnly:true});await tick();assert.equal(resolved,false);
 assert.match(node('#trailUpdateConfirmBannerText').textContent,/Not excluded/);assert.match(node('#trailUpdateConfirmList').innerHTML,/Local outcome evidence/);
 assert.doesNotMatch(node('#trailUpdateConfirmList').innerHTML,/本地/);trailUpdateConfirmClose(false);await result;
 console.log('non-exclusion UI safety checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        root = Path(__file__).resolve().parents[1] / "static/js"
        result = subprocess.run(["node", "-e", script, str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_dialog_parser_and_registered_module(self):
        root = Path(__file__).resolve().parents[1] / "static"
        html = (root / "index.html").read_text()
        self.assertIn('class="dialog issue-query-dialog" id="trailNonExclusionDialog"', html)
        for path in (root / "app.js", root / "js/MANIFEST"):
            self.assertIn("trail-update-non-exclusion.js", path.read_text())
        script = (root / "js/trail-update-non-exclusion.js").read_text()
        self.assertIn("parseIssueIdsInput", script)
        self.assertNotIn("allowReadOnlyMutation", script)
        self.assertNotIn("model_run_id", script)
