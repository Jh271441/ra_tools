"""Request ownership when chart controls change while a source read is pending."""
from pathlib import Path
import shutil
import subprocess
import unittest


def metric_source():
    root = Path(__file__).parents[1] / "static/js"
    return "const CASE_PAGE_SIZES=[10,20,50,100],DEFAULT_CASE_PAGE_SIZE=20;\n" + "\n".join(
        (root / name).read_text() for name in ("version-metrics.js", "version-metrics-reports.js")
    )


class VersionMetricFrontendTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_trend_connects_valid_metrics_across_gt_policies_and_breaks_at_missing_scores(self):
        program = metric_source() + r"""
const assert = require('node:assert/strict');
const chart = {clientWidth: 626, querySelectorAll: () => []};
const $ = selector => selector === '#vmChart' ? chart : null;
const uiText = (zh, en) => en, i18nLocale = () => 'en-US', escapeHtml = String;
const rows = ['20260102','20260109','20260116','20260123'].map((family, i) => ({
  family, reference_lanes: i ? ['arbitrated','te_prime','te','rd'] : ['te'],
  metrics: {chain:{accuracy:i / 4}, model:{accuracy:i === 2 ? null : i / 5}}
}));
versionMetrics.schemes = ['chain','model'];
versionMetrics.data = {items:rows};
vmChart();
const paths = Array.from(chart.innerHTML.matchAll(/<path class="vm-series-line" d="([^"]+)"/g),
  match => match[1].match(/[ML]/g).join(''));
assert.deepEqual(paths, ['MLLL','MLM']);
"""
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_report_keeps_every_version_and_each_scheme_denominator(self):
        program = metric_source() + r"""
const assert = require('node:assert/strict');
const uiText=(zh,en)=>en, i18nLocale=()=> 'en-US', escapeHtml=value=>String(value);
const rows=Array.from({length:25},(_,i)=>({family:'202601'+String(i+1).padStart(2,'0')}));
versionMetrics.data={items:rows};versionMetrics.thresholdFamily='20261030';
vmReconcileReports();assert.equal(versionMetrics.thresholdFamily,'20260125');
const nodes=new Map(), $=selector=>{
  if(!nodes.has(selector))nodes.set(selector,{querySelectorAll:()=>[],setAttribute:()=>{}});
  return nodes.get(selector);
};
vmRenderThresholdReport=()=>{};
vmRenderReports();
assert.equal(($('#vmReportRows').innerHTML.match(/<tr>/g)||[]).length,25);
assert.ok(!nodes.has('#vmPageSize'));
assert.equal(vmReferenceCounts({reference_lanes:['arbitrated','te_prime','te','rd'],reference_counts:{arbitrated:2,te_prime:3,te:4,rd:5}}),'Adjudication 2 · TE′ 3 · TE 4 · RD 5');
const row={metrics:{model:{accuracy:132/153,correct:132,total:153,reference_total:155},chain:{accuracy:134/155,correct:134,total:155,reference_total:155}},coverage:{te:{filled:157,total:158,observed:158}}};
assert.ok(vmScoreCell(row,'model').includes('132/153'));
assert.ok(vmScoreCell(row,'model').includes('86.27%'));
assert.ok(vmScoreCell(row,'chain').includes('134/155'));
assert.ok(vmScoreCell(row,'chain').includes('86.45%'));
assert.ok(vmCoverageCell(row,'te').includes('157/158'));
row.coverage.te.observed=0;
assert.ok(vmCoverageCell(row,'te').includes('Unknown'));
assert.ok(vmFreshnessSummary([]).label.includes('Not collected'));
assert.equal(vmSampleChange({sample_total:5,current_sample_total:8}), 'Current sample 8');
assert.equal(vmSampleChange({sample_total:8,current_sample_total:8}), '');
assert.equal(vmSampleChange({current_sample_total:0}), 'Current sample 0');
const freshness=vmFreshnessSummary([{status:'ready',observed_at:'2026-11-16T03:00:00Z'},{status:'ready',observed_at:'2026-11-16T02:00:00Z'},{status:'unavailable'}]);
assert.ok(freshness.label.includes('10:00'),'the compact badge uses the oldest selected collection');
assert.ok(freshness.title.includes('11:00'));
assert.ok(freshness.title.includes('scheduler checks automatically'));
const close={metrics:Object.fromEntries(VM_SCHEMES.map((key,i)=>[key,{accuracy:.999+i*.0002}]))};
const geometry=vmChartGeometry([close],VM_SCHEMES,320),labels=vmPointLabels(close,VM_SCHEMES,geometry.y);
assert.equal(labels.length,5);
labels.forEach((label,i)=>{assert.ok(label.y>=14);if(i)assert.ok(labels[i-1].y-label.y>=18)});
"""
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_scheme_toggles_preserve_scope_and_threshold_text_tracks_locale_and_route(self):
        path = Path(__file__).parents[1] / "static/js/version-metrics.js"
        program = r"""
const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const location = new URL('http://localhost/version-metrics?families=20261016&reference=rd&exclusion=exclude&threshold=0.85');
let english = false, reads = 0;
const context = vm.createContext({URL,URLSearchParams,location,AbortController,setTimeout,clearTimeout,
  history:{pushState:(s,t,u)=>location.href=u,replaceState:(s,t,u)=>location.href=u},withBase:p=>p,
  uiText:(zh,en)=>english?en:zh, api:()=>{reads++;throw Error('Local toggle must not fetch');},
  $:()=>({hidden:true,querySelectorAll:()=>[]})});
vm.runInContext(fs.readFileSync(0,'utf8'),context);
vm.runInContext('renderVersionMetrics=()=>{}; vmReadRoute()',context);
const state=vm.runInContext('versionMetrics',context), receipt={tag:'frozen'};
state.data=receipt;
assert.equal(state.schemes.join(','),'chain,chain_post_human_sim');
vm.runInContext('vmToggleScheme("chain_human_sim")',context);
assert.equal(location.searchParams.get('schemes'),'chain,chain_human_sim,chain_post_human_sim');
vm.runInContext('vmToggleScheme("chain_human_sim")',context);
assert.equal(location.searchParams.get('schemes'),'chain,chain_post_human_sim');
vm.runInContext('vmToggleScheme("chain")',context);
assert.equal(location.searchParams.get('schemes'),'chain_post_human_sim');
vm.runInContext('vmToggleScheme("chain_post_human_sim")',context);
assert.equal(location.searchParams.get('schemes'),'none');
vm.runInContext('vmReadRoute(); vmToggleScheme("chain")',context);
assert.equal(location.searchParams.get('schemes'),'chain');
assert.equal(location.searchParams.get('families'),'20261016');
assert.equal(location.searchParams.get('reference'),'rd');
assert.equal(location.searchParams.get('exclusion'),'exclude');
assert.equal(state.data,receipt);
assert.equal(reads,0);
assert.equal(vm.runInContext('vmThresholdText()',context),'conf < 0.85');
english=true;
assert.equal(vm.runInContext('vmThresholdText()',context),'conf < 0.85');
state.threshold=.75;
assert.equal(vm.runInContext('vmThresholdText()',context),'conf < 0.75');
"""
        result = subprocess.run(["node", "-e", program], input=metric_source(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_all_equal_point_labels_stay_above_points_and_inside_chart(self):
        path = Path(__file__).parents[1] / "static/js/version-metrics.js"
        program = metric_source() + r"""
const assert = require('node:assert/strict');
const keys = VM_SCHEMES;
for (const value of [0, 0.8, 1]) {
  const row = {metrics: Object.fromEntries(keys.map(key => [key, {accuracy:value}]))};
  const geometry = vmChartGeometry([row], keys, 320);
  const labels = vmPointLabels(row, keys, geometry.y);
  assert.equal(labels.length, 1, 'equal values share one label');
  assert.equal(labels[0].keys.length, keys.length);
  labels.forEach((label, index) => {
    assert.ok(label.y >= 14 && label.y <= geometry.y(value)-12, 'label must fit above its point');
    if (index) assert.ok(labels[index-1].y-label.y >= 18, 'equal labels must not overlap');
  });
  row.metrics.model.accuracy = null;
  assert.equal(vmPointLabels(row, keys, geometry.y)[0].keys.length, keys.length-1, 'unknown values stay absent');
}
"""
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_sim_scale_tracks_only_visible_values_and_centres_release_intervals(self):
        path = Path(__file__).parents[1] / "static/js/version-metrics.js"
        program = metric_source() + r"""
const assert = require('node:assert/strict');
const row = (model, chain) => ({metrics:{model:{accuracy:model},chain:{accuracy:chain}}});
const rows = [row(.7611,.9767),row(.8627,.9742),row(null,null)];
assert.deepEqual(vmPercentageScale(rows, ['model','chain']), {domain:[76,100],ticks:[76,82,88,94,100]});
assert.deepEqual(vmPercentageScale(rows, ['model']), {domain:[76,88],ticks:[76,79,82,85,88]});
assert.deepEqual(vmPercentageScale([row(0,1)], ['model','chain']), {domain:[0,100],ticks:[0,25,50,75,100]});
assert.deepEqual(vmPercentageScale([row(null,null)], ['model']), {domain:[0,100],ticks:[0,25,50,75,100]});
assert.deepEqual(vmPercentageScale([row(1,1)], ['model']), {domain:[96,100],ticks:[96,97,98,99,100]});
assert.deepEqual(vmPercentageScale([row(0,0)], ['model']), {domain:[0,4],ticks:[0,1,2,3,4]});
for (const count of [1,4,25]) {
  const population = Array.from({length:count}, () => row(.8,.9));
  const geometry = vmChartGeometry(population, ['model','chain'], 390);
  assert.equal(geometry.height, 288);
  assert.ok(geometry.width >= 680);
  assert.equal(geometry.x(0)-geometry.left, geometry.plotW/count/2);
  assert.ok(Math.abs(geometry.width-geometry.right-geometry.x(count-1)-geometry.plotW/count/2) < 1e-9);
  for (let i=1;i<count;i++) assert.ok(Math.abs(geometry.x(i)-geometry.x(i-1)-geometry.plotW/count) < 1e-9);
  assert.ok(Math.abs(geometry.y(geometry.scale.domain[1]/100)-geometry.top) < 1e-9);
  assert.ok(Math.abs(geometry.y(geometry.scale.domain[0]/100)-(geometry.height-geometry.bottom)) < 1e-9);
}
"""
        result = subprocess.run(["node", "-e", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_local_changes_keep_response_but_stale_scope_and_departure_do_not(self):
        program = r"""
const vm = require('node:vm'), fs = require('node:fs'), assert = require('node:assert/strict');
const requests = [], location = new URL('http://localhost/version-metrics');
const context = vm.createContext({URL, URLSearchParams, AbortController, location,
  history: {pushState: (s,t,u) => { location.href = u; }, replaceState: (s,t,u) => {location.href = u;}},
  withBase: p => p, uiText: z => z, setTimeout, clearTimeout,
  api: () => new Promise(resolve => requests.push(resolve)), $: () => ({hidden: true, querySelectorAll: () => []})});
vm.runInContext(fs.readFileSync(0, 'utf8'), context);
vm.runInContext('renderVersionMetrics = () => {}; versionMetrics.active = true; versionMetrics.families = "20261030"', context);
const state = vm.runInContext('versionMetrics', context);
const receipt = tag => ({tag, catalog: [], selected: ['20261030'], items: [], refresh: {status: 'idle'}});
(async () => {
  const first = vm.runInContext('loadVersionMetrics({restore:false})', context);
  vm.runInContext('vmChange({metric:"macro_f1",schemes:["chain"]},{local:true})', context);
  requests.shift()(receipt('local-change'));
  await first;
  assert.equal(state.data.tag, 'local-change');
  assert.equal(state.metric, 'macro_f1');
  assert.equal(location.searchParams.get('metric'), 'macro_f1');
  assert.equal(location.searchParams.get('schemes'), 'chain');
  const old = vm.runInContext('loadVersionMetrics({restore:false})', context);
  vm.runInContext('vmChange({reference:"rd"})', context);
  requests.shift()(receipt('stale-te'));
  await old;
  assert.equal(state.data, null);
  requests.shift()(receipt('current-rd'));
  await new Promise(setImmediate);
  assert.equal(state.data.tag, 'current-rd');
  assert.equal(location.searchParams.get('reference'), 'rd');
  const departure = vm.runInContext('loadVersionMetrics({restore:false})', context);
  vm.runInContext('setVersionMetricsActive(false)', context);
  requests.shift()(receipt('after-departure'));
  await departure;
  assert.equal(state.data.tag, 'current-rd');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        path = Path(__file__).parents[1] / "static/js/version-metrics.js"
        result = subprocess.run(["node", "-e", program], input=metric_source(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
