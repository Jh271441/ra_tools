// Run with Playwright available in NODE_PATH. Uses real DOM, source modules and CSS;
// makes no API requests and never submits a product form.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { chromium } = require('playwright');
const staticDir = path.resolve(__dirname, '../static');
const read = name => fs.readFileSync(path.join(staticDir, name), 'utf8');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    page.setDefaultTimeout(8000);
    const errors = [];
    page.on('pageerror', e => { errors.push(e.message); console.error('PAGE:', e.message); });
    const html = read('index.html');
    await page.setContent(html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replace(/(<meta name="ra-triage-base" content=")[^"]*/, '$1'));
    await page.addStyleTag({content:'body {visibility:visible!important;opacity:1!important}'});
    const styles = JSON.parse('[' + html.match(/const stylesheetPaths = \[([\s\S]*?)\];/)[1].replace(/,\s*$/, '') + ']');
    for (const file of styles) await page.addStyleTag({content: read(file)});
    for (const file of ['core-base', 'i18n-messages', 'i18n', 'format-api', 'session-config', 'detail-media']) {
      await page.addScriptTag({content: read(`js/${file}.js`)});
    }
    // Load the actual shared multi-filter dismissal bindings without app bootstrap/API.
    const bootstrap = read('js/bind-bootstrap.js');
    const start = bootstrap.indexOf('  document.addEventListener("click", () => closeAllMultiFilters());');
    const end = bootstrap.indexOf('  window.addEventListener("resize", () => closeAllMultiFilters());',start);
    await page.addScriptTag({content:'function hideAnalysisPieTooltip() {}\n' + bootstrap.slice(start,end) + 'window.addEventListener("resize", () => closeAllMultiFilters());'});
    console.log('Loaded modules');
    const inventory = await page.evaluate(() => {
      const selects = [...document.querySelectorAll('select')];
      const native = selects.filter(s => !s.matches('.ui-select-native, .gateway-model-native-select'));
      const special = selects.filter(s => s.matches('.ui-select-native, .gateway-model-native-select'));
      const parents = special.map(s => s.parentElement);
      enhanceDashboardSelects(); observeDashboardSelects();
      return {total: selects.length, enhanced: native.length,
        missed: native.filter(s => !s.closest('.dashboard-native-ui-select')).map(s => s.id),
        specialPreserved: special.every((s, i) => s.parentElement === parents[i])};
    });
    console.log('Inventory', inventory);
    assert.deepEqual(inventory.missed, []); assert.equal(inventory.specialPreserved, true);
    await page.evaluate(() => {
      document.documentElement.dataset.colorTheme = 'dark';
      document.body.dataset.activePage = 'daily-review';
      document.querySelector('#dailyReviewScope').textContent='1009 · 2026-10-16 · CST';
      document.querySelectorAll('.app-page').forEach(el => el.hidden = true);
      const root = document.querySelector('#dailyReviewPage');
      root.hidden = false; root.classList.remove('hidden');
      document.querySelectorAll('.app-shell, .app-main, main').forEach(el => el.style.visibility = 'visible');
      const date = document.querySelector('#dailyReviewDate');
      date.innerHTML = '<option value="2026-10-15">2026-10-15</option><option value="2026-10-16">2026-10-16</option>';
      date.value = '2026-10-16'; enhanceNativeUiSelect(date);
    });
    console.log('Prepared daily page');
    const date = page.locator('#dailyReviewDate').locator('..');
    assert.equal(await date.locator('.ui-select-summary').textContent(), '2026-10-16');
    await date.locator('button.ui-select-trigger').click();
    const active = date.locator('[data-ui-select-value="2026-10-16"]');
    await active.focus();
    await page.evaluate(() => enhanceDashboardSelects());
    assert.equal(await active.evaluate(el => el === document.activeElement), true, 'unchanged refresh retains focus');
    await page.keyboard.press('ArrowUp'); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#dailyReviewDate').inputValue(), '2026-10-15');
    await date.locator('.ui-select-trigger').click(); await page.keyboard.press('Escape');
    assert.equal(await date.locator('.ui-select-panel').isVisible(), false);
    console.log('Keyboard done');
    // Native option nodes and metadata survive enhancement, including empty value.
    await page.evaluate(() => {
      const reason = document.querySelector('#dailyReviewReason');
      reason.innerHTML = '<option value="" data-preserved="yes">All</option><option value="low">Low</option>';
      reason.value = ''; window.originalOption = reason.options[0]; enhanceNativeUiSelect(reason);
    });
    assert.equal(await page.evaluate(() => document.querySelector('#dailyReviewReason').options[0] === window.originalOption), true);
    assert.equal(await page.locator('#dailyReviewReason').inputValue(), '');
    // Disabled/hidden state updates after render; a disabled open menu closes.
    await date.locator('.ui-select-trigger').click();
    await page.evaluate(() => document.querySelector('#dailyReviewDate').disabled = true);
    await page.waitForFunction(() => document.querySelector('#dailyReviewDate').closest('.ui-select').querySelector('button').disabled);
    assert.equal(await date.locator('.ui-select-panel').isVisible(), false);
    await page.evaluate(() => { const s = document.querySelector('#dailyReviewDate'); s.disabled = false; s.hidden = true; });
    await page.waitForFunction(() => document.querySelector('#dailyReviewDate').closest('.ui-select').hidden);
    await page.evaluate(() => document.querySelector('#dailyReviewDate').hidden = false);
    await page.waitForFunction(() => !document.querySelector('#dailyReviewDate').closest('.ui-select').hidden);
    console.log('Disabled/hidden done');
    // Actual dynamic access renderer and video template: no ID whitelist required.
    await page.evaluate(() => {
      state.accessUsers = [{username:'preview-user',role:'writer',intent_permission:'view'}];
      renderAccessUsers();
      const fixture = document.createElement('section'); fixture.id = 'dynamicSelectFixture';
      fixture.innerHTML = videoPlayerMarkup({url:'/preview.webm',duration_ms:40000});
      document.body.append(fixture);
    });
    await page.waitForFunction(() => [...document.querySelectorAll('[data-video-step],[data-video-rate],[data-access-role],[data-intent-permission]')].every(s => s.closest('.dashboard-native-ui-select')));
    assert.equal(await page.locator('[data-intent-permission]').inputValue(), 'view');
    console.log('Dynamic done');
    // New options update summary without rewriting the source or firing change.
    await page.evaluate(() => {
      const s = document.querySelector('[data-video-rate]'); window.changeCount = 0;
      s.addEventListener('change', () => window.changeCount++);
      s.innerHTML = '<option value="1">Normal</option><option value="2" selected>Fast</option>';
    });
    await page.waitForFunction(() => document.querySelector('[data-video-rate]').closest('.ui-select').querySelector('.ui-select-summary').textContent === 'Fast');
    assert.equal(await page.evaluate(() => window.changeCount), 0);
    console.log('Options done');
    if (process.env.DROPDOWN_REPORT_DIR) { fs.mkdirSync(process.env.DROPDOWN_REPORT_DIR,{recursive:true}); await date.locator('.ui-select-trigger').click(); await page.screenshot({path:path.join(process.env.DROPDOWN_REPORT_DIR,'desktop.png')}); await page.keyboard.press('Escape'); }
    // Dialog controls remain in top layer and retain accessible labels.
    await page.evaluate(() => { document.querySelector('#analysisDiscussionViewField').hidden=false; document.querySelector('#analysisDiscussionChannelField').hidden=false; document.querySelector('#analysisDiscussionDialog').showModal(); });
    const discussion = page.locator('#analysisDiscussionView').locator('..');
    await discussion.locator('.ui-select-trigger').click();
    assert.equal(await discussion.locator('.ui-select-panel').isVisible(), true);
    await page.keyboard.press('Escape');
    await page.evaluate(() => document.querySelector('#analysisDiscussionDialog').close());
    await page.setViewportSize({width:390,height:844});
    await page.evaluate(() => { document.documentElement.dataset.colorTheme = 'light'; state.uiLanguage = 'en'; enhanceDashboardSelects(); });
    await date.locator('.ui-select-trigger').click();
    const bounds = await date.locator('.ui-select-panel').boundingBox();
    if (process.env.DROPDOWN_REPORT_DIR) { fs.mkdirSync(process.env.DROPDOWN_REPORT_DIR,{recursive:true}); await page.screenshot({path:path.join(process.env.DROPDOWN_REPORT_DIR,'mobile.png')}); }
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 391 && bounds.y >= 0 && bounds.y + bounds.height <= 845, JSON.stringify(bounds));
    await page.locator('#dailyReviewScope').click();
    assert.equal(await date.locator('.ui-select-panel').isVisible(), false);
    // Existing multi-select remains open for consecutive choices.
    await page.evaluate(() => {
      const root = document.createElement('div'); root.id='auditMulti'; root.className='multi-filter'; root.style.cssText='position:fixed;top:100px;left:10px;width:250px;z-index:999';
      document.body.append(root);
      renderMultiFilter(root, {options:[{value:'a',label:'A'},{value:'b',label:'B'}],selected:['a'],onChange(){}});
    });
    await page.locator('#auditMulti .multi-filter-trigger').click();
    await page.locator('#auditMulti [data-multi-value="b"]').check();
    assert.equal(await page.locator('#auditMulti .multi-filter-panel').isVisible(), true);
    await page.locator('#auditMulti [data-multi-clear]').click();
    assert.equal(await page.locator('#auditMulti .multi-filter-panel').isVisible(), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#auditMulti .multi-filter-panel').isVisible(), false);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({inventory, checks:'native coverage, custom preservation, keyboard, no-op refresh/focus, empty values, option identity, disabled/hidden, dynamic rows, dialog and mobile bounds passed'}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
