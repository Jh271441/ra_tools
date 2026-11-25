// Execute the actual shell's early-read block and normal API decoder together.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const read = name => process.env.COLD_TEST_REF
  ? execFileSync('git', ['show', `${process.env.COLD_TEST_REF}:ra_triage_dashboard/static/${name}`], {encoding: 'utf8'})
  : fs.readFileSync(path.join(__dirname, '../static', name), 'utf8');
const tick = () => new Promise(setImmediate);
const response = (data, extra = {}) => ({ok: true, status: 200, redirected: false,
  headers: {get: () => 'application/json'}, text: async () => JSON.stringify(data),
  json: async () => data, ...extra});
function fixture(fetcher, base = '/manual') {
  let counter = 0;
  const timers = new Map(), events = new Map(), calls = [];
  const s = {AbortController, FormData, URL, Error, TypeError, console, activeBase: base,
    state: {session: {}}, API_GET_TIMEOUT_MS: 6000, API_GET_MAX_ATTEMPTS: 3,
    API_GET_RETRYABLE_STATUSES: new Set([503]), withBase: value => base + value,
    uiText: (_zh, en) => en,
    window: {setTimeout(fn, ms) {timers.set(++counter, {fn, ms}); return counter;},
      clearTimeout(id) {timers.delete(id);}, addEventListener(name, fn) {events.set(name, fn);}},
    fetch: async (url, options) => {calls.push({url, options}); return fetcher(url, options, calls.length);}};
  vm.createContext(s);
  const html = read('index.html'), start = html.indexOf('// These same-origin reads');
  assert.ok(start >= 0, 'cold shell must initiate its two shared reads before bundle execution');
  vm.runInContext('(() => {' + html.slice(start, html.indexOf('const stylesheetPaths', start)) + '})();', s);
  vm.runInContext(read('js/format-api.js'), s);
  return {s, timers, events, calls};
}

async function reuseAndFreshness() {
  for (const base of ['', '/manual']) {
    const f = fixture(async () => response({verified: true, url: '/api/example'}), base);
    assert.deepEqual(f.calls.map(x => x.url), [base + '/api/dashboard-config', base + '/api/session']);
    await tick(); assert.equal(f.timers.size, 0, 'deadline ends after response body arrives, not after a slow JS download');
    const a = await f.s.api('/api/session'); assert.equal(a.verified, true);
    assert.equal(a.url, base + '/api/example'); assert.equal(f.calls.length, 2);
    await f.s.api('/api/session'); assert.equal(f.calls.length, 3, 'only the first page-load read is reused');
    await f.s.api('/api/dashboard-config', {cache: 'no-store'});
    assert.equal(f.calls.length, 4, 'explicit refresh must not consume an earlier read');
    await f.s.api('/api/dashboard-config');
    assert.equal(f.calls.length, 5, 'explicit refresh retires the earlier response');
  }
  for (const options of [{credentials: 'omit'}, {headers: {'X-Test': 'fresh'}}, {signal: new AbortController().signal}]) {
    const f = fixture(async () => response({ready: true}));
    await f.s.api('/api/session', options);
    assert.equal(f.calls.length, 3, 'custom request policies must use a fresh request');
    assert.equal(f.s.window.__RA_TRIAGE_INITIAL_READS__.has('/manual/api/session'), false);
    assert.equal(f.calls[1].options.signal.aborted, true);
  }
}

async function authenticationStillOwnsAccess() {
  const f = fixture(async () => response({}, {redirected: true, headers: {get: () => 'text/html'}, text: async () => '<html>Sign in</html>'}));
  await assert.rejects(f.s.api('/api/session'), error => error.code === 'auth_required');
  assert.equal(f.calls.length, 2, 'expired SSO is not retried or accepted as JSON');
  const broken = fixture(async () => response({}, {
    text: async () => 'not json', json: async () => {throw new SyntaxError('not json');},
  }));
  const pending = broken.s.api('/api/dashboard-config');
  const checked = assert.rejects(pending, error => error.code === 'invalid_response');
  for (const ms of [250, 500]) {
    await tick();
    const timer = [...broken.timers.entries()].find(([, t]) => t.ms === ms);
    assert.ok(timer); broken.timers.delete(timer[0]); timer[1].fn();
  }
  await checked;
}

async function failuresAndNavigation() {
  const f = fixture(async (_url, _options, count) => {
    if (count <= 2) throw new TypeError('temporary network interruption');
    return response({ready: true});
  });
  const retry = f.s.api('/api/dashboard-config'); await tick();
  const backoff = [...f.timers.entries()].find(([, t]) => t.ms === 250);
  assert.ok(backoff); f.timers.delete(backoff[0]); backoff[1].fn();
  assert.equal((await retry).ready, true); assert.equal(f.calls.length, 3);

  const timeout = fixture((_url, {signal}, count) => count > 2 ? response({ready: true})
    : new Promise((_, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error('deadline'), {name: 'AbortError'})))));
  const recovering = timeout.s.api('/api/session');
  const deadline = [...timeout.timers.entries()][1];
  timeout.timers.delete(deadline[0]); deadline[1].fn(); await tick();
  const delay = [...timeout.timers.entries()].find(([, t]) => t.ms === 250);
  assert.ok(delay); timeout.timers.delete(delay[0]); delay[1].fn();
  assert.equal((await recovering).ready, true);
  assert.equal(timeout.calls.length, 3, 'expired early read follows normal bounded GET recovery');
  timeout.events.get('pagehide')(); await tick();

  const signals = [];
  const leaving = fixture((_url, {signal}) => new Promise((_, reject) => {
    signals.push(signal); signal.addEventListener('abort', () => reject(Object.assign(new Error('cancelled'), {name: 'AbortError'})));
  }));
  assert.equal(leaving.timers.size, 2);
  assert.ok([...leaving.timers.values()].every(t => t.ms === 6000));
  leaving.events.get('pagehide')(); await tick();
  assert.ok(signals.every(s => s.aborted)); assert.equal(leaving.timers.size, 0);
  assert.equal(leaving.s.window.__RA_TRIAGE_INITIAL_READS__.size, 0);
}

(async () => {
  await reuseAndFreshness();
  await authenticationStillOwnsAccess();
  await failuresAndNavigation();
  console.log('Cold-start early-read reuse, deadline, authentication and navigation checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
