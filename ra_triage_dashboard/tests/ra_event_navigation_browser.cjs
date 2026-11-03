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
  const results = [], errors = [], density = [];
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
      window.clipboardWrites = [];
      window.fixtureClipboard = { writeText: async value => { window.clipboardWrites.push(value); } };
      Object.defineProperty(navigator, 'clipboard', { configurable:true, value:window.fixtureClipboard });
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
        const copy = dialog.locator('.ra-event-copy-timestamp').first();
        assert.equal(await copy.evaluate(button => button.parentElement.className),'ra-event-relative-time ra-event-copy-anchor');
        assert.ok((await copy.getAttribute('aria-label')).includes(lang === 'zh' ? '复制时间戳' : 'Copy timestamp'));
        await copy.scrollIntoViewIfNeeded();
        const dimensions = await copy.evaluate((button,mobile) => {
          const row = button.closest('tr');
          const link = row.querySelector(mobile ? '.ra-event-relative-time a' : '.ra-event-timestamp a');
          const r = button.getBoundingClientRect(), l = link.getBoundingClientRect();
          const height = row.getBoundingClientRect().height;
          const plain = row.cloneNode(true);
          plain.querySelectorAll('button').forEach(el => el.remove());
          plain.querySelectorAll('a').forEach(el => el.replaceWith(document.createTextNode(el.textContent)));
          plain.querySelectorAll('.ra-event-copy-cell').forEach(el => el.classList.remove('ra-event-copy-cell'));
          row.after(plain);
          const plainHeight = plain.getBoundingClientRect().height;
          plain.remove();
          return {height,plainHeight,copyWidth:r.width,copyHeight:r.height,overlap:r.left < l.right,
            decoration:getComputedStyle(link).textDecorationLine};
        },width < 640);
        assert.equal(dimensions.overlap,false);
        if (width === 1440) {
          assert.equal(dimensions.height,35);
          assert.equal(dimensions.height,dimensions.plainHeight);
        } else assert.ok(dimensions.copyWidth >= 44 && dimensions.copyHeight >= 44);
        density.push({width,lang,theme,view,...dimensions});
        const writesBefore = await page.evaluate(() => clipboardWrites.length);
        await copy.locator('svg').click();
        await page.waitForFunction(n => clipboardWrites.length === n + 1,writesBefore);
        assert.equal(await page.evaluate(() => clipboardWrites.at(-1)),'1788236481256');
        assert.equal(context.pages().length,1,'copy must not open Ares');
        assert.equal(await dialog.locator('#raEventCopyStatus').innerText(),
          lang === 'zh' ? '已复制时间戳：1788236481256' : 'Timestamp copied: 1788236481256');
        assert.equal(await copy.evaluate(el => el.closest('tr').getBoundingClientRect().height),dimensions.height);
        await copy.focus();
        await page.evaluate(lang => applyUiLanguage(lang === 'zh' ? 'en' : 'zh',{persist:false}),lang);
        assert.equal(await copy.evaluate(el => el === document.activeElement),true);
        assert.ok((await copy.getAttribute('title')).includes(lang === 'zh' ? 'Copy timestamp' : '复制时间戳'));
        assert.equal(await dialog.locator('#raEventCopyStatus').innerText(),
          lang === 'zh' ? 'Timestamp copied: 1788236481256' : '已复制时间戳：1788236481256');
        await page.evaluate(lang => applyUiLanguage(lang,{persist:false}),lang);
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
        const filteredCopy = dialog.locator('.ra-event-copy-timestamp').first();
        await filteredCopy.click();
        assert.equal(await page.evaluate(() => clipboardWrites.at(-1)),'1788236483556');
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
      missing.external_links.ra_events = [{event:'start',value:'unchanged',timestamp:1788236481256},
        ...[null,undefined,'',0,-1,'bad',Infinity,1.5,9000000000000000].map(timestamp => ({event:'bad',timestamp}))];
      openRaEventDialog(missing);
    });
    assert.equal(await page.locator('#raEventDialog .ra-event-playback-link').count(),0);
    assert.equal(await page.locator('#raEventDialog tbody tr').count(),10);
    assert.equal(await page.locator('#raEventDialog .ra-event-copy-timestamp').count(),1,'only valid timestamps get a copy action, even without a trip');
    const copy = page.locator('#raEventDialog .ra-event-copy-timestamp').first();
    await copy.click();
    assert.equal(await page.evaluate(() => clipboardWrites.at(-1)),'1788236481256');

    // Permission denial leaves the dialog and focus usable; feedback is localized.
    await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw new Error('denied'); }; });
    await copy.click();
    await page.waitForFunction(() => state.raEventDialog.copyStatus?.key === 'ra_event.copy_failed');
    assert.equal(await copy.evaluate(el => el === document.activeElement),true);
    await page.setViewportSize({width:320,height:900});
    await page.evaluate(() => applyUiLanguage('en',{persist:false}));
    assert.equal(await page.locator('#raEventCopyStatus').innerText(),'Copy failed. Check your browser clipboard permissions.');
    const failedBounds = await page.locator('#raEventDialog').evaluate(el => ({
      right:el.getBoundingClientRect().right,bottom:el.getBoundingClientRect().bottom,
      footer:el.querySelector('.dialog-actions').getBoundingClientRect().bottom,
      documentWidth:document.documentElement.scrollWidth,
    }));
    assert.ok(failedBounds.right <= 321 && failedBounds.bottom <= 901 && failedBounds.footer <= 901 && failedBounds.documentWidth <= 321);

    // The legacy fallback must select inside the native modal and restore focus.
    await page.evaluate(() => {
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});
      window.fallbackCopies = [];
      document.execCommand = command => {
        const input = document.activeElement;
        fallbackCopies.push({command,value:input.value,inModal:!!input.closest('#raEventDialog'),
          selection:input.value.slice(input.selectionStart,input.selectionEnd)});
        return true;
      };
    });
    await copy.click();
    assert.deepEqual(await page.evaluate(() => fallbackCopies.at(-1)),{
      command:'copy',value:'1788236481256',inModal:true,selection:'1788236481256',
    });
    assert.equal(await copy.evaluate(el => el === document.activeElement),true);
    assert.equal(await page.locator('#raEventDialog textarea').count(),0);
    await page.evaluate(() => { document.execCommand = () => false; });
    await copy.click();
    await page.waitForFunction(() => state.raEventDialog.copyStatus?.key === 'ra_event.copy_failed');
    assert.equal(await page.locator('#raEventDialog textarea').count(),0);
    assert.equal(await copy.evaluate(el => el === document.activeElement),true);

    // Breakpoint changes reposition the same node without losing keyboard focus.
    await page.evaluate(() => { window.savedCopyButton = document.querySelector('.ra-event-copy-timestamp'); });
    for (const width of [640,639,768,320,1440]) {
      await copy.focus();
      await page.setViewportSize({width,height:900});
      await page.waitForFunction(mobile => window.matchMedia('(max-width: 639px)').matches === mobile,width < 640);
      assert.equal(await copy.evaluate(el => el === window.savedCopyButton && el === document.activeElement),true,
        JSON.stringify({width,...await copy.evaluate(el => ({sameNode:el === window.savedCopyButton,
          parent:el.parentElement.className,active:document.activeElement.outerHTML.slice(0,180)}))}));
      assert.equal(await page.locator('#raEventDialog .ra-event-copy-timestamp').count(),1);
    }
    await page.evaluate(() => {
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value => clipboardWrites.push(value)}});
    });
    await page.locator('#raEventDialog [data-close]').first().click();
    await page.waitForFunction(() => !document.querySelector('#raEventDialog').open && !state.raEventDialog.issueId);
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
    await page.locator('#raEventDialog .ra-event-copy-timestamp').last().click();
    assert.equal(await page.evaluate(() => clipboardWrites.at(-1)),'1788236535286','refreshed rows keep copy behavior');
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
    const result = {browser:browser.version(),checks:results.length,metadataRequests,refreshRequests,refreshChecks:4,
      copyChecks:['raw milliseconds','no navigation','filtered rows','refreshed rows','locale and focus','missing trip',
        'invalid timestamps','permission denial','modal fallback','fallback failure','breakpoint identity and focus'],results,density,errors};
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
