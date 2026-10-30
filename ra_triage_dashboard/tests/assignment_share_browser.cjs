/* Actual shell/modules, synthetic task data, isolated clipboard, no business writes. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'),source=fs.readFileSync(path.join(root,'index.html'),'utf8');
const styles=[...source.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m=>m[1]);
const modules=fs.readFileSync(path.join(root,'js/MANIFEST'),'utf8').split('\n').map(s=>s.trim()).filter(s=>s&&!s.startsWith('#')&&s!=='bind-bootstrap.js');
const html=source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replaceAll('{{RA_TRIAGE_BASE_PATH}}','/manual')
 .replace('</head>',styles.map(p=>`<link rel="stylesheet" href="/static/${p}">`).join('')+'</head>')
 .replace('</body>',modules.map(p=>`<script src="/static/js/${p}"></script>`).join('')+'</body>');
const server=http.createServer((req,res)=>{
 const p=new URL(req.url,'http://localhost').pathname;
 if(req.method!=='GET')return res.writeHead(405).end();
 if(!p.startsWith('/static/'))return res.setHeader('Content-Type','text/html'),res.end(html);
 const file=path.resolve(root,p.slice(8));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file))return res.writeHead(404).end();
 res.setHeader('Content-Type',file.endsWith('.css')?'text/css':'text/javascript');res.end(fs.readFileSync(file));
});
async function init(page,lang,theme){
 await page.evaluate(async({lang,theme})=>{
  window.copiedLinks=[];window.manualLinks=[];
  Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>copiedLinks.push(text)},configurable:true});
  window.prompt=(label,value)=>{manualLinks.push({label,value});return null};
  state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;
  state.session={username:'jasperchen',verified:true,access_role:'writer',is_admin:false,identity_pending:false};
  state.modelRuns=[{id:'run1009',name:'1009'}];
  const member={username:'liangxianghui',assigned_count:20,completed_count:0,pending_count:20,completion_ratio:0};
  const base={model_run_id:'run1009',workflow_mode:'model_review_and_case_label',is_current:true,lifecycle:'active',total_count:20,assignment_count:20,completed_count:0,pending_count:20,members:[member],created_at:'2026-10-30T04:17:24Z',baseline_ids:['version-20261009'],filter_snapshot:{},page:3,page_count:5,changes:[],items:[{issue_id:'cn37071761',assignee:'liangxianghui',submitted:false,assignment_kind:'base'}]};
  window.tasks=[{...base,split_id:'campaign-905dd0d5a4144f589ea72b6c69b101ef',campaign_name:'1009 TE/RD 差异联合复核 / Combined disagreement review'},
   {...base,split_id:'campaign-version',appendable:true,release_family:'20261009',updated_at:'2026-10-30T04:17:24Z'},
   {...base,split_id:'campaign-history',campaign_name:'历史任务 / Historical task',is_current:false,lifecycle:'superseded'}];
  window.taskRequests=[];
  api=async p=>{
   taskRequests.push(p);const u=new URL(p,location.origin);
   if(u.pathname==='/api/cases/work-splits')return {items:tasks,metrics:{}};
   const id=decodeURIComponent(u.pathname.split('/').at(-1));
   const task=tasks.find(t=>t.split_id===id);if(!task)throw Error('Unknown fixture task');
   return {...task,page:Number(u.searchParams.get('page')||1)};
  };
  showToast=(text,error)=>{window.lastToast={text,error}};
  restoreReviewAllocationDraft=async()=>{};
  showPage('review-assignments',{loadPageData:false});
  bindReviewAssignmentsPage();bindMobileWorkbench();
  const splitId=new URLSearchParams(location.search).get('split')||'';
  await loadReviewAssignments({splitId});
 },{lang,theme});
}
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;
 try{
  browser=await chromium.launch({headless:true});
  const results=[],errors=[];
  const base=`http://127.0.0.1:${server.address().port}`;
  const task='campaign-905dd0d5a4144f589ea72b6c69b101ef';
  for(const width of [320,390,1440])for(const lang of ['zh','en'])for(const theme of ['dark','light']){
   const page=await browser.newPage({viewport:{width,height:1000}});page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base+`/manual/review-assignments?lifecycle=current&split=${task}&assignee=liangxianghui&status=pending&q=cn37&page=3&page_size=20`);
   await init(page,lang,theme);
   assert.equal(await page.evaluate(()=>state.reviewAssignments.page),3,'shared page must survive list loading');
   await page.evaluate(lang=>{applyUiLanguage(lang==='zh'?'en':'zh');applyUiLanguage(lang)},lang);
   assert.equal(await page.evaluate(()=>state.reviewAssignments.assignee),'liangxianghui','language preserves detail filter');
   const expected=lang==='zh'?'复制链接':'Copy link';
   assert.equal(await page.locator('#reviewAssignmentDetailShare').innerText(),expected);
   await page.locator('#reviewAssignmentDetailShare').focus();await page.keyboard.press('Enter');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'detail has no overflow');
   const shared=await page.evaluate(()=>copiedLinks.at(-1));
   const url=new URL(shared);assert.equal(url.pathname,'/manual/review-assignments');
   for(const [k,v] of Object.entries({split:task,assignee:'liangxianghui',status:'pending',q:'cn37',page:'3',page_size:'20'}))assert.equal(url.searchParams.get(k),v,k);
   // A fresh page and user state restore the full shared detail view.
   await page.goto(shared);await init(page,lang,theme);
   assert.equal(await page.evaluate(()=>state.reviewAssignments.assignee),'liangxianghui');
   assert.equal(await page.locator('#reviewAssignmentPageState').innerText(),'3 / 5');
   await page.locator('[data-share-review-assignment="campaign-version"]').click();
   const version=new URL(await page.evaluate(()=>copiedLinks.at(-1)));
   assert.equal(version.searchParams.get('split'),'campaign-version');
   for(const k of ['assignee','status','q','page','page_size','assigned_to_me'])assert.equal(version.searchParams.has(k),false,k);
   await page.locator('[data-share-review-assignment="campaign-history"]').click();
   assert.equal(new URL(await page.evaluate(()=>copiedLinks.at(-1))).searchParams.get('split'),'campaign-history');
   if(width===320&&lang==='en'&&theme==='light')await page.screenshot({path:'/tmp/assignment-share-detail-320-en-light.png',fullPage:true});
   await page.evaluate(()=>{const b=document.createElement('button');b.id='mirrorShare';b.dataset.shareReviewAssignment='campaign-version';b.textContent='Mirror link';document.querySelector('#reviewAssignmentsPage').append(b)});
   await page.locator('#mirrorShare').click();assert.equal(new URL(await page.evaluate(()=>copiedLinks.at(-1))).searchParams.get('split'),'campaign-version');
   await page.evaluate(()=>document.querySelector('#mirrorShare').remove());
   await page.locator('#reviewAssignmentDetailClose').click();await page.locator('#reviewAssignmentsShare').click();
   assert.equal(new URL(await page.evaluate(()=>copiedLinks.at(-1))).searchParams.has('split'),false);
   // Permission denial exposes the actual manual-copy link without success feedback.
   await page.evaluate(()=>{navigator.clipboard.writeText=async()=>{throw Error('denied')};window.lastToast=null});
   await page.locator('#reviewAssignmentsShare').click();
   assert.equal(await page.evaluate(()=>manualLinks.length),1);assert.equal(await page.evaluate(()=>lastToast),null);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no page overflow');
   if(width<640)for(const selector of ['#reviewAssignmentsShare','[data-share-review-assignment="campaign-version"]'])assert.ok(await page.locator(selector).evaluate(el=>el.getBoundingClientRect().height>=44),'44px tap target');
   if((width===320&&lang==='en'&&theme==='light')||(width===1440&&lang==='zh'&&theme==='dark'))await page.screenshot({path:`/tmp/assignment-share-${width}-${lang}-${theme}.png`,fullPage:true});
   results.push({width,language:lang,theme,passed:true});await page.close();
  }
  assert.deepEqual(errors,[]);
  const result={browser:browser.version(),combinations:results,errors};
  fs.writeFileSync('/tmp/assignment-share-browser-results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(browser)await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
