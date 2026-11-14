import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSavedEvaluationInitializer, savedEvaluationInitializationKey } from '../src/lib/evaluationInitialization.ts';

const context = { release:'gen4-release-20261023', profile_id:'auto_triage_sql_v2', date_start:'2026-10-29', date_end:'2026-11-04' };
const empty = () => ({ context:{...context}, revision:null, stale:false, profile:{status:'published'},
  sample_source:{status:'ready',mode:'database',snapshot_id:'saved-1023'}, cron:{processing_enabled:true}, refresh:{} });

test('a saved legacy date range initializes its exact scope using the DB-only request', async () => {
  const requests=[];
  let finish;
  const initializer=createSavedEvaluationInitializer(body=>{requests.push(body);return new Promise(resolve=>{finish=resolve;});});
  const board=empty(), first=initializer(board), second=initializer(structuredClone(board));
  assert.equal(first,second);
  await Promise.resolve();
  assert.deepEqual(requests,[{...context,refresh_labels:false}]);
  finish({status:'queued'});await first;
  assert.equal(initializer(board),first,'rerendering does not enqueue the same saved scope twice');
  assert.equal(requests.length,1);
});

test('ready metrics, missing samples, unpublished rules and paused processing do not initialize', () => {
  for(const change of [{revision:{revision_key:'published'}},{stale:true},
    {sample_source:{status:'missing'}},{profile:{status:'draft'}},{cron:{processing_enabled:false}},
    {context:{...context,date_end:undefined}}]) {
    const board={...empty(),...change};
    assert.equal(savedEvaluationInitializationKey(board),null);
  }
});

test('queued, running and failed requests are observed without automatic resubmission', () => {
  const initializer=createSavedEvaluationInitializer(()=>{throw Error('must not enqueue');});
  for(const status of ['queued','running','failed'])assert.equal(initializer({...empty(),refresh:{status}}),null);
});

test('a failed initialization remains one attempt until an explicit retry', async () => {
  let count=0;
  const initializer=createSavedEvaluationInitializer(async()=>{count++;throw Error('pipeline_busy');});
  const first=initializer(empty());await assert.rejects(first,/pipeline_busy/);
  assert.equal(initializer(empty()),first);
  await assert.rejects(initializer(empty()),/pipeline_busy/);
  assert.equal(count,1);
});

test('different dates and newly imported sample snapshots get independent initialization', async () => {
  const requests=[];
  const initializer=createSavedEvaluationInitializer(async body=>{requests.push(body);});
  const first=empty(), otherDates={...empty(),context:{...context,date_end:'2026-11-03'}},
    newSnapshot={...empty(),sample_source:{...empty().sample_source,snapshot_id:'newer-1023'}};
  await Promise.all([initializer(first),initializer(otherDates),initializer(newSnapshot)]);
  assert.equal(requests.length,3);
  assert.equal(requests[1].date_end,'2026-11-03');
  assert.deepEqual(first.context,context,'initialization does not rewrite a shared link');
});
