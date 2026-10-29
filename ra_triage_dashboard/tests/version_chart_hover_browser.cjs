/* Actual modules, synthetic data, no business API or writes. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'),source=fs.readFileSync(path.join(root,'index.html'),'utf8');
const styles=[...source.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m=>m[1]);
const modules=['core-base','i18n-messages','i18n','format-api','daily-review','version-datasets','version-rd'];
const html=source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replaceAll('{{RA_TRIAGE_BASE_PATH}}','')
 .replace('</head>',styles.map(p=>`<link rel="stylesheet" href="/static/${p}">`).join('')+'</head>')
 .replace('</body>',modules.map(p=>`<script src="/static/js/${p}.js"></script>`).join('')+'</body>');
const server=http.createServer((req,res)=>{
 const p=new URL(req.url,'http://localhost').pathname;
 if(req.method!=='GET')return res.writeHead(405).end();
 if(!p.startsWith('/static/'))return res.setHeader('Content-Type','text/html'),res.end(html);
 const file=path.resolve(root,p.slice(8));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
 res.setHeader('Content-Type',file.endsWith('.css')?'text/css':'text/javascript');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 let browser;
 try{
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage(),errors=[],apiRequests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/'))apiRequests.push(r.url());});
  await page.goto(`http://127.0.0.1:${server.address().port}/version-datasets`);
  await page.evaluate(()=>{
   state.activePage='version-datasets';state.uiLanguage='zh';document.body.dataset.activePage='version-datasets';
   document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.id!=='versionDatasetsPage'));
   document.querySelectorAll('.topbar,.sidebar,#versionDatasetSummary,.version-filter-panel,.version-composition,.version-gallery,.version-history').forEach(p=>p.hidden=true);
   document.querySelector('.app-frame').style.display='block';
   document.querySelector('#versionDatasetsPage').style.padding='12px';
   window.hoverData={dataset:{historical:false},snapshot_revision:'test',te:{summary:{total:100,filled:60,unfilled:30,unknown:10},source_status:'ready',distribution:[{value:'误触发',count:30},{value:'成功',count:20},{value:'无需协助',count:10}],daily:[{date:'2026-10-20',summary:{total:100,filled:60,unfilled:30,unknown:10,rate:.6}}]}};
   window.hoverRD={total:100,completed:60,pending:30,conflict:10,distribution:{'正确触发':30,'误触发':20,'无需协助':10}};
   window.renderHover=()=>{renderVersionTE(hoverData);renderVersionRD(hoverRD);};
   renderHover();
   enhanceDashboardSelects(document);
  });
  const opacity=async selector=>Number(await page.locator(selector).evaluate(el=>getComputedStyle(el).opacity));
  const progress='.version-rd-block:first-child',mix='.version-rd-block:last-child';
  const checks=[];
  for(const width of [1440,390,320])for(const lang of ['zh','en'])for(const theme of ['dark','light']){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(({lang,theme})=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;renderHover();},{lang,theme});
   await page.mouse.move(0,0);
   const before=await page.evaluate(()=>JSON.stringify(versionDatasetState));
   await page.locator(mix+' .version-rd-category[data-chart-key="rd-false"]').hover();
   await page.waitForTimeout(170);
   assert.equal(await opacity(mix+' .version-rd-stack [data-chart-key="rd-false"]'),1);
   assert.ok(await opacity(mix+' .version-rd-stack [data-chart-key="rd-correct"]')<.5);
   assert.equal(await opacity(progress+' .version-rd-track [data-chart-key="filled"]'),1,'card-local only');
   await page.locator(mix+' .version-rd-stack [data-chart-key="rd-correct"]').hover();
   await page.waitForTimeout(170);
   assert.equal(await opacity(mix+' .version-rd-category[data-chart-key="rd-correct"]'),1);
   assert.ok(await opacity(mix+' .version-rd-category[data-chart-key="rd-false"]')<.5);
   await page.mouse.move(0,0);await page.waitForTimeout(170);
   assert.equal(await opacity(mix+' .version-rd-stack [data-chart-key="rd-false"]'),1,'leave resets');
   await page.locator('#versionTEStatusChart [data-chart-key="unfilled"]').hover();await page.waitForTimeout(170);
   assert.equal(await opacity('#versionTERing [data-chart-key="unfilled"]'),1);
   assert.ok(await opacity('#versionTERing [data-chart-key="filled"]')<.5);
   // Hover a point on the 60%-filled arc, not its SVG bounding box center.
   const ring=await page.locator('#versionTERing').boundingBox();
   await page.mouse.move(ring.x+ring.width-5,ring.y+ring.height/2);await page.waitForTimeout(170);
   assert.equal(await opacity('#versionTEStatusChart [data-chart-key="filled"]'),1);
   assert.ok(await opacity('#versionTEStatusChart [data-chart-key="unfilled"]')<.5);
   await page.mouse.move(0,0);
   await page.locator('#versionTEDistribution .version-result-row').first().hover();await page.waitForTimeout(170);
   assert.equal(await opacity('#versionTEDistribution .version-result-row:first-child'),1);
   assert.ok(await opacity('#versionTEDistribution .version-result-row:last-child')<.5);
   await page.locator('#versionTEDailyChart .te-day').hover();
   assert.notEqual(await page.locator('#versionTEDailyChart .te-day').evaluate(el=>getComputedStyle(el).boxShadow),'none');
   await page.mouse.move(0,0);
   await page.keyboard.press('Tab');
   await page.locator(progress+' .version-rd-category[data-chart-key="conflict"]').focus();await page.waitForTimeout(170);
   assert.equal(await opacity(progress+' .version-rd-track [data-chart-key="conflict"]'),1);
   assert.ok(await opacity(progress+' .version-rd-track [data-chart-key="filled"]')<.5);
   await page.evaluate(()=>{window.savedFocus=document.activeElement;renderVersionRD(hoverRD);});
   assert.ok(await page.evaluate(()=>document.activeElement===savedFocus),'unchanged poll keeps focused node');
   await page.evaluate(()=>{hoverRD.pending=29;hoverRD.conflict=11;renderVersionRD(hoverRD);});
   assert.equal(await page.evaluate(()=>document.activeElement.dataset.chartKey),'conflict','changed counts keep focus');
   await page.evaluate(()=>document.activeElement.blur());
   assert.equal(await page.evaluate(()=>JSON.stringify(versionDatasetState)),before,'hover/focus must not filter');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no page overflow');
   if(width<640)assert.ok(await page.locator(mix+' .version-rd-category').first().evaluate(el=>el.getBoundingClientRect().height>=44));
   await page.locator('#versionTEStatusChart [data-chart-key="filled"]').focus();
   await page.evaluate(()=>{window.savedTEFocus=document.activeElement;renderVersionTE(hoverData);});
   assert.ok(await page.evaluate(()=>document.activeElement===savedTEFocus),'TE polling preserves focused node');
   await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';renderVersionTE(hoverData);});
   assert.equal(await page.evaluate(()=>document.activeElement.dataset.chartKey),'filled','TE locale retains focus');
   await page.evaluate(lang=>{state.uiLanguage=lang;renderVersionTE(hoverData);document.activeElement.blur();},lang);
   if(width===320&&lang==='en'&&theme==='light')await page.locator('#versionDatasetsPage').screenshot({path:'/private/tmp/version-chart-hover-mobile.png'});
   checks.push({width,lang,theme});
  }
  await page.setViewportSize({width:1440,height:900});
  await page.evaluate(()=>{state.uiLanguage='zh';document.documentElement.dataset.uiLang='zh';document.documentElement.dataset.colorTheme='dark';renderHover();});
  await page.locator(mix+' .version-rd-category[data-chart-key="rd-false"]').hover();await page.waitForTimeout(180);
  await page.locator('#versionDatasetsPage').screenshot({path:'/private/tmp/version-chart-hover.png'});
  await page.mouse.move(0,0);
  await page.evaluate(()=>{hoverRD.distribution={'正确触发':60,'误触发':0,'无需协助':0};renderVersionRD(hoverRD);});
  assert.equal(await page.locator(mix+' .version-rd-stack [data-chart-key]').count(),1,'no fabricated zero segments');
  assert.equal(await page.locator(mix+' .version-rd-category').count(),3);
  for(const status of ['empty','error','loading','unsupported']){
   await page.evaluate(status=>renderVersionRD(status==='empty'?{total:0}:status==='unsupported'?{source_status:'unsupported'}:null,status==='error'),status);
   assert.equal(await page.locator('#versionRDPanel [data-chart-key]').count(),0);
  }
  await page.evaluate(()=>{hoverData.te.summary={total:0,filled:0,unfilled:0,unknown:0};hoverData.te.distribution=[];renderVersionTE(hoverData);});
  assert.equal(await page.locator('#versionTERing [data-chart-key]').count(),0);
  assert.equal(await page.locator('#versionTERate').textContent(),'—');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.evaluate(()=>renderVersionRD(hoverRD));
  assert.equal(await page.locator(mix+' .version-rd-category').first().evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
  assert.deepEqual(apiRequests,[]);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:checks.length,checks,screenshot:'/private/tmp/version-chart-hover.png'}));
 }finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
