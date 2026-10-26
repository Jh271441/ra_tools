from pathlib import Path
import shutil
import subprocess
import unittest


class TrailLocalImportFrontendTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_preview_confirmation_dedup_stale_scope_and_language(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let lang='zh',scope='0508',epoch=1,allowed=true,calls=[],reply,refreshFails=false;
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',open:false,hidden:false,textContent:'',innerHTML:'',
 classList:{add(){},remove(){}},toggleAttribute(k,v){this[k]=v},focus(){},showModal(){this.open=true}});return nodes.get(id)}
Object.assign(global,{$:node,state:{session:{username:'alice'},trailUpdate:{selectionBusy:false}},
 uiText:(a,b)=>lang==='zh'?a:b,escapeHtml:s=>String(s).replaceAll('<','&lt;'),
 selectedBaselineQueryValue:()=>scope,capturePageContext:()=>({epoch}),isPageContextCurrent:c=>c?.epoch===epoch,
 trailNonExclusionAllowed:()=>allowed,syncTrailAttributeActions(){},
 loadTrailAttributePreview:async()=>{if(refreshFails)throw Error('refresh failed')},
 api:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});if(reply instanceof Error)throw reply;return reply}});
for(const file of ['issue-query.js','trail-update-local-import.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+file,'utf8'));
const actualScan=scanTrailLocalImport;
scanTrailLocalImport=async()=>{};
node('#trailLocalImportManual').open=true;
const preview={preview_id:'receipt',direction:'trail_to_local',items:[{issue_id:'cn12345678',before:{is_excluded:false,rationale:''},after:{is_excluded:true,rationale:'<reason>'},expected_output:'正确触发'}]};
function reset(){scope='0508';allowed=true;calls=[];reply=preview;node('#trailLocalImportInput').value='cn12345678,cn12345678';openTrailLocalImport()}
(async()=>{
 allowed=false;openTrailLocalImport();assert.equal(node('#trailLocalImportDialog').open,false);
 reset();assert.equal(calls.length,0);await runTrailLocalImport();assert.equal(calls.length,1);
 assert.deepEqual(calls[0].body,{issue_ids:['cn12345678'],baselines:'0508'});
 assert.match(node('#trailLocalImportDiff').innerHTML,/不排除 → 排除/);
 assert.match(node('#trailLocalImportDiff').innerHTML,/&lt;reason>/);
 lang='en';refreshTrailLocalImportLanguage();assert.match(node('#trailLocalImportDiff').innerHTML,/not excluded → excluded/);
 assert.equal(node('#trailLocalImportInput').value,'cn12345678,cn12345678');
 scope='0821';await runTrailLocalImport(true);assert.equal(calls.length,1);
 reset();let resolve;reply=new Promise(r=>resolve=r);const running=runTrailLocalImport();await runTrailLocalImport();assert.equal(calls.length,1);
 epoch++;resolve(preview);await running;assert.equal(trailLocalImport.preview,null);
 reset();await runTrailLocalImport();reply={ok:true,imported_count:1};refreshFails=true;await runTrailLocalImport(true);
 assert.deepEqual(calls[1].body,{preview_id:'receipt',confirm:true});assert.equal(trailLocalImport.preview,null);
 assert.match(node('#trailLocalImportFeedback').textContent,/Saved locally/);assert.equal(state.trailUpdate.selectionBusy,false);
 reset();reply=Error('source conflict');await runTrailLocalImport();assert.match(node('#trailLocalImportFeedback').textContent,/source conflict/);
 assert.equal(trailLocalImport.busy,false);
 reset();node('#trailLocalImportInput').value='!invalid';await runTrailLocalImport();assert.equal(calls.length,0);
 // Dataset scan traverses pages, never commits or preselects, and ignores late responses.
 reset();node('#trailLocalImportManual').open=false;
 reply={direction:'trail_to_local',items:[{issue_id:'cn23456789',local_excluded:null,can_import:true}],scanned:100,total:101,next_cursor:'cn23456789'};
 let next;const initial=api;
 api=async(url,options)=>{const body=JSON.parse(options.body);calls.push({url,body});return body.after ? {direction:'trail_to_local',items:[],scanned:101,total:101,next_cursor:null} : reply};
 await actualScan();assert.equal(calls.length,2);assert.equal(trailLocalImport.candidates.length,1);assert.equal(trailLocalImport.selected.size,0);
 assert.equal(trailLocalImport.scanDone,true);assert.match(node('#trailLocalImportScanStatus').textContent,/101 checked/);
 trailLocalImport.selected.add('cn23456789');assert.deepEqual(trailLocalImportIds().ids,['cn23456789']);
 api=async()=>new Promise(r=>next=r);const staleScan=actualScan();epoch++;next(reply);await staleScan;assert.equal(trailLocalImport.candidates.length,0);
 reset();api=async()=>{throw Error('network failed')};await actualScan();assert.match(node('#trailLocalImportScanStatus').textContent,/Scan incomplete/);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(["node", "-e", script, str(Path(__file__).resolve().parents[1] / "static/js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
