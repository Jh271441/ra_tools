// Synthetic read-only browser proof; never posts comments or sends notifications.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../static');
const original = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = [...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = ['core-base', 'i18n-messages', 'i18n', 'format-api', 'session-config', 'work-split', 'runs', 'trail-update-state', 'review-mentions', 'analysis', 'routing'];
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
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const url = `http://127.0.0.1:${server.address().port}/review?issue=cn123&run=run1&work_split=campaign-test&baselines=fixture&comments=1&channel=case&source=combined_review&comment=117`;
    const setup = async (lang='zh', theme='dark') => page.evaluate(async ({lang,theme}) => {
      state.uiLanguage=lang;
      document.documentElement.dataset.uiLang=lang;
      document.documentElement.dataset.colorTheme=theme;
      document.documentElement.dataset.sessionPending='false';
      document.body.dataset.activePage='review';
      state.activePage='review'; state.selectedId='cn123'; state.selectedRunId='run1';
      state.reviewWorkSplitId='campaign-test'; state.selectedBaselineIds=['fixture'];
      state.selectedCase={issue_id:'cn123',review_assignment:{split_id:'campaign-test',model_run_id:'run1'}};
      state.session={username:'alice',verified:true,can_write:true,access_role:'writer'};
      window.requested=[];
      api=async (path, options) => {
        if(options?.method && options.method!=='GET') throw Error('No writes allowed');
        window.requested.push(path);
        return {count:2,task:{id:'campaign-test',name:'联合复核 / Combined review',read_only:false},comments:[
          {id:114,discussion_channel:'case',author:'alice',author_verified:true,body:'Issue 标签 #3238 · 标注依据 / Label rationale\nReason @bob',created_at:'2026-10-29T04:15:22+00:00'},
          {id:117,discussion_channel:'case',author:'bob',author_verified:true,body:'从触发角度讲偏误触发 / More likely a false trigger',reply_to_id:114,reply_to_author:'alice',reply_to_body:'Label rationale',created_at:'2026-10-29T06:14:27+00:00'}]};
      };
      applyDomI18n(document);
      await openReviewRouteDiscussion(parsePageRoute());
    },{lang,theme});
    for(const width of [1440,390,320]) for(const lang of ['zh','en']) for(const theme of ['dark','light']) {
      await page.setViewportSize({width,height:900});
      await page.goto(url);
      await setup(lang,theme);
      assert.equal(await page.evaluate(()=>state.analysisDiscussion.status),'ready');
      assert.equal(await page.locator('#analysisDiscussionThread [data-comment-id="117"].is-deep-linked').count(),1);
      assert.equal(await page.evaluate(()=>state.analysisDiscussion.kind),'issue');
      assert.ok((await page.evaluate(()=>window.requested)).every(p=>p==='/api/cases/cn123/discussion'));
      const box=await page.locator('#analysisDiscussionDialog').boundingBox();
      assert.ok(box && box.x>=0 && box.x+box.width<=width+1 && box.y>=0 && box.y+box.height<=901,JSON.stringify({width,lang,theme,box}));
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.equal(await page.locator('#analysisDiscussionChannel').isVisible(),false,'shared enhanced select');
      if(width===390 && lang==='en' && theme==='light') await page.screenshot({path:'/tmp/comment-source-mobile.png'});
      if(width===1440 && lang==='zh' && theme==='dark') await page.screenshot({path:'/tmp/comment-source-desktop.png'});
    }
    // Canonicalize, reload and restore browser history using the real route parser.
    await page.evaluate(()=>history.replaceState({},'',pageUrl('review')));
    assert.equal(new URL(page.url()).searchParams.get('comment'),'117');
    await page.reload(); await setup();
    assert.equal(await page.locator('[data-comment-id="117"].is-deep-linked').count(),1);
    await page.goto(url.replace('cn123','cn456'));
    await page.goBack(); await setup();
    assert.equal(await page.evaluate(()=>state.analysisDiscussion.issueId),'cn123');
    // Old model-review links keep their independent Run thread.
    await page.evaluate(async()=>{closeAnalysisDiscussion();await openReviewRouteDiscussion({issue:'cn123',runId:'run1',commentId:117});});
    assert.equal(await page.evaluate(()=>state.analysisDiscussion.kind),'issue');
    assert.ok((await page.evaluate(()=>window.requested)).at(-1).includes('/api/cases/cn123/discussion'));
    assert.deepEqual(errors,[]);
    console.log('PASS: 12 viewport/language/theme combinations; Issue vs Run endpoint, comment focus, URL refresh/history, shared select; synthetic data, no sends.');
  } finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
