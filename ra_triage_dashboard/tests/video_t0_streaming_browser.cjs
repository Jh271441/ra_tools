// Native Range streaming with the actual player. Uses a local 40s H264 fixture;
// valid filler NAL units enlarge it without changing frames or keyframe spacing.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const clip = process.env.PLAYBACK_TEST_CLIP;
if (!clip) throw Error('Set PLAYBACK_TEST_CLIP to the local 40s/400-frame H264 fixture');
const output = process.env.PLAYBACK_QA_OUTPUT || '/tmp/video-t0-streaming-qa';
fs.mkdirSync(output, {recursive: true});

function streamingFixture(source) {
  const stsz = source.indexOf(Buffer.from('stsz')) - 4;
  const stco = source.indexOf(Buffer.from('stco')) - 4;
  const mdat = source.indexOf(Buffer.from('mdat')) - 4;
  const avcc = source.indexOf(Buffer.from('avcC')) - 4;
  assert.ok([stsz, stco, mdat, avcc].every(n => n >= 0));
  assert.equal((source[avcc + 12] & 3) + 1, 4, 'AVC samples use four-byte NAL lengths');
  assert.equal(source.readUInt32BE(stsz + 12), 0, 'explicit sample sizes');
  const count = source.readUInt32BE(stsz + 16);
  assert.equal(count, 400);
  assert.equal(source.readUInt32BE(stco + 12), 1, 'single contiguous video chunk');
  const start = source.readUInt32BE(stco + 16);
  assert.equal(start, mdat + 8);
  assert.ok(stsz < mdat, 'faststart metadata precedes media data');
  const header = Buffer.from(source.subarray(0, start));
  const filler = Buffer.alloc(16388, 255);
  filler.writeUInt32BE(16384, 0); filler[4] = 12; filler[filler.length - 1] = 128;
  const frames = []; let at = start;
  for (let i = 0; i < count; i++) {
    const size = source.readUInt32BE(stsz + 20 + i * 4);
    frames.push(source.subarray(at, at + size), filler); at += size;
    header.writeUInt32BE(size + filler.length, stsz + 20 + i * 4);
  }
  assert.equal(at, source.length);
  const result = Buffer.concat([header, ...frames]);
  result.writeUInt32BE(result.length - mdat, mdat);
  return result;
}

