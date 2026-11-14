import {test} from 'node:test';
import assert from 'node:assert/strict';
import {completeMetrics,evaluationFlow,evaluationActivity,evaluationMotion} from '../src/lib/evaluationFlow.ts';
const board=()=>({context:{release:'gen4-release-20261016',profile_id:'auto_triage_sql_v2'},profile:{name:'SQL v2'},
  sample_source:{status:'ready',row_count:2007},refresh:{},stale:false,starts:[],executions:[],
  revision:{source_count:2007,metrics:{available:false,eligible:1816,covered:1815,coverage:1815/1816}},
  plan:{id:'new-plan',runnable_count:0,gap_count:1,blocked_count:1,review_count:0}});
const job=(status='complete')=>({id:'execution',status,job_id:49407141,created_at:'2026-11-05T17:49:44Z',metrics_status:'complete',progress:{completed:64,total:64,started_at:'2026-11-05T17:49:44Z'}});
const stage=(data,key)=>evaluationFlow(data).find(s=>s.step===key);

test('the completed production delta and a missing bag keep distinct task and population states',()=>{
 const d=board();d.executions=[job()];
 assert.deepEqual([stage(d,'manual').state,stage(d,'manual').value,stage(d,'manual').total],['complete',64,64]);
 assert.equal(stage(d,'manual').status,'flow_job_complete');
 assert.equal(stage(d,'plan').status,'flow_deferred');
 assert.deepEqual(stage(d,'plan').params,{amount:1});
 assert.deepEqual([stage(d,'evaluate').value,stage(d,'evaluate').total,stage(d,'evaluate').state],[1815,1816,'warning']);
 assert.equal(completeMetrics(d.revision.metrics),false);
});
for(const status of ['preparing','submitting','running','verifying','submission_uncertain'])test(`active ${status} receipts drive the simulation node`,()=>{
 const d=board();d.executions=[{...job(status),metrics_status:undefined,progress:{completed:55,total:64}}];
 const value=stage(d,'manual');assert.equal(value.value,55);assert.equal(value.total,64);
 assert.equal(value.state,status==='submission_uncertain'?'blocked':'active');
 assert.notEqual(stage(d,'evaluate').state,'complete');
});

test('audited job completion waits for automatic metric reprojection, without returning to manual-start waiting',()=>{
 const d=board();d.plan.runnable_count=64;d.executions=[{...job(),metrics_status:'pending'}];
 assert.equal(stage(d,'manual').state,'complete');
 assert.equal(stage(d,'evaluate').state,'active');
 assert.equal(stage(d,'evaluate').status,'flow_updating_metrics');
});

test('full metrics require fresh complete population coverage, not just a completed Job or available flag',()=>{
 const d=board();d.executions=[job()];d.revision.metrics.available=true;
 assert.equal(stage(d,'evaluate').state,'warning');
 Object.assign(d.revision.metrics,{covered:1816,coverage:1});
 assert.equal(stage(d,'evaluate').state,'complete');
 d.stale=true;assert.equal(stage(d,'evaluate').state,'warning');assert.equal(stage(d,'evaluate').status,'flow_recalculate');
 d.stale=false;d.revision.metrics.eligible=0;d.revision.metrics.covered=0;assert.equal(completeMetrics(d.revision.metrics),false);
});

test('new gaps and human review return a completed context to manual review',()=>{
 const d=board();d.executions=[job()];d.plan.runnable_count=3;
 assert.equal(stage(d,'manual').value,3);assert.equal(stage(d,'manual').status,'await_manual');
 d.plan.review_count=2;assert.equal(stage(d,'manual').state,'blocked');assert.equal(stage(d,'manual').status,'flow_review');
});

