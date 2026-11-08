// Full frontend, synthetic read-only API. Optional metadata stays blocked until
// visible content paints. STARTUP_TEST_REF + STARTUP_MEASURE_ONLY compare a Git ref.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const zlib = require('node:zlib'), assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../..'), staticDir = path.join(root, 'ra_triage_dashboard/static');
const ref = process.env.STARTUP_TEST_REF, measureOnly = process.env.STARTUP_MEASURE_ONLY === '1';
// Request probes cover every canonical route, without calling an API arrival a
// visible-content measurement. The existing six routes retain real DOM checks.
const probeOnly = process.env.STARTUP_PROBE_ONLY === '1';
const routePaths = {status: 'system-status', analysis: 'review-analysis', assignments: 'review-assignments',
  summary: 'labeling-summary', labeling: 'case-labeling', 'labeling-new-task': 'case-labeling/new-task',
  intent: 'intent-labeling', 'trail-update': 'trail-attribute-update', comparison: 'run-comparison',
  'run-collections': 'multi-run-evaluation', prediction: 'batch-prediction', 'trail-history': 'trail-update-history'};
const primaryEndpoints = {status: 'status', users: 'access-users', 'rd-results': 'rd-results',
  analysis: 'review-reason-analysis', assignments: 'cases/work-splits', summary: 'labeling/summary',
  review: 'cases', labeling: 'labeling/tasks', 'labeling-new-task': 'access-users', campaigns: 'campaigns',
  intent: 'intent-datasets', 'intent-experiments': 'intent-datasets', 'intent-summary': 'intent-datasets',
  'trail-update': 'trail-attribute-update/issue-history', runs: 'model-runs', comparison: 'model-runs',
  'run-collections': 'run-collections', prediction: 'prediction-batches', 'daily-review': 'version-datasets',
  'version-datasets': 'version-datasets', 'daily-cron': 'daily-cron', 'trail-history': 'trail-history'};
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
const profile = process.env.STARTUP_NETWORK_PROFILE || '';
const occurrence = new Map();
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://localhost'), endpoint = u.pathname.replace('/manual/api/', '');
  const call = {path: u.pathname, at: Date.now(), aborted: false}; calls.push(call);
  res.on('close', () => {call.aborted = !res.writableFinished;});
  if (req.method !== 'GET') {writes.push(req.method + ' ' + u.pathname); res.writeHead(405).end(); return;}
  // The production server redirects this legacy entry before serving the shell.
  if (u.pathname === '/manual/daily-review') {
    res.writeHead(307, {Location: '/manual/version-datasets' + u.search}).end(); return;
  }
  const send = (body, mime) => {
    res.setHeader('Content-Type', mime);
    if (req.headers['accept-encoding']?.includes('gzip') && body.length >= 1024) {
      body = zlib.gzipSync(body, {level: 5}); res.setHeader('Content-Encoding', 'gzip');
    }
    res.setHeader('Cache-Control', mime === 'text/html' || mime === 'application/json' ? 'no-store' : 'public, max-age=604800, immutable');
    res.end(body);
  };
  const json = data => send(Buffer.from(JSON.stringify(data)), 'application/json');
  if (u.pathname.startsWith('/manual/api/')) {
    const blocked = ['model-runs', 'mention-users', 'review-work-splits'].includes(endpoint)
      || (activeRoute === 'assignments' && endpoint === 'access-users')
      || (activeRoute === 'summary' && endpoint === 'labeling/tasks');
    const data = endpoint === 'dashboard-config' ? {baselines: [{id: '0508', label: '0508', scope: 'test', issue_count: 10}], default_baseline_ids: ['0508'], tag_catalog: [],
      case_labeling: {active_baseline_ids: ['0508']}}
      : endpoint === 'session' ? {username: 'tester', authenticated: true, verified: true, is_admin: true, access_role: 'admin', can_write: true,
        can_view_intent: true, can_manage_intent: true, can_annotate_intent: true}
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
      : endpoint === 'labeling/tasks' ? {items: [{id: 'task-fixture', name: 'Weak-network task'}]}
      : endpoint === 'labeling/summary' ? {page: Number(u.searchParams.get('page') || 1), page_size: Number(u.searchParams.get('page_size') || 20), page_count: 3,
        annotated: 41, comparable: 41, matches: 30, labelers: ['tester'], assignees: ['tester'], submitted_states: {resolved: 41},
        items: [{issue_id: 'cn1', label_state: 'resolved', expected_output: '误触发', gt_label: '误触发', rationales: ['Network fixture'], authors: ['tester']}]}
      : {items: [], issues: 10, total: 0, page: 1, page_size: 20, revision: 0, poll_after_ms: 30000};
    const finish = () => {if (!res.destroyed) json(data);};
    const count = (occurrence.get(endpoint) || 0) + 1; occurrence.set(endpoint, count);
    if (profile === 'transient' && endpoint === 'labeling/summary' && count === 1) {
      return setTimeout(() => res.destroy(), 120);
    }
    if (blocked && !measureOnly && !probeOnly) pending.push({endpoint, finish});
    else {
      const delay = profile === 'jitter' ? (endpoint === 'labeling/tasks' ? 1800 : [40, 400, 100][(endpoint.length + count) % 3])
        : blocked ? endpoint === 'model-runs' ? 900 : 1200 : 30;
      setTimeout(finish, delay);
    }
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
    const combinations = measureOnly || probeOnly ? Array.from({length: Number(process.env.STARTUP_TRIALS || 1)}, () => [1440, 'zh', 'dark']) : [320, 390, 1440].flatMap(w => ['zh', 'en'].flatMap(l => ['dark', 'light'].map(t => [w, l, t])));
    for (const route of (process.env.STARTUP_ROUTES || 'status,users,rd-results,analysis,assignments,summary').split(',')) {
      for (const [width, lang, theme] of combinations) {
        const context = await browser.newContext({viewport: {width, height: 1000}});
        await context.addInitScript(({lang, theme}) => {localStorage.setItem('ra-triage-ui-language', lang); localStorage.setItem('ra-triage-color-theme', theme);}, {lang, theme});
        const page = await context.newPage(), errors = [];
        page.on('pageerror', e => errors.push(e.message)); calls = []; pending = []; occurrence.clear(); activeRoute = route;
        if (process.env.STARTUP_NETWORK_MS) {
          const cdp = await context.newCDPSession(page); await cdp.send('Network.enable');
          await cdp.send('Network.emulateNetworkConditions', {offline: false, latency: Number(process.env.STARTUP_NETWORK_MS), downloadThroughput: 2500000, uploadThroughput: 2500000});
        }
        const started = Date.now();
        const routePath = routePaths[route] || route;
        const query = route === 'assignments' ? 'baselines=0508&lifecycle=current&split=campaign-fixture' : 'baselines=0508';
        await page.goto(`http://127.0.0.1:${server.address().port}/manual/${routePath}?${query}`, {waitUntil: 'domcontentloaded'});
        if (!measureOnly && !probeOnly && route === 'analysis') {
          await page.waitForFunction(() => typeof state !== 'undefined' && state.config && state.session.authenticated);
          const deadline = Date.now() + 15000;
          while (!pending.some(p => p.endpoint === 'model-runs')) {
            assert.ok(Date.now() < deadline, 'Run request must start');
            await page.waitForTimeout(10);
          }
          release('model-runs');
        }
        if (probeOnly) {
          assert.ok(primaryEndpoints[route], 'known route probe: ' + route);
          const deadline = Date.now() + 20000;
          while (!calls.some(c => c.path === '/manual/api/' + primaryEndpoints[route])) {
            assert.ok(Date.now() < deadline, 'primary request never started: ' + route + ' ' + JSON.stringify({calls, errors}));
            await page.waitForTimeout(10);
          }
        } else await page.waitForFunction(route => route === 'status' ? document.querySelectorAll('#systemStatusGrid article').length > 0
          : route === 'users' ? document.querySelectorAll('[data-access-user="tester"]').length > 0
          : route === 'rd-results' ? typeof rdResults !== 'undefined' && Boolean(rdResults.data)
          : route === 'assignments' ? document.querySelectorAll('[data-review-assignment-batch="campaign-fixture"]').length > 0
          : route === 'summary' ? document.querySelectorAll('#labelSummaryCaseList .label-summary-case-row').length > 0
          : route === 'trail-history' ? document.querySelectorAll('#trailHistoryResults table').length > 0
          : typeof state !== 'undefined' && Boolean(state.reviewAnalysis.data), route);
        const readyMs = probeOnly ? undefined : Date.now() - started;
        const firstPageRequestMs = calls.find(c => c.path === '/manual/api/' + primaryEndpoints[route])?.at - started;
        if (!ref) await page.waitForFunction(() => performance.getEntriesByType('resource')
          .filter(r => /\/api\/(dashboard-config|session)$/.test(new URL(r.name).pathname)).length === 2);
        const resources = await page.evaluate(() => performance.getEntriesByType('resource')
          .filter(r => /\/(app-bundle\.js|dashboard-config|session)(\?|$)/.test(r.name))
          .map(r => ({path: new URL(r.name).pathname, startTime: r.startTime, responseEnd: r.responseEnd})));
        if (!ref) {
          const script = resources.find(r => r.path.endsWith('/app-bundle.js'));
          assert.ok(script, 'bundle resource timing is present');
          for (const endpoint of ['dashboard-config', 'session']) {
            assert.equal(calls.filter(c => c.path.endsWith('/api/' + endpoint)).length, 1, endpoint + ' is fetched once');
            const shared = resources.find(r => r.path.endsWith('/api/' + endpoint));
            assert.ok(shared && shared.startTime < script.responseEnd, endpoint + ' overlaps bundle download');
          }
        }
        const bounds = await page.evaluate(() => ({scroll: document.documentElement.scrollWidth, width: innerWidth}));
        assert.ok(bounds.scroll <= width + 1, JSON.stringify({route, width, bounds}));
        if (!measureOnly && !probeOnly) {
          assert.ok(pending.some(p => p.endpoint === 'mention-users'), '@ directory remains optional');
          if (!['analysis', 'summary'].includes(route)) {
            assert.ok(pending.some(p => p.endpoint === 'model-runs'), 'content paints before Run catalog');
            assert.equal(calls.some(c => /\/(reviewers|work-assignees)$/.test(c.path)), false, 'unrelated facets stay idle');
          } else if (route === 'analysis') assert.ok(pending.some(p => p.endpoint === 'review-work-splits'), 'analysis paints before task facet');
          if (route === 'summary') {
            assert.ok(pending.some(p => p.endpoint === 'labeling/tasks'), 'summary paints before task directory');
            assert.equal(await page.locator('#labelSummaryTaskPicker .ui-select-trigger').isDisabled(), true);
          }
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
          if (route === 'summary') {
            const task = page.locator('#labelSummaryTaskPicker .ui-select-trigger');
            await page.waitForFunction(() => !document.querySelector('#labelSummaryTaskPicker .ui-select-trigger').disabled);
            if (!(await task.isVisible())) await page.locator('[data-mobile-filter-toggle="labelSummaryFilters"]').click();
            await task.click(); await page.keyboard.press('Escape');
            assert.equal(await task.getAttribute('aria-expanded'), 'false');
            const table = await page.locator('#labelSummaryCaseList').elementHandle();
            const original = page.url();
            await page.locator('#labelSummaryNext').click();
            await page.waitForFunction(() => document.querySelector('#labelSummaryPageState')?.textContent === '2 / 3');
            assert.equal(new URL(page.url()).searchParams.get('page'), '2');
            assert.equal(await page.locator('#labelSummaryTaskPicker .ui-select-native').inputValue(), '');
            release(); await page.waitForTimeout(100);
            assert.equal(await page.locator('#labelSummaryCaseList').evaluate((el, old) => el !== old, table), true);
            assert.equal(new URL(original).searchParams.get('page'), null);
          }
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
        if (!ref) {
          assert.equal(calls.filter(c => c.path.endsWith('/app-bundle.js')).length, 1, 'preload reused by executing script');
          assert.equal(calls.filter(c => c.path.endsWith('/app.js')).length, 0, 'no loader network round trip');
        }
        results.push({route, width, lang, theme, readyMs, firstPageRequestMs, resources, bounds, errors, requests: calls.map(c => ({path: c.path, atMs: c.at - started, aborted: c.aborted}))});
        await context.close(); release();
      }
    }
    assert.deepEqual(writes, []);
    const output = {browser: browser.version(), ref: ref || 'working-tree', probeOnly,
      bundleGzipBytes: zlib.gzipSync(bundle, {level: 5}).length,
      networkLatencyMs: Number(process.env.STARTUP_NETWORK_MS || 0), profile, results};
    if (report) fs.writeFileSync(path.join(report, 'startup.json'), JSON.stringify(output, null, 2));
    console.log(JSON.stringify(results.map(({route, width, lang, theme, readyMs, firstPageRequestMs}) => ({route, width, lang, theme, readyMs, firstPageRequestMs}))));
  } finally {await browser.close(); release(); server.closeAllConnections(); server.close();}
})().catch(e => {console.error(e); release(); server.closeAllConnections(); server.close(); process.exitCode = 1;});
