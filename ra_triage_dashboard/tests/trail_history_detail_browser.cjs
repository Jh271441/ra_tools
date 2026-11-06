// Actual Workbench dialog, API client, theme and locale code; synthetic loopback receipts only.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'),original=fs.readFileSync(path.join(root,'index.html'),'utf8');
const css=[...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(match=>match[1]);
const modules=['core-base','text-input','i18n-messages','i18n','format-api','routing','trail-history'];
const html=original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replaceAll('{{RA_TRIAGE_BASE_PATH}}','')
  .replace('</head>',css.map(file=>`<link rel="stylesheet" href="/static/${file}">`).join('')+'</head>')
  .replace('</body>',modules.map(file=>`<script src="/static/js/${file}.js"></script>`).join('')+'</body>');
const operation={id:'synthetic-update-20261026',source:'exclusion_summary',actor:'fixture_operator',created_at:'2026-10-26T03:17:16Z',status:'succeeded',restorable:true,children:[],parent_id:'',reason:'',
  items:[{issue_id:'cn00000001',before:{should_exclude:true,should_exclude_comment:'',operation_id:'previous-update'},after:{should_exclude:true,should_exclude_comment:'Updated exclusion reason / 合成排除理由',operation_id:'synthetic-update-20261026'}},
    {issue_id:'cn00000002',before:{should_exclude:true,should_exclude_comment:'',operation_id:'previous-update'},after:{should_exclude:true,should_exclude_comment:'Synthetic reason',operation_id:'synthetic-update-20261026'}}],
  outcomes:{cn00000001:'succeeded',cn00000002:'succeeded'},events:[{status:'pending',actor:'fixture_operator',created_at:'2026-10-26T03:17:15Z',outcomes:{cn00000001:'pending',cn00000002:'pending'}},{status:'succeeded',actor:'fixture_operator',created_at:'2026-10-26T03:17:16Z',outcomes:{cn00000001:'succeeded',cn00000002:'succeeded'}}]};
let previewMode='ready',verifiedOperation=operation,receiptDelay=0,posts=[];
const json=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/')) {
    if(req.method==='POST') {
      const chunks=[];for await(const chunk of req)chunks.push(chunk);
      const body=JSON.parse(Buffer.concat(chunks).toString());posts.push({path:url.pathname,body});
      assert.equal(req.headers['x-ra-triage-request'],'browser-v1');
      if(url.pathname.endsWith('/verify')) {if(receiptDelay)await new Promise(resolve=>setTimeout(resolve,receiptDelay));return json(res,200,verifiedOperation);}
      if(url.pathname.endsWith('/restore-preview')) {
        assert.ok(body.issue_ids.length);assert.ok(body.reason.trim());
        return json(res,200,previewMode==='conflict'?{ready:false,items:[],conflicts:body.issue_ids}:{ready:true,preview_id:'synthetic-preview',conflicts:[],items:operation.items.filter(item=>body.issue_ids.includes(item.issue_id)).map(item=>({issue_id:item.issue_id,current:item.after,restore:{...item.before,operation_id:'synthetic-restore'}}))});
      }
      return json(res,405,{detail:'This test never writes Trail.'});
    }
    if(url.pathname.endsWith('/missing'))return json(res,404,{detail:'Update record not found'});
    return json(res,200,operation);
  }
  if(url.pathname.startsWith('/static/')) {
    const file=path.resolve(root,url.pathname.slice(8));
    if(!file.startsWith(root+'/')||!fs.existsSync(file))return res.writeHead(404).end();
    res.writeHead(200,{'Content-Type':file.endsWith('.css')?'text/css':'text/javascript'});return res.end(fs.readFileSync(file));
  }
  res.writeHead(200,{'Content-Type':'text/html'});res.end(html);
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const evidenceDir=process.env.TRAIL_HISTORY_EVIDENCE_DIR||'/tmp/trail-history-detail-20261106';fs.mkdirSync(evidenceDir,{recursive:true});
  let browser;
  try {
    browser=await chromium.launch({headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const setup=async(width=1440,lang='zh',theme='dark',variant='normal')=>{
      await page.setViewportSize({width,height:900});await page.goto(`http://127.0.0.1:${server.address().port}/trail-update-history`);
      await page.evaluate(async({lang,theme,variant})=>{
        state.activePage='trail-history';state.uiLanguage=lang;state.colorTheme=theme;state.session={username:'fixture_operator',verified:true,access_role:'admin'};
        document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;document.documentElement.dataset.sessionPending='false';document.body.dataset.activePage='trail-history';
        $('#trailHistoryPage').classList.remove('hidden');
        renderPageChrome=()=>{};renderSystemStatus=()=>{};applySidebarState=()=>{};renderSession=()=>{};
        trailHistory.data={can_restore:true,total:0,page:1,page_size:20,items:[]};renderTrailHistoryFilters();renderTrailHistory();
        await openTrailHistoryDetail('synthetic-update-20261026');
        if(variant==='long') {
          trailHistory.detail.actor='operator_with_a_very_long_identifier_that_must_wrap_without_overflow';
          trailHistory.detail.items[0].after.should_exclude_comment='LongEnglishReasonWithoutSpaces_'.repeat(18)+'\n多行理由，需要完整展示。\nAn additional line of evidence.';
          renderTrailHistoryDetail();
        }
      },{lang,theme,variant});
      await page.locator('#trailHistoryDialog').waitFor({state:'visible'});
    };
    const geometry=()=>page.evaluate(()=>{
      const dialog=$('#trailHistoryDialog'),body=dialog.querySelector('.trail-history-dialog-body'),footer=dialog.querySelector('.trail-history-dialog-footer');
      const rect=dialog.getBoundingClientRect(),b=body.getBoundingClientRect(),f=footer.getBoundingClientRect();
      return {x:rect.x,y:rect.y,right:rect.right,bottom:rect.bottom,height:innerHeight,bodyBottom:b.bottom,footerTop:f.top,dialogOverflow:dialog.scrollWidth-dialog.clientWidth,bodyOverflow:body.scrollWidth-body.clientWidth,pageOverflow:document.documentElement.scrollWidth-innerWidth};
    });
    const bounded=async(width)=>{
      const box=await geometry();assert.ok(box.x>=0&&box.y>=0&&box.right<=width+1&&box.bottom<=box.height+1,JSON.stringify(box));
      assert.ok(box.bodyBottom<=box.footerTop+1,JSON.stringify(box));assert.ok(box.dialogOverflow<=1&&box.bodyOverflow<=1&&box.pageOverflow<=1,JSON.stringify(box));
    };
    const layouts=[];
    for(const width of [320,390,1440])for(const lang of ['zh','en'])for(const theme of ['dark','light']) {
      await setup(width,lang,theme);await bounded(width);
      assert.equal(await page.locator('#trailHistoryDialog details').count(),1);
      assert.equal(await page.locator('.trail-history-reason pre:visible').count(),4);
      assert.equal(await page.locator('.trail-history-execution:visible').count(),1);
      assert.equal(await page.locator('[data-restore-issue]').count(),0);
      assert.equal(await page.locator('[data-action="commit"]').isVisible(),false);
      if(width<640)assert.ok((await page.locator('[data-action="dismiss"]').boundingBox()).height>=44);
      if((width===1440&&lang==='zh'&&theme==='dark')||(width===390&&lang==='en'&&theme==='light')||(width===320&&lang==='en'&&theme==='dark'))await page.screenshot({path:path.join(evidenceDir,`detail-${width}-${lang}-${theme}.png`)});
      await page.locator('#trailHistoryAuditSummary').click();assert.equal(await page.locator('.trail-history-audit-content:visible').count(),1);await bounded(width);
      await page.evaluate(()=>applyUiLanguage(state.uiLanguage==='zh'?'en':'zh',{persist:false}));
      assert.equal(await page.locator('.trail-history-audit').getAttribute('open'),'');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'trailHistoryAuditSummary');
      layouts.push({width,lang,theme});
    }
    await setup(320,'en','light','long');await bounded(320);
    await page.locator('[data-action="start-restore"]').click();assert.equal(await page.locator('[data-restore-issue]:checked').count(),0);
    await page.locator('[data-restore-issue="cn00000001"]').check();
    await page.locator('#trailHistoryReason').fill('First line');await page.locator('#trailHistoryReason').press('End');await page.locator('#trailHistoryReason').press('Enter');
    assert.equal(await page.locator('#trailHistoryReason').inputValue(),'First line\n');assert.equal(posts.length,0);
    const reason='Original reason\n第二行：保留草稿';await page.locator('#trailHistoryReason').fill(reason);
    await page.locator('#trailHistoryReason').evaluate(el=>{el.focus();el.setSelectionRange(3,9);});
    const scroll=await page.locator('.trail-history-dialog-body').evaluate(el=>el.scrollTop);
    await page.evaluate(()=>applyUiLanguage('zh',{persist:false}));
    assert.equal(await page.locator('#trailHistoryReason').inputValue(),reason);
    assert.deepEqual(await page.locator('#trailHistoryReason').evaluate(el=>[el.selectionStart,el.selectionEnd]),[3,9]);
    assert.equal(await page.locator('[data-restore-issue]:checked').count(),1);
    assert.equal(await page.locator('.trail-history-dialog-body').evaluate(el=>el.scrollTop),await page.locator('.trail-history-dialog-body').evaluate((el,previous)=>Math.min(previous,el.scrollHeight-el.clientHeight),scroll));await bounded(320);
    await page.locator('[data-action="preview"]').click();await page.waitForFunction(()=>trailHistory.preview?.ready);
    assert.equal(await page.locator('.trail-history-changes').count(),0);
    assert.equal(await page.locator('#trailHistoryRestoreResult .trail-history-issue').count(),1);
    assert.equal(await page.locator('[data-action="commit"]').isEnabled(),true);await bounded(320);
    await page.screenshot({path:path.join(evidenceDir,'restore-preview-320-zh-light.png')});
    await page.locator('[data-action="edit-preview"]').click();assert.equal(await page.evaluate(()=>trailHistory.preview),null);
    assert.equal(await page.locator('#trailHistoryReason').inputValue(),reason);
    previewMode='conflict';await page.locator('[data-action="preview"]').click();await page.waitForFunction(()=>trailHistory.preview&&!trailHistory.busy);
    assert.equal(await page.locator('[data-action="commit"]').isVisible(),false);assert.match(await page.locator('#trailHistoryRestoreResult').innerText(),/cn00000001/);await bounded(320);
    await page.locator('[data-action="cancel-restore"]').click();assert.equal(await page.evaluate(()=>trailHistory.selected.length),0);assert.equal(await page.evaluate(()=>trailHistory.reason),'');
    // Verification retains the explicit eligible subset and never selects the whole batch.
    await page.locator('[data-action="start-restore"]').click();await page.locator('[data-restore-issue="cn00000001"]').check();
    receiptDelay=1500;await page.locator('[data-action="verify"]').click();
    assert.equal(await page.locator('[data-action="dismiss"]').isDisabled(),true);assert.equal(await page.locator('[data-action="cancel-restore"]').isDisabled(),true);
    assert.match(await page.locator('#trailHistoryActionHint').innerText(),/正在处理/);await page.keyboard.press('Escape');assert.equal(await page.locator('#trailHistoryDialog').isVisible(),true);await bounded(320);
    await page.waitForFunction(()=>!trailHistory.busy);receiptDelay=0;
    assert.deepEqual(await page.evaluate(()=>trailHistory.selected),['cn00000001']);
    verifiedOperation={...operation,restorable:false,status:'unknown',outcomes:{cn00000001:'unknown',cn00000002:'unknown'}};
    await page.locator('[data-action="verify"]').click();await page.waitForFunction(()=>!trailHistory.busy);
    assert.equal(await page.evaluate(()=>trailHistory.selected.length),0);assert.equal(await page.locator('[data-action="preview"]').isEnabled(),false);
    await page.locator('[data-action="dismiss"]').click();await page.waitForFunction(()=>!$('#trailHistoryDialog').open);
    assert.equal(await page.evaluate(()=>trailHistory.restoring),false);assert.equal(await page.evaluate(()=>trailHistory.reason),'');
    // Legacy, missing values, mixed receipts and an empty history remain explicit and bounded.
    await setup(390,'en','light');
    await page.evaluate(()=>{trailHistory.detail.source='legacy';renderTrailHistoryDetail();});
    assert.equal(await page.locator('[data-action="start-restore"]').isVisible(),false);assert.match(await page.locator('.trail-history-dialog-body').innerText(),/No complete snapshots/);await bounded(390);
    await page.evaluate(()=>{trailHistory.detail.source='exclusion_summary';trailHistory.detail.outcomes.cn00000002='unknown';trailHistory.detail.items[0].before={};trailHistory.detail.items[0].after={should_exclude:null,should_exclude_comment:''};renderTrailHistoryDetail();});
    assert.match(await page.locator('.trail-history-issue').first().innerText(),/Field absent/);assert.match(await page.locator('.trail-history-issue').first().innerText(),/null/);assert.match(await page.locator('.trail-history-issue').first().innerText(),/Empty string/);await bounded(390);
    await page.evaluate(()=>{trailHistory.detail.items=[];trailHistory.detail.events=[];renderTrailHistoryDetail();});
    assert.match(await page.locator('.trail-history-dialog-body').innerText(),/No Issue records/);assert.match(await page.locator('.trail-history-dialog-body').innerText(),/No execution events/);await bounded(390);
    // A shorter responsive viewport still leaves actions outside the scroll body; this does not emulate a real keyboard.
    await page.setViewportSize({width:320,height:480});await bounded(320);
    await page.locator('[data-action="dismiss"]').click();await page.waitForFunction(()=>!$('#trailHistoryDialog').open);
    await page.evaluate(()=>openTrailHistoryDetail('missing'));assert.match(await page.locator('#toast').innerText(),/Update record not found/);
    assert.equal(await page.locator('#trailHistoryDialog').isVisible(),false);
    for(const [lang,theme] of [['zh','dark'],['en','light']]) {
      await setup(1440,lang,theme);await page.setViewportSize({width:1440,height:1080});await bounded(1440);
      await page.locator('#trailHistoryDialog').screenshot({path:path.join(evidenceDir,`detail-desktop-${lang}-${theme}.png`)});
    }
    await setup(390,'en','light');await page.locator('#trailHistoryDialog').screenshot({path:path.join(evidenceDir,'detail-phone-en-light.png')});
    assert.equal(posts.some(post=>post.path.endsWith('/restore-commit')),false);assert.deepEqual(errors,[]);
    const result={browser:browser.version(),layouts,checks:['visible changes','one audit disclosure','audit locale/focus','long text','multiline Enter','restore draft/caret/scroll','preview subset','conflict blocks confirmation','cancel clears draft','busy disables dismissal','verification retains subset','legacy','missing/null/empty values','empty records','short viewport','failed detail'],posts:posts.map(post=>post.path),errors};
    fs.writeFileSync(path.join(evidenceDir,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,layouts:layouts.length,evidenceDir}));
  } finally {await browser?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
