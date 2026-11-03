// Exercise the real request cache and URL builder without a remote Trail call.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = ['format-api.js', 'detail-media.js']
  .map(name => fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8')).join('\n');

vm.runInNewContext(`
const assert = require('node:assert/strict');
const window = {setTimeout, clearTimeout};
const state = {};
function withBase(path) { return '/manual' + path; }
${source}
(async () => {
  let clock = 1000, calls = 0, finish;
  Date.now = () => clock;
  const response = id => ({issue_id:id, status:'ready', external_links:{ra_events:[{event:'start'}]}});
  api = async () => { calls++; return new Promise(resolve => { finish = resolve; }); };
  const controller = new AbortController();
  const first = startTrailDetailMetadata('cn1', 1, controller.signal);
  controller.abort();
  const returned = startTrailDetailMetadata('cn1', 3);
  assert.equal(calls, 1, 'returning while a request runs must share it');
  finish(response('cn1'));
  assert.equal(await first, null, 'obsolete consumer gets no metadata');
  const copy = await returned;
  copy.external_links.ra_events[0].event = 'mutated';
  assert.equal((await startTrailDetailMetadata('cn1', 4)).external_links.ra_events[0].event, 'start');
  assert.equal(calls, 1, 'reopening a ready Issue needs no HTTP request');

  api = async p => { calls++; return response(decodeURIComponent(p.split('/')[3])); };
  await startTrailDetailMetadata('cn2', 5);
  await startTrailDetailMetadata('cn1', 6);
  assert.equal(calls, 2, 'A -> B -> A loads only A and B');
  clock += TRAIL_DETAIL_CACHE_TTL_MS - 1;
  await startTrailDetailMetadata('cn1', 7);
  assert.equal(calls, 2);
  clock++;
  await startTrailDetailMetadata('cn1', 8);
  assert.equal(calls, 3, 'success TTL expires without being extended by hits');

  api = async () => { calls++; throw new Error('offline'); };
  assert.equal(await startTrailDetailMetadata('cn3', 9), null);
  await startTrailDetailMetadata('cn3', 10);
  assert.equal(calls, 4, 'network failures are backed off');
  clock += TRAIL_DETAIL_FAILURE_TTL_MS;
  api = async () => { calls++; return {issue_id:'cn3', status:'unavailable', external_links:{}}; };
  assert.equal((await startTrailDetailMetadata('cn3', 11)).status, 'unavailable');
  clock += TRAIL_DETAIL_FAILURE_TTL_MS - 1;
  await startTrailDetailMetadata('cn3', 12);
  assert.equal(calls, 5, 'unavailable API results use the same short backoff');
  clock++;
  api = async () => { calls++; return response('cn3'); };
  assert.equal((await startTrailDetailMetadata('cn3', 13)).status, 'ready');
  assert.equal(calls, 6);
  const alreadyAborted = new AbortController();
  alreadyAborted.abort();
  assert.equal(await startTrailDetailMetadata('cn4', 14, alreadyAborted.signal), null);
  assert.equal(calls, 6);

  api = async () => response('wrong-issue');
  assert.equal(await startTrailDetailMetadata('cn4', 15), null, 'reject another Issue payload');
  api = async p => response(decodeURIComponent(p.split('/')[3]));
  for (let i = 0; i <= TRAIL_DETAIL_CACHE_LIMIT; i++) await startTrailDetailMetadata('bounded-' + i, i);
  assert.equal(trailDetailMetadataCache.size, TRAIL_DETAIL_CACHE_LIMIT);

  let refreshes = 0;
  api = async p => { refreshes++; return response(p.includes('refresh=true') ? 'cn_refresh' : decodeURIComponent(p.split('/')[3])); };
  await startTrailDetailMetadata('cn_refresh', 1);
  assert.equal(refreshes, 1);
  const refreshed = await startTrailDetailMetadata('cn_refresh', 2, null, {refresh:true});
  assert.equal(refreshes, 2, 'explicit refresh bypasses browser cache');
  assert.equal(refreshed.status, 'ready');
  api = async () => { throw new Error('refresh failed'); };
  const retained = await startTrailDetailMetadata('cn_refresh', 3, null, {refresh:true});
  assert.equal(retained.status, 'ready');
  assert.equal(retained.refresh_status, 'unavailable');
  assert.equal((await startTrailDetailMetadata('cn_refresh', 4)).external_links.ra_events[0].event,'start');

  const caseData = {issue_id:'cn35759965', assets:{capture:{trip_id:'car_trip',timestamp_ms:1788236483601}}};
  const base = 'https://voyager.intra.xiaojukeji.com/issue/cn35759965?view_id=2410';
  const event = 1788236535286;
  const url = new URL(aresStudioUrl(caseData, base, event));
  assert.equal(url.pathname, '/static/ares-studio/');
  assert.equal(url.searchParams.get('ds.issue_id'), caseData.issue_id);
  assert.equal(url.searchParams.get('ds.trip_id'), 'car_trip');
  assert.equal(Number(url.searchParams.get('ds.start')), event - 10000);
  assert.equal(Number(url.searchParams.get('ds.end')), event + 10000);
  assert.equal(Number(new URL(aresStudioUrl(caseData, base)).searchParams.get('ds.start')), 1788236473601, 'ordinary Ares link retains media t0');
  for (const invalid of [NaN, Infinity, 0, -1]) assert.equal(aresStudioUrl(caseData, base, invalid), '');
  assert.equal(aresStudioUrl({issue_id:'cn1'}, base, event), '');
  console.log('Trail cache: concurrency, navigation, copies, expiry, failures, bounds and event ±10s passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
`, {require, console, process, URL, AbortController, structuredClone, setTimeout, clearTimeout});
