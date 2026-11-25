// Read-only synthetic DOM regression for full-filter navigation. Requires Playwright.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const staticDir=path.resolve(__dirname,'../static'), read=name=>fs.readFileSync(path.join(staticDir,name),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const html=read('index.html');
  await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('{{RA_TRIAGE_BASE_PATH}}',''));
  const styles=JSON.parse('['+html.match(/const stylesheetPaths = \[([\s\S]*?)\];/)[1].replace(/,\s*$/,'')+']');
  for(const file of styles)await page.addStyleTag({content:read(file)});
  for(const file of ['core-base','i18n-messages','i18n','case-labeling'])await page.addScriptTag({content:read('js/'+file+'.js')});
  // Only media/editor/route transport are synthetic; queue selection, detail
  // hydration, counter markup, click and Enter handlers are production code.
  await page.addScriptTag({content:`
    function escapeHtml(s){return String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');}
    function safeUrl(){return '';}
    function ensureDetailMediaState(){} function labelBadge(){return '';}
    function detailMediaCommandMarkup(){return '';}
    function heroMediaSection(){return '<div style="height:100px">Synthetic media</div>';}
    function bindDetailMedia(){} function renderCaseLabelingEditor(){}
    function clearPendingCaseLabelingImages(){} function withBaselineQuery(p){return p;}
    function startTrailDetailMetadata(){return Promise.resolve({});}
    function detailExternalLinksMarkup(){return '';} function bindDetailExternalLinks(){}
    function capturePageContext(){return {page:state.activePage};}
    function isPageContextCurrent(c){return c.page===state.activePage;}
    function persistCaseLabelingRoute(o){window.lastRoute={...caseLabelingRouteOptions(),...o};}
    function showToast(message){throw Error(message);}
    const queue=Array.from({length:45},(_,i)=>'cn'+(100+i));
    state.activePage='labeling';state.selectedBaselineIds=['0508'];
    Object.assign(state.caseLabeling,{page:2,pageSize:20,detailSeq:0,exclusion:['excluded'],
      data:{items:queue.slice(20,40).map(issue_id=>({issue_id})),queue_issue_ids:queue,total:45,page:2,page_size:20}});
    window.reads=[];
    async function api(url){window.reads.push(url);return url.includes('/media')?{}:{issue_id:url.split('/').pop().split('?')[0]};}
    document.body.dataset.activePage='labeling';
    document.querySelectorAll('[data-page]').forEach(el=>el.classList.toggle('hidden',el.dataset.page!=='labeling'));
  `});
  const select=issue=>page.evaluate(id=>selectCaseLabelingIssue(id),issue);
  const position=()=>page.locator('#caseLabelingQueueIndex').inputValue();
  const next=page.locator('#caseLabelingNextIssue'),prev=page.locator('#caseLabelingPreviousIssue');
  await select('cn119');assert.equal(await position(),'20');
  assert.equal(await page.locator('.detail-queue-total').filter({visible:true}).count(),1);
  assert.equal(await page.locator('#caseLabelingQueueIndex').getAttribute('max'),'45');
  await next.click();await page.waitForFunction(()=>state.caseLabeling.issueId==='cn120');assert.equal(await position(),'21');
  await prev.click();await page.waitForFunction(()=>state.caseLabeling.issueId==='cn119');assert.equal(await position(),'20');
  await page.locator('#caseLabelingQueueIndex').fill('45');await page.locator('#caseLabelingQueueIndex').press('Enter');
  await page.waitForFunction(()=>state.caseLabeling.issueId==='cn144');assert.equal(await next.isDisabled(),true);
  for(const invalid of ['0','46','1.5']){
    await page.locator('#caseLabelingQueueIndex').fill(invalid);await page.locator('#caseLabelingQueueIndex').press('Enter');assert.equal(await position(),'45');
  }
  await select('cn100');assert.equal(await position(),'1');assert.equal(await prev.isDisabled(),true);
  await select('cn999');assert.equal(await next.isDisabled(),true);assert.equal(await prev.isDisabled(),true);
  await page.evaluate(()=>navigateCaseLabelingIssue(1));assert.equal(await page.evaluate(()=>state.caseLabeling.issueId),'cn999');
  await select('cn130');assert.equal(await position(),'31','deep link outside current gallery page has global ordinal');
  await page.locator('#caseLabelingBack').click();
  assert.deepEqual(await page.evaluate(()=>({page:state.caseLabeling.page,filter:state.caseLabeling.exclusion,items:state.caseLabeling.data.items.length,route:window.lastRoute.issue})),{page:2,filter:['excluded'],items:20,route:''});
  const layouts=[];
  for(const [width,language,theme] of [[1440,'zh','dark'],[390,'en','light'],[320,'en','light']]){
    await page.setViewportSize({width,height:1000});
    await page.evaluate(({language,theme})=>{state.uiLanguage=language;document.documentElement.dataset.uiLang=language;document.documentElement.dataset.colorTheme=theme;},{language,theme});
    await select('cn130');assert.equal(await position(),'31');
    const bounds=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(bounds.scroll<=width+1,JSON.stringify(bounds));
    const label=await page.locator('#caseLabelingQueueIndex').getAttribute('aria-label');assert.ok(language==='en'?label.includes('all filtered'):label.includes('全部筛选'));
    if(process.env.CASE_QUEUE_REPORT_DIR){fs.mkdirSync(process.env.CASE_QUEUE_REPORT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.CASE_QUEUE_REPORT_DIR,'queue-'+width+'.png')});}
    layouts.push({width,language,theme,bounds});
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({checks:'global count, cross-page previous/next, global jump, invalid jump, out-of-filter deep link, gallery return, layouts',layouts,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
