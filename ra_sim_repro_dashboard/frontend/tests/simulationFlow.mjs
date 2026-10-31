import { test } from 'node:test';
import assert from 'node:assert/strict';
import { simulationFlow, executionSeconds, collectionProgress, issueAge } from '../src/lib/simulationFlow.ts';
const base = () => ({ selected: {kind:'current',period:{status:'completed'},population_complete:true,issue_count:10,scenario_count:10,metrics:{available:false},jobs:[]},current_status:'ready' });
const job = (state='RUNNING') => ({job_id:1,status:'running',scenario_count:10,progress:{state,total:10,finished:4,completed:4,running:6,queued:0,failed:0,cancelled:0,unknown:0}});
const evaluation = () => ({primary_job_id:1,scenario_count:10,valid_scenario_count:9,missing_scenario_count:1,quality_gate_passed:false,comparison:{conflicts:[]}});
const publication = () => ({primary_job_id:1,valid_scenario_count:9,scenario_count:10,excluded_scenario_ids:['x'],coverage:.9,issue_coverage:.9});
const states = data => Object.fromEntries(simulationFlow(data).stages.map(s=>[s.id,s.state]));
test('collecting does not invent execution',()=>{ const d=base();d.selected.period.status='running';d.selected.population_complete=false;assert.deepEqual(states(d),{collect:'active',prepare:'waiting',execute:'waiting',verify:'waiting',publish:'waiting'}); });
test('terminal execution is separate from publication',()=>{const d=base();const j=job('COMPLETED');j.progress.finished=10;j.progress.failed=1;d.selected.jobs=[j];const s=states(d);assert.equal(s.execute,'warning');assert.equal(s.verify,'waiting');assert.equal(s.publish,'waiting');});
test('explicit publication preserves exceptions',()=>{const d=base();d.selected.evaluation=evaluation();d.selected.metrics.publication=publication();assert.equal(states(d).verify,'warning');assert.equal(states(d).publish,'complete');});
test('high coverage alone cannot publish',()=>{const d=base();d.selected.evaluation={...evaluation(),scenario_count:2004,valid_scenario_count:2002};assert.equal(states(d).publish,'blocked');});
test('archive does not fabricate stage receipts',()=>{const d=base();d.selected.kind='archived';d.selected.population_complete=false;d.selected.metrics={available:true,archived:true};assert.deepEqual(states(d),{collect:'unknown',prepare:'unknown',execute:'unknown',verify:'unknown',publish:'archived'});});
test('progress errors retain last observation without animation',()=>{const d=base();d.selected.jobs=[{...job(),progress_error:'timeout'}];assert.equal(states(d).execute,'unknown');d.selected.jobs=[job()];assert.equal(simulationFlow(d,true).stages[2].state,'unknown');});
test('invalid denominator has no progress bar',()=>{const d=base();const j=job();j.progress.finished=11;d.selected.jobs=[j];assert.equal(simulationFlow(d).stages[2].progress,undefined);});
test('rerun and retained publication have separate scopes',()=>{const d=base();d.selected.jobs=[{...job(),job_id:2}];d.selected.metrics.publication=publication();const m=simulationFlow(d);assert.equal(m.retained,true);assert.equal(m.job.job_id,2);assert.equal(m.stages[2].state,'active');assert.equal(m.stages[4].state,'complete');});
test('uncertain submission and preflight require inspection',()=>{const d=base();d.selected.jobs=[{...job(),status:'submission_uncertain',progress:null}];assert.equal(states(d).execute,'blocked');d.selected.jobs[0].status='preflight_failed';assert.equal(states(d).prepare,'blocked');});
test('elapsed uses receipts, rejects invalid timing',()=>{assert.equal(executionSeconds('2026-10-19T07:01:31Z','2026-10-19T08:19:03.220Z'),4652);assert.equal(executionSeconds(null,null),null);assert.equal(executionSeconds('2026-10-20','2026-10-19'),null);assert.equal(executionSeconds('bad','bad'),null);});

const observing = () => { const d=base(); d.mode='auto'; d.driver_ready=true; d.scheduler_enabled=true; d.selected.kind='observation'; d.selected.period=null; d.selected.population_complete=false; d.selected.collection={source:'observation',monitor_status:'observing',collection_status:'collecting',auto_count:100,manual_count:20,issue_count:120,stale:false,quiet_seconds:3600,quiet_seconds_required:86400}; return d; };
test('collection reflects observed hours, not a predicted issue total',()=>{const d=observing();const c=collectionProgress(d);assert.equal(c.progress,1/24);assert.equal(c.status,'collectionAuto');assert.equal(states(d).collect,'active');assert.equal(states(d).execute,'waiting');});
test('stale collection cannot show ready or automatic activation',()=>{const d=observing();d.selected.collection.quiet_seconds=86400;d.selected.collection.stale=true;assert.equal(collectionProgress(d).progress,0);assert.equal(collectionProgress(d).status,'collectionPaused');assert.equal(states(d).collect,'unknown');});
test('stable collection enables preparation but never fabricates a job',()=>{const d=observing();Object.assign(d.selected.collection,{quiet_seconds:86400,collection_status:'stable'});assert.equal(collectionProgress(d).status,'collectionPreparing');assert.equal(states(d).collect,'complete');assert.equal(states(d).execute,'waiting');d.mode='manual';assert.equal(collectionProgress(d).status,'collectionManual');});
test('preparation blockers and post-submit changes stay visible',()=>{const d=observing();d.selected.collection.monitor_status='blocked';assert.equal(collectionProgress(d).status,'collectionNeedsReview');assert.equal(states(d).prepare,'blocked');d.selected.collection.population_changed_after_submission=true;assert.equal(states(d).collect,'warning');});

