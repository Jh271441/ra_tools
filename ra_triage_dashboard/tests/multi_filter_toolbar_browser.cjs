// Read-only fixture using the actual shared component and stylesheet load order.
// Run with Playwright available via NODE_PATH.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../static');
const shell = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = [...shell.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = ['core-base', 'i18n-messages', 'i18n', 'format-api', 'session-config'];
const html = `<html data-ui-lang="zh"><head><meta name="viewport" content="width=device-width,initial-scale=1">${styles.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('')}</head><body><div style="padding:16px;width:240px;max-width:calc(100vw - 32px)"><label>Issue tags<div id="reviewIssueTagFilter" class="multi-filter" data-placeholder="全部 Issue 标签" data-placeholder-en="All Issue tags"></div></label></div>${modules.map(p => `<script src="/static/js/${p}.js"></script>`).join('')}</body></html>`;
const server = http.createServer((req, res) => {
  if (req.method !== 'GET') return res.writeHead(405).end();
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (!pathname.startsWith('/static/')) {res.setHeader('Content-Type', 'text/html; charset=utf-8'); return res.end(html);}
  const file = path.resolve(root, pathname.slice(8));
  if (!file.startsWith(root + '/') || !fs.existsSync(file)) return res.writeHead(404).end();
  res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage(), errors = [], results = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/review`);
    const selected = () => page.evaluate(() => getMultiFilterValues(document.querySelector('#reviewIssueTagFilter')));
    for (const width of [1440, 390, 320]) for (const lang of ['zh', 'en']) for (const theme of ['dark', 'light']) {
      await page.setViewportSize({width, height:800});
      for (const searchable of [true, false]) {
        await page.evaluate(({lang, theme, searchable}) => {
          closeAllMultiFilters();
          state.uiLanguage = lang;
          document.documentElement.dataset.uiLang = lang;
          document.documentElement.dataset.colorTheme = theme;
          renderMultiFilter(document.querySelector('#reviewIssueTagFilter'), {
            searchable, selected: [], groups: [{label: lang === 'en' ? 'Environment' : '环境', items:
              Array.from({length:60}, (_, i) => ({value:`tag-${i}`, label:i === 0 ? 'UniqueMatch' : (lang === 'en' ? `Long environment label ${i}` : `施工／变更区域 ${i}`)}))}],
          });
        }, {lang, theme, searchable});
        await page.locator('.multi-filter-trigger').click();
        assert.equal(await page.locator('[data-multi-select-all]').innerText(), lang === 'zh' ? '全选' : 'All');
        const geometry = await page.evaluate(() => {
          const box = selector => {const el=document.querySelector(selector),r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height,clientHeight:el.clientHeight,scrollHeight:el.scrollHeight};};
          return {toolbar:box('.multi-filter-toolbar'),actions:[...document.querySelectorAll('.multi-filter-action')].map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height};}), panel:box('.multi-filter-panel'),options:box('.multi-filter-options'),search:document.querySelector('.multi-filter-search') ? box('.multi-filter-search') : null};
        });
        for (const action of geometry.actions) {
          assert.ok(action.top >= geometry.toolbar.top && action.bottom <= geometry.toolbar.bottom, 'toolbar must fully contain buttons');
          if (width < 640) assert.ok(action.height >= 44, 'phone action hit target');
        }
        assert.ok(geometry.options.scrollHeight > geometry.options.clientHeight, 'long list must scroll');
        assert.ok(geometry.panel.left >= 0 && geometry.panel.right <= width && geometry.panel.bottom <= 800, 'panel inside viewport');
        if (searchable) {
          assert.ok(geometry.search.top >= geometry.toolbar.bottom, 'search below toolbar');
          await page.locator('.multi-filter-search').fill('UniqueMatch');
        }
        await page.locator('[data-multi-select-all]').click();
        assert.equal((await selected()).length, searchable ? 1 : 60);
        await page.locator('[data-multi-invert]').click();
        assert.equal((await selected()).length, 0);
        await page.locator('[data-multi-select-all]').click();
        await page.locator('[data-multi-clear]').click();
        assert.equal((await selected()).length, 0);
        if (searchable) {
          await page.locator('.multi-filter-search').fill('no-matching-tag');
          assert.equal(await page.locator('[data-multi-search-empty]').isVisible(), true);
          await page.locator('.multi-filter-search').fill('');
        }
        const toolbarTop = await page.locator('.multi-filter-toolbar').evaluate(el => el.getBoundingClientRect().top);
        await page.locator('.multi-filter-options').evaluate(el => {el.scrollTop = 300;});
        assert.equal(await page.locator('.multi-filter-toolbar').evaluate(el => el.getBoundingClientRect().top), toolbarTop);
        if (searchable && theme === 'dark' && lang === 'zh') await page.screenshot({path:`/tmp/multi-filter-toolbar-${width}.png`});
        await page.locator('.multi-filter-trigger').click();
        assert.equal(await page.locator('.multi-filter-panel').isVisible(), false);
        results.push({width,lang,theme,searchable,toolbarHeight:geometry.toolbar.height});
      }
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({checks:results.length,errors,results}));
  } finally {await browser.close();server.close();}
})().catch(error => {console.error(error);server.close();process.exitCode=1;});
