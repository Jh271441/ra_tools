// Isolated full-frontend regression. Requires Playwright in NODE_PATH; never contacts production.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../..'),staticDir=path.join(root,'ra_triage_dashboard/static');
const report=process.env.CRON_PERFORMANCE_REPORT_DIR; if(report)fs.mkdirSync(report,{recursive:true});
const fixture={observed_at:Date.now()/1000,sources:{overview:'ready'},overview:{collected_at:Date.now()/1000,daily:{health:'success',runs:[{id:'daily-2026-10-20',target_date_cst:'2026-10-20',state:'complete',health:'success',selected:10,inferred:10,published:10,verified:10,skipped:0}],jobs:[]}},history:[],sidecar:null,media_daily:null};
const versionQA=process.env.CRON_VERSION_QA==='1';
if(versionQA){
 const families=['20261009','20261016','20261023'];
 fixture.incremental={enabled:true,updated_at:Date.now()/1000,stale:false,families,states:{published:60},
  media:{selected:15,verified:12},discovery_schedule:{hours:[7,19]},
  versions:families.map((family,i)=>({family,states_status:'ready',states:{published:(i+1)*10,waiting_metadata:3},media:{selected:3+i*2,verified:2+i*2,queued:1,reused:0,failure_count:0}})),
  datasets:families.map((release_family,i)=>({release_family,targets:3+i*2,assigned:{tester:3+i*2}})),
  increments:{status:'ready',items:families.map(family=>({family,start_at:1793314800,new:0,filled:0,published:0,target_added:0,target_removed:0,scan_state:'success'}))}};
 fixture.closeup={state:'collecting',versions:{'1009':{verified:8},'1016':{verified:18},'1023':{verified:28}}};
}
let blockedConfig=[],requests=[],writes=[];
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost'); requests.push({path:u.pathname,at:Date.now()});
 if(req.method!=='GET'){writes.push(req.method+' '+u.pathname);res.writeHead(405).end();return;}
 const json=value=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(value));};
 if(u.pathname==='/manual/api/dashboard-config'){blockedConfig.push(()=>json({baselines:[{id:'0508',label:'0508',scope:'0508',issue_count:10}],default_baseline_ids:['0508'],tag_catalog:[]}));return;}
 if(u.pathname==='/manual/api/daily-cron') return json(fixture);
 if(u.pathname==='/manual/api/session')return json({authenticated:false,browser_lca_fallback:false,can_write:false,read_only:true});
 if(u.pathname.startsWith('/manual/api/'))return json({items:[],issues:10,revision:0,poll_after_ms:30000});
 if(u.pathname.startsWith('/manual/static/')){
  const file=path.join(staticDir,u.pathname.slice('/manual/static/'.length));
  if(!file.startsWith(staticDir+'/')){res.writeHead(403).end();return;}
  if(!fs.existsSync(file)){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'application/octet-stream');res.end(fs.readFileSync(file));return;
 }
 res.setHeader('Content-Type','text/html');res.end(fs.readFileSync(path.join(staticDir,'index.html'),'utf8').replaceAll('{{RA_TRIAGE_BASE_PATH}}','/manual'));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try{
 const results=[];
 const combinations=versionQA?[1440,390,320].flatMap(w=>['zh','en'].flatMap(l=>['dark','light'].map(t=>[w,l,t]))):[[1440,'zh','dark'],[390,'en','light'],[320,'en','light']];
 for(const [width,lang,theme] of combinations){
 const context=await browser.newContext({viewport:{width,height:1000}});
 await context.addInitScript(({lang,theme})=>{localStorage.setItem('ra-triage-ui-language',lang);localStorage.setItem('ra-triage-color-theme',theme);},{lang,theme});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));requests=[];blockedConfig=[];
 const started=Date.now();await page.goto(`http://127.0.0.1:${server.address().port}/manual/daily-cron?baselines=0508,0206,0626,0522,0821,0821-review-extra,1009-2026-10-15,review-2026-10-15-extra,1009-2026-10-16,review-2026-10-16-extra,1009-2026-10-17,review-2026-10-18,review-2026-10-18-extra,review-2026-10-19,review-2026-10-20`,{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelectorAll('#dailyCronGraph .cron-dag-task').length>0,{timeout:15000});
 const ready=Date.now()-started;
 assert.ok(blockedConfig.length,'config must still be pending at graph paint');
 assert.equal(requests.some(r=>r.path.endsWith('/model-runs')),false,'graph must paint before Runs start');
 const count=requests.filter(r=>r.path.endsWith('/daily-cron')).length;assert.equal(count,2); // HTML + API
 const bounds=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));assert.ok(bounds.scroll<=width+1,JSON.stringify(bounds));
 for(const resolve of blockedConfig.splice(0))resolve();
 await page.waitForFunction(()=>state.config!==null && Array.isArray(state.config.baselines));
 await page.waitForTimeout(500);
 assert.equal(requests.filter(r=>r.path==='/manual/api/daily-cron').length,1,'bootstrap must reuse snapshot');
 if(versionQA){
  const control=page.locator('.cron-scope-control .ui-select-trigger');
  assert.equal(await page.locator('#dailyCronRunDate').inputValue(),'version:20261023');
  assert.match(await page.locator('#dailyCronMainValue').textContent(),/1023.*30 \/ 30/);
  await control.click();
  await page.locator('.cron-scope-control [data-ui-select-value="version:20261009"]').click();
  assert.match(await page.locator('#dailyCronMainValue').textContent(),/1009.*10 \/ 10/);
  assert.equal((await page.locator('#dailyCronMediaValue').textContent()).trim(),'2 / 3');
  assert.ok((await page.locator('#dailyCronCloseupValue').textContent()).includes('1009'));
  assert.ok(!(await page.locator('#dailyCronCloseupValue').textContent()).includes('1016'));
  assert.ok(!(await page.locator('#dailyCronIncrementRows').textContent()).includes('1023'));
  assert.match(page.url(),/cron_version=20261009/);
  await control.click();await page.keyboard.press('Escape');assert.equal(await control.getAttribute('aria-expanded'),'false');
  await control.click();await page.locator('#dailyCronScopeNote').click();assert.equal(await control.getAttribute('aria-expanded'),'false');
  await control.focus();await page.keyboard.press('ArrowUp');await page.keyboard.press('Enter');
  assert.equal(await page.locator('#dailyCronRunDate').inputValue(),'version:20261016');
  await control.click();await page.locator('.cron-scope-control [data-ui-select-value="version:20261009"]').click();
  await page.evaluate(()=>{dailyCronState.data.incremental.families.push('20261030');renderDailyCron();});
  assert.equal(await page.locator('#dailyCronRunDate').inputValue(),'version:20261009');
  await page.locator('#languageToggleButton').dispatchEvent('click');
  assert.equal(await page.locator('#dailyCronRunDate').inputValue(),'version:20261009');
  await page.locator('#languageToggleButton').dispatchEvent('click');
  // Unknown snapshots cannot show another version's counts or a false success.
  await page.evaluate(()=>{const v=dailyCronState.data.incremental.versions[0];v.states_status='unavailable';renderDailyCron();});
  assert.match(await page.locator('#dailyCronMainValue').textContent(),/— \/ —/);
  assert.equal((await page.locator('#dailyCronMediaValue').textContent()).trim(),'2 / 3');
  await page.evaluate(()=>{dailyCronState.data.incremental.versions[0].states_status='ready';renderDailyCron();});
  const b=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));assert.ok(b.scroll<=width+1,JSON.stringify(b));
  if(width<640){const box=await control.boundingBox();assert.ok(box.height>=44);}
  await control.click();
  const panel=page.locator('.cron-scope-control .ui-select-panel');const pb=await panel.boundingBox();
  assert.ok(pb.x>=0&&pb.x+pb.width<=width+1,'picker fits viewport');await page.keyboard.press('Escape');
  if(width===1440&&lang==='zh'&&theme==='dark'){
   await page.reload({waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>document.querySelector('#dailyCronRunDate')?.value==='version:20261009');
   for(const resolve of blockedConfig.splice(0))resolve();
   await page.waitForFunction(()=>state.config!==null && Array.isArray(state.config.baselines));
   assert.match(await page.locator('#dailyCronMainValue').textContent(),/1009.*10 \/ 10/);
  }
  await page.waitForFunction(()=>[...document.querySelectorAll('#dailyCronGraph .cron-dag-task')].some(el=>el.textContent.includes('10 / 10')));
 }
 if(report)await page.screenshot({path:path.join(report,`cron-${width}-${lang}-${theme}.png`),fullPage:false});
 assert.deepEqual(errors,[]);results.push({width,lang,theme,graphWhileConfigBlockedMs:ready,bounds,errors});await context.close();
 }
 assert.deepEqual(writes,[]);if(report)fs.writeFileSync(path.join(report,'browser.json'),JSON.stringify({results,writes},null,2));console.log(JSON.stringify(results));
 }finally{await browser.close();for(const resolve of blockedConfig.splice(0))resolve();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
