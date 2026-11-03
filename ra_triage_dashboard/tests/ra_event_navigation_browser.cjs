// Actual shell, ordered modules and CSS; synthetic Case data, no Trail traffic.
// NODE_PATH=<directory containing playwright> node this-file.cjs
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../static');
const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = [...source.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = fs.readFileSync(path.join(root, 'js/MANIFEST'), 'utf8').split('\n')
  .map(s => s.trim()).filter(s => s && !s.startsWith('#') && s !== 'bind-bootstrap.js');
const html = source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
  .replaceAll('{{RA_TRIAGE_BASE_PATH}}', '')
  .replace('</head>', styles.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('') + '</head>')
  .replace('</body>', modules.map(p => `<script src="/static/js/${p}"></script>`).join('') + '</body>');
let metadataRequests = 0;
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname.startsWith('/api/')) {
    if (pathname.endsWith('/trail-metadata')) metadataRequests++;
    res.setHeader('Content-Type', 'application/json');
    return res.end('{}');
  }
  if (!pathname.startsWith('/static/')) {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    return res.end(html);
  }
  const file = path.resolve(root, pathname.slice(8));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8');
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  const results = [], errors = [];
  const output = process.env.RA_EVENT_QA_OUTPUT || '/tmp/ra-event-navigation-qa';
  fs.mkdirSync(output, {recursive:true});
  try {
    browser = await chromium.launch({headless:true});
    const context = await browser.newContext();
    await context.route('https://voyager.intra.xiaojukeji.com/**', route => route.fulfill({
      contentType:'text/html', body:'<title>Intercepted Ares playback destination</title>',
    }));
    const page = await context.newPage();
    page.setDefaultTimeout(6000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/review`);
    const bootstrap = fs.readFileSync(path.join(root, 'js/bind-bootstrap.js'), 'utf8');
    const start = bootstrap.indexOf('  $("#raEventSearchInput").addEventListener');
    const end = bootstrap.indexOf('  $("#importFile").addEventListener', start);
    assert.ok(start >= 0 && end > start);
    await page.addScriptTag({content:bootstrap.slice(start, end)});
    await page.evaluate(() => {
      state.config = {baselines:[], review_tag_catalog:[]};
      state.session = {username:'fixture', verified:true, access_role:'writer', identity_pending:false};
      document.documentElement.dataset.sessionPending = 'false';
      document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.close)));
      window.fixtureCase = {
        issue_id:'cn35759965',
        assets:{capture:{trip_id:'fixture_trip',timestamp_ms:1788236483601}},
        external_links:{
          ra_event_url:'https://voyager.intra.xiaojukeji.com/issue/cn35759965?view_id=2410',
          ra_events:Array.from({length:24}, (_, i) => ({
            event:i === 0 ? 'stationary' : 'waypoint',
            value:i === 0 ? null : 'kPreparePoints_long_event_value_for_wrapping_' + i,
            timestamp:1788236481256 + i * 2300,
          })),
        },
      };
    });
    for (const width of [320,390,1440]) for (const lang of ['zh','en'])
      for (const theme of ['dark','light']) for (const view of ['review','labeling']) {
        await page.setViewportSize({width,height:900});
        await page.evaluate(({lang,theme,view}) => {
          state.activePage = view;
          document.body.dataset.activePage = view;
          document.querySelectorAll('.app-page').forEach(p => p.classList.toggle('hidden',p.dataset.page !== view));
          document.querySelector(view === 'review' ? '#reviewDetailView' : '#caseLabelingDetail').classList.remove('hidden');
          applyColorTheme(theme,{persist:false});
          applyUiLanguage(lang,{persist:false});
          document.querySelector('#fixtureExternalLinks')?.remove();
          const host = document.querySelector(view === 'review' ? '#detailPane' : '#caseLabelingMedia');
          host.innerHTML = '<div id="fixtureExternalLinks" class="detail-external-links">' + detailExternalLinksMarkup(fixtureCase) + '</div>';
          bindDetailExternalLinks(fixtureCase, host.querySelector('#fixtureExternalLinks'));
        }, {lang,theme,view});
        await page.locator('#fixtureExternalLinks [data-open-ra-event]').click();
        const dialog = page.locator('#raEventDialog');
        await dialog.waitFor({state:'visible'});
        assert.equal(await dialog.locator('tbody tr').count(),24);
        const geometry = await dialog.evaluate(el => {
          const r = el.getBoundingClientRect();
          const actions = el.querySelector('.dialog-actions').getBoundingClientRect();
          const wrapper = el.querySelector('.ra-event-table-wrap');
          return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,actionsBottom:actions.bottom,
            documentWidth:document.documentElement.scrollWidth,innerWidth,
            tableScroll:wrapper.scrollHeight > wrapper.clientHeight};
        });
        assert.ok(geometry.left >= 0 && geometry.right <= width + 1, JSON.stringify(geometry));
        assert.ok(geometry.top >= 0 && geometry.bottom <= 901 && geometry.actionsBottom <= 901);
        assert.ok(geometry.documentWidth <= width + 1 && geometry.tableScroll);
        const relative = dialog.locator('.ra-event-relative-time a').first();
        await relative.scrollIntoViewIfNeeded();
        const eventUrl = new URL(await relative.getAttribute('href'));
        assert.equal(Number(eventUrl.searchParams.get('ds.start')),1788236471256);
        assert.equal(Number(eventUrl.searchParams.get('ds.end')),1788236491256);
        if (width < 640) assert.ok((await relative.boundingBox()).height >= 44);
        if (width === 1440 && lang === 'zh' && theme === 'dark' && view === 'review') {
          const [popup] = await Promise.all([context.waitForEvent('page'), relative.click()]);
          await popup.waitForLoadState();
          assert.equal(popup.url(),eventUrl.href);
          await popup.close();
          await page.bringToFront();
        }
        const search = page.locator('#raEventSearchInput');
        await search.fill('kPreparePoints');
        assert.equal(await dialog.locator('tbody tr').count(),23);
        await search.focus();
        const url = page.url();
        await page.evaluate(lang => applyUiLanguage(lang === 'zh' ? 'en' : 'zh',{persist:false}),lang);
        assert.equal(await search.inputValue(),'kPreparePoints');
        assert.equal(await search.evaluate(el => el === document.activeElement),true);
        assert.equal(page.url(),url);
        assert.ok((await dialog.locator('.ra-event-relative-time a').first().getAttribute('title'))
          .includes(lang === 'zh' ? 'new tab' : '新标签页'));
        await search.fill('no-matching-event');
        assert.equal(await page.locator('#raEventEmpty').isVisible(),true);
        assert.equal(await page.locator('#raEventEmpty').innerText(),lang === 'zh' ? 'No matching RA Events.' : '没有匹配的 RA Event。');
        await search.fill('');
        if ((width === 320 && lang === 'zh' && theme === 'light' && view === 'review') ||
            (width === 1440 && lang === 'en' && theme === 'dark' && view === 'review')) {
          await dialog.screenshot({path:path.join(output,`${view}-${width}-${lang === 'zh' ? 'en' : 'zh'}-${theme}.png`)});
        }
        await page.keyboard.press('Escape');
        await dialog.waitFor({state:'hidden'});
        results.push({width,lang,theme,view});
      }
    await page.evaluate(() => {
      const missing = structuredClone(fixtureCase);
      missing.assets.capture.trip_id = '';
      missing.external_links.ra_events = [{event:'start',value:'unchanged',timestamp:1788236481256},{event:'bad',timestamp:null}];
      openRaEventDialog(missing);
    });
    assert.equal(await page.locator('#raEventDialog .ra-event-playback-link').count(),0);
    assert.equal(await page.locator('#raEventDialog tbody tr').count(),2);
    await page.locator('#raEventDialog [data-close]').first().click();
    assert.equal(metadataRequests,0,'open, search and language changes use the Case payload');

    // Explicit refresh uses the HTTP client, preserves search, and rejects
    // obsolete dialog responses. A failed refresh retains the last good rows.
    let refreshRequests = 0, refreshMode = 'ready';
    const updated = await page.evaluate(() => ({issue_id:fixtureCase.issue_id,status:'ready',refresh_status:'ready',
      external_links:{...fixtureCase.external_links,ra_events:[...fixtureCase.external_links.ra_events,
        {event:'waypoint',value:'new-event',timestamp:1788236535286}]}}));
    await page.route('**/api/cases/*/trail-metadata?refresh=true', async route => {
      refreshRequests++;
      const mode = refreshMode;
      await new Promise(resolve => setTimeout(resolve,200));
      await route.fulfill({contentType:'application/json',body:JSON.stringify(mode === 'ready' ? updated :
        {issue_id:updated.issue_id,status:'unavailable',refresh_status:'unavailable',external_links:{}})});
    });
    await page.setViewportSize({width:320,height:900});
    await page.evaluate(() => {applyUiLanguage('en',{persist:false}); applyColorTheme('light',{persist:false}); openRaEventDialog(fixtureCase);});
    await page.locator('#raEventSearchInput').fill('waypoint');
    const refresh = page.locator('#raEventRefreshButton');
    await refresh.click();
    assert.equal(await refresh.isDisabled(),true);
    await page.evaluate(() => document.querySelector('#raEventRefreshButton').click());
    await page.locator('#raEventRefreshStatus').filter({hasText:'Updated'}).waitFor();
    assert.equal(refreshRequests,1,'busy button cannot duplicate a refresh');
    assert.equal(await page.locator('#raEventSearchInput').inputValue(),'waypoint');
    assert.equal(await page.locator('#raEventDialog tbody tr').count(),24);
    refreshMode = 'unavailable';
    await refresh.click();
    await page.locator('#raEventRefreshStatus').filter({hasText:'Previous data was kept'}).waitFor();
    assert.equal(await page.locator('#raEventDialog tbody tr').count(),24);
    const failureBounds = await page.locator('#raEventDialog').evaluate(el => {
      const r = el.getBoundingClientRect();
      return {left:r.left,right:r.right,bottom:r.bottom,buttonHeight:el.querySelector('#raEventRefreshButton').getBoundingClientRect().height};
    });
    assert.ok(failureBounds.left >= 0 && failureBounds.right <= 321 && failureBounds.bottom <= 901 && failureBounds.buttonHeight >= 44);
    await page.evaluate(() => applyUiLanguage('zh',{persist:false}));
    assert.equal(await page.locator('#raEventRefreshStatus').innerText(),'刷新失败，已保留原有数据。');
    refreshMode = 'ready';
    await refresh.click();
    await page.locator('#raEventDialog [data-close]').first().click();
    await page.waitForFunction(() => !document.querySelector('#raEventDialog').open && !state.raEventDialog.issueId);
    await page.evaluate(() => openRaEventDialog({...fixtureCase,issue_id:'cn_another'}));
    await page.waitForTimeout(300);
    assert.equal(await page.locator('#raEventDialogMeta').innerText(),'25 条 · cn_another');
    assert.equal(await page.locator('#raEventRefreshStatus').isVisible(),false,'obsolete refresh cannot update another dialog');
    assert.deepEqual(errors,[]);
    const result = {browser:browser.version(),checks:results.length,metadataRequests,refreshRequests,refreshChecks:4,results,errors};
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
