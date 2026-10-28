"""Exercise date filtering/loading boundaries without browser or business writes."""
from pathlib import Path
import shutil
import subprocess
import unittest


class VersionFrontendBehaviorTest(unittest.TestCase):
    def test_composition_precedes_te_and_results_do_not_clip(self):
        root = Path(__file__).resolve().parents[1] / 'static'
        html = (root / 'index.html').read_text()
        self.assertLess(html.index('id="versionDatasetSummary"'), html.index('class="version-composition"'))
        self.assertLess(html.index('class="version-composition"'), html.index('id="versionTEPanel"'))
        self.assertLess(html.index('id="versionTEPanel"'), html.index('id="versionRDPanel"'))
        self.assertLess(html.index('id="versionRDPanel"'), html.index('class="gallery-panel version-gallery"'))
        css = (root / 'css/version-datasets.css').read_text()
        chart = css.split('.version-result-chart {', 1)[1].split('}', 1)[0]
        self.assertNotIn('max-height', chart)
        self.assertNotIn('overflow', chart)
        self.assertIn('minmax(32px,1fr) max-content', css)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_date_toggle_cancellation_and_scope_safe_chart_retention(self):
        source = Path(__file__).resolve().parents[1] / "static/js/version-datasets.js"
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodes=new Map();
global.escapeHtml=value=>String(value);
function element(){return {innerHTML:'existing chart',textContent:'existing text',disabled:false,hidden:false,dataset:{},attrs:{},handlers:{},classList:{add(){},toggle(){}},style:{setProperty(){}},replaceChildren(){this.innerHTML='';this.textContent='';},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,v){this.handlers[k]=v;},querySelectorAll(){return [];}};}
Object.assign(global,{$:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},uiText:zh=>zh,enhanceNativeUiSelect:()=>{},document:{addEventListener(){},hidden:false},location:{href:'http://localhost/version-datasets?dataset=A'},history:{pushState(_,__,url){location.href=String(url);}}});
document.getElementById=id=>$('#'+id);
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
vm.runInThisContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'version-rd.js'),'utf8'));
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
versionDatasetChange({mode:'sampled_targets',assignee:'alice',teStatus:'filled',reviewStatus:'pending'});
assert.equal(versionDatasetView(),'review');
assert.equal(versionDatasetScopeLabel(),'随机抽样集');
assert.equal($('#versionTEScope').textContent,'');
assert.equal($('#versionTEPanel').hidden,false);
assert.equal($('#versionDatasetSummary').hidden,false);
assert.equal($('#versionDatasetView').value,'review');
assert.equal(($('#versionDatasetMode').innerHTML.match(/<option/g)||[]).length,3);
assert.ok(!$('#versionDatasetMode').innerHTML.includes('value="samples"'));
switchVersionDatasetView('processing');
assert.equal(versionDatasetState.mode,'all');
assert.equal(versionDatasetState.teStatus,'filled');
assert.equal(versionDatasetState.assignee,'alice');
assert.equal($('#versionTEPanel').hidden,false);
assert.equal($('#versionDatasetView').value,'processing');
assert.equal(($('#versionDatasetMode').innerHTML.match(/<option/g)||[]).length,6);
assert.ok(!$('#versionDatasetMode').innerHTML.includes('value="sampled_targets"'));
versionDatasetChange({mode:'source_waiting'});
switchVersionDatasetView('review');
assert.equal(versionDatasetState.mode,'sampled_targets');
assert.equal(versionDatasetState.teStatus,'filled');
assert.equal(versionDatasetState.assignee,'alice');
switchVersionDatasetView('processing');
assert.equal(versionDatasetState.mode,'source_waiting');
assert.equal(new URL(location.href).searchParams.get('mode'),'source_waiting');
for(const mode of ['all','samples','waiting','published','excluded','source_waiting'])assert.equal(versionDatasetView(mode),'processing');
for(const mode of ['targets','low','sampled_targets'])assert.equal(versionDatasetView(mode),'review');
location.pathname='/version-datasets';location.search='?dataset=A&mode=samples&date=2026-10-20&te_status=unknown';
versionDatasetRoute();syncVersionDatasetViews();
assert.equal(versionDatasetState.mode,'samples');
assert.equal($('#versionDatasetMode').value,'samples');
assert.equal(versionDatasetState.date,'2026-10-20');
assert.equal(versionDatasetState.teStatus,'unknown');
assert.equal(versionDatasetRouteOptions().mode,'samples');
versionDatasetState.viewMemory={review:'low',processing:'samples'};
versionDatasetRoute();
assert.equal(versionDatasetState.viewMemory.review,'low');
location.search='?dataset=B&mode=sampled_targets';
versionDatasetRoute();syncVersionDatasetViews();
assert.deepEqual(versionDatasetState.viewMemory,{});
assert.equal($('#versionDatasetMode').value,'sampled_targets');
const beforeLocale=JSON.stringify(versionDatasetState);
global.uiText=(_,en)=>en;
assert.equal(versionTEResult('成功'),'Succeeded');
assert.equal(versionTEResult('超出范围'),'Out of scope');
assert.equal(versionTEResult('out_of_scope'),'Out of scope');
assert.equal(versionTEResult('custom result'),'custom result');
syncVersionDatasetViews();
assert.ok($('#versionDatasetMode').innerHTML.includes('Low confidence (excluding samples)'));
assert.equal($('#versionDatasetMode').value,'sampled_targets');
assert.equal(JSON.stringify(versionDatasetState),beforeLocale);
switchVersionDatasetView('processing');
assert.equal(versionDatasetState.mode,'all');
versionDatasetChange({dataset:'C'});
assert.deepEqual(versionDatasetState.viewMemory,{});
renderVersionRD({total:10,completed:5,pending:3,conflict:2,distribution:{'正确触发':3,'误触发':2,'无需协助':0}});
const rd=$('#versionRDPanel');
assert.ok(rd.innerHTML.includes('50.0%'));
assert.ok(rd.innerHTML.includes('60.0%'));
assert.ok(rd.innerHTML.includes('section-heading version-chart-heading'));
assert.equal((rd.innerHTML.match(/class="page-card version-rd-block"/g)||[]).length,2);
assert.ok(rd.innerHTML.includes('Labeled'));
renderVersionRD({total:10,completed:0,pending:10,conflict:0,distribution:{'正确触发':0,'误触发':0,'无需协助':0}});
assert.ok(rd.innerHTML.includes('No valid classifications yet'));
assert.ok(!rd.innerHTML.includes('NaN'));
renderVersionRD({total:0});
assert.ok(rd.innerHTML.includes('No review targets'));
renderVersionRD(null,true);
assert.ok(rd.innerHTML.includes('unavailable'));
renderVersionRD({source_status:'unsupported'});
assert.ok(rd.innerHTML.includes('frozen historical set'));
global.uiText=zh=>zh;
renderVersionRD(null,true);
assert.ok(rd.innerHTML.includes('暂不可用'));
renderVersionRD();
assert.ok(rd.innerHTML.includes('正在读取'));
`);
"""
        result = subprocess.run(["node", "-e", script, str(source)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
