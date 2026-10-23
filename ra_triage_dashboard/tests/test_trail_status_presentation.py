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
Object.assign(global,{uiText:(zh,en)=>en,parseFilterList:v=>Array.isArray(v)?v:[],LABELS:[],state:{trailUpdate:{view:'local',selectionIntent:'reason_only',filters:{trailStatus:['excluded']}}},$:()=>null});
for(const name of ['trail-update-state.js','trail-update-reasons.js','trail-update-preview.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
const item=(id,status,extra={})=>({issue_id:id,trail_detail:{state:status,...extra},trail_update_status:'pending'});
const items=[item('keep','excluded_keep_reason',{trail_should_exclude:true}),item('empty','excluded_no_reason',{trail_should_exclude:true}),item('same','synced',{trail_should_exclude:true}),item('changed','reason_changed',{trail_should_exclude:true,needs_reason_update:true}),item('missing','reason_missing',{trail_should_exclude:true,needs_reason_update:true}),item('exclude','needs_exclusion',{trail_should_exclude:false,needs_exclusion_update:true}),item('failed','query_failed')];
assert.deepEqual(trailUpdateFilteredItems({items}).map(x=>x.issue_id),['keep','empty']);
state.trailUpdate.filters.trailStatus=['reason_update'];
assert.deepEqual(trailUpdateFilteredItems({items}).map(x=>x.issue_id),['changed','missing']);
assert.equal(trailUpdateFilterOptions(items).trail.filter(x=>x.value==='excluded').length,1);
assert.deepEqual(trailUpdateStatusSummary({items},items),{excluded:2,synced:1,reason_update:2,needs_exclusion:1,unconfirmed:1});
assert.equal(trailReasonEligible(items[3]),true);assert.equal(trailReasonEligible(items[0]),false);assert.equal(trailReasonEligible({...items[3],readonly:true}),false);
state.trailUpdate.selectionIntent='exclude';assert.equal(trailReasonEligible(items[3]),false);assert.equal(trailReasonEligible(items[5]),true);
assert.equal(trailRemoteState(items[6]),'unknown');assert.notEqual(trailUpdateStatusMeta('synced').className,trailUpdateStatusMeta('excluded_keep_reason').className);
"""
        result = subprocess.run(["node", "-e", script, str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
