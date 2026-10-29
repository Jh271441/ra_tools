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
        self.assertLess(html.index('class="version-composition"'), html.index('class="review-commandbar version-filter-panel"'))
        self.assertNotIn('id="versionDatasetView"', html)
        self.assertLess(html.index('id="versionTEPanel"'), html.index('id="versionRDPanel"'))
        self.assertLess(html.index('id="versionRDPanel"'), html.index('class="gallery-panel version-gallery"'))
        css = (root / 'css/version-datasets.css').read_text()
        chart = css.split('.version-result-chart {', 1)[1].split('}', 1)[0]
        self.assertNotIn('max-height', chart)
        self.assertNotIn('overflow', chart)
        self.assertIn('grid-column:1/-1;grid-row:2', css)
        self.assertIn('background:var(--te-result-color,var(--muted))', css)
        self.assertLess(html.index('id="versionTEDistribution"'), html.index('id="versionTEDays"'))
        self.assertEqual(html.count('id="versionTEAllDates"'), 1)
        self.assertIn('--version-low:var(--chart-primary)', css)
        self.assertIn('.version-rd .rd-filled {background:var(--te-done)}', css)
        self.assertIn('.version-rd .rd-pending {background:var(--te-pending)}', css)
        self.assertIn('background:var(--version-label-color,var(--muted))', css)
        tokens = (root / 'styles.css').read_text()
        self.assertEqual(tokens.count('--chart-primary: color-mix(in srgb, var(--accent) 65%, var(--muted))'), 2)

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
assert.equal(versionDatasetScopeLabel(),'随机抽样集');
assert.equal(($('#versionDatasetMode').innerHTML.match(/<option/g)||[]).length,3);
assert.deepEqual([...$('#versionDatasetMode').innerHTML.matchAll(/value="([^"]+)"/g)].map(m=>m[1]),['targets','sampled_targets','low']);
versionDatasetChange({mode:'source_waiting'});
assert.equal(versionDatasetState.teStatus,'filled');
assert.equal(versionDatasetState.assignee,'alice');
assert.equal(new URL(location.href).searchParams.get('mode'),'source_waiting');
location.pathname='/version-datasets';location.search='?dataset=A&mode=samples&date=2026-10-20&te_status=unknown';
versionDatasetRoute();syncVersionDatasetViews();
assert.equal(versionDatasetState.mode,'samples');
assert.equal($('#versionDatasetMode').value,'samples');
assert.equal(($('#versionDatasetMode').innerHTML.match(/<option/g)||[]).length,4,'only an explicitly selected legacy scope is retained');
assert.ok(!$('#versionDatasetMode').innerHTML.includes('value="source_waiting"'));
assert.equal(versionDatasetState.date,'2026-10-20');
assert.equal(versionDatasetState.teStatus,'unknown');
assert.equal(versionDatasetRouteOptions().mode,'samples');
location.search='?dataset=B&mode=sampled_targets';
versionDatasetRoute();syncVersionDatasetViews();
assert.equal($('#versionDatasetMode').value,'sampled_targets');
assert.equal(($('#versionDatasetMode').innerHTML.match(/<option/g)||[]).length,3,'returning to a target cohort removes the legacy entry');
const beforeLocale=JSON.stringify(versionDatasetState);
global.uiText=(_,en)=>en;
assert.equal(versionTEResult('成功'),'Succeeded');
assert.equal(versionTEResult('超出范围'),'Out of scope');
assert.equal(versionTEResult('out_of_scope'),'Out of scope');
assert.equal(versionTEResult('custom result'),'custom result');
// Result categories use stable distinct hues, not success/warning/error colors.
for(const [value,color] of [['成功','chart-teal'],['正确触发','chart-teal'],['失败','chart-indigo'],['误触发','chart-rose'],['无需协助','chart-blue'],['未接起','chart-slate'],['超出范围','muted'],['out_of_scope','muted'],['custom result','muted'],['__proto__','muted']]) {
  assert.equal(versionLabelColor(value),'var(--'+color+')');
}
global.dailyReviewStatusRows=()=>[];
global.withBase=value=>value;
$('#versionTEDailyChart').contains=()=>false;
const sample={dataset:{historical:false},te:{summary:{total:10,filled:10,unfilled:0,unknown:0},source_status:'ready',distribution:[{value:'成功',count:2},{value:'误触发',count:8}],daily:[]}};
renderVersionTE(sample);
assert.doesNotMatch($('#versionTEDistribution').innerHTML,/--fail|--warn|--ok/);
assert.ok($('#versionTEDistribution').innerHTML.includes('--te-result-color:var(--chart-rose)'));
assert.ok($('#versionTEDistribution').innerHTML.includes('<small>80.0%</small>'));
assert.match($('#versionTEDistribution').innerHTML,/False trigger.*width:80%/);
assert.match($('#versionTEDistribution').innerHTML,/Succeeded.*width:20%/);
global.uiText=zh=>zh;
sample.te.distribution.reverse();renderVersionTE(sample);
assert.doesNotMatch($('#versionTEDistribution').innerHTML,/--fail|--warn|--ok/);
assert.match($('#versionTEDistribution').innerHTML,/误触发/);
sample.te.summary={total:0,filled:0,unfilled:0,unknown:0};sample.te.distribution=[];renderVersionTE(sample);
assert.match($('#versionTEDistribution').innerHTML,/暂无已标结果/);
assert.doesNotMatch($('#versionTEDistribution').innerHTML,/NaN|Infinity/);
global.uiText=(_,en)=>en;
syncVersionDatasetViews();
assert.ok($('#versionDatasetMode').innerHTML.includes('Low confidence (excluding samples)'));
assert.equal($('#versionDatasetMode').value,'sampled_targets');
assert.equal(JSON.stringify(versionDatasetState),beforeLocale);
versionDatasetChange({mode:'all'});
assert.equal(versionDatasetState.mode,'all');
versionDatasetChange({dataset:'C'});
renderVersionRD({total:10,completed:5,pending:3,conflict:2,distribution:{'正确触发':3,'误触发':2,'无需协助':0}});
const rd=$('#versionRDPanel');
assert.ok(rd.innerHTML.includes('50.0%'));
assert.ok(rd.innerHTML.includes('60.0%'));
assert.ok(rd.innerHTML.includes('section-heading version-chart-heading'));
assert.equal((rd.innerHTML.match(/class="page-card version-rd-block"/g)||[]).length,2);
assert.ok(rd.innerHTML.includes('Labeled'));
for(const language of ['zh','en']) {
  global.uiText=(zh,en)=>language==='zh'?zh:en;
  renderVersionRD({total:6,completed:6,pending:0,conflict:0,distribution:{'正确触发':3,'误触发':2,'无需协助':1}});
  for(const label of ['正确触发','误触发','无需协助']) {
    const color=versionLabelColor(label);
    assert.equal(rd.innerHTML.split('--version-label-color:'+color).length-1,2,'legend and chart must match TE: '+label);
  }
  renderVersionRD({total:159,completed:159,pending:0,conflict:0,distribution:{'正确触发':50,'误触发':94,'无需协助':15}});
  for(const value of ['50 · 31.4%','94 · 59.1%','15 · 9.4%'])assert.ok(rd.innerHTML.includes('<span>'+value+'</span>'),'visible count and share: '+value);
  renderVersionRD({total:3,completed:3,pending:0,conflict:0,distribution:{'正确触发':3,'误触发':0,'无需协助':0}});
  assert.equal(rd.innerHTML.split('<span>0 · 0.0%</span>').length-1,2,'zero-count categories remain in the legend');
}
global.uiText=(_,en)=>en;
renderVersionRD({total:10,completed:5,pending:3,conflict:2,distribution:{'正确触发':3,'误触发':2,'无需协助':0}},false,{mode:'sampled_targets',date:'2026-10-22'});
assert.ok(rd.innerHTML.includes('Random sample · 2026-10-22'));
global.dailyReviewStatusRows=()=>[];
$('#versionTEDailyChart').contains=()=>false;
$('#versionDatasetExport').hidden=false;
renderVersionTE({dataset:{historical:false},te:{summary:{total:10,filled:5,unfilled:3,unknown:2},distribution:[],daily:[],source_status:'ready'}},{scope:{mode:'sampled_targets',date:'2026-10-22',assignee:'alice',reviewStatus:'pending'},exportReady:false});
assert.ok($('#versionTEScope').textContent.includes('2026-10-22 · Random sample · 10 targets'));
assert.ok($('#versionTEScope').textContent.includes('alice · Combined review pending'));
assert.equal($('#versionDatasetExport').hidden,true,'retained chart never enables old-scope export');
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
