const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../static');
const original = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = [...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = ['core-base', 'i18n-messages', 'i18n', 'format-api', 'session-config', 'work-split', 'run-comparison'];
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
    await page.goto(`http://127.0.0.1:${server.address().port}/review-analysis`);
    await page.evaluate(() => {
      window.fixtureItems = [];
      api = async () => ({ items: window.fixtureItems });
      selectedBaselineQueryValue = () => 'fixture';
      scheduleAnalysisFilterReload = () => {};
      state.selectedRunId = 'fixture-run';
      state.config = {};
      document.querySelectorAll('.multi-filter').forEach(root => renderMultiFilter(root));
      enhanceDashboardSelects(document);
      document.querySelector('#runCollectionsWorkbench').hidden = true;
      document.querySelector('#comparisonEmptyState').hidden = true;
      window.fixtureSummary = { summary: { baseline: { accuracy: 0, total_count: 598 }, candidate: { accuracy: 307 / 598, total_count: 598, correct_count: 307, prediction_count: 598 }, accuracy_delta: 307 / 598, transition_counts: { F2P: 307 }, total_count: 598, label_changed_count: 598 }, gt_references: Array.from({length: 20}, (_, i) => ({baseline_scope: 'manual_sidecar_' + i, reference_type: 'gt_snapshot', snapshot_id: 'gt-fixture'})) };
    });
    const results = [];
    for (const width of [1440, 390, 320]) for (const lang of ['zh', 'en']) for (const theme of ['dark', 'light']) {
      await page.setViewportSize({width, height: 1000});
      for (const view of ['analysis', 'comparison']) {
        await page.evaluate(async ({view, lang, theme}) => {
          state.uiLanguage = lang;
          document.documentElement.dataset.uiLang = lang;
          document.documentElement.dataset.colorTheme = theme;
          document.documentElement.dataset.sessionPending = 'false';
          document.body.dataset.activePage = view;
          document.querySelectorAll('.app-page').forEach(p => p.classList.toggle('hidden', p.dataset.page !== view));
          document.querySelector('#reviewAnalysisFilterForm').classList.add('is-open');
          document.querySelector('#comparisonResults').classList.remove('hidden');
          applyDomI18n(document);
          await loadAnalysisWorkSplits({force: true});
          renderRunComparisonSummary(window.fixtureSummary);
        }, {view, lang, theme});
        assert.equal(await page.locator('#analysisWorkSplitHint, #comparisonGtReference').count(), 0);
        const bounds = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
        assert.ok(bounds.scroll <= width + 1, JSON.stringify({view, lang, theme, bounds}));
        assert.equal(await page.locator('#comparisonSummary .comparison-metric').count(), 6);
        if (view === 'analysis') {
          const info = page.locator('#analysisScopeInfo button');
          await page.mouse.move(0, 0);
          await info.click();
          assert.equal(await info.getAttribute('aria-expanded'), 'true');
          const tip = page.locator('#analysisScopeInfoPanel');
          await tip.waitFor({state: 'visible'});
          assert.equal(await tip.isVisible(), true);
          const box = await tip.boundingBox();
          assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= width && box.y + box.height <= 1000);
          assert.equal(await info.getAttribute('aria-label'), lang === 'en' ? 'About Review data scope' : 'Review 数据范围说明');
          if (width < 640) { const hit = await info.boundingBox(); assert.ok(hit.width >= 44 && hit.height >= 44); }
          await page.keyboard.press('Escape');
          assert.equal(await info.getAttribute('aria-expanded'), 'false');
          await tip.waitFor({state: 'hidden'});
          assert.equal(await tip.isVisible(), false);
          await info.click();
          await page.locator('#analysisIssueInput').click();
          assert.equal(await info.getAttribute('aria-expanded'), 'false');
          const trigger = page.locator('#analysisWorkSplitPicker .ui-select-trigger');
          await trigger.click();
          await page.keyboard.press('Escape');
          assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
        }
        results.push({view, width, lang, theme, bounds});
        if ((width === 1440 && lang === 'zh' && theme === 'dark') || (width === 320 && lang === 'en' && theme === 'light'))
          await page.screenshot({path: `/tmp/trim-hints-${view}-${width}.png`, fullPage: false});
      }
    }
    await page.evaluate(async () => {
      window.fixtureItems = [{split_id: 'task-fixture', name: 'Fixture task', assignment_count: 2, completed_count: 1}];
      state.reviewAnalysis.workSplitId = 'task-fixture';
      await loadAnalysisWorkSplits({force: true});
    });
    assert.equal(await page.locator('#analysisWorkSplitFilter').inputValue(), 'task-fixture');
    await page.evaluate(async () => { window.fixtureItems = []; await loadAnalysisWorkSplits({force: true}); });
    assert.equal(await page.locator('#analysisWorkSplitFilter').inputValue(), 'task-fixture');
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({checks: results.length, preservedSelection: true, errors, results}));
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
