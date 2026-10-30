from pathlib import Path
import subprocess
import unittest


class VersionViewTest(unittest.TestCase):
    def test_scopes_preserve_selection_and_never_substitute_totals(self):
        static = Path(__file__).resolve().parents[1] / 'static/js'
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ctx=vm.createContext({window:{},document:{addEventListener(){}},state:{colorTheme:'dark'},uiText:zh=>zh,$:()=>null,Date,URL,URLSearchParams,assert});
for(const f of process.argv.slice(1))vm.runInContext(fs.readFileSync(f,'utf8'),ctx);
vm.runInContext(`
const source={enabled:true,states:{published:1000},families:['20261009','20261016','20261023'],
 versions:[{family:'20261009',states_status:'ready',states:{published:10,waiting_metadata:3},media:{selected:3,verified:2}},
 {family:'20261016',states_status:'ready',states:{published:20},media:{selected:5,verified:4}},
 {family:'20261023',states_status:'ready',states:{published:30},media:{selected:7,verified:6}}],
 datasets:[{release_family:'20261009',targets:3,assigned:{a:3}},{release_family:'20261016',targets:5}],
 increments:{status:'ready',items:[{family:'20261009',new:0},{family:'20261023',new:5}]}};
const data={incremental:source};
assert.equal(cronSelectedIncremental(data).family,'20261023');
dailyCronState.selectedVersion='20261009';
let v=cronSelectedIncremental(data);
assert.equal(v.states.published,10);assert.equal(v.media.selected,3);assert.equal(v.datasets.length,1);
assert.equal(v.increments.items.length,1);assert.equal(v.increments.items[0].family,'20261009');
const task=id=>buildDailyCronGraph(data).lanes.flatMap(l=>l.nodes).find(n=>n.id===id).data;
assert.equal(task('main-infer').progress.done,10);assert.equal(task('media-verify').progress.total,3);
source.families.push('20261030');assert.equal(cronSelectedIncremental(data).family,'20261009');
source.versions=source.versions.filter(v=>v.family!=='20261009');
assert.equal(cronSelectedIncremental(data).family,'20261009');assert.equal(task('main-infer').progress.mode,'unknown');
assert.equal(task('media-verify').status,'unknown');
source.versions.push({family:'20261009',states_status:'unavailable',states:null,media:{selected:3,verified:2}});
assert.equal(task('main-infer').detail,'—');assert.equal(task('media-verify').progress.done,2);
dailyCronState.error=true;assert.equal(task('media-verify').status,'unknown');
assert.equal(source.stale,undefined); // projection does not mutate the cached response
dailyCronState.selectedVersion='all';assert.equal(cronSelectedIncremental(data).states.published,1000);
assert.equal(cronSelectedIncremental({}).unavailable,true);
dailyCronState.selectedVersion='20261009';
assert.equal(cronSelectedIncremental({}).family,'20261009');
assert.equal(buildDailyCronGraph({}).lanes[0].nodes.find(n=>n.id==='main-infer').data.progress.mode,'unknown');
window.location={search:'?cron_version=20261009'};restoreCronScope();
const url=new URL('https://example.test/manual/daily-cron?keep=1');writeCronScope(url);
assert.equal(url.searchParams.get('cron_version'),'20261009');assert.equal(url.searchParams.get('keep'),'1');
window.location.search='?cron_version=20261016&cron_day=2026-10-20';restoreCronScope();
assert.equal(dailyCronState.selectedDay,'2026-10-20');
`,ctx);
"""
        result = subprocess.run(['node','-e',script,str(static/'daily-cron.js'),str(static/'daily-cron-graph.js')],
                                capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
