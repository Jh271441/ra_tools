import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { coldStart, coldStartPlugin } from '../build/coldStart.mjs';
import { takeInitialRead } from '../src/api/initialRead.ts';

const config = { base: '/sim/', flowJs: 'assets/flow-a1.js', flowCss: ['assets/flow-a1.css'] };
const boardUrl = release => '/sim/api/dashboard/workflow/board?' + new URLSearchParams({ release, refresh:'false' });
function page(path = '/sim/simulation?version=gen4-release-20261016', state = {}, fail = false) {
  const calls = [], links = [];
  const location = new URL('https://dashboard.example' + path);
  const context = { window: { __RA_SIM_STARTUP__:state }, location, URL, URLSearchParams, Date:{now:()=>1000},
    fetch(url, options) {
      calls.push({url,options});
      return fail ? Promise.reject(new Error('offline')) : Promise.resolve({ok:true,status:200,text:async()=>'{"selected":{"release":"1016"}}'});
    },
    document: {createElement:()=>({}),head:{appendChild:link=>links.push(link)}} };
  const run = (value=config) => vm.runInNewContext(`(${coldStart.toString()})(${JSON.stringify(value)})`,context);
  return { calls,links,state,run };
}

test('cold HTML starts one read before React; the application adopts it once', async () => {
  const p=page();p.run();p.run();
  assert.equal(p.calls.length,1);
  assert.equal(p.calls[0].url,boardUrl('gen4-release-20261016'));
  assert.equal(p.calls[0].options.headers['Content-Type'],'application/json');
  const read=takeInitialRead(p.state,boardUrl('gen4-release-20261016'),false,1200);
  assert.ok(read);
  assert.equal((await read).status,200);
  assert.equal(JSON.parse((await read).text).selected.release,'1016');
  assert.equal(takeInitialRead(p.state,boardUrl('gen4-release-20261016'),false,1201),undefined);
  p.run();assert.equal(p.calls.length,1);
  assert.deepEqual(p.links.map(x=>[x.rel,x.as,x.href]),[
    ['modulepreload',undefined,'https://dashboard.example/sim/assets/flow-a1.js'],
    ['preload','style','https://dashboard.example/sim/assets/flow-a1.css'],
  ]);
});

test('following the current version starts its read without loading flow assets', async () => {
  const p=page('/sim/simulation');p.run();
  assert.equal(p.calls[0].url,boardUrl('@current'));assert.equal(p.links.length,0);
  await p.state.read;
});

test('overview/issues/status and an external asset base never start speculative API reads', () => {
  for (const path of ['/sim/overview','/sim/issues','/sim/status','/manual/simulation']) {
    const p=page(path);p.run();assert.equal(p.calls.length,0);assert.equal(p.links.length,0);
  }
  const p=page();p.run({...config,base:'https://other.example/sim/'});assert.equal(p.calls.length,0);
});

test('a late bootstrap cannot duplicate an application read or a read after a mutation', () => {
  const p=page();
  assert.equal(takeInitialRead(p.state,boardUrl('gen4-release-20261016'),false,1000),undefined);
  p.run();assert.equal(p.calls.length,0);
  const afterWrite=page();takeInitialRead(afterWrite.state,'',true,1000);afterWrite.run();
  assert.equal(afterWrite.calls.length,0);
});

test('fresh reads, version changes and expired startup results discard the receipt', async () => {
  for (const [url,fresh,now] of [[boardUrl('gen4-release-20261016'),true,1200],
    [boardUrl('gen4-release-20261009'),false,1200],
    [boardUrl('gen4-release-20261016'),false,16000],
    [boardUrl('gen4-release-20261016'),false,900]]) {
    const p=page();p.run();const original=p.state.read;
    assert.equal(takeInitialRead(p.state,url,fresh,now),undefined);
    assert.equal(p.state.read,undefined);assert.equal(p.state.claimed,true);await original;
  }
});

test('an early network failure remains observable to the main application', async () => {
  const p=page(undefined,{},true);p.run();
  await assert.rejects(takeInitialRead(p.state,boardUrl('gen4-release-20261016'),false,1200),/offline/);
  assert.equal(p.calls.length,1);
});

test('release parameters remain encoded inside one same-origin read', async () => {
  const release='https://other.example/?x=1&refresh=true';
  const p=page('/sim/simulation?'+new URLSearchParams({version:release}));p.run();
  const url=new URL(p.calls[0].url,'https://dashboard.example');
  assert.equal(url.origin,'https://dashboard.example');assert.equal(url.searchParams.get('release'),release);
  assert.equal(url.searchParams.get('refresh'),'false');assert.equal(url.searchParams.getAll('refresh').length,1);
  await p.state.read;
});

test('the production HTML references a hashed standalone startup asset and resolved flow files', () => {
  const plugin=coldStartPlugin();plugin.configResolved({base:'/sim/'});
  const html={type:'asset',source:'<html><head></head></html>'};
  let emitted;
  plugin.generateBundle.handler.call({emitFile(file){emitted=file;return 'startup';},getFileName(){return 'assets/sim-startup-hash.js';}}, {}, {
    'index.html':html,flow:{type:'chunk',facadeModuleId:'/app/src/components/SimulationFlow.tsx',fileName:'assets/flow-a1.js',viteMetadata:{importedCss:new Set(['assets/flow-a1.css'])}},
  });
  assert.match(html.source,/<script async src="\/sim\/assets\/sim-startup-hash.js"><\/script>/);
  assert.match(emitted.source,/assets\/flow-a1\.js/);assert.match(emitted.source,/assets\/flow-a1\.css/);
  assert.doesNotMatch(emitted.source,/\/app\/src/);
});
