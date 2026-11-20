import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LiveView, ViewCache, pollVisible } from '../src/lib/liveView.ts';
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('returning to a version displays its cache but requires a new receipt before writes', async () => {
  const cache = new ViewCache();
  const pending = [];
  const view = new LiveView('1016', cache, key => { const d = deferred(); pending.push({ key, ...d }); return d.promise; });
  const first = view.reload(); await flush();
  const original = { release: '1016', progress: 23 };
  pending[0].resolve(original); await first;
  assert.equal(view.getSnapshot().verified, true);
  view.select('1009'); assert.equal(view.getSnapshot().data, null);
  const old = view.reload(); await flush();
  view.select('1016');
  assert.equal(view.getSnapshot().data, original);
  assert.equal(view.getSnapshot().verified, false);
  const latest = view.reload(); await flush();
  pending[1].resolve({ release:'1009' }); await old;
  assert.equal(view.getSnapshot().key, '1016');
  assert.equal(view.getSnapshot().verified, false);
  pending[2].resolve({ ...original }); await latest;
  assert.equal(view.getSnapshot().data, original, 'unchanged data keeps graph prop identity');
  assert.equal(view.getSnapshot().verified, true);
});

test('a failed read keeps known progress visible with writes disabled', async () => {
  const cache = new ViewCache(); cache.put('1016', { progress: 60 });
  const view = new LiveView('1016', cache, async () => { throw new Error('HTTP 504'); });
  assert.equal(await view.reload(), null);
  assert.deepEqual(view.getSnapshot().data, { progress:60 });
  assert.equal(view.getSnapshot().verified, false);
  assert.equal(view.getSnapshot().error, 'HTTP 504');
});

test('a mutation invalidates every display and rejects reads started before it', async () => {
  const cache = new ViewCache(); cache.put('1009', {}); cache.put('1016', { old:true });
  const pending = [];
  const view = new LiveView('1016', cache, (key, options) => { const d=deferred(); pending.push({ options,...d }); return d.promise; });
  const before = view.reload(); await flush();
  assert.equal(view.reload(), before, 'poll/manual readers share one in-flight read');
  view.invalidate();
  assert.equal(cache.get('1009'), null);
  const after = view.reload({fresh:true}); await flush();
  pending[0].resolve({ old:true }); await before;
  assert.equal(view.getSnapshot().verified, false);
  pending[1].resolve({ old:false }); await after;
  assert.deepEqual(view.getSnapshot().data, {old:false});
  assert.deepEqual(pending[1].options, {fresh:true});
});

test('manual force read supersedes a pending poll rather than accepting its old receipt', async () => {
  const pending=[];const view=new LiveView('1016',new ViewCache(),(key,options)=>{const d=deferred();pending.push({options,...d});return d.promise;});
  const poll=view.reload();await flush();const force=view.reload({force:true});await flush();
  pending[1].resolve({progress:80});await force;pending[0].resolve({progress:60});await poll;
  assert.deepEqual(view.getSnapshot().data,{progress:80});
  assert.deepEqual(pending[1].options,{force:true});
});

test('snapshot retention has a TTL and bound, and a changed result replaces the old reference', () => {
  let now=0;const cache=new ViewCache(100,2,()=>now);
  const a=cache.put('a',{count:1});assert.equal(cache.put('a',{count:1}),a);
  assert.notEqual(cache.put('a',{count:2}),a);
  cache.put('b',{});cache.put('c',{});assert.equal(cache.get('a'),null);
  now=100;assert.equal(cache.get('b'),null);assert.equal(cache.get('c'),null);
});

function environment(hidden=false) {
  let listener;let id=0;const timers=new Map();
  return { timers, env:{hidden:()=>hidden,listen:fn=>{listener=fn;return()=>{listener=null;};},schedule:(fn,delay)=>{timers.set(++id,{fn,delay});return id;},clear:key=>timers.delete(key)},
    visible(value){hidden=!value;listener?.();}, async next(){const [key,{fn,delay}]=timers.entries().next().value;timers.delete(key);fn();await flush();return delay;}};
}
test('hidden pages make no reads, visibility resume never overlaps, and cleanup leaves no timer', async () => {
  const clock=environment(true);let calls=0;const d=deferred();
  const stop=pollVisible(()=>{calls++;return d.promise;},()=>false,clock.env);
  assert.equal(calls,0);clock.visible(true);assert.equal(calls,1);
  clock.visible(false);clock.visible(true);assert.equal(calls,1);
  clock.visible(false);d.resolve({});await flush();assert.equal(clock.timers.size,0);
  clock.visible(true);await flush();assert.equal(calls,2);assert.equal(clock.timers.size,1);
  stop();assert.equal(clock.timers.size,0);clock.visible(true);assert.equal(clock.timers.size,0);
});
test('progress-refresh fast polling is bounded and ordinary results use 30 seconds', async () => {
  const clock=environment();let refreshing=true;
  const stop=pollVisible(async()=>({refreshing}),v=>v.refreshing,clock.env);await flush();
  assert.equal(await clock.next(),5000);assert.equal(await clock.next(),5000);assert.equal(await clock.next(),5000);
  assert.equal(await clock.next(),30000);refreshing=false;assert.equal(await clock.next(),30000);
  assert.equal([...clock.timers.values()][0].delay,30000);stop();
});