test('an old failed start is history and a later failed start is actionable',()=>{
 const d=board();d.executions=[job()];
 d.starts=[{id:'old',status:'failed',created_at:'2026-11-05T13:00:00Z'},{id:'current',status:'complete',created_at:'2026-11-05T17:49:30Z'}];
 assert.equal(evaluationActivity(d).currentFailure,undefined);assert.equal(evaluationActivity(d).failed.length,1);
 d.starts.push({id:'latest',status:'failed',created_at:'2026-11-06T00:00:00Z'});
 assert.equal(evaluationActivity(d).currentFailure.id,'latest');assert.equal(stage(d,'manual').state,'blocked');
});

test('a quality failure cannot publish full metrics or fabricate execution success',()=>{
 const d=board();d.executions=[job('quality_failed')];
 assert.equal(stage(d,'manual').state,'warning');assert.notEqual(stage(d,'evaluate').state,'complete');
});

test('a missing snapshot never looks imported, executed, or evaluated',()=>{
 const d=board();d.sample_source={status:'missing'};d.revision=null;d.plan={};
 assert.equal(stage(d,'sync').state,'waiting');assert.equal(stage(d,'sync').status,'flow_no_snapshot');
 assert.equal(stage(d,'manual').state,'waiting');assert.equal(stage(d,'evaluate').state,'waiting');
});

test('initial loading does not invent a sample, profile, plan, or execution receipt',()=>{
 for(const stage of evaluationFlow(null)){assert.equal(stage.state,'waiting');assert.equal(stage.status,'flow_waiting');assert.equal(stage.value,undefined);}
});

test('completed executions from another metric context do not become this context’s own start receipt',()=>{
 const d=board();d.executions=[{...job(),context:{release:d.context.release,profile_id:'another-profile'}}];
 assert.equal(evaluationActivity(d).latest,undefined);assert.notEqual(stage(d,'manual').status,'flow_job_complete');
});

test('completed simulation stays still while enabled periodic checks move slowly',()=>{
 const d=board();d.executions=[job()];d.cron={enabled:true,effective:true};
 assert.deepEqual(evaluationMotion(d),{check:true,refreshing:false,dispatch:false,evaluating:false});
 assert.equal(stage(d,'evaluate').state,'warning'); // The missing bag is not completed by the scheduler.
});

test('disabled scheduling stops the check, without hiding an actually running job',()=>{
 const d=board();d.cron={enabled:true,effective:false};
 assert.equal(evaluationMotion(d).check,false);
 d.executions=[job('running')];assert.equal(evaluationMotion(d).dispatch,true);
 d.executions=[job('submission_uncertain')];assert.equal(evaluationMotion(d).dispatch,false);
 assert.equal(evaluationMotion(d).evaluating,false);
});

test('database recalculation and audited metric projection animate evaluation, not simulation',()=>{
 const d=board();d.cron={enabled:true,effective:true};d.executions=[job()];
 d.refresh={status:'running'};
 assert.deepEqual(evaluationMotion(d),{check:false,refreshing:true,dispatch:false,evaluating:true});
 d.refresh={status:'complete'};d.executions[0].metrics_status='pending';
 assert.equal(evaluationMotion(d).dispatch,false);assert.equal(evaluationMotion(d).evaluating,true);
});

test('stale, failed and missing sources never animate a healthy sidecar',()=>{
 const d=board();d.cron={enabled:true,effective:true};d.executions=[job('running')];
 for (const mutation of [{stale:true},{refresh:{status:'failed'}},{sample_source:{status:'missing'}}]) {
  assert.deepEqual(evaluationMotion({...d,...mutation}),{check:false,refreshing:false,dispatch:false,evaluating:false});
 }
 assert.equal(evaluationMotion(null).check,false);
});

test('active or projecting execution from another profile cannot animate this profile',()=>{
 const d=board();d.cron={enabled:false};
 d.executions=[{...job('running'),metrics_status:'pending',context:{...d.context,profile_id:'different'}}];
 assert.equal(evaluationActivity(d).active,undefined);
 assert.equal(evaluationMotion(d).dispatch,false);assert.equal(evaluationMotion(d).evaluating,false);
});
