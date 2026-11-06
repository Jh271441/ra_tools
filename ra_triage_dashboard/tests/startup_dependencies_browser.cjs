// Full frontend, synthetic read-only API. Optional metadata stays blocked until
// visible content paints. STARTUP_TEST_REF + STARTUP_MEASURE_ONLY compare a Git ref.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const zlib = require('node:zlib'), assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../..'), staticDir = path.join(root, 'ra_triage_dashboard/static');
const ref = process.env.STARTUP_TEST_REF, measureOnly = process.env.STARTUP_MEASURE_ONLY === '1';
const assets = new Map();
const read = file => {
  if (!assets.has(file)) assets.set(file, ref ? execFileSync('git', ['show', `${ref}:ra_triage_dashboard/static/${file}`], {cwd: root, maxBuffer: 8e6}) : fs.readFileSync(path.join(staticDir, file)));
  return assets.get(file);
};
const bundle = Buffer.concat(read('js/MANIFEST').toString().split('\n').map(s => s.trim()).filter(s => s && !s.startsWith('#')).flatMap(name => [read(`js/${name}`), Buffer.from('\n;\n')]));
const cssNames = JSON.parse('[' + read('index.html').toString().match(/const stylesheetPaths = \[([\s\S]*?)\];/)[1].replace(/,\s*$/, '') + ']');
const cssBundle = Buffer.from(cssNames.map(name => read(name).toString()).join('\n\n'));
read('app.js');
const report = process.env.STARTUP_REPORT_DIR;
if (report) fs.mkdirSync(report, {recursive: true});
let calls = [], pending = [], writes = [], activeRoute = '';
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://localhost'), endpoint = u.pathname.replace('/manual/api/', '');
  calls.push({path: u.pathname, at: Date.now()});
  if (req.method !== 'GET') {writes.push(req.method + ' ' + u.pathname); res.writeHead(405).end(); return;}
  const send = (body, mime) => {
    res.setHeader('Content-Type', mime);
    if (req.headers['accept-encoding']?.includes('gzip') && body.length >= 1024 && (!ref || mime !== 'text/html')) {
      body = zlib.gzipSync(body, {level: 5}); res.setHeader('Content-Encoding', 'gzip');
    }
    res.setHeader('Cache-Control', mime === 'text/html' || mime === 'application/json' ? 'no-store' : 'public, max-age=604800, immutable');
    res.end(body);
  };
  const json = data => send(Buffer.from(JSON.stringify(data)), 'application/json');
  if (u.pathname.startsWith('/manual/api/')) {
    const blocked = ['model-runs', 'mention-users', 'review-work-splits'].includes(endpoint)
      || (activeRoute === 'assignments' && endpoint === 'access-users');
    const data = endpoint === 'dashboard-config' ? {baselines: [{id: '0508', label: '0508', scope: 'test', issue_count: 10}], default_baseline_ids: ['0508'], tag_catalog: []}
      : endpoint === 'session' ? {username: 'tester', authenticated: true, verified: true, is_admin: true, access_role: 'admin', can_write: true}
      : endpoint === 'access-users' ? {items: [{username: 'tester', role: 'admin', enabled: true, intent_permission: 'manage'}]}
      : endpoint === 'model-runs' ? {items: [{id: 'fixture-run', name: 'Fixture model Run', baseline_prediction_count: 10}], default_model_run_id: 'fixture-run'}
      : endpoint === 'status' ? {overall: {status: 'healthy', problems: []}, application: {build_commit: 'fixture'}, database: {available: true, persistent: true}}
      : endpoint === 'rd-results' ? {items: [], page: 1, page_size: 20, page_count: 1, total: 0, counts: {total: 0, resolved: 0, pending: 0, conflict: 0}, write_enabled: false}
      : endpoint === 'review-reason-analysis' ? {items: [], total: 0, page: 1, page_size: 20, page_count: 1, summary: {}, scope: {}}
      : endpoint === 'cases/work-splits' ? {items: [{split_id: 'campaign-fixture', campaign_name: 'Assignment loading fixture',
        model_run_id: 'fixture-run', is_current: true, lifecycle: 'active', created_at: '2026-11-06T00:00:00Z',
        total_count: 10, assignment_count: 10, members: []}]}
      : endpoint === 'cases/work-splits/campaign-fixture' ? {split_id: 'campaign-fixture',
        model_run_id: 'fixture-run', is_current: true, lifecycle: 'active', total_count: 1,
        assignment_count: 1, page: 1, page_count: 1, members: [{username: 'tester'}],
        items: [{issue_id: 'cn1', assignee: 'tester', assignment_kind: 'base', submitted: false}]}
      : endpoint === 'cases/cn1/discussion' ? {comments: [], count: 0}
      : {items: [], issues: 10, total: 0, page: 1, page_size: 20, revision: 0, poll_after_ms: 30000};
    const finish = () => {if (!res.destroyed) json(data);};
    if (blocked && !measureOnly) pending.push({endpoint, finish});
    else setTimeout(finish, blocked ? endpoint === 'model-runs' ? 900 : 1200 : 30);
    return;
  }
  if (u.pathname.startsWith('/manual/static/')) {
    const file = u.pathname.slice('/manual/static/'.length);
    if (file.includes('..')) {res.writeHead(403).end(); return;}
    if (file === 'app-bundle.js') return send(bundle, 'text/javascript');
    if (file === 'app-bundle.css') return send(cssBundle, 'text/css');
    if (!fs.existsSync(path.join(staticDir, file))) {res.writeHead(404).end(); return;}
    return send(read(file), file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'application/octet-stream');
  }
  send(Buffer.from(read('index.html').toString().replaceAll('{{RA_TRIAGE_BASE_PATH}}', '/manual')), 'text/html');
});
const release = endpoint => {
  const ready = pending.filter(p => !endpoint || p.endpoint === endpoint);
  pending = pending.filter(p => endpoint && p.endpoint !== endpoint);
  ready.forEach(p => p.finish());
};
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const browser = await chromium.launch({headless: true}), results = [];
  try {
    const combinations = measureOnly ? Array.from({length: Number(process.env.STARTUP_TRIALS || 1)}, () => [1440, 'zh', 'dark']) : [320, 390, 1440].flatMap(w => ['zh', 'en'].flatMap(l => ['dark', 'light'].map(t => [w, l, t])));
    for (const route of (process.env.STARTUP_ROUTES || 'status,users,rd-results,analysis,assignments').split(',')) {
      for (const [width, lang, theme] of combinations) {
        const context = await browser.newContext({viewport: {width, height: 1000}});
        await context.addInitScript(({lang, theme}) => {localStorage.setItem('ra-triage-ui-language', lang); localStorage.setItem('ra-triage-color-theme', theme);}, {lang, theme});
        const page = await context.newPage(), errors = [];
        page.on('pageerror', e => errors.push(e.message)); calls = []; pending = []; activeRoute = route;
        if (process.env.STARTUP_NETWORK_MS) {
          const cdp = await context.newCDPSession(page); await cdp.send('Network.enable');
          await cdp.send('Network.emulateNetworkConditions', {offline: false, latency: Number(process.env.STARTUP_NETWORK_MS), downloadThroughput: 2500000, uploadThroughput: 2500000});
        }
        const started = Date.now();
        const routePath = {status: 'system-status', analysis: 'review-analysis', assignments: 'review-assignments'}[route] || route;
        const query = route === 'assignments' ? 'baselines=0508&lifecycle=current&split=campaign-fixture' : 'baselines=0508';
        await page.goto(`http://127.0.0.1:${server.address().port}/manual/${routePath}?${query}`, {waitUntil: 'domcontentloaded'});
        if (!measureOnly && route === 'analysis') {
          await page.waitForFunction(() => typeof state !== 'undefined' && state.config && state.session.authenticated);
          const deadline = Date.now() + 15000;
          while (!pending.some(p => p.endpoint === 'model-runs')) {
            assert.ok(Date.now() < deadline, 'Run request must start');
            await page.waitForTimeout(10);
          }
          release('model-runs');
        }
        await page.waitForFunction(route => route === 'status' ? document.querySelectorAll('#systemStatusGrid article').length > 0
          : route === 'users' ? document.querySelectorAll('[data-access-user="tester"]').length > 0
          : route === 'rd-results' ? typeof rdResults !== 'undefined' && Boolean(rdResults.data)
          : route === 'assignments' ? document.querySelectorAll('[data-review-assignment-batch="campaign-fixture"]').length > 0
          : typeof state !== 'undefined' && Boolean(state.reviewAnalysis.data), route);
        const readyMs = Date.now() - started;
        const bounds = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, width: innerWidth}));
        assert.ok(bounds.scroll <= width + 1, JSON.stringify({route, width, bounds}));
        if (!measureOnly) {
          assert.ok(pending.some(p => p.endpoint === 'mention-users'), '@ directory remains optional');
          if (route !== 'analysis') {
            assert.ok(pending.some(p => p.endpoint === 'model-runs'), 'content paints before Run catalog');
            assert.equal(calls.some(c => /\/(reviewers|work-assignees)$/.test(c.path)), false, 'unrelated facets stay idle');
          } else assert.ok(pending.some(p => p.endpoint === 'review-work-splits'), 'analysis paints before task facet');
          if (route === 'assignments') {
            assert.ok(pending.some(p => p.endpoint === 'access-users'), 'assignment list also paints before user directory');
            await page.waitForSelector('[data-review-assignment-row][data-issue-id="cn1"]');
            assert.equal(await page.locator('.review-assignment-person-picker .ui-select-trigger').isDisabled(), true,
              'reassignment waits for its directory while task detail is already visible');
          }
          const originalUrl = page.url();
          await page.locator('#languageToggleButton').dispatchEvent('click');
          assert.equal(page.url(), originalUrl, 'language switch preserves route');
          await page.locator('#languageToggleButton').dispatchEvent('click');
          if (report && ((width === 320 && lang === 'en' && theme === 'light') || (width === 1440 && lang === 'zh' && theme === 'dark'))) {
            await page.screenshot({path: path.join(report, `${route}-${width}-${lang}-${theme}.png`)});
          }
          release();
          await page.waitForTimeout(250);
          if (route === 'assignments') {
            const picker = page.locator('.review-assignment-person-picker .ui-select-trigger');
            await picker.waitFor();
            assert.equal(await picker.isDisabled(), false);
            await picker.click(); await page.keyboard.press('Escape');
            assert.equal(await picker.getAttribute('aria-expanded'), 'false');
            assert.equal(await page.locator('.review-assignment-person-picker .ui-select-native').inputValue(), 'tester');
            await page.evaluate(() => {
              const video = document.createElement('video'); video.id = 'network-fixture-player';
              video.style.display = 'none'; video._pauses = 0; video._resumes = 0;
              video._pauseBevPlayback = () => video._pauses++;
              video._resumeBevPlayback = () => video._resumes++;
              document.querySelector('#reviewAssignmentsPage').append(video);
              return openAnalysisDiscussion('cn1');
            });
            const modal = await page.locator('#analysisDiscussionDialog').boundingBox();
            assert.ok(modal.x >= -1 && modal.x + modal.width <= width + 1);
            assert.equal(await page.locator('#network-fixture-player').evaluate(v => v._pauses), 1);
            await page.locator('#analysisDiscussionDialog [data-close]').first().click();
            await page.waitForFunction(() => document.querySelector('#network-fixture-player')._resumes === 1);
            await page.locator('#network-fixture-player').evaluate(v => v.remove());
          }
          if (route === 'status' && width === 1440) {
            await page.reload({waitUntil: 'domcontentloaded'});
            await page.waitForFunction(() => document.querySelectorAll('#systemStatusGrid article').length > 0);
            assert.ok(pending.some(p => p.endpoint === 'model-runs'), 'refresh content also paints before Run catalog');
            release(); await page.waitForTimeout(250);
            await page.evaluate(() => navigatePage('review'));
            await page.waitForFunction(() => state.activePage === 'review');
            await page.waitForTimeout(200);
            assert.ok(calls.some(c => c.path.endsWith('/reviewers')), 'SPA entry loads reviewer facet');
            assert.ok(calls.some(c => c.path.endsWith('/work-assignees')), 'SPA entry loads assignee facet');
          }
          if (route === 'users') {
            const control = page.locator('[data-access-user="tester"] .ui-select-trigger').first();
            assert.equal(await control.count(), 1, 'reuse shared dropdown');
            await control.click(); await page.keyboard.press('Escape');
            assert.equal(await control.getAttribute('aria-expanded'), 'false');
          }
        }
        assert.deepEqual(errors, []);
        results.push({route, width, lang, theme, readyMs, bounds, errors, requests: calls.map(c => ({path: c.path, atMs: c.at - started}))});
        await context.close(); release();
      }
    }
    assert.deepEqual(writes, []);
    const output = {browser: browser.version(), ref: ref || 'working-tree', networkLatencyMs: Number(process.env.STARTUP_NETWORK_MS || 0), results};
    if (report) fs.writeFileSync(path.join(report, 'startup.json'), JSON.stringify(output, null, 2));
    console.log(JSON.stringify(results.map(({route, width, lang, theme, readyMs}) => ({route, width, lang, theme, readyMs}))));
  } finally {await browser.close(); release(); server.closeAllConnections(); server.close();}
})().catch(e => {console.error(e); release(); server.closeAllConnections(); server.close(); process.exitCode = 1;});
