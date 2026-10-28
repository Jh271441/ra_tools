const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const nodes=new Map(),requests=[],paints=[];let now=1000;
function node(){return {textContent:'',innerHTML:'chart',hidden:false,disabled:false,attrs:{},style:{setProperty(){}},classList:{add(){}},setAttribute(k,v){this.attrs[k]=v;},replaceChildren(){this.innerHTML='';},querySelectorAll(){return [];}};}
const ctx={console,URL,URLSearchParams,AbortController,Date:{now:()=>now},Map,JSON,Math,
  document:{hidden:false},uiText:(zh,en)=>en,$:id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},
  setTimeout:()=>1,clearTimeout(){},renderVersionRD(){},enhanceNativeUiSelect(){},
  location:{href:'http://localhost/version-datasets'},history:{pushState(_,__,u){ctx.location.href=String(u);}},
  api:(url,{signal})=>new Promise((resolve,reject)=>requests.push({url,signal,resolve,reject}))};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/version-datasets.js','utf8'),ctx);
const s=vm.runInContext('versionDatasetState',ctx);
ctx.renderVersionDatasets=()=>paints.push(s.members?.mode||'pending');ctx.loadVersionDatasetBatches=()=>{};
ctx.syncVersionTEFilters=()=>{};ctx.syncVersionDatasetViews=()=>{};
s.active=true;s.dataset='A';
const catalog={items:[{id:'A',targets:10},{id:'B',targets:4}]};
const result=(mode='targets',dataset='A')=>({dataset_id:dataset,mode,total:10,items:[],rd:{total:10},count_scope:{total:10}});
const flush=()=>new Promise(setImmediate);
(async()=>{
  let load=ctx.loadVersionDatasets({force:false});
  assert.equal(requests.length,1);assert(requests[0].url.includes('include_legacy'));
  requests[0].resolve(catalog);await flush();assert.equal(requests.length,2);
  requests[1].resolve(result());await load;assert.equal(s.members.mode,'targets');
  ctx.versionDatasetChange({mode:'low'});assert.equal(requests.length,3);
  assert(requests[2].url.includes('mode=low'));assert.equal(s.chartsPending,true);
  assert.equal(ctx.$('#versionCompositionBar').innerHTML,'chart');
  assert(ctx.$('#versionDatasetLoading').textContent.includes('previous scope'));
  await ctx.loadVersionDatasets({force:false});assert.equal(requests.length,3,'same in-flight request coalesces');
  requests[2].resolve(result('low'));await flush();assert.equal(s.chartsPending,false);
  ctx.versionDatasetChange({mode:'targets'});await flush();
  assert.equal(requests.length,3,'fresh revisit is served from cache');assert.equal(s.members.mode,'targets');
  ctx.versionDatasetChange({mode:'targets'});assert.equal(requests.length,3,'same selection is a no-op');
  s.page=2;ctx.versionDatasetChange({media:'camera'});
  assert.equal(requests.length,3,'media is display-only');assert.equal(s.page,2);
  ctx.versionDatasetChange({mode:'sampled_targets'});const old=requests.at(-1);
  ctx.versionDatasetChange({mode:'excluded'});const latest=requests.at(-1);
  assert(old.signal.aborted);latest.resolve(result('excluded'));await flush();
  old.resolve(result('sampled_targets'));await flush();assert.equal(s.members.mode,'excluded');
  assert(![...s.cache.values()].some(x=>x.members.mode==='sampled_targets'));
  ctx.versionDatasetChange({mode:'waiting'});requests.at(-1).reject(new Error('offline'));await flush();
  assert(s.chartsPending);assert(ctx.$('#versionDatasetExport').hidden);
  assert(ctx.$('#versionDatasetLoading').textContent.includes('Update failed'));
  assert.equal(ctx.$('#versionTEPanel').attrs['aria-busy'],'false');
  load=ctx.loadVersionDatasets();const catalogRead=requests.at(-1);assert(catalogRead.url.includes('include_legacy'));
  catalogRead.resolve(catalog);await flush();requests.at(-1).resolve(result('waiting'));await load;
  assert.equal(s.cache.size,1);assert(!s.chartsPending);
  now+=31000;load=ctx.loadVersionDatasets({force:false});
  assert(requests.at(-1).url.includes('include_legacy'));requests.at(-1).resolve(catalog);await flush();
  requests.at(-1).resolve(result('waiting'));await load;
  ctx.versionDatasetChange({dataset:'B'});assert.equal(ctx.$('#versionCompositionBar').innerHTML,'');
  assert.equal(s.overview,null);assert(!s.chartsPending);
  requests.at(-1).resolve(result('targets','B'));await flush();assert.equal(s.members.dataset_id,'B');
  for(let i=0;i<20;i++)ctx.cacheVersionDatasetMembers(String(i),result());
  assert.equal(s.cache.size,12,'bounded cache');
  const count=requests.length;ctx.document.hidden=true;await ctx.loadVersionDatasets();assert.equal(requests.length,count);
  console.log('PASS catalog reuse, cache/TTL/force, coalescing, stale cancellation, retained charts, media-only and bounds');
})().catch(error=>{console.error(error);process.exitCode=1;});
