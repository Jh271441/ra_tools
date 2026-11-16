import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { coldStart, coldStartPlugin } from '../build/coldStart.mjs';
import { takeInitialRead, claimEvaluationInitialRead, discardInitialRead } from '../src/api/initialRead.ts';

const config = { base: '/sim/', flowJs: 'assets/flow-a1.js', flowCss: ['assets/flow-a1.css'],
  evaluationJs:'assets/evaluation-b2.js',evaluationCss:['assets/common.css'],overviewJs:'assets/overview-c3.js',overviewCss:['assets/common.css'] };
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

test('ordinary simulation retains the live release alias and version priority', () => {
  for (const query of ['release=gen4-release-20261016', 'version=gen4-release-20261016&release=ignored']) {
    const p=page('/sim/simulation?'+query);p.run();
    assert.equal(p.calls[0].url,boardUrl('gen4-release-20261016'));
  }
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

test('AutoTriage overview overlaps its exact board, profile comparison and lightweight catalogue with React download', async () => {
  const q=new URLSearchParams({basis:'auto-triage',release:'gen4-release-20261016',version:'ignored',profile:'rules+v2',date_start:'2026-10-01',date_end:'2026-10-10',release_start:'2026-09-01',platform_gen:'GEN4_PT'});
  const p=page('/sim/overview?'+q);p.run();p.run();
  assert.deepEqual(p.calls.map(call=>call.url),[
    '/sim/api/dashboard/evaluation/board?'+new URLSearchParams({release:'gen4-release-20261016',profile_id:'rules+v2',date_start:'2026-10-01',date_end:'2026-10-10',view:'metrics'}),
    '/sim/api/dashboard/evaluation/versions',
    '/sim/api/dashboard/evaluation/comparison?'+new URLSearchParams({profile_id:'rules+v2'}),
  ]);
  assert.deepEqual(p.links.map(link=>link.href),['https://dashboard.example/sim/assets/evaluation-b2.js','https://dashboard.example/sim/assets/common.css','https://dashboard.example/sim/assets/overview-c3.js']);
  for(const kind of ['board','comparison','versions']) {
    const receipt=p.state.evaluation[kind];assert.ok(await takeInitialRead(receipt,receipt.url,false,1200));
  }
});

test('AutoTriage issues prefetches only the exact issue scope and no history or issue rows', () => {
  const p=page('/sim/issues?basis=auto-triage');p.run();
  assert.deepEqual(p.calls.map(call=>call.url),['/sim/api/dashboard/evaluation/board?release=%40stable&view=metrics','/sim/api/dashboard/evaluation/versions']);
  assert.deepEqual(p.links.map(link=>link.href),['https://dashboard.example/sim/assets/evaluation-b2.js','https://dashboard.example/sim/assets/common.css']);
  const root=page('/overview?basis=auto-triage');root.run({...config,base:'/'});
  assert.equal(root.calls[0].url,'/api/dashboard/evaluation/board?release=%40current&view=metrics');
  const other=page('/sim/overview?basis=auto-triage');other.run({...config,base:'https://other.example/sim/'});
  assert.equal(other.calls.length,0);
});

test('AutoTriage receipts are independently claimed, scope checked and all discarded by mutations', async () => {
  const p=page('/sim/overview?basis=auto-triage&profile=one');p.run();
  globalThis.window={__RA_SIM_STARTUP__:p.state};
  try {
    const board=p.state.evaluation.board, comparison=p.state.evaluation.comparison;
    assert.equal(takeInitialRead(board,board.url.replace('profile_id=one','profile_id=two'),false,1200),undefined);
    assert.ok(await takeInitialRead(comparison,comparison.url,false,1200));
    assert.equal(p.state.evaluation.versions.claimed,undefined,'claiming another slot preserves catalogue');
    discardInitialRead();
    assert.equal(p.state.evaluation.versions.read,undefined);
    p.run();assert.equal(p.calls.length,3,'late bootstrap cannot restart discarded reads');
    assert.equal(claimEvaluationInitialRead('versions','/sim/api/dashboard/evaluation/versions'),undefined);
  } finally { delete globalThis.window; }
});

test('the production HTML references a hashed standalone startup asset and resolved flow files', () => {
  const plugin=coldStartPlugin();plugin.configResolved({base:'/sim/'});
  const html={type:'asset',source:'<html><head></head></html>'};
  let emitted;
  plugin.generateBundle.handler.call({emitFile(file){emitted=file;return 'startup';},getFileName(){return 'assets/sim-startup-hash.js';}}, {}, {
    'index.html':html,flow:{type:'chunk',facadeModuleId:'/app/src/components/SimulationFlow.tsx',fileName:'assets/flow-a1.js',viteMetadata:{importedCss:new Set(['assets/flow-a1.css'])}},
    evaluation:{type:'chunk',facadeModuleId:'/app/src/components/EvaluationWorkspace.tsx',fileName:'assets/evaluation-b2.js',viteMetadata:{importedCss:new Set(['assets/common.css'])}},
    overview:{type:'chunk',facadeModuleId:'/app/src/components/Overview.tsx',fileName:'assets/overview-c3.js',viteMetadata:{importedCss:new Set(['assets/common.css'])}},
  });
  assert.match(html.source,/<script async src="\/sim\/assets\/sim-startup-hash.js"><\/script>/);
  assert.match(emitted.source,/assets\/flow-a1\.js/);assert.match(emitted.source,/assets\/flow-a1\.css/);
  assert.match(emitted.source,/assets\/evaluation-b2\.js/);assert.match(emitted.source,/assets\/overview-c3\.js/);
  assert.doesNotMatch(emitted.source,/\/app\/src/);
});
