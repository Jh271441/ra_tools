const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const elements=new Map();const el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,value:0,replaceChildren(){},classList:{toggle(){}}});return elements.get(id);};
let pending=[],renders=0;
const ctx={URLSearchParams,AbortController,Set,Map,console,location:{pathname:'/manual/daily-review',search:'?dataset=1009&date=2026-10-19&te_status=filled'},
 state:{activePage:'daily-review',media:{requestSeq:0}},document:{hidden:false},$:el,uiText:x=>x,
 capturePageContext:()=>({url:ctx.location.search}),isPageContextCurrent:c=>c.url===ctx.location.search&&ctx.state.activePage==='daily-review',
 clearTimeout(){},setTimeout(){return 1;},URL:{revokeObjectURL(){}},api:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))};
vm.createContext(ctx);vm.runInContext(source,ctx);vm.runInContext('renderDailyReview=()=>recordRender();dailyReviewState.active=true;',ctx);ctx.recordRender=()=>renders++;
(async()=>{
 assert.equal(vm.runInContext('dailyReviewRouteOptions().te_status',ctx),'filled');
 const first=vm.runInContext('loadDailyReview()',ctx);
 ctx.location.search='?dataset=0821';const second=vm.runInContext('loadDailyReview()',ctx);
 assert.equal(pending[0].options.signal.aborted,true);
 pending[1].resolve({scope:{dataset:'0821'},snapshot_revision:'new'});await second;
 pending[0].resolve({scope:{dataset:'1009'},snapshot_revision:'old'});await first;
 assert.equal(vm.runInContext('dailyReviewState.data.scope.dataset',ctx),'0821');assert.equal(renders,1);
 const third=vm.runInContext('loadDailyReview()',ctx);vm.runInContext('setDailyReviewActive(false)',ctx);ctx.state.activePage='review';
 assert.equal(pending[2].options.signal.aborted,true);pending[2].resolve({scope:{dataset:'1009'}});await third;assert.equal(renders,1);
 ctx.state.activePage='daily-review';ctx.document.hidden=true;vm.runInContext('dailyReviewState.active=true',ctx);await vm.runInContext('loadDailyReview()',ctx);assert.equal(pending.length,3);
 console.log('TE UI: scope race, request cancellation, leave guard, hidden polling and route restoration passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
