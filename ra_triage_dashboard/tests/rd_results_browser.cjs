// Real Manual shell/widgets, synthetic RD endpoints; no Trail credentials/network.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'),original=fs.readFileSync(path.join(root,'index.html'),'utf8');
const css=[...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m=>m[1]);
const modules=['core-base','i18n-messages','i18n','format-api','session-config','routing','rd-results'];
const html=original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replaceAll('{{RA_TRIAGE_BASE_PATH}}','')
 .replace('</head>',css.map(p=>`<link rel="stylesheet" href="/static/${p}">`).join('')+'</head>')
 .replace('</body>',modules.map(p=>`<script src="/static/js/${p}.js"></script>`).join('')+'</body>');
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(!url.pathname.startsWith('/static/')){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(html);}
 const file=path.resolve(root,url.pathname.slice(8));
 if(!file.startsWith(root+'/')||!fs.existsSync(file))return res.writeHead(404).end();
 res.setHeader('Content-Type',file.endsWith('.css')?'text/css; charset=utf-8':'text/javascript; charset=utf-8');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/rd-results`);
  await page.evaluate(()=>{
   state.activePage='rd-results';state.selectedBaselineIds=['fixture'];state.session={is_admin:true,read_only:false};
   document.documentElement.dataset.sessionPending='false';document.body.dataset.activePage='rd-results';
   document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!=='rd-results'));
   document.querySelectorAll('.sidebar-item[data-page-target]').forEach(p=>p.classList.toggle('active',p.dataset.pageTarget==='rd-results'));
   window.fixtureRows=[{issue_id:'cn123',label:'正确触发',group:'resolved',authors:['reviewer_with_a_long_name']},{issue_id:'cn124',label:'误触发',group:'resolved',authors:['reviewer']},{issue_id:'cn125',label:'',group:'conflict',authors:['reviewer']}];
   window.fixtureMode='normal';
   window.commitMode='success';window.commitCalls=0;window.receiptCalls=0;window.previewMode='immediate';window.previewPolls=0;
   api=async(url,options={})=>{
    if(window.fixtureMode==='error')throw Error('读取失败 / Could not load results');
    if(url.includes('/operations/')){
     window.receiptCalls++;
     if(window.previewPhase){
      window.previewPolls++;
      if(window.previewMode==='lost'&&window.previewPolls===1)throw Error('预览状态暂不可用 / Preview status unavailable');
      if(window.previewMode==='failed'){window.previewPhase=false;return {...structuredClone(window.operationFixture),state:'preview_failed',reason:'preview_check_failed',items:[]};}
      if(window.previewPolls<3)return {...structuredClone(window.operationFixture),state:'preparing',items:[],progress:{stage:'trail',checked:window.previewPolls,total:3}};
      window.previewPhase=false;
     }
     if(window.commitMode==='lost_receipt')throw Error('记录暂不可用 / Receipt unavailable');
     return structuredClone(window.operationFixture);
    }
    if(url.includes('/status'))return {items:window.fixtureRows.map((r,i)=>({issue_id:r.issue_id,current:window.failureScenario?null:i===1?'无需协助':null,status:window.failureScenario?'pending':['pending','conflict','blocked'][i]})).filter(r=>JSON.parse(options.body).issue_ids.includes(r.issue_id))};
    if(url.includes('/preview')){
     const body=JSON.parse(options.body),scope=new URL(url,location.origin).pathname.endsWith('/preview-scope');window.lastPreviewBody=body;
     const scopeRows=window.fixtureRows.filter(r=>r.issue_id.includes(body.q||'')&&(body.status==='all'||r.group===body.status));
     const rows=scope?scopeRows.filter(r=>r.group==='resolved'):window.fixtureRows.filter(r=>body.issue_ids.includes(r.issue_id));
     window.operationFixture={id:'a'.repeat(32),state:'preview',results:[],...(scope?{scope:{total:scopeRows.length,blocked:scopeRows.length-rows.length,q:body.q,status:body.status}}:{}),items:rows.map(r=>({issue_id:r.issue_id,current:null,desired:r.label==='正确触发'?'成功':r.label,status:'pending',eligible:true}))};
     window.previewPolls=0;
     if(window.previewMode!=='immediate'){window.previewPhase=true;return {...structuredClone(window.operationFixture),state:'preparing',items:[],progress:{stage:'labels',checked:0,total:0}};}
     return structuredClone(window.operationFixture);
    }
    if(url.includes('/commit')){
     window.commitCalls++;
     if(window.commitMode==='rejected_commit')throw Error('写入未启用 / Writing disabled');
     const partial=window.commitMode==='partial';
     window.operationFixture.state=partial?'needs_recheck':'complete';
     window.operationFixture.results=window.operationFixture.items.map((r,i)=>({issue_id:r.issue_id,state:partial?['verified','unverified','not_attempted'][i]:'verified',reason:partial?['','readback_failed','batch_stopped'][i]:'',...(i===0||!partial?{observed:r.desired}:{})}));
     if(window.commitMode==='lost_running'){
      window.operationFixture.state='running';
      window.operationFixture.results=window.operationFixture.items.map((r,i)=>({issue_id:r.issue_id,state:['verified','intent','not_attempted'][i]}));
     }
     if(window.commitMode.startsWith('lost'))throw Error('连接中断 / Connection lost');
     return structuredClone(window.operationFixture);
    }
    const params=new URL(url,location.origin).searchParams,size=Number(params.get('page_size'))||20;
    const rows=window.fixtureMode==='empty'?[]:window.fixtureRows.filter(r=>r.issue_id.includes(params.get('q')||''));
    const filtered=rows.filter(r=>params.get('status')==='all'||r.group===params.get('status'));
    const pages=Math.max(1,Math.ceil(filtered.length/size)),page=Math.max(1,Math.min(pages,Number(params.get('page'))||1));
    return {items:filtered.slice((page-1)*size,page*size),counts:{total:rows.length,resolved:rows.filter(r=>r.group==='resolved').length,pending:rows.filter(r=>r.group==='pending').length,conflict:rows.filter(r=>r.group==='conflict').length},page,pages,page_size:size,total:filtered.length,write_enabled:window.fixtureWriteEnabled!==false};
   };
  });
  let checks=0;
  assert.equal(await page.locator('#sidebarNavLabeling #rdResultsNavButton').count(),1);
  assert.equal(await page.locator('#sidebarNavReview #rdResultsNavButton').count(),0);
  for(const width of [1440,390,320])for(const lang of ['zh','en'])for(const theme of ['dark','light']){
   await page.setViewportSize({width,height:950});
   await page.evaluate(async({lang,theme})=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;window.fixtureMode='normal';await loadRdResults();},{lang,theme});
   assert.equal(await page.locator('.rd-overview h3').innerText(),lang==='zh'?'标注上传':'Label upload');
   assert.equal(await page.locator('.rd-upload-target code').first().innerText(),'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/');
   assert.equal(await page.locator('.rd-upload-target code').last().innerText(),'ra_rd_review_result');
   assert.equal(await page.locator('.rd-metric small').count(),0);
   assert.equal(await page.locator('[data-rd-id="cn123"]').isEnabled(),true);
   await page.locator('[data-rd-filter="resolved"]').click();
   assert.equal(new URL(page.url()).searchParams.get('status'),'resolved');
   assert.equal(await page.locator('[data-rd-filter="resolved"]').getAttribute('aria-pressed'),'true');
   await page.locator('[data-rd-filter="all"]').click();
   await page.locator('[data-rd-action="status"]').click();
   await page.locator('[data-rd-action="select"]').click();
   assert.equal(await page.locator('[data-rd-id="cn123"]').isChecked(),true);
   assert.equal(await page.locator('[data-rd-id="cn124"]').isEnabled(),false);
   for(const checkbox of await page.locator('.rd-checkbox input').all()){
    assert.equal(await checkbox.evaluate(el=>getComputedStyle(el).appearance),'none');
    assert.equal(await checkbox.evaluate(el=>getComputedStyle(el,'::before').content),'""');
   }
   await page.locator('#rdOverwrite').focus();await page.keyboard.press('Space');
   assert.equal(await page.locator('#rdOverwrite').isChecked(),true);
   assert.equal(await page.locator('#rdOverwrite').evaluate(el=>el===document.activeElement),true);
   await page.keyboard.press('Space');
   assert.equal(await page.locator('#rdOverwrite').isChecked(),false);
   await page.locator('[data-rd-id="cn123"]').focus();await page.keyboard.press('Space');
   assert.equal(await page.locator('[data-rd-id="cn123"]').isChecked(),true);
   assert.equal(await page.locator('[data-rd-id="cn123"]').evaluate(el=>el===document.activeElement),true);
   const trigger=page.locator('#rdFilters .ui-select-trigger');
   await trigger.click();await page.keyboard.press('Escape');
   assert.equal(await trigger.getAttribute('aria-expanded'),'false');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   assert.equal(await page.locator('.rd-metric').count(),4);
   for(const card of await page.locator('.rd-metric').all()){
    assert.ok(await card.locator('strong').isVisible());assert.ok(await card.locator('em').isVisible());
   }
   if(width<640)assert.ok((await trigger.boundingBox()).height>=44);
   await page.locator('#rdSearch').fill('cn draft');
   await page.locator('[data-rd-action="preview"]').click();
   const dialog=page.locator('#rdResultsDialog');await dialog.waitFor({state:'visible'});
   const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1&&box.y>=0&&box.y+box.height<=951);
   await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';renderRdResults();});
   assert.equal(await page.locator('[data-rd-id="cn123"]').isChecked(),true);
   assert.equal(await page.locator('#rdSearch').inputValue(),'cn draft');
   await page.keyboard.press('Escape');
   await page.evaluate(lang=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;renderRdResults();},lang);
   await page.locator('#rdSearch').fill('');
   if((width===1440&&lang==='zh'&&theme==='dark')||(width===320&&lang==='en'&&theme==='light')){
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.screenshot({path:`/tmp/rd-results-${width}.png`,fullPage:width<640});
   }
   checks++;
  }
  const pagination=[];
  await page.evaluate(()=>{window.originalRows=structuredClone(window.fixtureRows);window.fixtureRows=Array.from({length:103},(_,i)=>({issue_id:`cn${1000+i}`,label:'正确触发',group:'resolved',authors:['reviewer_with_a_long_name']}));window.failureScenario=true;});
  for(const [width,lang,theme] of [[1440,'zh','dark'],[743,'zh','dark'],[390,'en','dark'],[320,'en','light']]){
   await page.setViewportSize({width,height:950});
   await page.evaluate(async({lang,theme})=>{
    state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;
    history.replaceState(null,'','/rd-results?baselines=fixture&status=all&page=2&page_size=10');await loadRdResults();
   },{lang,theme});
   assert.equal(await page.locator('.rd-workspace tbody tr').count(),10);
   await page.locator('[data-rd-action="status"]').click();await page.locator('[data-rd-action="select"]').click();
   assert.equal(await page.evaluate(()=>rdResults.selected.size),10);
   await page.locator('[data-rd-action="next"]').click();
   assert.equal(await page.evaluate(()=>rdResults.selected.size),0);
   assert.equal(await page.evaluate(()=>Object.keys(rdResults.remote).length),0);
   await page.locator('#rdPageJump').fill('999');await page.locator('#rdPageJump').press('Enter');
   assert.equal(new URL(page.url()).searchParams.get('page'),'11');
   assert.equal(await page.locator('.rd-workspace tbody tr').count(),3);
   await page.locator('#rdPageJump').fill('1.5');await page.locator('[data-rd-action="jump"]').click();
   assert.equal(await page.locator('#rdPageJump').inputValue(),'11');
   const sizeRoot=page.locator('.rd-workspace .rd-pagination .dashboard-native-ui-select');
   await sizeRoot.locator('.ui-select-trigger').click();await page.keyboard.press('Escape');
   assert.equal(await sizeRoot.locator('.ui-select-trigger').getAttribute('aria-expanded'),'false');
   await sizeRoot.locator('.ui-select-trigger').click();await sizeRoot.locator('[data-ui-select-value="50"]').click();
   assert.equal(await page.locator('.rd-workspace tbody tr').count(),50);
   assert.equal(new URL(page.url()).searchParams.get('page'),'1');
   assert.equal(new URL(page.url()).searchParams.get('page_size'),'50');
   await page.locator('#rdPageJump').fill('2');
   await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';renderRdResults();});
   assert.equal(await page.locator('#rdPageJump').inputValue(),'2');
   assert.equal(await page.locator('#rdPageSize').inputValue(),'50');
   await page.evaluate(()=>{window.commitCalls=0;window.fixtureWriteEnabled=false;rdResults.data.write_enabled=false;renderRdResults();});
   await page.locator('[data-rd-action="preview-scope"]').click();
   const dialog=page.locator('#rdResultsDialog');await dialog.waitFor({state:'visible'});
   assert.equal(await page.evaluate(()=>rdResults.preview.items.length),103);
   assert.equal(await page.evaluate(()=>window.lastPreviewBody.issue_ids),undefined);
   assert.equal(await page.evaluate(()=>window.lastPreviewBody.status),'all');
   assert.equal(await dialog.locator('[data-rd-action="commit"]').isDisabled(),true);
   assert.equal(await page.evaluate(()=>window.commitCalls),0);
   assert.equal(await dialog.locator('tbody tr').count(),20);
   await dialog.locator('#rdPreviewPageJump').fill('999');await dialog.locator('#rdPreviewPageJump').press('Enter');
   assert.equal(await dialog.locator('tbody tr').count(),3);
   await dialog.locator('.dashboard-native-ui-select .ui-select-trigger').click();await dialog.locator('[data-ui-select-value="100"]').click();
   assert.equal(await dialog.locator('tbody tr').count(),100);
   assert.equal(await page.evaluate(()=>rdResults.preview.items.length),103);
   assert.equal(await dialog.locator('[data-rd-action="commit"]').isDisabled(),true);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   const box=await dialog.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1&&box.y>=0&&box.y+box.height<=951);
   if(width<760){
    assert.ok((await dialog.locator('#rdPreviewPageJump').boundingBox()).height>=44);
    assert.ok((await dialog.locator('[data-rd-action="preview-jump"]').boundingBox()).height>=44);
   }
   await dialog.locator('[data-rd-action="close"]').click();
   await page.evaluate(lang=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;renderRdResults();window.scrollTo(0,0);rdResults.previewPageSize=20;},lang);
   await page.screenshot({path:`/tmp/rd-results-708-${width}.png`,fullPage:false});
   if(width===1440)await page.screenshot({path:'/tmp/rd-results-708-toolbar.png',clip:{x:0,y:0,width:1440,height:480}});
   pagination.push({width,lang,theme});
  }
  await page.evaluate(()=>{window.fixtureRows=window.originalRows;window.fixtureWriteEnabled=true;history.replaceState(null,'','/rd-results?baselines=fixture&status=all');});
  const previews=[];
  for(const [width,lang,theme] of [[1440,'zh','dark'],[390,'en','dark'],[320,'en','light']]){
   await page.setViewportSize({width,height:950});
   for(const mode of ['slow','lost','failed']){
    await page.evaluate(async({mode,lang,theme})=>{
     state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;
     window.previewMode=mode;window.commitMode='success';window.commitCalls=0;window.fixtureMode='normal';
     await loadRdResults();
    },{mode,lang,theme});
    // Selection no longer requires the optional page check; preview owns it.
    assert.equal(await page.locator('[data-rd-id="cn123"]').isEnabled(),true);
    await page.locator('[data-rd-action="select"]').click();
    assert.equal(await page.evaluate(()=>rdResults.selected.size),2);
    await page.locator('[data-rd-action="preview"]').click();
    await page.locator('.rd-notice').waitFor({state:'visible'});
    assert.equal(await page.locator('[data-rd-action="preview-scope"]').isDisabled(),true);
    if(mode==='lost'){
     await page.locator('[data-rd-operation]').waitFor({state:'visible'});
     assert.equal(await page.locator('#rdResultsDialog').isVisible(),false);
     await page.locator('[data-rd-operation]').click();
    }
    if(mode==='failed'){
     await page.waitForFunction(()=>!rdResults.busy);
     assert.equal(await page.locator('#rdResultsDialog').isVisible(),false);
     assert.match(await page.locator('.rd-notice').innerText(),/未执行上传|nothing was uploaded/);
    }else{
     await page.locator('#rdResultsDialog').waitFor({state:'visible'});
     assert.equal(await page.locator('#rdResultsDialog tbody tr').count(),2);
     await page.locator('#rdResultsDialog [data-rd-action="close"]').click();
    }
    assert.equal(await page.evaluate(()=>window.commitCalls),0);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    previews.push({width,lang,theme,mode});
   }
  }
  await page.evaluate(()=>{window.previewMode='immediate';window.previewPhase=false;});
  const outcomes=[];
  for(const [width,lang,theme] of [[1440,'zh','dark'],[390,'en','dark'],[320,'en','light']]){
   await page.setViewportSize({width,height:950});
   for(const mode of ['partial','lost_response','lost_receipt','rejected_commit','lost_running']){
    await page.evaluate(async({lang,theme,mode})=>{
     state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;
     window.failureScenario=true;window.fixtureMode='normal';window.commitMode=mode;window.commitCalls=window.receiptCalls=0;
     window.fixtureRows=window.fixtureRows.map(r=>({...r,group:'resolved',label:r.label||'正确触发'}));
     await loadRdResults();
    },{lang,theme,mode});
    await page.locator('[data-rd-action="status"]').click();
    await page.locator('[data-rd-action="select"]').click();
    await page.locator('[data-rd-action="preview"]').click();
    if(width<640){
     const size=await page.locator('#rdResultsDialog [data-rd-action="commit"]').evaluate(el=>({height:el.offsetHeight,minHeight:getComputedStyle(el).minHeight}));
     assert.ok(size.height>=48,JSON.stringify({width,mode,size}));
    }
    await page.locator('#rdResultsDialog [data-rd-action="commit"]').click();
    await page.waitForFunction(()=>!rdResults.busy);
    assert.equal(await page.evaluate(()=>window.commitCalls),1);
    assert.equal(await page.locator('#rdResultsDialog [data-rd-action="commit"]').count(),0);
    assert.equal(await page.evaluate(()=>rdResults.selected.size),0);
    assert.equal(await page.evaluate(()=>Object.keys(rdResults.remote).length),0);
    if(width<640){
     assert.ok(await page.locator('#rdResultsDialog .rd-table-wrap').evaluate(el=>el.scrollWidth>el.clientWidth&&getComputedStyle(el).overflowX==='auto'));
     assert.ok(await page.locator('#rdResultsDialog .rd-table td:first-child').first().evaluate(el=>getComputedStyle(el).whiteSpace==='nowrap'));
    }
    if(mode==='partial'){
     const text=await page.locator('#rdResultsDialog').innerText();
     assert.ok(text.includes(lang==='zh'?'未执行':'Not attempted'));
     assert.ok(text.includes(lang==='zh'?'写入后读回失败':'Readback failed after writing'));
     assert.equal(await page.evaluate(()=>window.receiptCalls),0);
    }else if(mode==='lost_response'){
     assert.equal(await page.evaluate(()=>rdResults.preview.state),'complete');
     assert.equal(await page.evaluate(()=>window.receiptCalls),1);
    }else if(mode==='rejected_commit'){
     assert.equal(await page.evaluate(()=>rdResults.preview.state),'outcome_unknown');
     assert.equal(await page.evaluate(()=>rdResults.preview.reason),'receipt_pending');
     await page.locator('#rdResultsDialog [data-rd-action="receipt"]').click();
     await page.waitForFunction(()=>!rdResults.busy);
     assert.equal(await page.evaluate(()=>rdResults.preview.state),'outcome_unknown');
     assert.equal(await page.evaluate(()=>window.commitCalls),1);
    }else{
     if(mode==='lost_running'){
      assert.equal(await page.evaluate(()=>rdResults.preview.state),'running');
      await page.evaluate(()=>{window.operationFixture.state='complete';window.operationFixture.results=window.operationFixture.items.map(r=>({issue_id:r.issue_id,state:'verified',observed:r.desired}));});
     }else{
     assert.equal(await page.evaluate(()=>rdResults.preview.state),'outcome_unknown');
     }
     await page.evaluate(()=>window.commitMode='success');
     await page.locator('#rdResultsDialog [data-rd-action="receipt"]').click();
     await page.waitForFunction(()=>!rdResults.busy);
     assert.equal(await page.evaluate(()=>rdResults.preview.state),'complete');
     assert.equal(await page.evaluate(()=>window.commitCalls),1);
    }
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    const box=await page.locator('#rdResultsDialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1&&box.y>=0&&box.y+box.height<=951);
    if(width===320&&mode==='partial'){
     await page.locator('#rdResultsDialog .rd-table-wrap').evaluate(el=>el.scrollLeft=el.scrollWidth);
     await page.screenshot({path:'/tmp/rd-results-partial-320.png'});
    }
    await page.locator('#rdResultsDialog [data-rd-action="close"]').click();
    outcomes.push({width,lang,mode});
   }
  }
  for(const mode of ['empty','error']){await page.evaluate(async mode=>{window.fixtureMode=mode;await loadRdResults();},mode);assert.equal(await page.locator('[data-rd-action="preview"]').isEnabled(),false);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,pagination,previews,outcomes,states:['normal','empty','error'],errors}));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
