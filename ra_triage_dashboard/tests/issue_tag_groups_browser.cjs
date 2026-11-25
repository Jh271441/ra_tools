// Actual shell/modules/styles and built-in catalog; synthetic state, no business writes.
// Run with Playwright available through NODE_PATH.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../static');
const source = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = [...source.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = fs.readFileSync(path.join(root, 'js/MANIFEST'), 'utf8').split('\n')
  .map(s => s.trim()).filter(s => s && !s.startsWith('#') && s !== 'bind-bootstrap.js');
const catalog = JSON.parse(execFileSync('python3', ['-c',
  'import json,runpy,sys; print(json.dumps(runpy.run_path(sys.argv[1])["REVIEW_TAG_CATALOG"]))',
  path.join(root, '../app/runtime_catalogs.py')], {encoding: 'utf8'}));
const html = source.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
  .replaceAll('{{RA_TRIAGE_BASE_PATH}}', '')
  .replace('</head>', styles.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('') + '</head>')
  .replace('</body>', modules.map(p => `<script src="/static/js/${p}"></script>`).join('') + '</body>');
const server = http.createServer((req, res) => {
  if (req.method !== 'GET') return res.writeHead(405).end();
  const pathname = new URL(req.url, 'http://localhost').pathname;
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
  const output = process.env.ISSUE_TAG_QA_OUTPUT || '/tmp/issue-tag-groups-qa';
  fs.mkdirSync(output, {recursive: true});
  try {
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage();
    page.setDefaultTimeout(6000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/review`);
    const bootstrap = fs.readFileSync(path.join(root, 'js/bind-bootstrap.js'), 'utf8');
    const start = bootstrap.indexOf('  document.addEventListener("click", () => closeAllMultiFilters());');
    const end = bootstrap.indexOf('  $("#resetReviewAnalysisButton")', start);
    assert.ok(start >= 0 && end > start);
    await page.addScriptTag({content: bootstrap.slice(start, end)});
    await page.evaluate(catalog => {
      state.config = {review_tag_catalog: catalog,
        baselines: [{id: 'version-20261009', scope: 'fixture', label: '1009'}]};
      state.selectedBaselineIds = ['version-20261009'];
      state.session = {username: 'fixture', verified: true, access_role: 'writer', identity_pending: false};
      api = async () => ({});
      scheduleReviewFilterReload = () => history.replaceState({}, '', pageUrl('review'));
      loadCaseLabelingCases = async () => {};
      document.querySelectorAll('.multi-filter').forEach(root => renderMultiFilter(root));
      enhanceDashboardSelects();
    }, catalog);

    for (const width of [320, 390, 1440]) for (const lang of ['zh', 'en'])
      for (const theme of ['dark', 'light']) for (const view of ['review', 'labeling']) {
        await page.setViewportSize({width, height: 1000});
        await page.evaluate(({view, lang, theme}) => {
          closeAllMultiFilters();
          state.activePage = view;
          state.reviewIssueTags = ['gate'];
          state.caseLabeling.issueTags = ['gate'];
          state.caseLabeling.page = 3;
          document.documentElement.dataset.sessionPending = 'false';
          applyColorTheme(theme, {persist: false});
          document.body.dataset.activePage = view;
          document.querySelectorAll('.app-page').forEach(p => p.classList.toggle('hidden', p.dataset.page !== view));
          document.querySelector('#filterForm').classList.add('is-open');
          document.querySelector('#caseLabelingFilterForm').classList.add('is-open');
          applyUiLanguage(lang, {persist: false});
          renderReviewIssueTagFilter();
          renderCaseLabelingStatusPicker();
          history.replaceState({}, '', pageUrl(view));
        }, {view, lang, theme});
        const selector = view === 'review' ? '#reviewIssueTagFilter' : '#caseLabelingIssueTagFilter';
        const picker = page.locator(selector), trigger = picker.locator('.multi-filter-trigger');
        const search = picker.locator('.multi-filter-search');
        await trigger.scrollIntoViewIfNeeded();
        await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
        await trigger.press('Enter');
        await search.fill('');
        const geometry = await picker.evaluate(root => {
          const box = el => {
            const r = el.getBoundingClientRect();
            return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, height: r.height};
          };
          return {panel: box(root.querySelector('.multi-filter-panel')),
            options: box(root.querySelector('.multi-filter-options')),
            jumps: [...root.querySelectorAll('[data-multi-group-jump]')].map(box)};
        });
        assert.equal(geometry.jumps.length, 6, 'all six groups have direct entry points');
        assert.ok(geometry.panel.left >= 0 && geometry.panel.right <= width + 1 && geometry.panel.bottom <= 1001);
        for (const jump of geometry.jumps) {
          assert.ok(jump.top >= geometry.options.top && jump.bottom <= geometry.options.bottom, 'all group entries visible on open');
          if (width < 640) assert.ok(jump.height >= 44, 'phone group target');
        }
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        if ((width === 320 && lang === 'en' && theme === 'light') || (width === 1440 && lang === 'zh' && theme === 'dark')) {
          await page.screenshot({path: path.join(output, `${view}-${width}-${lang}-${theme}.png`)});
          await picker.locator('.multi-filter-panel').screenshot({path: path.join(output, `${view}-${width}-${lang}-${theme}-panel.png`)});
        }
        const scrollY = await page.evaluate(() => window.scrollY);
        await picker.locator('[data-multi-group-jump="1"]').press('Enter');
        assert.equal(await page.evaluate(() => document.activeElement.value), 'intent_straight');
        assert.equal(await page.evaluate(() => window.scrollY), scrollY, 'jump scrolls only the menu');
        await page.keyboard.press('Space');
        await page.waitForFunction(() => new URL(location.href).searchParams.get('issue_tags') === 'gate,intent_straight');
        assert.equal(new URL(page.url()).searchParams.get('issue_tags'), 'gate,intent_straight', JSON.stringify(await picker.evaluate(root => ({
          selected: getMultiFilterValues(root), review: state.reviewIssueTags, labeling: state.caseLabeling.issueTags,
          active: document.activeElement.outerHTML, view: state.activePage,
        }))));
        if (view === 'labeling') assert.equal(await page.evaluate(() => state.caseLabeling.page), 1);
        await search.fill('intent_');
        assert.equal(await picker.locator('[data-multi-group-jump]:visible').count(), 1);
        await picker.locator('[data-multi-select-all]').click();
        assert.equal(await picker.locator('input:checked').count(), 5, 'search all preserves selected environment');
        await picker.locator('[data-multi-invert]').click();
        assert.equal(await picker.locator('input:checked').count(), 1);
        assert.equal(await picker.locator('[data-multi-value="gate"]').isChecked(), true);
        // Locale refresh preserves the live search, selection, focused node and URL.
        await search.focus();
        const url = page.url();
        await page.evaluate(lang => applyUiLanguage(lang === 'zh' ? 'en' : 'zh', {persist: false}), lang);
        assert.equal(await search.inputValue(), 'intent_');
        assert.equal(await search.evaluate(el => el === document.activeElement), true);
        assert.equal(await picker.locator('[data-multi-value="gate"]').isChecked(), true);
        assert.equal(page.url(), url);
        assert.equal(await picker.locator('[data-multi-group-jump="1"]').innerText(), lang === 'zh' ? 'Ego intent' : '自车意图');
        await search.fill('no-matching-issue-tag');
        assert.equal(await picker.locator('[data-multi-search-empty]').isVisible(), true);
        assert.equal(await picker.locator('.multi-filter-group-nav').isVisible(), false);
        await search.fill('');
        await picker.locator('[data-multi-group-jump="5"]').click();
        assert.equal(await page.evaluate(() => document.activeElement.value), 'lead_vehicle_departed');
        await page.keyboard.press('Space');
        await page.waitForFunction(() => new URL(location.href).searchParams.get('issue_tags') === 'gate,lead_vehicle_departed');
        assert.equal(new URL(page.url()).searchParams.get('issue_tags'), 'gate,lead_vehicle_departed');
        await page.keyboard.press('Escape');
        assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
        await trigger.click();
        assert.equal(await picker.locator('.multi-filter-options').evaluate(el => el.scrollTop), 0, 'reopen shows group navigation');
        await picker.locator('[data-multi-clear]').click();
        assert.equal(new URL(page.url()).searchParams.has('issue_tags'), false);
        await page.mouse.click(1, 1);
        assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
        results.push({width, lang, theme, view});
      }
    // Empty catalog during loading, and a selected retired/unknown key, remain usable.
    await page.evaluate(() => {
      state.config.review_tag_catalog = [];
      state.reviewIssueTags = [];
      renderReviewIssueTagFilter();
    });
    assert.equal(await page.locator('#reviewIssueTagFilter [data-multi-group-jump]').count(), 0);
    await page.evaluate(() => {state.reviewIssueTags = ['retired-key']; renderReviewIssueTagFilter();});
    assert.equal(await page.locator('#reviewIssueTagFilter [data-multi-value="retired-key"]').isChecked(), true);
    assert.deepEqual(errors, []);
    const result = {browser: browser.version(), checks: results.length, results, errors};
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