test('last issue age rolls over days and rejects missing, invalid or future timestamps',()=>{const now=Date.parse('2026-10-23T06:00:00Z');assert.deepEqual(issueAge('2026-10-21T05:58:59Z',now),{days:2,hours:0,minutes:1,seconds:1});assert.deepEqual(issueAge('2026-10-23T06:00:00Z',now+1000),{days:0,hours:0,minutes:0,seconds:1});for(const stamp of [null,'bad','2026-10-24T00:00:00Z'])assert.equal(issueAge(stamp,now),null);});

test('scene preparation and timeout expose automatic system actions',()=>{const d=observing();Object.assign(d.selected.collection,{quiet_seconds:86400,collection_status:'stable',monitor_status:'preparing_scenes'});assert.equal(states(d).prepare,'active');assert.equal(collectionProgress(d).status,'preparingScenes');Object.assign(d.selected.collection,{monitor_status:'blocked',monitor_error_code:'driver_timeout',monitor_error_action:'prepare_scenes'});assert.equal(states(d).prepare,'warning');assert.equal(simulationFlow(d).stages[1].detail,'scenesTimeout');assert.equal(collectionProgress(d).status,'sceneRetry');assert.equal(collectionProgress(d,true).status,'collectionPaused');d.selected.collection.monitor_error_action='lookup_binary';assert.equal(states(d).prepare,'blocked');});

test('missing bag is a source blocker rather than a driver timeout',()=>{const d=observing();Object.assign(d.selected.collection,{monitor_status:'blocked',monitor_error_code:'scene_preparation_failed',preparation:{prepared:1855,failed:1,failures:[{issue_id:'cn123',reason:'missing_bag'}]}});assert.equal(simulationFlow(d).stages[1].detail,'scenesFailed');assert.equal(states(d).prepare,'blocked');assert.equal(states(d).execute,'waiting');});

test('tolerated preparation remains visible while execution continues',()=>{const d=base();d.selected.jobs=[job()];d.selected.issue_tolerance={abnormal_issue_count:1};const m=simulationFlow(d);assert.equal(m.stages[1].detail,'preparedWithExceptions');assert.equal(m.stages[1].state,'warning');assert.equal(m.stages[2].state,'active');});

test('typed anomaly details preserve collection changes and every execution category',()=>{const d=observing();d.selected.collection.population_changed_after_submission=true;d.selected.collection_anomalies=[{code:'label_changed',count:3,items:[{issue_id:'cn1',field:'ra_merge_result',before:'失败',after:'误触发'}]}];const j=job('COMPLETED');Object.assign(j.progress,{finished:10,completed:7,failed:1,cancelled:1,unknown:1});d.selected.jobs=[j];let m=simulationFlow(d);assert.equal(m.stages[0].anomalies[0].count,3);assert.deepEqual(m.stages[2].anomalies.map(a=>a.code),['execution_failed','execution_cancelled','execution_unknown']);d.selected.collection_anomalies=[];assert.equal(simulationFlow(d).stages[0].anomalies[0].code,'collection_change_unresolved');});
test('verification exclusions retain IDs and missing results remain separate from conflicts',()=>{const d=base();d.selected.evaluation={...evaluation(),comparison:{conflicts:['c1']},failures:[{scenario_id:'s1',issue_id:'i1',outcome:'missing_dpe'}]};d.selected.metrics.publication=publication();const a=simulationFlow(d).stages[3].anomalies;assert.deepEqual(a.map(v=>v.code),['results_missing','results_conflict','results_excluded']);assert.equal(a[0].items[0].issue_id,'i1');assert.equal(a[2].items[0].scenario_id,'x');});

test('applied labels clear the collection warning while retaining history',()=>{
  const d=observing();d.selected.collection.collection_status='stable';d.selected.collection.population_changed_after_submission=true;
  d.selected.collection_anomalies=[{code:'label_changed',count:16,resolved:true,items:[{issue_id:'i1',before:'失败',after:'误触发'}]}];
  let c=simulationFlow(d).stages[0];assert.equal(c.state,'complete');assert.equal(c.resolvedLabelCount,16);assert.equal(c.anomalies[0].items.length,1);
  d.selected.collection_anomalies.push({code:'issues_added',count:1,items:[]});assert.equal(simulationFlow(d).stages[0].state,'warning');
  assert.equal(simulationFlow(d,true).stages[0].state,'unknown');
  delete d.selected.collection_anomalies[0].resolved;assert.equal(simulationFlow(d).stages[0].resolvedLabelCount,0);
});

test('main path motion follows active and completed stages, stopping on blockers',async()=>{
  const {stageMotion}=await import('../src/lib/simulationFlow.ts');
  assert.deepEqual(stageMotion({state:'active'},{state:'waiting'}),{animated:true,scheduled:false});
  assert.deepEqual(stageMotion({state:'complete'},{state:'complete'}),{animated:false,scheduled:true});
  assert.deepEqual(stageMotion({state:'warning'},{state:'complete'}),{animated:false,scheduled:true});
  assert.deepEqual(stageMotion({state:'waiting'},{state:'waiting'}),{animated:false,scheduled:false});
  for(const state of ['blocked','unknown','archived'])assert.deepEqual(stageMotion({state},{state:'active'}),{animated:false,scheduled:false});
  assert.deepEqual(stageMotion({state:'complete'},{state:'complete'},true),{animated:false,scheduled:false});
});

test('recovery job cannot replace the main execution in the five stage flow',()=>{
  const d=base();const main={...job('COMPLETED'),status:'complete'};main.progress.finished=10;
  d.selected.jobs=[{...job(),job_id:2,backfill:true,scenario_count:1},main];
  const model=simulationFlow(d);
  assert.equal(model.job.job_id,1);assert.equal(model.stages[2].state,'complete');
});
