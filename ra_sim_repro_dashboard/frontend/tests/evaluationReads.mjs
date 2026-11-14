import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createComparisonReader, createRevisionObserver, evaluationParams, evaluationScope, matchingComparison } from '../src/lib/evaluationReads.ts';

const ctx={release:'gen4-release-20261016',profile_id:'rules+v2',date_start:'2026-10-01',date_end:'2026-10-10'};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};

test('board scopes preserve release, profile and exact sample dates with stable startup encoding',()=>{
  assert.equal(evaluationScope(ctx),new URLSearchParams(ctx).toString());
  assert.equal(evaluationScope({date_end:ctx.date_end,date_start:ctx.date_start,profile_id:ctx.profile_id,release:ctx.release}),evaluationScope(ctx));
  assert.equal(evaluationParams({release:'@current',profile_id:undefined}).toString(),'release=%40current');
  assert.notEqual(evaluationScope(ctx),evaluationScope({...ctx,date_end:'2026-10-11'}));
  assert.notEqual(evaluationScope(ctx),evaluationScope({...ctx,profile_id:'other'}));
});

test('retained history never paints a previous rule profile while a new request is pending',()=>{
  const result={requestedProfile:'old',value:{profile:{id:'old'},versions:[]}};
  assert.equal(matchingComparison(result,'new'),undefined);
  assert.equal(matchingComparison(result,undefined),undefined,'an unspecified/default profile must be resolved anew');
  assert.equal(matchingComparison(result,'old'),result.value);
  const canonical={requestedProfile:undefined,value:{profile:{id:'resolved-default'},versions:[]}};
  assert.equal(matchingComparison(canonical,'resolved-default'),canonical.value);
  assert.equal(matchingComparison(canonical,undefined),canonical.value);
});

test('canonicalizing the default profile reuses one pending or completed comparison after proving its profile',async()=>{
  for(const completed of [false,true]) {
    const calls=[],pending=deferred(),result={profile:{id:'rules+v2'},versions:[]};
    const read=createComparisonReader(profile=>{calls.push(profile);return pending.promise;});
    const initial=read(undefined,0);
    if(completed){pending.resolve(result);await initial;}
    const canonical=read('rules+v2',0);
    pending.resolve(result);
    assert.equal(await canonical,result);assert.equal(await initial,result);
    assert.deepEqual(calls,[undefined]);
    assert.equal(await read('rules+v2',0),result);
  }
});

test('a default profile response cannot satisfy another selected profile',async()=>{
  const calls=[];
  const read=createComparisonReader(async profile=>{calls.push(profile);return{profile:{id:profile||'default'},versions:[]};});
  await read(undefined,0);const value=await read('specific',0);
  assert.equal(value.profile.id,'specific');assert.deepEqual(calls,[undefined,'specific']);
  await read('another',0);assert.deepEqual(calls,[undefined,'specific','another']);
});

test('comparison errors remain visible and explicit retries issue a new read',async()=>{
  const calls=[];
  const read=createComparisonReader(async profile=>{calls.push(profile);if(calls.length===1)throw Error('HTTP 504');return{profile:{id:profile},versions:[]};});
  await assert.rejects(read('rules',0),/HTTP 504/);
  await assert.rejects(read('rules',0),/HTTP 504/);
  assert.equal((await read('rules',1)).profile.id,'rules');
  assert.deepEqual(calls,['rules','rules']);
});

test('comparison canonicalization receipts expire and navigation invalidations refresh history',async()=>{
  let now=0;const calls=[];
  const read=createComparisonReader(async profile=>{calls.push(profile);return{profile:{id:profile||'rules'},versions:[]};},()=>now);
  await read(undefined,0);await read('rules',0);assert.equal(calls.length,1);
  await read('rules',1);assert.equal(calls.length,2,'real navigation or a changed revision supplies a new attempt');
  now=30_000;await read('rules',1);assert.equal(calls.length,3,'expired receipts never serve a later visit indefinitely');
});

test('initial hydration and release switching do not reload all history; later revisions invalidate it',()=>{
  const changed=createRevisionObserver();
  assert.equal(changed(ctx,'first'),false);
  assert.equal(changed(ctx,'first'),false);
  assert.equal(changed({...ctx,release:'later'},'later-first'),false);
  assert.equal(changed(ctx,'recomputed'),true);
  assert.equal(changed(ctx,null),true);
  assert.equal(changed(ctx,'recomputed-again'),true);
  assert.equal(changed({...ctx,date_end:'2026-10-11'},'different-scope'),false);
});
