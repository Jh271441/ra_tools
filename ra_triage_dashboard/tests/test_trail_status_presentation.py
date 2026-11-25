from pathlib import Path
import shutil
import subprocess
import unittest


class TrailStatusPresentationTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_grouped_filters_do_not_change_write_eligibility(self):
        root = Path(__file__).resolve().parents[1] / "static/js"
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
Object.assign(global,{uiText:(zh,en)=>en,parseFilterList:v=>Array.isArray(v)?v:String(v||'').split(',').filter(Boolean),LABELS:[],state:{trailUpdate:{view:'local',selectionIntent:'reason_only',filters:{trailStatus:['reason_update']}}},$:()=>null});
for(const name of ['trail-update-state.js','trail-update-reasons.js','trail-update-preview.js','routing.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
const item=(id,status,extra={})=>({issue_id:id,trail_detail:{state:status,...extra},trail_update_status:'pending'});
const items=[item('keep','excluded_keep_reason',{trail_should_exclude:true}),item('empty','excluded_no_reason',{trail_should_exclude:true}),item('same','synced',{trail_should_exclude:true}),item('changed','reason_changed',{trail_should_exclude:true,needs_reason_update:true}),item('missing','reason_missing',{trail_should_exclude:true,needs_reason_update:true}),item('exclude','needs_exclusion',{trail_should_exclude:false,needs_exclusion_update:true}),item('failed','query_failed')];
assert.deepEqual(trailUpdateFilteredItems({items}).map(x=>x.issue_id),['keep','changed','missing']);
state.trailUpdate.filters.trailStatus=['reason_update'];
assert.deepEqual(trailUpdateFilteredItems({items}).map(x=>x.issue_id),['keep','changed','missing']);
assert.equal(trailUpdateFilterOptions(items).trail.filter(x=>x.value==='matched').length,1);
assert.deepEqual(trailUpdateStatusSummary({items},items),{reason_needed:1,reason_sync:2,matched:2,needs_exclusion:1,unconfirmed:1});
state.trailUpdate.filters.trailStatus=['reason_sync'];
assert.deepEqual(trailUpdateFilteredItems({items}).map(x=>x.issue_id),['changed','missing']);
state.trailUpdate.filters.trailStatus=['reason_needed'];
assert.deepEqual(trailUpdateFilteredItems({items}).map(x=>x.issue_id),['keep']);
assert.equal(trailUpdateFilteredItems({items},{ignoreStatus:true}).length,7);
global.CASE_PAGE_SIZES=[20,50];global.DEFAULT_CASE_PAGE_SIZE=20;
for(const value of ['reason_sync','reason_needed','excluded','not_excluded','unconfirmed','querying','needs_exclusion']){
 const parsed=normalizedTrailUpdateRouteFilters(new URLSearchParams('trail_status='+value));
 assert.deepEqual(parsed.trailStatus,[value]);
}
assert.deepEqual(trailStatusFilterValues(['reason_update']),['reason_sync','reason_needed']);
assert.deepEqual(trailStatusFilterValues(['excluded_keep_reason','reason_missing','bogus']),['reason_needed','reason_sync']);
assert.equal(trailReasonEligible(items[3]),true);assert.equal(trailReasonEligible(items[0]),false);assert.equal(trailReasonEligible({...items[3],readonly:true}),false);
state.trailUpdate.selectionIntent='exclude';assert.equal(trailReasonEligible(items[3]),false);assert.equal(trailReasonEligible(items[5]),true);
assert.equal(trailUpdateStatusMeta('synced').label,'Synced');assert.equal(trailUpdateStatusMeta('excluded_no_reason').label,'Synced');assert.equal(trailRemoteState(items[6]),'unknown');assert.notEqual(trailUpdateStatusMeta('synced').className,trailUpdateStatusMeta('excluded_keep_reason').className);
// Reproduce the reported 37-row scope: 9 empty, 2 writable, 26 matching.
const scope=Array.from({length:37},(_,i)=>({...item('cn'+i,i<9?'excluded_no_reason':i<11?'reason_missing':'synced',{
 trail_should_exclude:true,needs_reason_update:i>=9&&i<11}),
 source_kind:'local',local_selected:true,gt_label:i%2?'A':'B',
 reason_source:{author:i%2?'alice':'bob'},review:{reviewer:'legacy'},comment:'local '+i}));
state.trailUpdate={view:'local',selectionIntent:'reason_only',filters:{},page:1,pageSize:50};
assert.deepEqual(trailUpdateStatusSummary({items:scope},scope),{matched:35,reason_sync:2});
let page=trailSelectionPageStats({items:scope});assert.equal(page.eligible.size,2);assert.equal(page.reasonNeeded,0);
state.trailUpdate.pageSize=9;assert.equal(trailSelectionPageStats({items:scope}).eligible.size,0);
state.trailUpdate.page=2;assert.equal(trailSelectionPageStats({items:scope}).eligible.size,2);
state.trailUpdate.page=1;state.trailUpdate.pageSize=50;
state.trailUpdate.filters={trailStatus:['reason_sync','reason_needed'],reviewer:['alice'],gtLabel:['A'],remoteState:'true',localState:'true',sourceKind:'local'};
assert.equal(trailUpdateFilteredItems({items:scope}).length,1); // OR within statuses, AND across fields.
assert.equal(trailUpdateFilteredItems({items:scope},{ignoreStatus:true}).length,18);
state.trailUpdate.filters={reviewer:['missing-author'],trailStatus:['unconfirmed'],gtLabel:['A']};
assert.equal(trailUpdateFilteredItems({items:scope}).length,0);
assert.ok(trailUpdateFilterOptions(scope).reviewer.some(x=>x.value==='missing-author')); // Zero-match choices stay visible.
assert.ok(trailUpdateFilterOptions(scope).trail.some(x=>x.value==='unconfirmed'));
state.trailUpdate.filters={search:'ALICE'};assert.equal(trailUpdateFilteredItems({items:scope}).length,18);
state.trailUpdate.view='reconciliation';assert.equal(trailSelectionPageStats({items:scope}).eligible.size,0);
"""
        result = subprocess.run(["node", "-e", script, str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
