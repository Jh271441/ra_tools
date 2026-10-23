"""Execute actual shared JS functions with isolated state; no browser/Trail I/O."""
from pathlib import Path
import shutil
import subprocess
import unittest

class TrailFrontendBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_readonly_filters_scope_language_and_initial_route(self):
        root=Path(__file__).resolve().parents[1]/'static/js'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let lang='zh';
Object.assign(global,{state:{trailUpdate:{filters:{},data:null}},
  document:{querySelectorAll:()=>[],querySelector:()=>null,activeElement:null},
  $:()=>null,uiText:(zh,en)=>lang==='en'?en:zh,escapeHtml:s=>String(s),
  formatTime:s=>s||'—',selectedBaselineQueryValue:()=> '0508',
  parseFilterList:v=>Array.isArray(v)?v:String(v||'').split(',').filter(Boolean),
  LABELS:['误触发'], CASE_PAGE_SIZES:[10,20,50,100], DEFAULT_CASE_PAGE_SIZE:20,
  enhanceNativeUiSelect:()=>{}, CSS:{escape:s=>s}});
for(const name of ['trail-update-state.js','trail-update-reasons.js','trail-update-preview.js','routing.js'])
  vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'),{filename:name});
const pending={issue_id:'cn1',baseline_id:'0508',local_selected:true,source_kind:'local',comment:'new',trail_detail:{state:'reason_changed',trail_should_exclude:true,needs_reason_update:true}};
const readonly={issue_id:'cn2',baseline_id:'0508',local_selected:false,readonly:true,source_kind:'historical',trail_detail:{state:'excluded_no_reason',trail_should_exclude:true,needs_reason_update:true}};
applyTrailUpdateRouteControls(normalizedTrailUpdateRouteFilters(new URLSearchParams('view=reconciliation&source_kind=historical&local_state=false&remote_state=true&trail_status=reconcile_excluded')));
assert.equal(state.trailUpdate.view,'reconciliation');
assert.equal(trailReasonState(readonly),'reconcile_excluded');
assert.equal(trailReasonEligible(readonly),false);assert.equal(trailSelectionCheckbox(readonly),'');
assert.equal(trailReasonEligible(pending),false);
assert.deepEqual(trailUpdateFilteredItems({items:[pending,readonly]}),[readonly]);
const historyKey=trailUpdatePreviewKey();state.trailUpdate.view='local';assert.notEqual(trailUpdatePreviewKey(),historyKey);
assert.equal(trailReasonEligible(pending),true);assert.equal(trailReasonEligible(readonly),false);
trailSelectedIssues().add('cn1');state.trailUpdate.filters={search:'cn2'};
trailUpdateFilteredItems({items:[pending,readonly]});assert.deepEqual([...trailSelectedIssues()],['cn1']);
for(const marker of [false,null]) { readonly.trail_detail.trail_should_exclude=marker; assert.equal(trailReasonState(readonly),'reconcile_not_excluded'); }
readonly.trail_detail.state='query_failed';assert.equal(trailReasonState(readonly),'query_failed');assert.equal(trailRemoteState(readonly),'unknown');
readonly.trail_detail.state='excluded_no_reason';readonly.trail_detail.trail_should_exclude=true;
lang='en';assert.equal(trailUpdateStatusMeta(trailReasonState(readonly)).label,"Excluded");
assert.match(trailUpdateStatusMeta(trailReasonState(readonly)).detail,/Read-only/);
assert.match(trailReasonSummaryMarkup(readonly),/No reason provided/);
const restoredMarkup=trailReasonComparisonMarkup({...pending,reason_source:{kind:'legacy_exclusion_note',author:'alice',source_annotation_id:81,revision_id:99,original_created_at:'2026-09-18',created_at:'2026-10-23'}},true);
assert.match(restoredMarkup,/Original exclusion note/);assert.match(restoredMarkup,/Original Review #81/);assert.match(restoredMarkup,/2026-09-18/);assert.doesNotMatch(restoredMarkup,/Restored 2026-10-23/);
lang='zh';assert.equal(trailUpdateStatusMeta(trailReasonState(readonly)).label,"已排除");
assert.match(trailUpdateStatusMeta(trailReasonState(readonly)).detail,/仅供核对/);
assert.notEqual(trailRowKey(pending),trailRowKey({...pending,baseline_id:'0821'}));
console.log('Trail frontend behavioral checks passed');
'''
        result=subprocess.run(['node','-e',script,str(root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
