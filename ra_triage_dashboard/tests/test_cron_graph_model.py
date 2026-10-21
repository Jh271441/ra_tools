from pathlib import Path
import subprocess
import unittest


class CronGraphModelTest(unittest.TestCase):
    def test_run_scope_missing_evidence_and_state_transitions(self):
        static = Path(__file__).resolve().parents[1] / "static/js"
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = vm.createContext({ window:{}, document:{addEventListener:()=>{}}, state:{colorTheme:'dark'}, uiText:(zh)=>zh, $:()=>null, Date });
for (const path of process.argv.slice(1)) vm.runInContext(fs.readFileSync(path,'utf8'),ctx);
vm.runInContext(`
dailyCronState.active=true;
const data={overview:{collected_at:Date.now()/1000,daily:{runs:[{id:'daily-2026-10-18',target_date_cst:'2026-10-18',state:'complete_with_gaps',health:'partial',selected:210,inferred:206,published:206,verified:206,skipped:4},{id:'daily-2026-10-16',target_date_cst:'2026-10-16',state:'complete',health:'success',selected:278,inferred:278,published:278,verified:278,skipped:0}]}},media_daily:{runs:[{day:'2026-10-18',selected:90,verified:90,imported:90,assigned:90,state:'complete',original_orion_total:90,original_orion_failed:2},{day:'2026-10-16',selected:112,verified:112,imported:112,assigned:112,state:'complete'}]}};
function task(model,id) { return model.lanes.flatMap(l=>l.nodes).find(n=>n.id===id).data; }
`,ctx);
assert.equal(vm.runInContext('buildDailyCronGraph(data).lanes.length',ctx),2);
assert.equal(vm.runInContext('task(buildDailyCronGraph(data),"main-infer").status',ctx),'warn');
vm.runInContext('data.overview.daily.runs[0].stage_timings={"main-infer":{mode:"finished",kind:"span",elapsed_seconds:6040.3,basis:"registration_to_publication"}}',ctx);
assert.equal(vm.runInContext('task(buildDailyCronGraph(data),"main-infer").timingText',ctx),'阶段用时 1小时40分钟');
assert.equal(vm.runInContext('task(buildDailyCronGraph(data),"main-infer").rows.some(row=>row[0]==="计时口径"&&row[1].includes("未单独记录纯推理耗时"))',ctx),true);
assert.equal(vm.runInContext('task(buildDailyCronGraph(data),"media-ready").status',ctx),'success');
assert.equal(vm.runInContext('task(buildDailyCronGraph(data),"media-retry").status',ctx),'unknown');
assert.equal(vm.runInContext('buildDailyCronGraph(data).edges.some(e=>e.source.startsWith("media-")&&e.target.startsWith("main-"))',ctx),false);
vm.runInContext('dailyCronState.selectedDay="2026-10-16"',ctx);
assert.equal(vm.runInContext('cronSelectedRuns(data).media.selected',ctx),112);
vm.runInContext('dailyCronState.selectedDay="";const missing={...data,media_daily:null};',ctx);
assert.equal(vm.runInContext('task(buildDailyCronGraph(missing),"main-publish").status',ctx),'success');
assert.equal(vm.runInContext('task(buildDailyCronGraph(missing),"media-orion").status',ctx),'unknown');
vm.runInContext('const running=JSON.parse(JSON.stringify(data));Object.assign(running.overview.daily.runs[0],{state:"running",health:"running",stage:"inference",inferred:null,published:null,verified:null});',ctx);
assert.equal(vm.runInContext('task(buildDailyCronGraph(running),"main-infer").status',ctx),'running');
vm.runInContext('running.overview.stale=true',ctx);
assert.equal(vm.runInContext('task(buildDailyCronGraph(running),"main-infer").status',ctx),'unknown');
assert.equal(vm.runInContext('buildDailyCronGraph(data,"media").lanes.length',ctx),1);
assert.equal(vm.runInContext('buildDailyCronGraph(data,"media").lanes[0].nodes.every(n=>n.data.status==="definition")',ctx),true);
'''
        result = subprocess.run(["node", "-e", script, str(static / "daily-cron.js"), str(static / "daily-cron-graph.js")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
