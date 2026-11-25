// Read-only lifecycle tests: no browser profile, production service or business writes.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const source = name => fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
// Exercise the retained experimental loader independently; production defaults
// to the native path and must never instantiate MediaSource or fetch an index.
const segmentFixtureSource = () => source('video-segments.js').replace(
  'const VIDEO_SEGMENT_LOADING_ENABLED = false;', 'const VIDEO_SEGMENT_LOADING_ENABLED = true;');
{
  const context = {};
  vm.createContext(context); vm.runInContext(source('video-segments.js'), context);
  assert.equal(context.videoSegmentManifestUrl('/api/assets/cn1/bev-video-0'), '');
  assert.equal(context.createVideoSegmentLoader({}, {url:'/api/assets/cn1/bev-video-0'}), null);
}
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
  const segments = [0, 1, 2, 3, 4, 5].map(i => ({start: i * 2, end: i * 2 + 2, first: i * 100, last: i * 100 + 99}));
  const manifest = {recipe: 'segments-v1', codec: 'avc1.640028', fingerprint: 'a'.repeat(64),
    duration: 12, size: 600, init: 'AA==', segments};
  let playbackRequested = false;
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
      headers: {'Content-Range': range.replace('=', ' ') + '/600'}});
  }};
  vm.createContext(context); vm.runInContext(segmentFixtureSource(), context);
  const loader = context.createVideoSegmentLoader(video, {url: '/api/assets/cn1/bev-video-0',
    position: () => video.currentTime, playbackRequested: () => playbackRequested,
    attached() {}, fallback() { throw Error('Unexpected native fallback'); }});
  for (let i = 0; i < 10; i++) await tick();
  assert.deepEqual(requests.map(r => r.range), ['bytes=200-299', 'bytes=300-399'],
    'paused video fetches target and forward decoder flush only');
  assert.equal(requests[1].priority, 'low', 'optional decoder neighbor yields network priority');
  video.currentTime = 2.2; video.dispatchEvent(new Event('seeking'));
  for (let i = 0; i < 10; i++) await tick();
  assert.equal(requests.at(-1).range, 'bytes=100-199', 'backward seek still loads the requested GOP');
  video.readyState = 4;
  video.buffered = {length: 1, start: () => 2, end: () => 3};
  video.dispatchEvent(new Event('timeupdate'));
  for (let i = 0; i < 10; i++) await tick();
  assert.ok(!requests.some(row => row.range === 'bytes=0-99'), 'a short forward reserve gets priority');
  video.buffered = {length: 1, start: () => 2, end: () => 8};
  video.dispatchEvent(new Event('timeupdate'));
  for (let i = 0; i < 10; i++) await tick();
  assert.deepEqual(requests.at(-1), {range: 'bytes=0-99', priority: 'low'},
    'a paused player with the forward GOP and enough reserve can warm a left neighbor');
  video.dispatchEvent(new Event('timeupdate'));
  for (let i = 0; i < 10; i++) await tick();
  assert.equal(requests.filter(row => row.range === 'bytes=0-99').length, 1, 'a failed preload does not retry');
  video.currentTime = .2;
  video.dispatchEvent(new Event('seeking'));
  for (let i = 0; i < 10; i++) await tick();
  assert.deepEqual(requests.at(-1), {range: 'bytes=0-99', priority: 'auto'}, 'an explicit seek retries the failed preload as foreground');
  playbackRequested = true;
  video.currentTime = 4.2;
  video.dispatchEvent(new Event('timeupdate'));
  for (let i = 0; i < 10; i++) await tick();
  assert.equal(video.paused,true);
  assert.deepEqual(requests.slice(-2).map(row => row.range),['bytes=400-499','bytes=500-599'],
    'Automatic rebuffering keeps filling forward data while native video is paused');
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
  vm.createContext(context);
  vm.runInContext(source('discussion-drafts.js'), context);
  vm.runInContext(source('issue-discussion.js'), context);
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

