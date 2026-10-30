// Local synthetic responses only: no business comments or notifications are sent.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const probe = process.argv.includes('--probe');
const replyProbe = process.argv.includes('--reply-probe');
const root = path.resolve(__dirname, '../static');
const original = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = [...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = ['core-base', 'text-input', 'i18n-messages', 'i18n', 'format-api', 'session-config', 'work-split', 'runs', 'trail-update-state', 'review-mentions', 'analysis', 'routing'];
const html = original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replaceAll('{{RA_TRIAGE_BASE_PATH}}', '')
  .replace('</head>', css.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('') + '</head>')
  .replace('</body>', modules.map(p => `<script src="/static/js/${p}.js"></script>`).join('') + '</body>');
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (req.method !== 'GET') return res.writeHead(405).end();
  if (!pathname.startsWith('/static/')) { res.setHeader('Content-Type', 'text/html'); return res.end(html); }
  const file = path.resolve(root, pathname.slice(8));
  if (!file.startsWith(root + '/') || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : 'text/javascript');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const cdp = await page.context().newCDPSession(page);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const url = `http://127.0.0.1:${server.address().port}/review?issue=cn123&run=run1&work_split=campaign-test&baselines=fixture`;
    const setup = async (lang='zh', theme='dark') => {
      await page.goto(url);
      await page.evaluate(async ({lang,theme}) => {
        state.uiLanguage=lang;
        document.documentElement.dataset.uiLang=lang;
        document.documentElement.dataset.colorTheme=theme;
        document.documentElement.dataset.sessionPending='false';
        document.body.dataset.activePage='review';
        state.activePage='review'; state.selectedId='cn123'; state.selectedRunId='run1';
        state.reviewWorkSplitId='campaign-test'; state.selectedBaselineIds=['fixture'];
        state.session={username:'alice',verified:true,can_write:true,access_role:'writer'};
        state.mentionUsers=[{username:'bob',display_name:'Bob',enabled:true},{username:'carol',display_name:'Carol',enabled:true}];
        state.config={review_notifications:{enabled:true}};
        window.posts=[];
        api=async (path, options) => {
          if(options?.method === 'POST') {
            window.posts.push({path,body:JSON.parse(options.body)});
            return await new Promise((resolve,reject) => {
              window.finishPost={resolve,reject};
              options.signal?.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true});
            });
          }
          return {count:2,task:{id:'campaign-test',name:'1009 联合复核 / Combined disagreement review',read_only:false},comments:[
            {id:117,discussion_channel:'case',author:'bob',author_verified:true,body:'Long label rationale / 问题讨论',created_at:'2026-10-30T08:15:22+00:00'},
            {id:119,discussion_channel:'case',author:'carol',author_verified:true,body:'Another reply / 另一条回复',created_at:'2026-10-30T08:16:22+00:00'}]};
        };
        $('#analysisDiscussionForm').addEventListener('submit',saveAnalysisDiscussion);
        $('#analysisDiscussionDialog').addEventListener('close',closeAnalysisDiscussion);
        bindAnalysisDiscussionEnterSubmit();
        applyDomI18n(document);
        await openAnalysisDiscussion('cn123',{kind:'labeling',taskId:'campaign-test',discussionChannel:'case',runId:''});
        beginAnalysisDiscussionReply(117);
      },{lang,theme});
    };
    const draft='@bob 无需协助和正确触发需要区分。\nA longer English reply about the original issue and its traffic lights.';
    const clickWithoutMovingTarget = async (selector, bottom=false) => {
      const submit=page.locator(selector);
      await submit.scrollIntoViewIfNeeded();
      const before=await submit.boundingBox();
      await page.mouse.move(before.x+before.width/2,before.y+(bottom?before.height-3:before.height/2));
      await page.mouse.down(); await page.waitForTimeout(80);
      const after=await submit.boundingBox();
      await page.mouse.up();
      assert.ok(Math.abs(after.y-before.y)<0.1,JSON.stringify({before,after}));
      assert.ok(Math.abs(after.height-before.height)<0.1);
    };
    if(replyProbe) {
      const rows=[];
      for(const body of ['A plain comment without mentions.',draft]) {
        await setup(); await page.locator('#analysisDiscussionNote').fill(body);
        const before=await page.locator('#analysisDiscussionSubmit').boundingBox();
        await page.mouse.move(before.x+before.width/2,before.y+before.height-3);
        await page.mouse.down(); await page.waitForTimeout(80);
        const after=await page.locator('#analysisDiscussionSubmit').boundingBox();
        await page.mouse.up();
        rows.push({hasMention:body.includes('@'),before,after,posts:await page.evaluate(()=>posts.length)});
      }
      console.log(JSON.stringify({replyClickProbe:rows})); return;
    }
    await setup();
    await page.locator('#analysisDiscussionNote').fill(draft);
    // A background route serializer adds display filters without changing ownership.
    await page.evaluate(() => { const next=new URL(location.href); next.searchParams.set('comparison','all'); history.replaceState({},'',next); });
    await page.locator('#analysisDiscussionSubmit').click();
    if(probe) {
      const dropped = await page.evaluate(()=>({posts:posts.length,draft:$('#analysisDiscussionNote').value,buttonDisabled:$('#analysisDiscussionSubmit').disabled}));
      await setup(); await page.locator('#analysisDiscussionNote').fill(draft);
      await page.locator('#analysisDiscussionSubmit').click();
      await page.evaluate(()=>finishPost.reject(Error('Synthetic network failure')));
      await page.waitForFunction(()=>!state.analysisDiscussion.saving);
      console.log(JSON.stringify({dropped,feedback:await page.evaluate(()=>({toast:$('#toast').textContent,toastInsideDialog:!!$('#toast').closest('dialog'),modalOpen:$('#analysisDiscussionDialog').open,inlineStatus:!!$('#analysisDiscussionSubmitStatus')}))}));
      return;
    }
    await page.waitForFunction(()=>posts.length===1);
    assert(await page.locator('#analysisDiscussionSubmit').isDisabled());
    assert((await page.locator('#analysisDiscussionSubmit').innerText()).includes('发表中'));
    await page.evaluate(()=>$('#analysisDiscussionForm').requestSubmit($('#analysisDiscussionSubmit')));
    assert.equal(await page.evaluate(()=>posts.length),1);
    assert.deepEqual(await page.evaluate(()=>posts[0].body),{body:draft,reply_to_id:117,task_id:''});
    await page.evaluate(()=>finishPost.resolve({comment:{id:118,body:'saved',discussion_channel:'case',author:'alice'}}));
    await page.waitForFunction(()=>!state.analysisDiscussion.saving);
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'');
    assert.equal(await page.locator('#analysisDiscussionChannel').isDisabled(),false);
    assert((await page.locator('#analysisDiscussionSubmitStatus').innerText()).includes('已发表'));

    const results=[];
    for(const width of [1440,390,320]) for(const lang of ['zh','en']) for(const theme of ['dark','light']) {
      await page.setViewportSize({width,height:900}); await setup(lang,theme);
      await page.locator('#analysisDiscussionNote').fill(draft);
      const beforeComposition=await page.locator('#analysisDiscussionSubmit').boundingBox();
      await cdp.send('Input.imeSetComposition',{text:'ni',selectionStart:2,selectionEnd:2});
      assert.equal(await page.locator('#analysisDiscussionNote').getAttribute('data-ime-composing'),'1');
      const duringComposition=await page.locator('#analysisDiscussionSubmit').boundingBox();
      await cdp.send('Input.insertText',{text:'你'});
      const afterComposition=await page.locator('#analysisDiscussionSubmit').boundingBox();
      assert.equal(beforeComposition.y,duringComposition.y);
      assert.equal(beforeComposition.y,afterComposition.y);
      await page.locator('#analysisDiscussionNote').fill(draft);
      // Native pointerdown blurs the editor; the target must stay under pointerup.
      await clickWithoutMovingTarget('#analysisDiscussionSubmit',true);
      assert.equal(await page.evaluate(()=>posts.length),1);
      await page.evaluate(()=>finishPost.reject(Error('Synthetic network failure with enough detail to wrap on a narrow phone viewport.')));
      await page.waitForFunction(()=>!state.analysisDiscussion.saving);
      const status=page.locator('#analysisDiscussionSubmitStatus');
      await status.scrollIntoViewIfNeeded();
      assert(await status.isVisible());
      assert((await status.innerText()).includes(lang==='en'?'Could not confirm':'未能确认'));
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
      assert(await page.locator('#analysisDiscussionChannel').isDisabled());
      assert.equal(await page.evaluate(()=>state.analysisDiscussion.replyTo.id),117);
      assert.equal(await page.locator('#analysisDiscussionSubmit').isDisabled(),false);
      const box=await page.locator('#analysisDiscussionDialog').boundingBox();
      assert.ok(box && box.x>=0 && box.x+box.width<=width+1 && box.y>=0 && box.y+box.height<=901);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.ok(await status.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
      if(width<640) assert.ok((await page.locator('#analysisDiscussionSubmit').boundingBox()).height>=48);
      // Existing dual-language spans must switch without dropping the reply/draft.
      await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='en'?'zh':'en';document.documentElement.dataset.uiLang=state.uiLanguage;});
      assert((await status.innerText()).includes(lang==='en'?'未能确认':'Could not confirm'));
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
      await page.evaluate(({lang})=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;},{lang});
      if(width===320&&lang==='en'&&theme==='light') await page.screenshot({path:'/tmp/comment-submit-320-en-light.png'});
      if(width===1440&&lang==='zh'&&theme==='dark') await page.screenshot({path:'/tmp/comment-submit-1440-zh-dark.png'});
      // Retry preserves the original reply destination and creates one synthetic result.
      await page.locator('#analysisDiscussionSubmit').click();
      assert.equal(await page.evaluate(()=>posts.length),2);
      await page.evaluate(()=>finishPost.resolve({comment:{id:118,body:'saved',discussion_channel:'case',author:'alice'}}));
      await page.waitForFunction(()=>!state.analysisDiscussion.saving);
      assert.equal(await page.locator('[data-comment-id="118"]').count(),1);
      // Switching the reply target while editing must also survive blur, without changing authored text.
      await page.locator('#analysisDiscussionNote').fill(draft);
      await clickWithoutMovingTarget('[data-comment-reply="119"]');
      assert.equal(await page.evaluate(()=>state.analysisDiscussion.replyTo.id),119);
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
      await page.locator('[data-cancel-comment-reply]').click();
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
      results.push({width,lang,theme});
    }
    // Autocomplete selection, Escape and composition still work with retained status.
    await setup();
    await page.locator('#analysisDiscussionNote').fill('@bo');
    await page.locator('#analysisDiscussionNote').press('Enter');
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'@bob ');
    assert.equal(await page.evaluate(()=>posts.length),0);
    await page.locator('#analysisDiscussionNote').fill('@bo');
    await page.evaluate(()=>{const input=$('#analysisDiscussionNote');input.blur();input.focus();});
    await page.waitForTimeout(30);
    assert.equal(await page.locator('.review-mention-popover:visible').count(),1);
    await page.locator('#analysisDiscussionNote').fill('@bo');
    await page.locator('#analysisDiscussionNote').press('Escape');
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'@bo');
    assert.equal(await page.locator('.review-mention-popover:visible').count(),0);
    await page.locator('#analysisDiscussionNote').fill('@bob reply with image');
    await page.evaluate(()=>addAnalysisDiscussionImages([new File(['invalid'], 'bad.gif',{type:'image/gif'})]));
    assert((await page.locator('#analysisDiscussionSubmitStatus').innerText()).includes('仅支持'));
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'@bob reply with image');
    // A historical author outside the current directory remains replyable.
    await page.evaluate(()=>{state.mentionUsers=[];$('#analysisDiscussionNote').value='';beginAnalysisDiscussionReply(117);});
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'');
    assert.equal(await page.evaluate(()=>state.analysisDiscussion.replyTo.id),117);
    await page.evaluate(()=>{state.mentionUsers=[{username:'bob',enabled:true},{username:'carol',enabled:true}];beginAnalysisDiscussionReply(117);});
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'@bob ');
    await page.locator('[data-comment-reply="119"]').click();
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'@carol ');
    await page.locator('[data-cancel-comment-reply]').click();
    assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),'');
    // Replying from Markdown preview returns to the editor.
    await page.evaluate(()=>{toggleAnalysisDiscussionPreview();beginAnalysisDiscussionReply(117);});
    assert(await page.locator('#analysisDiscussionNote').isVisible());
    assert.equal(await page.evaluate(()=>state.analysisDiscussion.preview),false);
    await page.locator('#analysisDiscussionNote').fill('@bob 输入法测试');
    const beforeIme=await page.locator('#analysisDiscussionSubmit').boundingBox();
    await page.locator('#analysisDiscussionNote').dispatchEvent('compositionstart');
    const duringIme=await page.locator('#analysisDiscussionSubmit').boundingBox();
    await page.locator('#analysisDiscussionNote').dispatchEvent('compositionend');
    const afterIme=await page.locator('#analysisDiscussionSubmit').boundingBox();
    assert.equal(duringIme.y,beforeIme.y); assert.equal(afterIme.y,beforeIme.y);
    // Any real scope change still blocks posts and gives an explanation inside the modal.
    for(const [key,value] of [['issue','cn456'],['run','run2'],['work_split','campaign-other'],['baselines','other'],['task','campaign-other'],['campaign','campaign-other'],['dataset','other'],['case','other']]) {
      await setup(); await page.locator('#analysisDiscussionNote').fill(draft);
      await page.evaluate(({key,value})=>{const next=new URL(location.href);next.searchParams.set(key,value);history.replaceState({},'',next);},{key,value});
      await page.locator('#analysisDiscussionSubmit').click();
      assert.equal(await page.evaluate(()=>posts.length),0);
      assert(await page.locator('#analysisDiscussionSubmitStatus').isVisible());
      assert.equal(await page.locator('#analysisDiscussionNote').inputValue(),draft);
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:results,scenarios:['reply pointerdown/blur/pointerup target stable','route serialization','pending/duplicate','reply success','error visible in modal','draft and reply retry','mention selection/Escape','disabled directory author','attachment validation','runtime language switch','scope change rejected']}));
  } finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
