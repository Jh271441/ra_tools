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
 uiText:(a,b)=>lang==='zh'?a:b,escapeHtml:s=>String(s).replaceAll('<','&lt;'),formatTime:s=>s,
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
 // Reads persisted results with no cursor/refresh, never commits or preselects.
 reset();node('#trailLocalImportManual').open=false;
 reply={direction:'trail_to_local',status:'ready',snapshot_available:true,checked_at:'2026-10-26T00:00:00Z',snapshot_total:101,
   items:[{issue_id:'cn23456789',local_excluded:null,can_import:true}],scanned:101,total:101,next_cursor:null};
 let next;const initial=api;
 api=async(url,options)=>{const body=JSON.parse(options.body);calls.push({url,body});return reply};
 await actualScan();assert.equal(calls.length,1);assert.equal(trailLocalImport.candidates.length,1);assert.equal(trailLocalImport.selected.size,0);
 assert.deepEqual(calls[0].body,{baselines:'0508',refresh:false});
 assert.equal(trailLocalImport.scanDone,true);assert.match(node('#trailLocalImportScanStatus').textContent,/Last scanned/);
 trailLocalImport.selected.add('cn23456789');assert.deepEqual(trailLocalImportIds().ids,['cn23456789']);
 await actualScan();assert.equal(trailLocalImport.selected.size,1);assert.equal(calls[1].body.refresh,false);
 await actualScan(true);assert.equal(calls[2].body.refresh,true);assert.equal(trailLocalImport.selected.size,0);
 // A worker persists beyond close; the browser only polls while open.
 reply={...reply,status:'running',scanned:100};
 await actualScan();assert.equal(trailLocalImport.scanning,true);assert.match(node('#trailLocalImportScanStatus').textContent,/continues after closing/);
 clearTimeout(trailLocalImport.pollTimer);
 reply={...reply,status:'failed',error:'failed',membership_changed:true};
 await actualScan();assert.equal(trailLocalImport.scanning,false);assert.equal(trailLocalImport.candidates.length,1);
 assert.match(node('#trailLocalImportScanStatus').textContent,/Previous complete results retained/);
 assert.match(node('#trailLocalImportScanStatus').textContent,/membership changed/);
 reset();api=async()=>new Promise(r=>next=r);const staleScan=actualScan();epoch++;next(reply);await staleScan;assert.equal(trailLocalImport.candidates.length,0);
 reset();api=async()=>{throw Error('network failed')};await actualScan();assert.match(node('#trailLocalImportScanStatus').textContent,/Scan incomplete/);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(["node", "-e", script, str(Path(__file__).resolve().parents[1] / "static/js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