async function interruptedSegments(fault, cancel = false) {
  const ranges = [], appends = [];
  let media, fallback = 0, parserResets = 0, loads = 0;
  class Buffer extends EventTarget {
    appendBuffer(bytes) { appends.push(bytes.byteLength); queueMicrotask(() => this.dispatchEvent(new Event('updateend'))); }
    abort() { parserResets++; }
  }
  class Media extends EventTarget {
    constructor() { super(); media = this; this.readyState = 'open'; }
    static isTypeSupported() { return true; }
    addSourceBuffer() { return new Buffer(); }
  }
  const video = new EventTarget();
  Object.assign(video, {paused:true,currentTime:4.2,playbackRate:1,buffered:{length:0},
    load() { loads++; queueMicrotask(() => media.dispatchEvent(new Event('sourceopen'))); }});
  const manifest = {recipe:'segments-v1',codec:'avc1.640028',fingerprint:'b'.repeat(64),
    duration:10,size:500,init:'AA==',segments:[0,1,2,3,4].map(i=>({start:i*2,end:i*2+2,first:i*100,last:i*100+99}))};
  const context = {URL:class extends URL {static createObjectURL(){return 'blob:recovery';} static revokeObjectURL(){}},
    location:{origin:'https://triage.test'},MediaSource:Media,AbortController,Uint8Array,atob,
    setTimeout,clearTimeout,performance,safeSameOriginAssetUrl:value=>value,
    fetch:async(url,options)=>{
      if(url.includes('stream='))return new Response(JSON.stringify(manifest));
      const range=options.headers.Range;ranges.push(range);
      if(fault==='503'&&ranges.length<=2)return new Response(null,{status:503});
      if(fault==='disconnect'&&ranges.length===1)return new Response(new ReadableStream({
        start(controller){controller.enqueue(new Uint8Array(30));setImmediate(()=>controller.error(new TypeError('connection reset')));}
      }),{status:206,headers:{'Content-Range':'bytes 200-299/500'}});
      const [,first,last]=range.match(/bytes=(\d+)-(\d+)/);
      return new Response(new Uint8Array(Number(last)-Number(first)+1),{status:206,
        headers:{'Content-Range':range.replace('=',' ')+'/500'}});
    }};
  vm.createContext(context);vm.runInContext(segmentFixtureSource(),context);
  const loader=context.createVideoSegmentLoader(video,{url:'/api/assets/cn1/bev-video-0',
    position:()=>video.currentTime,attached(){},fallback(){fallback++;}});
  for(let i=0;i<10;i++)await tick();
  if(cancel){
    if(cancel==='suspend')loader.suspend();
    else if(cancel==='seek'){video.currentTime=6.2;video.dispatchEvent(new Event('seeking'));}
    else loader.dispose();
    await new Promise(resolve=>setTimeout(resolve,350));
    if(cancel==='seek'){
      assert.equal(ranges.filter(range=>range==='bytes=200-299').length,1,'A new seek cancels the old retry');
      assert.ok(ranges.includes('bytes=300-399'),'The new target takes over network work');
    }else assert.equal(ranges.length,1,'Suspension/disposal cancels a pending network retry');
    assert.equal(fallback,0,'An old retry cannot replace a disposed source');
    if(cancel!=='suspend'){loader.dispose();return;}
    loader.resume();
  }
  for(let i=0;i<200&&!ranges.includes('bytes=300-399')&&!fallback;i++)await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(fallback,0,'Transient '+fault+' must not replace the current media source');
  assert.equal(loads,1,'Network recovery keeps the existing native video');
  if(fault==='disconnect'){
    assert.deepEqual(ranges,['bytes=200-299','bytes=230-299','bytes=300-399'],
      'Retry requests only the missing suffix of the interrupted GOP');
    assert.deepEqual(appends,[1,30,30,70,100],'Parser recovery replays the prefix before its suffix');
    assert.ok(parserResets>=1);
  }else assert.deepEqual(ranges,['bytes=200-299','bytes=200-299','bytes=200-299','bytes=300-399']);
  loader.dispose();
}

(async () => {
  await pausedSegments();
  await discussionOwnsSuspension();
  await interruptedSegments('disconnect');
  await interruptedSegments('503');
  await interruptedSegments('503',true);
  await interruptedSegments('503','suspend');
  await interruptedSegments('503','seek');
  console.log('Manual network lifecycle checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
