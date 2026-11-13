// Real API client, dialog, Markdown and CSS; synthetic local HTTP only.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../static');
const original = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = [...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = ['core-base','text-input','i18n-messages','i18n','format-api','session-config','work-split','runs','trail-update-state','review-mentions','analysis-charts', 'analysis', 'discussion-drafts', 'issue-discussion','routing'];
const html = original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replaceAll('{{RA_TRIAGE_BASE_PATH}}','')
  .replace('</head>', css.map(p=>`<link rel="stylesheet" href="/static/${p}">`).join('')+'</head>')
  .replace('</body>', modules.map(p=>`<script src="/static/js/${p}.js"></script>`).join('')+'</body>');
const evidence = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="960" height="540" fill="#233044"/><path d="M100 540 L340 0 M860 540 L620 0 M480 540 L480 0" stroke="#f6e5a8" stroke-width="12" stroke-dasharray="50 20"/><text x="40" y="60" font-family="sans-serif" font-size="28" fill="white">Historical evidence A / synthetic fixture</text></svg>');
let mode, posts, lookups, records, nextId;
const parents = [
  {id:117,author:'bob',author_verified:true,is_label_evidence:true,discussion_channel:'case',body:'Issue 标签 #4136 · 标注依据 / Label rationale\nHistorical rationale with its original screenshot.',created_at:'2026-11-04T20:45:42+08:00',attachments:[{id:'old-image',url:'/api/labeling/attachments/old-image'}]},
  {id:119,author:'carol',author_verified:true,discussion_channel:'case',body:'![Inline evidence](attachment:inline-image)',created_at:'2026-11-04T20:52:55+08:00',attachments:[{id:'inline-image',url:'/api/comment-attachments/inline-image'}]},
];
function json(res, status, value) {res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(value));}
const server = http.createServer(async(req,res)=>{
  const url = new URL(req.url,'http://localhost');
  if(url.pathname.includes('/attachments/') || url.pathname.includes('/comment-attachments/')) {res.writeHead(200,{'Content-Type':'image/svg+xml'});return res.end(evidence);}
  if(url.pathname.includes('/discussion-submissions/')) {
    const key=url.pathname.split('/').at(-1);lookups.push(key);
    if(mode==='offline-check') return req.socket.destroy();
    return records.has(key)?json(res,200,{comment:records.get(key),idempotent_replay:true}):json(res,404,{detail:'Not found'});
  }
  if(url.pathname.startsWith('/api/')) {
    if(req.method==='GET') return json(res,200,{comments:parents,count:parents.length});
    const chunks=[];for await(const chunk of req) chunks.push(chunk);
    const raw=Buffer.concat(chunks).toString();
    const multipart=String(req.headers['content-type']).includes('multipart/form-data');
    const body=JSON.parse(multipart?raw.match(/name="payload"\r\n\r\n([^\r]+)\r\n/)[1]:raw);
    const key=req.headers['idempotency-key'];posts.push({key,body,multipart});
    if(mode==='forbidden') return json(res,403,{detail:'Expired SSO'});
    if(mode==='bad-request') return json(res,400,{detail:'Invalid comment / 评论不合法'});
    if(mode==='login') {res.writeHead(302,{Location:'/sign-in'});return res.end();}
    if(mode==='always-503' || mode==='offline-check' || (mode==='retry-503' && posts.length===1)) return json(res,503,{detail:'Temporary gateway failure'});
    if(!records.has(key)) records.set(key,{id:nextId++,issue_id:'cn123',body:body.body,author:'alice',author_verified:true,reply_to_id:body.reply_to_id,discussion_channel:'case',created_at:'2026-11-04T21:00:00+08:00',attachments:[]});
    const comment=records.get(key);
    if(mode==='lost-response') return req.socket.destroy();
    if(mode==='unreadable') {res.writeHead(200,{'Content-Type':'text/html'});return res.end('<html>proxy response</html>');}
    if(mode==='timeout') return; // Client's actual AbortController ends this request.
    return json(res,200,{comment,notification:{queued:['bob']}});
  }
  if(url.pathname==='/sign-in') {res.writeHead(200,{'Content-Type':'text/html'});return res.end('<html>Sign in</html>');}
  if(url.pathname.startsWith('/static/')) {
    const file=path.resolve(root,url.pathname.slice(8));
    if(!file.startsWith(root+'/')||!fs.existsSync(file)) return res.writeHead(404).end();
    res.writeHead(200,{'Content-Type':file.endsWith('.css')?'text/css':'text/javascript'});return res.end(fs.readFileSync(file));
  }
  res.writeHead(200,{'Content-Type':'text/html'});res.end(html);
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const evidenceDir=process.env.DISCUSSION_EVIDENCE_DIR||'/tmp/discussion-reliability-20261104';fs.mkdirSync(evidenceDir,{recursive:true});
  let browser;
  try {
    browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH}:{})});
    const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    const setup=async(scenario='success',lang='zh',theme='dark',width=1440)=>{
      mode=scenario;posts=[];lookups=[];records=new Map();nextId=200;
      await page.setViewportSize({width,height:900});
      await page.goto(`http://127.0.0.1:${server.address().port}/review?issue=cn123`);
      await page.evaluate(async({lang,theme})=>{
        state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;
        state.colorTheme=theme;document.documentElement.dataset.colorTheme=theme;
        document.documentElement.dataset.sessionPending='false';document.body.dataset.activePage='review';
        state.activePage='review';state.selectedId='cn123';state.session={username:'alice',verified:true,can_write:true,access_role:'writer'};
        state.mentionUsers=[{username:'bob',display_name:'Bob',enabled:true}];state.config={review_notifications:{enabled:true}};
        renderSystemStatus=()=>{};renderSession=()=>{};applySidebarState=()=>{};
        $('#analysisDiscussionForm').addEventListener('submit',saveAnalysisDiscussion);
        $('#analysisDiscussionDialog').addEventListener('close',closeAnalysisDiscussion);
        bindAnalysisDiscussionEnterSubmit();bindAnalysisDiscussionEditor();applyDomI18n(document);
        await openAnalysisDiscussion('cn123');beginAnalysisDiscussionReply(117);
      },{lang,theme});
      await page.locator('#analysisDiscussionNote').fill('@bob A reply about the historical screenshot. / 对原标注截图的回复。');
    };
    const submit=async()=>{await page.locator('#analysisDiscussionSubmit').click();await page.waitForFunction(()=>!state.analysisDiscussion.saving);};
    const result=[];
    for(const scenario of ['lost-response','retry-503','unreadable','timeout']) {
      await setup(scenario);
      if(scenario==='timeout') await page.evaluate(()=>{const native=window.setTimeout;window.setTimeout=(fn,ms,...args)=>native(fn,ms===30000?80:ms,...args);});
      await submit();assert.equal(records.size,1,scenario);
      // Chromium may transparently resend a POST on a reset pooled connection.
      // Every wire request must still carry the same idempotency key.
      if(scenario==='lost-response') assert.ok(posts.length>=1);
      else assert.equal(posts.length,scenario==='retry-503'?2:1,scenario);
      assert.equal(new Set(posts.map(p=>p.key)).size,1);assert.ok(posts[0].key.length>=8);
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'');
      assert.equal(await page.locator('[data-comment-id="200"]').count(),1);
      result.push({scenario,posts:posts.length,receiptReads:lookups.length,comments:records.size});
    }
    for(const scenario of ['forbidden','bad-request','login']) {
      await setup(scenario,'en');const draft=await page.locator('#analysisDiscussionNote').inputValue();await submit();
      assert.equal(posts.length,1);assert.equal(lookups.length,0);assert.equal(records.size,0);
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
      assert.equal(await page.evaluate(()=>state.analysisDiscussion.replyTo.id),117);
      assert.match(await page.locator('#analysisDiscussionSubmitStatus').innerText(),/Comment not posted/);
      result.push({scenario,posts:1,receiptReads:0});
    }
    await setup('always-503');const draft=await page.locator('#analysisDiscussionNote').inputValue();await submit();
    assert.equal(posts.length,2);assert.equal(lookups.length,2);assert.equal(records.size,0);
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
    const originalKey=posts[0].key;mode='success';await submit();
    assert.equal(posts.length,3);assert.equal(posts[2].key,originalKey);assert.equal(records.size,1);
    result.push({scenario:'bounded retries then manual retry',posts:3,comments:1});
    await setup('offline-check');await submit();assert.equal(posts.length,1);assert.equal(records.size,0);
    // It committed after the disconnected read. Manual retry must recover it without another POST.
    const saved={id:201,issue_id:'cn123',author:'alice',body:posts[0].body.body,reply_to_id:117,attachments:[]};
    records.set(posts[0].key,saved);mode='success';await submit();assert.equal(posts.length,1);
    assert.equal(await page.locator('[data-comment-id="201"]').count(),1);
    result.push({scenario:'manual confirmation after lost connection',posts:1,comments:1});
    // A valid server receipt cannot be reclassified as a failed POST by a UI exception.
    await setup();await page.evaluate(()=>{window.originalAcknowledge=acknowledgeLocalChange;acknowledgeLocalChange=()=>{throw Error('Synthetic render failure');};});
    await submit();assert.equal(posts.length,1);assert.match(await page.locator('#analysisDiscussionSubmitStatus').innerText(),/评论已发表/);
    assert.equal(await page.locator('#analysisDiscussionSubmit').isDisabled(),true);
    assert.equal(await page.locator('#analysisDiscussionNote').getAttribute('readonly'),'');
    result.push({scenario:'UI failure after commit',posts:1,comments:1});
    // Multipart retries carry the same key and retain the file/reply until confirmed.
    await setup('retry-503');
    await page.evaluate(()=>addAnalysisDiscussionImages([new File(['fixture'],'evidence.png',{type:'image/png'})]));await submit();
    assert.equal(posts.length,2);assert.ok(posts.every(p=>p.multipart));assert.equal(posts[0].key,posts[1].key);
    assert.equal(await page.evaluate(()=>state.analysisDiscussion.pendingImages.length),0);
    result.push({scenario:'multipart reconnect',posts:2,comments:1});
    const layouts=[];
    for(const width of [320,390,1440]) for(const lang of ['zh','en']) for(const theme of ['dark','light']) {
      await setup('always-503',lang,theme,width);
      const images=page.locator('#analysisDiscussionThread .comment-markdown-image img');
      assert.equal(await images.count(),2,'append the unreferenced label image and avoid repeating inline evidence');
      await page.locator('[data-comment-id="117"]').scrollIntoViewIfNeeded();
      await page.waitForFunction(()=>[...document.querySelectorAll('#analysisDiscussionThread img')].every(img=>img.complete&&img.naturalWidth>0));
      const oldImage=page.locator('[data-comment-id="117"] img');assert.match(await oldImage.getAttribute('src'),/old-image$/);
      const imgBox=await oldImage.boundingBox();assert.ok(imgBox.width>44&&imgBox.width<width);
      await page.evaluate(()=>{window.retainedEditor=$('#analysisDiscussionNote');window.retainedImage=document.querySelector('[data-comment-id="117"] img');});
      await page.locator('#analysisDiscussionNote').focus();
      await page.evaluate(()=>applyUiLanguage(state.uiLanguage==='zh'?'en':'zh',{persist:false}));
      assert.equal(await page.evaluate(()=>window.retainedEditor===$('#analysisDiscussionNote')&&window.retainedImage===document.querySelector('[data-comment-id="117"] img')),true);
      assert.equal(await page.evaluate(()=>document.activeElement===$('#analysisDiscussionNote')),true);
      assert.equal(await oldImage.getAttribute('alt'),lang==='zh'?'Comment image':'评论图片');
      await page.evaluate(lang=>applyUiLanguage(lang,{persist:false}),lang);
      assert.equal(await page.locator('[data-comment-image]').innerText(),lang==='en'?'Image':'图片');
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'@bob A reply about the historical screenshot. / 对原标注截图的回复。');
      await submit();assert.match(await page.locator('#analysisDiscussionSubmitStatus').innerText(),lang==='zh'?/未能确认/:/Could not confirm/);
      assert.equal(await page.evaluate(()=>state.analysisDiscussion.replyTo.id),117);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      const box=await page.locator('#analysisDiscussionDialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1&&box.y>=0&&box.y+box.height<=901);
      assert.ok(await page.locator('#analysisDiscussionSubmitStatus').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
      if(width<640) assert.ok((await page.locator('#analysisDiscussionSubmit').boundingBox()).height>=48);
      if((width===320&&lang==='en'&&theme==='light')||(width===1440&&lang==='zh'&&theme==='dark')) {
        await page.locator('[data-comment-id="117"]').scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(evidenceDir,`discussion-${width}-${lang}-${theme}.png`)});
      }
      layouts.push({width,lang,theme});
    }
    // Empty/loading and failed reads remain bounded; they never enable a write.
    await setup();await page.evaluate(()=>{state.analysisDiscussion.comments=[];renderAnalysisDiscussionThread();});
    assert.match(await page.locator('#analysisDiscussionThread').innerText(),/还没有评论/);
    await setup('success','en');await page.evaluate(()=>{state.session.read_only=true;renderAnalysisDiscussionThread();updateAnalysisDiscussionComposerAccess();});
    assert.equal(await page.locator('[data-comment-id="117"] img').count(),0);
    assert.match(await page.locator('[data-comment-id="117"]').innerText(),/Sign in through SSO/);
    assert.equal(await page.locator('[data-comment-id="119"] img').count(),1);
    assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidenceDir,'results.json'),JSON.stringify({result,layouts,errors},null,2));
    console.log(JSON.stringify({browser:browser.version(),result,layouts:layouts.length,errors,evidenceDir}));
  } finally {await browser?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
