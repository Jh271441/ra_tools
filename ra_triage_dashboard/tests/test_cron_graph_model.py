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

    def test_stage_progress_preserves_scopes_failures_unknowns_and_stale_snapshots(self):
        static = Path(__file__).resolve().parents[1] / "static/js"
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const ctx=vm.createContext({window:{},document:{addEventListener(){}},state:{colorTheme:'dark'},uiText:zh=>zh,$:()=>null,Date});
for(const path of process.argv.slice(2))vm.runInContext(fs.readFileSync(path,'utf8'),ctx);
vm.runInContext(`
dailyCronState.active=true;
const run={id:'daily-2026-10-20',target_date_cst:'2026-10-20',started_at:Date.now()/1000-60,state:'running',health:'running',stage:'inference',finished:160,succeeded:159,total:255,selected:null,inferred:null,skipped:0};
const media={day:'2026-10-20',state:'collecting',selected:103,imported:103,assigned:103,camera_verified:80,verified:70,original_orion_total:103,original_orion_completed:102,original_orion_failed:1,retry_state:'running',retry_total:1,retry_completed:0,retry_failed:0,stage_timings:{'media-local':{observed:1,total:2}}};
const data={overview:{collected_at:Date.now()/1000,daily:{runs:[run]}},media_daily:{runs:[media]}};
function task(id){return buildDailyCronGraph(data).lanes.flatMap(l=>l.nodes).find(n=>n.id===id).data;}
let p=task('main-infer').progress;
if(p.done!==160||p.total!==255||p.percent!==62.7||p.failed!==1)throw Error('active stage counts must work before terminal aggregates exist');
if(task('main-publish').progress.mode!=='waiting'||task('main-verify').progress.mode!=='waiting')throw Error('future phases must not pretend to have started');
if(task('main-query').detail!=='选集已冻结')throw Error('active downstream phase proves cohort registration');
p=task('media-orion').progress;if(p.percent!==100||p.failed!==1||p.failurePercent<=0)throw Error('queue processing completion includes failures without making them successes');
p=task('media-retry').progress;if(p.total!==1||p.done!==0||p.percent!==0)throw Error('retry denominator must be its own subset');
p=task('media-local').progress;if(p.total!==2||p.done!==1||task('media-local').status!=='running')throw Error('local attempt receipts retain their own units');
run.stage='sample_hook';run.finished=17;run.total=17;run.verified=255;run.inferred=255;run.published=255;run.selected=256;run.skipped=1;
p=task('main-verify').progress;if(p.done!==17||p.total!==17)throw Error('sample scope must not use whole-run verified count');
p=task('main-infer').progress;if(p.done!==256||p.skipped!==1)throw Error('inference processing includes explicit skips');
media.original_orion_total=74;media.original_orion_completed=74;media.original_orion_failed=0;
p=task('media-orion').progress;if(p.total!==74||!p.label.includes('原始'))throw Error('old queue coverage cannot be labelled as full replacement cohort');
media.selected=0;media.state='waiting';if(task('media-camera').progress.mode!=='waiting')throw Error('unregistered media is waiting, not complete');
media.selected=103;media.state='collecting';delete media.retry_total;if(task('media-retry').progress.mode!=='unknown')throw Error('missing denominator must remain unknown');
if(cronTaskProgress(104,103).mode!=='unknown'||cronTaskProgress(null,103).mode!=='unknown'||cronTaskProgress(1,0).mode!=='unknown'||cronTaskProgress(true,2).mode!=='unknown'||cronTaskProgress(1,2,{skipped:-1}).mode!=='unknown')throw Error('invalid counters must not be clamped into plausible percentages');
run.stage='inference';run.finished=160;run.total=255;data.overview.stale=true;
p=task('main-infer').progress;if(!p.stale||p.percent!==62.7||task('main-infer').status==='running')throw Error('stale snapshot must be frozen and marked');
if(buildDailyCronGraph(data,'media').lanes[0].nodes.some(n=>n.data.progress))throw Error('definition diagrams have no live progress');
`,ctx);
'''
        result = subprocess.run(["node", "-", str(static / "daily-cron.js"), str(static / "daily-cron-graph.js")], input=script, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
