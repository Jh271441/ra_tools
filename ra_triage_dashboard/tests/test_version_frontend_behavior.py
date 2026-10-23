"""Exercise date filtering/loading boundaries without browser or business writes."""
from pathlib import Path
import shutil
import subprocess
import unittest


class VersionFrontendBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_date_toggle_cancellation_and_scope_safe_chart_retention(self):
        source = Path(__file__).resolve().parents[1] / "static/js/version-datasets.js"
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodes=new Map();
function element(){return {innerHTML:'existing chart',textContent:'existing text',disabled:false,hidden:false,dataset:{},attrs:{},handlers:{},classList:{add(){},toggle(){}},style:{setProperty(){}},replaceChildren(){this.innerHTML='';this.textContent='';},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this.handlers[k]=v;},querySelectorAll(){return [];}};}
Object.assign(global,{$:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},uiText:zh=>zh,enhanceNativeUiSelect:()=>{},document:{addEventListener(){},hidden:false},location:{href:'http://localhost/version-datasets?dataset=A'},history:{pushState(_,__,url){location.href=String(url);}}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
vm.runInThisContext(`
const requests=[];
loadVersionDatasets=()=>{requests.push([versionDatasetState.dataset,versionDatasetState.date]);};
bindVersionTEInfo=()=>{};
versionDatasetState.dataset='A';
versionDatasetState.members={dataset_id:'A'};
const days=['2026-10-22','2026-10-23'].map(date=>Object.assign(element(),{dataset:{versionDate:date}}));
$('#versionTEDailyChart').querySelectorAll=()=>days;
const statuses=['filled','unfilled','unknown'].map(status=>Object.assign(element(),{dataset:{versionTeStatus:status}}));
$('#versionTEStatusChart').querySelectorAll=()=>statuses;
bindVersionDatasets();
const click=selector=>$('#versionDatasetsPage').handlers.click({target:{closest:s=>s===selector?(s==='[data-version-date]'?days[0]:element()):null}});
click('[data-version-date]');
assert.equal(versionDatasetState.date,'2026-10-22');
assert.equal($('#versionDatasetDate').value,'2026-10-22');
assert.equal(days[0].attrs['aria-pressed'],'true');
assert.equal($('#versionTEAllDates').attrs['aria-pressed'],'false');
assert.equal($('#versionTEDailyChart').innerHTML,'existing chart');
assert.equal($('#versionDatasetDate').disabled,false);
assert.equal(versionDatasetState.members,null);
assert.equal($('#versionDatasetGrid').innerHTML,'');
click('[data-version-date]');
assert.equal(versionDatasetState.date,'');
assert.equal(new URL(location.href).searchParams.has('date'),false);
assert.equal($('#versionDatasetDate').value,'');
assert.equal($('#versionTEAllDates').attrs['aria-pressed'],'true');
versionDatasetChange({date:'2026-10-23',teStatus:'unfilled',assignee:'alice',reviewStatus:'pending'});
click('[data-version-all-dates]');
assert.equal(versionDatasetState.date,'');
assert.equal(versionDatasetState.teStatus,'unfilled');
assert.equal(versionDatasetState.assignee,'alice');
assert.equal(versionDatasetState.reviewStatus,'pending');
assert.equal(statuses[1].attrs['aria-pressed'],'true');
assert.equal($('#versionTEDistribution').innerHTML,'existing chart');
versionDatasetChange({dataset:'B'});
assert.equal($('#versionTEDailyChart').innerHTML,'');
assert.equal($('#versionTEStatusChart').innerHTML,'');
assert.equal($('#versionDatasetDate').disabled,true);
assert.equal(versionDatasetState.date,'');
assert.equal(requests.length,5);
`);
"""
        result = subprocess.run(["node", "-e", script, str(source)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
