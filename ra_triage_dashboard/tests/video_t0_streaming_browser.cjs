// Whole-clip playback under an interrupted network using the actual player.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const clip = process.env.PLAYBACK_TEST_CLIP;
if (!clip) throw Error('Set PLAYBACK_TEST_CLIP to the local 40s/400-frame H264 fixture');
const output = process.env.PLAYBACK_QA_OUTPUT || '/tmp/video-t0-streaming-qa';
fs.mkdirSync(output, {recursive: true});

// Use the exact 40-second MP4 supplied to this test. Withhold the end
// of the first transfer until the test explicitly releases it.
const media = fs.readFileSync(clip);
let releaseTail = false;
let failNextDownload = false;
const requests = [];
const playerJs = fs.readFileSync(path.resolve(__dirname, '../static/js/bev-video.js'), 'utf8');
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.endsWith('.mp4')) {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    return res.end('<!doctype html><body><div id="player"></div></body>');
  }
  if (failNextDownload) {
    failNextDownload = false;
    res.writeHead(206, {'Content-Type': 'video/mp4', 'Content-Range': `bytes 0-15/${media.length}`});
    return res.end(media.subarray(0, 16));
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
  const timer = setInterval(() => {
    const limit = releaseTail ? media.length : Math.floor(media.length * .7);
    if (res.destroyed || at >= limit) return;
    const next = Math.min(end + 1, at + 65536, limit);
    res.write(media.subarray(at, next));
    receipt.bytesSent += next - at;
    at = next;
    if (at > end) {receipt.complete = true; res.end();}
  }, 2);
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
      mountPlayer('initial');
    });
    assert.equal(await page.locator('video').evaluate(v => v.paused), true, 'preloading does not start playback');
    await page.locator('[data-bev-video-player]').press('Space');
    for (let i = 0; i < 200 && (requests[0]?.bytesSent || 0) < Math.floor(media.length * .7); i++) {
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    assert.equal(requests[0]?.bytesSent, Math.floor(media.length * .7));
    assert.equal(await page.locator('video').getAttribute('src'), null);
    assert.equal(await page.locator('[data-video-play]').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('video').evaluate(v => v.readyState), 0);
    releaseTail = true;
    const waitPlaying = () => page.waitForFunction(() => !video.paused && !video.seeking && video.currentTime > 20.2);
    await waitPlaying();
    assert.ok(requests[0].complete);
    await page.locator('[data-bev-video-player]').press('Space');
    await page.context().setOffline(true);
    for (const target of [37, 2, 35, 4]) {
      await page.evaluate(t => {
        window.presented = null;
        function frame(_, metadata) {
          if (Math.abs(metadata.mediaTime - t) < .11) window.presented = metadata.mediaTime;
          else video.requestVideoFrameCallback(frame);
        }
        video.requestVideoFrameCallback(frame);
        const seek = document.querySelector('[data-video-seek]');
        seek.value = t;
        seek.dispatchEvent(new Event('change'));
      }, target);
      await page.waitForFunction(() => presented !== null && !video.seeking);
    }
    await page.locator('[data-bev-video-player]').press('ArrowLeft');
    await page.waitForFunction(() => video.currentTime === 3 && !video.seeking);
    await page.locator('[data-bev-video-player]').press('ArrowRight');
    await page.waitForFunction(() => video.currentTime === 4 && !video.seeking);
    await page.locator('[data-bev-video-player]').press('Space');
    await page.waitForFunction(() => !video.paused && video.currentTime > 4.3);
    assert.equal(requests.length, 1);
    results.push({name: 'offline-seek-and-play', requests: structuredClone(requests)});
    await page.context().setOffline(false);
    const position = await page.evaluate(() => {
      video.playbackRate = 1.5; document.querySelector('[data-video-rate]').value = '1.5';
      const position = video.currentTime;
      video._setBevVideoTrack('/api/source-next.mp4'); return position;
    });
    assert.match(await page.locator('video').getAttribute('data-video-source'), /source-next\.mp4\?playback=short-gop-v1#t=\d/);
    await page.waitForFunction(() => !video.paused && !video.seeking && video.readyState >= 2);
    assert.ok(await page.locator('video').evaluate((v, p) => v.currentTime >= p - .02, position));
    assert.equal(await page.locator('video').evaluate(v => v.playbackRate), 1.5);
    results.push({name: 'retained-source-position', position, time: await page.locator('video').evaluate(v => v.currentTime)});

    await page.evaluate(() => mountPlayer('cancelled'));
    assert.equal(await page.locator('video').evaluate(v => v.paused), true, 'a new video does not inherit Play');
    await page.locator('[data-bev-video-player]').press('Space');
    await page.locator('[data-bev-video-player]').press('Space');
    assert.equal(await page.locator('[data-bev-video-player]').getAttribute('data-playback-state'), 'paused');
    assert.equal(await page.locator('video').evaluate(v => v.paused), true);
    await page.waitForFunction(() => video.readyState >= 2 && !video.seeking);
    assert.equal(await page.locator('video').evaluate(v => v.paused), true, 'late t0 data cannot reverse Pause');
    assert.deepEqual(await page.evaluate(() => events.filter(e => e.name === 'playing')), []);
    results.push({name: 'cancel-before-t0-ready'});
    failNextDownload = true;
    await page.evaluate(() => mountPlayer('partial'));
    const retry = page.locator('[data-video-retry]');
    await retry.waitFor({state: 'visible'});
    assert.equal(await page.locator('video').getAttribute('src'), null);
    await retry.click();
    await page.waitForFunction(() => video.readyState >= 2 && !video.seeking && video.currentTime === 20);
    assert.equal(await page.locator('video').evaluate(v => v.paused), true);
    results.push({name: 'partial-response-rejected-and-retried'});
    assert.deepEqual(errors, []);
    const result = {browser: browser.version(), fixtureBytes: media.length,
      results, errors};
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    if (page) await page.screenshot({path: path.join(output, 'failure.png')});
    console.error(JSON.stringify({errors, requests})); throw error;
  } finally {
    if (browser) await browser.close(); server.closeAllConnections(); server.close();
  }
})().catch(error => {console.error(error); server.closeAllConnections(); server.close(); process.exitCode = 1;});
