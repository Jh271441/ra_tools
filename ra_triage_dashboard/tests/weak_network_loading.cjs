// Real frontend controllers with delayed reads: no service, profile or writes.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const load = name => process.env.WEAK_NETWORK_TEST_REF
  ? require('node:child_process').execFileSync('git', ['show', `${process.env.WEAK_NETWORK_TEST_REF}:ra_triage_dashboard/static/js/${name}`], {encoding: 'utf8'})
  : fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
const deferred = () => {let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;}); return {promise, resolve, reject};};
const tick = () => new Promise(setImmediate);
const aborted = () => Object.assign(new Error('cancelled'), {name: 'AbortError'});

async function deadlinesAndCancellation() {
  let next = 0, attempts = 0;
  const timers = new Map();
  const s = {URL, AbortController, FormData, Error, TypeError, Set, Map, console,
    state: {session: {}}, uiText: (zh, en) => en, withBase: value => value,
    API_GET_TIMEOUT_MS: 6000, API_GET_MAX_ATTEMPTS: 3, API_GET_RETRYABLE_STATUSES: new Set([503]),
    window: {setTimeout(fn, ms) {timers.set(++next, {fn, ms}); return next;}, clearTimeout(id) {timers.delete(id);}},
    fetch: (_url, {signal}) => {attempts++; return new Promise((_, reject) => {
      signal.addEventListener('abort', () => reject(aborted()), {once: true});
    });}};
  vm.createContext(s); vm.runInContext(load('format-api.js'), s);
  const caller = new AbortController();
  const stalled = s.api('/api/labeling/summary', {signal: caller.signal});
  const rejected = assert.rejects(stalled, error => error.code === 'timeout');
  for (const ms of [6000, 250, 6000, 500, 6000]) {
    await tick();
    const timer = [...timers.entries()].find(([, item]) => item.ms === ms);
    assert.ok(timer, 'caller-owned GET must retain timeout/retry timer ' + ms);
    timers.delete(timer[0]); timer[1].fn();
  }
  await rejected;
  assert.equal(attempts, 3); assert.equal(caller.signal.aborted, false);
  assert.equal(timers.size, 0);

  attempts = 0;
  const cancelled = new AbortController();
  const pending = s.api('/api/cases', {signal: cancelled.signal});
  const done = assert.rejects(pending, error => error.name === 'AbortError');
  cancelled.abort(); await done;
  assert.equal(attempts, 1, 'superseded read is not retried');
  assert.equal(timers.size, 0);
  await assert.rejects(s.api('/api/cases', {signal: cancelled.signal}));
  assert.equal(attempts, 1, 'already cancelled read never reaches network');

  const result = deferred(); attempts = 0;
  s.fetch = async () => {attempts++; return result.promise;};
  const a = s.api('/api/session'), b = s.api('/api/session');
  result.resolve({ok: true, redirected: false, headers: {get: () => 'application/json'}, json: async () => ({verified: true})});
  assert.equal(await a, await b); assert.equal(attempts, 1, 'ordinary GETs remain single-flight');
  attempts = 0; s.fetch = async () => {attempts++; throw new TypeError('offline');};
  await assert.rejects(s.api('/api/cases/cn1/discussion', {method: 'POST', body: '{}'}));
  assert.equal(attempts, 1, 'writes never automatically replay');
}

function summaryFixture(taskId = '') {
  const tasks = deferred(), summaries = [], paints = [], picks = [], errors = [], content = {innerHTML: ''};
  let epoch = 1, route = 'original';
  const s = {AbortController, URLSearchParams, console, DEFAULT_CASE_PAGE_SIZE: 20,
    state: {activePage: 'labeling-summary'}, document: {getElementById: () => null},
    $: key => key === '#labelSummaryContent' ? content : null,
    capturePageContext: () => ({epoch, route}), isPageContextCurrent: previous => previous.epoch === epoch && previous.route === route,
    selectedBaselineQueryValue: () => 'version-20261016', joinFilterList: values => values.join(','),
    uiText: (zh, en) => en, escapeHtml: text => text, showToast: text => errors.push(text),
    api: (url, options = {}) => {
      if (url.includes('/tasks?')) return tasks.promise;
      const read = deferred(); summaries.push({url, ...read, signal: options.signal});
      options.signal?.addEventListener('abort', () => read.reject(aborted()), {once: true});
      return read.promise;
    }};
  vm.createContext(s); vm.runInContext(load('labeling-summary.js'), s);
  s.restoreLabelSummaryRoute = () => {};
  s.persistLabelSummaryRoute = () => {route = 'canonical';};
  s.renderLabelSummaryFilters = () => {};
  s.renderLabelingSummary = data => paints.push(data);
  s.renderLabelSummaryTaskPicker = tasks => picks.push(tasks);
  vm.runInContext('labelSummaryFilters.taskId=' + JSON.stringify(taskId), s);
  return {s, tasks, summaries, paints, picks, errors,
    navigate() {epoch++;}, value: expression => vm.runInContext(expression, s)};
}

async function summaryCatalogIsOptionalAndScoped() {
  const f = summaryFixture(); const request = f.s.loadLabelingSummary();
  assert.equal(f.summaries.length, 1, 'stats starts before task directory settles');
  f.summaries[0].resolve({page: 2, page_size: 20}); await request;
  assert.equal(f.paints.length, 1, 'slow directory cannot hold all-annotations content');
  f.tasks.resolve({items: [{id: 'task-a', name: 'A'}]}); await tick();
  assert.equal(f.paints.length, 1, 'late catalog does not replace the table');
  assert.equal(f.picks.length, 1, 'catalog updates only its shared picker after URL canonicalization');
  assert.equal(f.value('labelSummaryTasks[0].id'), 'task-a');

  const valid = summaryFixture('task-a'); const scoped = valid.s.loadLabelingSummary();
  valid.summaries[0].resolve({page: 1}); await tick(); assert.equal(valid.paints.length, 0);
  valid.tasks.resolve({items: [{id: 'task-a'}]}); await scoped;
  assert.equal(valid.paints.length, 1); assert.equal(valid.value('labelSummaryFilters.taskId'), 'task-a');

  const invalid = summaryFixture('removed-task'); const corrected = invalid.s.loadLabelingSummary();
  invalid.tasks.resolve({items: []}); await tick();
  assert.equal(invalid.summaries[0].signal.aborted, true);
  assert.equal(invalid.paints.length, 0, 'invalid-task result never flashes');
  assert.equal(new URL(invalid.summaries[1].url, 'https://fixture.test').searchParams.get('task_id'), '');
  invalid.summaries[1].resolve({page: 1}); await corrected;
  assert.equal(invalid.value('labelSummaryFilters.taskId'), ''); assert.equal(invalid.paints.length, 1);

  const stale = summaryFixture(); const old = stale.s.loadLabelingSummary();
  stale.navigate(); stale.s.cancelLabelingSummaryLoad(); await old;
  stale.tasks.resolve({items: [{id: 'old'}]}); await tick();
  assert.equal(stale.paints.length + stale.picks.length, 0);
  assert.equal(stale.summaries[0].signal.aborted, true);

  const failed = summaryFixture(); const fallback = failed.s.loadLabelingSummary();
  failed.tasks.reject(new Error('Directory unavailable'));
  failed.summaries[0].resolve({page: 1}); await fallback; await tick();
  assert.equal(failed.paints.length, 1); assert.deepEqual(failed.errors, ['Directory unavailable']);
}

(async () => {
  await deadlinesAndCancellation();
  await summaryCatalogIsOptionalAndScoped();
  console.log('Weak-network deadline, cancellation and summary ownership checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