const media = streamingFixture(fs.readFileSync(clip));
const requests = [];
const playerJs = fs.readFileSync(path.resolve(__dirname, '../static/js/detail-media.js'), 'utf8');
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.endsWith('.mp4')) {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    return res.end('<!doctype html><body><div id="player"></div></body>');
  }
  const match = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
  const start = match ? Number(match[1]) : 0;
  const end = match?.[2] ? Math.min(media.length - 1, Number(match[2])) : media.length - 1;
  const receipt = {url: url.pathname, start, end, bytesSent: 0, complete: false};
  requests.push(receipt);
  res.writeHead(match ? 206 : 200, {'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes',
    'Cache-Control': 'no-store', 'Content-Length': end - start + 1,
    ...match ? {'Content-Range': `bytes ${start}-${end}/${media.length}`} : {}});
  let at = start;
  // 16KiB/50ms = 320KiB/s. The last 30% is withheld entirely, so waiting for
  // the full resource to finish cannot pass this test.
  const tailGate = Math.floor(media.length * .7);
  const timer = setInterval(() => {
    if (res.destroyed || at >= tailGate) return;
    const next = Math.min(end + 1, at + 16384, tailGate);
    const bytes = media.subarray(at, next); at = next; receipt.bytesSent += bytes.length;
    res.write(bytes);
    if (at > end) {receipt.complete = true; res.end();}
  }, 50);
  res.once('close', () => clearInterval(timer));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser, page;
  const errors = [], results = [];
  try {
    browser = await chromium.launch({headless: true});
    page = await browser.newPage(); page.setDefaultTimeout(12000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.evaluate(() => {
      window.enhanceDashboardSelects = () => {};
      window.bindPlanningConstraint = () => ({refresh() {}, dispose() {}});
      window.uiText = (zh, en) => en;
      window.escapeHtml = value => String(value).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
      window.t = key => key;
      window.showToast = message => {throw Error(message);};
      window.safeSameOriginAssetUrl = value => {
        const url = new URL(String(value || ''), location.origin);
        return url.origin === location.origin && url.pathname.startsWith('/api/') ? url.pathname + url.search : '';
      };
    });
    await page.addScriptTag({content: playerJs});
    await page.evaluate(() => {
      window.mountPlayer = (name, duration = 40000) => {
        const root = document.querySelector('#player'); releaseBevVideoPlayer(root);
        root.innerHTML = videoPlayerMarkup({url: `/api/${name}.mp4`, duration_ms: duration});
        window.events = []; window.startedAt = performance.now();
        const video = root.querySelector('video'); window.video = video;
        for (const name of ['loadedmetadata', 'seeking', 'seeked', 'playing', 'waiting']) {
          video.addEventListener(name, () => events.push({name, ms: Math.round(performance.now() - startedAt),
            time: video.currentTime, readyState: video.readyState}));
        }
        bindBevVideoPlayers(root);
      };
      bevVideoPlaybackPreference = true; mountPlayer('initial');
    });
    assert.equal(await page.locator('video').getAttribute('src'), '/api/initial.mp4#t=20');
    assert.equal(await page.locator('video').evaluate(v => v.readyState), 0);
    assert.equal(await page.locator('video').evaluate(v => v.paused), false, 'play is submitted before metadata');
    const waitPlaying = () => page.waitForFunction(() => !video.paused && !video.seeking && video.currentTime > 20.2
      && document.querySelector('[data-bev-video-player]').dataset.playbackState === 'playing');
    await waitPlaying();
    const initial = await page.evaluate(() => ({events, time: video.currentTime,
      buffered: Array.from({length: video.buffered.length}, (_, i) => [video.buffered.start(i), video.buffered.end(i)])}));
    const initialRequests = requests.filter(r => r.url === '/api/initial.mp4');
    assert.ok(initialRequests.some(r => r.start > media.length * .4), 'a Range request jumps to the t0 keyframe region');
    assert.ok(initialRequests.every(r => !r.complete), 'no full response finished before playback');
    assert.ok(initialRequests.reduce((sum, r) => sum + r.bytesSent, 0) < media.length / 2);
    assert.ok(initial.buffered.some(([start, end]) => start <= 20 && end > 20.2 && end < 39), 'only a local playable window is required');
    assert.ok(initial.events.filter(e => e.name === 'playing').every(e => e.time >= 19.99), 'never play the clip beginning before t0');
    const bufferedEnd = Math.max(...initial.buffered.map(r => r[1]));
    await page.waitForFunction(end => video.buffered.length && video.buffered.end(video.buffered.length - 1) > end + .2, bufferedEnd);
    assert.equal(await page.locator('video').evaluate(v => v.paused), false, 'later media buffers while playback continues');
    results.push({name: 'progressive-t0', ...initial, requests: structuredClone(initialRequests)});

    const position = await page.evaluate(() => {
      video.playbackRate = 1.5; document.querySelector('[data-video-rate]').value = '1.5';
      const position = video.currentTime;
      video._setBevVideoTrack('/api/source-next.mp4'); return position;
    });
    assert.match(await page.locator('video').getAttribute('src'), /source-next\.mp4#t=2\d/);
    await waitPlaying();
    assert.ok(await page.locator('video').evaluate((v, p) => v.currentTime >= p - .02, position));
    assert.equal(await page.locator('video').evaluate(v => v.playbackRate), 1.5);
    results.push({name: 'retained-source-position', position, time: await page.locator('video').evaluate(v => v.currentTime)});

    await page.evaluate(() => mountPlayer('cancelled'));
    await page.locator('[data-bev-video-player]').press('Space');
    assert.equal(await page.locator('[data-bev-video-player]').getAttribute('data-playback-state'), 'paused');
    assert.equal(await page.locator('video').evaluate(v => v.paused), true);
    await page.waitForFunction(() => video.readyState >= 2 && !video.seeking);
    assert.equal(await page.locator('video').evaluate(v => v.paused), true, 'late t0 data cannot reverse Pause');
    assert.deepEqual(await page.evaluate(() => events.filter(e => e.name === 'playing')), []);
    results.push({name: 'cancel-before-t0-ready'});
    assert.deepEqual(errors, []);
    const result = {browser: browser.version(), fixtureBytes: media.length,
      fixture: '40s H264 with valid filler NAL units; original frames/keyframes unchanged',
      bytesPerSecond: 327680, withheldTailFraction: .3, results, errors};
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    if (page) await page.screenshot({path: path.join(output, 'failure.png')});
    console.error(JSON.stringify({errors, requests})); throw error;
  } finally {
    if (browser) await browser.close(); server.closeAllConnections(); server.close();
  }
})().catch(error => {console.error(error); server.closeAllConnections(); server.close(); process.exitCode = 1;});
