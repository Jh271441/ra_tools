// Read-only lifecycle tests: no browser profile, production service or business writes.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
const tick = () => new Promise(setImmediate);

async function pausedSegments() {
  class Buffer extends EventTarget {
    appendBuffer() { queueMicrotask(() => this.dispatchEvent(new Event('updateend'))); }
    abort() {}
  }
  let media;
  class Media extends EventTarget {
    constructor() { super(); media = this; this.readyState = 'open'; }
    static isTypeSupported() { return true; }
    addSourceBuffer() { return new Buffer(); }
    endOfStream() { this.readyState = 'ended'; }
  }
  const video = new EventTarget();
  Object.assign(video, {paused: true, currentTime: 4.2, playbackRate: 1,
    load() { queueMicrotask(() => media.dispatchEvent(new Event('sourceopen'))); }});
  const segments = [0, 1, 2, 3].map(i => ({start: i * 2, end: i * 2 + 2, first: i * 100, last: i * 100 + 99}));
  const manifest = {recipe: 'segments-v1', codec: 'avc1.640028', fingerprint: 'a'.repeat(64),
    duration: 8, size: 400, init: 'AA==', segments};
  const requests = [], context = {URL: class extends URL {
    static createObjectURL() { return 'blob:fixture'; }
    static revokeObjectURL() {}
  }, location: {origin: 'https://triage.test'}, MediaSource: Media, AbortController, Uint8Array,
  atob, setTimeout, clearTimeout, performance, safeSameOriginAssetUrl: value => value,
  fetch: async (url, options) => {
    if (url.includes('stream=')) return new Response(JSON.stringify(manifest));
    const range = options.headers.Range;
    requests.push({range, priority: options.priority});
    if (range === 'bytes=0-99' && options.priority === 'low') return new Response(null, {status: 503});
    return new Response(new Uint8Array(100), {status: 206,
      headers: {'Content-Range': range.replace('=', ' ') + '/400'}});
  }};
  vm.createContext(context); vm.runInContext(source('video-segments.js'), context);
  const loader = context.createVideoSegmentLoader(video, {url: '/api/assets/cn1/bev-video-0',
    position: () => video.currentTime, attached() {}, fallback() { throw Error('Unexpected native fallback'); }});
  for (let i = 0; i < 10; i++) await tick();
  assert.deepEqual(requests.map(r => r.range), ['bytes=200-299', 'bytes=300-399'],
    'paused video fetches target and forward decoder flush only');
  assert.equal(requests[1].priority, 'low', 'optional decoder neighbor yields network priority');
  video.currentTime = 2.2; video.dispatchEvent(new Event('seeking'));
  for (let i = 0; i < 10; i++) await tick();
  assert.equal(requests.at(-1).range, 'bytes=100-199', 'backward seek still loads the requested GOP');
  video.paused = false;
  video.readyState = 4;
  video.buffered = {length: 1, start: () => 2, end: () => 3};
  video.dispatchEvent(new Event('play'));
  for (let i = 0; i < 10; i++) await tick();
  assert.ok(!requests.some(row => row.range === 'bytes=0-99'), 'a short forward reserve gets priority');
  video.buffered = {length: 1, start: () => 2, end: () => 8};
  video.dispatchEvent(new Event('timeupdate'));
  for (let i = 0; i < 10; i++) await tick();
  assert.deepEqual(requests.at(-1), {range: 'bytes=0-99', priority: 'low'});
  video.dispatchEvent(new Event('timeupdate'));
  for (let i = 0; i < 10; i++) await tick();
  assert.equal(requests.filter(row => row.range === 'bytes=0-99').length, 1, 'a failed preload does not retry');
  video.currentTime = .2;
  video.dispatchEvent(new Event('seeking'));
  for (let i = 0; i < 10; i++) await tick();
  assert.deepEqual(requests.at(-1), {range: 'bytes=0-99', priority: 'auto'}, 'an explicit seek retries the failed preload as foreground');
  loader.dispose();
}

async function discussionOwnsSuspension() {
  const events = [], element = () => ({value: '', hidden: false, innerHTML: '', dataset: {},
    querySelector: () => ({}), querySelectorAll: () => []});
  const nodes = new Map(), get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  };
  get('#analysisDiscussionDialog').showModal = () => events.push('modal');
  const player = name => ({isConnected: true, hidden: false, closest() { return this.hidden ? {} : null; },
    _pauseBevPlayback() { events.push('pause:' + name); }, _resumeBevPlayback() { events.push('resume:' + name); }});
  const [visible, removed, hiddenLater, alreadyHidden] = ['visible', 'removed', 'hiddenLater', 'alreadyHidden'].map(player);
  alreadyHidden.hidden = true;
  const context = {state: {}, $: get, document: {querySelectorAll: selector => selector === 'video'
    ? [visible, removed, hiddenLater, alreadyHidden] : []}, capturePageContext: () => ({}),
    uiText: zh => zh, escapeHtml: value => value};
  vm.createContext(context); vm.runInContext(source('issue-discussion.js'), context);
  for (const name of ['renderAnalysisDiscussionImages', 'updateAnalysisDiscussionComposerAccess',
    'renderAnalysisDiscussionReplyContext', 'bindReviewMentionComposer', 'updateReviewMentionComposer',
    'disposeReviewMentionComposer']) context[name] = () => {};
  context.discussionActionText = value => value;
  context.loadAnalysisDiscussion = async () => events.push('discussion GET');
  await context.openAnalysisDiscussion('cn1');
  assert.ok(events.indexOf('pause:visible') < events.indexOf('discussion GET'),
    'suspend existing segment downloads before issuing discussion request');
  assert.equal(events.includes('pause:alreadyHidden'), false);
  removed.isConnected = false; hiddenLater.hidden = true;
  context.closeAnalysisDiscussion();
  assert.deepEqual(events.filter(e => e.startsWith('resume:')), ['resume:visible'],
    'closing never restarts removed/hidden players');
  assert.equal(context.state.analysisDiscussion, null);
}

(async () => {
  await pausedSegments();
  await discussionOwnsSuspension();
  console.log('Manual network lifecycle checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
