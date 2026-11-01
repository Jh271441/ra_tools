// Actual shell, player, media hotkeys and styles; local delayed/range-served media.
// PLAYBACK_TEST_CLIP / PLAYBACK_TEST_POSTER must be local 40s H264/t0 fixtures.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../static');
const clip = process.env.PLAYBACK_TEST_CLIP, poster = process.env.PLAYBACK_TEST_POSTER;
if (!clip || !poster) throw Error('Set local PLAYBACK_TEST_CLIP and PLAYBACK_TEST_POSTER');
const output = process.env.PLAYBACK_QA_OUTPUT || '/tmp/video-playback-intent-qa';
fs.mkdirSync(output, {recursive: true});
const original = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = [...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = fs.readFileSync(path.join(root, 'js/MANIFEST'), 'utf8').split('\n')
  .map(s => s.trim()).filter(s => s && !s.startsWith('#') && s !== 'bind-bootstrap.js');
const html = original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replaceAll('{{RA_TRIAGE_BASE_PATH}}', '')
  .replace('</head>', styles.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('') + '</head>')
  .replace('</body>', modules.map(p => `<script src="/static/js/${p}"></script>`).join('') + '</body>');
const server = http.createServer((req, res) => {
  if (req.method !== 'GET') return res.writeHead(405).end();
  const url = new URL(req.url, 'http://localhost');
  let file, type, delay = 0;
  if (url.pathname.endsWith('.mp4')) {
    file = clip; type = 'video/mp4'; delay = 500;
  } else if (url.pathname.endsWith('/poster.png')) {
    file = poster; type = 'image/png';
  } else if (url.pathname.startsWith('/static/')) {
    file = path.resolve(root, url.pathname.slice(8));
    if (!file.startsWith(root + path.sep)) return res.writeHead(404).end();
    type = file.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8';
  } else {
    res.setHeader('Content-Type', 'text/html; charset=utf-8'); return res.end(html);
  }
  if (!fs.existsSync(file)) return res.writeHead(404).end();
  const size = fs.statSync(file).size, range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
  const start = range ? Number(range[1]) : 0;
  const end = range && range[2] ? Math.min(size - 1, Number(range[2])) : size - 1;
  setTimeout(() => {
    if (res.destroyed) return;
    res.setHeader('Content-Type', type); res.setHeader('Accept-Ranges', 'bytes');
    res.setHeader('Cache-Control', 'no-store'); res.setHeader('Content-Length', end - start + 1);
    if (range) res.writeHead(206, {'Content-Range': `bytes ${start}-${end}/${size}`});
    fs.createReadStream(file, {start, end}).pipe(res);
  }, delay);
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser, page;
  const results = [], errors = [];
  try {
    browser = await chromium.launch({headless: true});
    page = await browser.newPage(); page.setDefaultTimeout(7000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/review`);
    const bootstrap = fs.readFileSync(path.join(root, 'js/bind-bootstrap.js'), 'utf8');
    const start = bootstrap.indexOf('  document.addEventListener("keydown", (event) => {\n    if (!$("#mediaDialog").open)');
    const end = bootstrap.indexOf('  window.addEventListener("popstate"', start);
    assert.ok(start >= 0 && end > start);
    await page.addScriptTag({content: bootstrap.slice(start, end)});
    await page.evaluate(() => {
      api = async () => ({});
      state.config = {baselines: []};
      state.session = {username: 'fixture', verified: true, access_role: 'writer', identity_pending: false};
      document.documentElement.dataset.sessionPending = 'false';
      document.querySelector('#mediaDialog').addEventListener('close', cleanupMediaDialog);
      window.fixtureMount = (view, id) => {
        const pane = document.querySelector(view === 'review' ? '#detailPane' : '#caseLabelingMedia');
        releaseBevVideoPlayer(pane);
        const data = {issue_id: id, reference_media: true, assets: {
          frames: [{url: '/api/poster.png', offset_ms: 0}], video: {
            url: `/api/${id}.mp4`, duration_ms: 40000, frame_step_ms: 100,
            tracks: [{url: `/api/${id}.mp4`, label: 'BEV 视频'},
              {url: `/api/${id}-closeup.mp4`, label: '局部 BEV 视频', source_id: 'bev_closeup', poster_url: '/api/poster.png'}],
          }}, camera: {frames: [{url: '/api/poster.png', offset_ms: 0}]}};
        state.selectedId = id; state.selectedCase = data;
        state.caseLabeling.issueId = id; state.caseLabeling.caseData = data;
        pane.innerHTML = detailMediaCommandMarkup(data) + heroMediaSection(data);
        bindDetailMedia(data);
      };
    });
    const waitReady = () => page.waitForFunction(() => {
      const v = detailHeroMediaEl().querySelector('video'); return v.readyState >= 2 && !v.seeking;
    });
    const waitPlaying = () => page.waitForFunction(() => {
      const root = detailHeroMediaEl(), v = root.querySelector('video');
      return !v.paused && !v.seeking && v.currentTime > 20.02 && root.querySelector('[data-bev-video-player]').dataset.playbackState === 'playing';
    });
    let n = 0;
    for (const width of [320, 390, 1440]) for (const lang of ['zh', 'en'])
      for (const theme of ['dark', 'light']) for (const view of ['review', 'labeling']) {
        await page.setViewportSize({width, height: 1000});
        const id = `cn_fixture_${++n}`;
        await page.evaluate(({view, lang, theme, id}) => {
          closeDialog('mediaDialog');
          pauseBevVideoPlayers(detailHeroMediaEl());
          bevVideoPlaybackPreference = false;
          state.activePage = view; document.body.dataset.activePage = view;
          applyColorTheme(theme, {persist: false});
          document.querySelectorAll('.app-page').forEach(p => p.classList.toggle('hidden', p.dataset.page !== view));
          setReviewView(id);
          document.querySelector('#caseLabelingDetail').classList.remove('hidden');
          document.querySelector('#caseLabelingGalleryView').classList.add('hidden');
          applyUiLanguage(lang, {persist: false});
          fixtureMount(view, id);
        }, {view, lang, theme, id});
        const selector = view === 'review' ? '#detailHeroMedia' : '#caseLabelingHeroMedia';
        let hero = page.locator(selector), player = hero.locator('[data-bev-video-player]');
        const focus = async () => (width === 1440 ? hero : player).focus();
        await focus();
        await page.keyboard.press('Space');
        assert.equal(await player.getAttribute('data-playback-state'), 'waiting');
        assert.equal(await player.locator('[data-video-play]').innerText(), lang === 'zh' ? '暂停' : 'Pause');
        assert.equal(await player.locator('video').evaluate(v => v.readyState), 0, 'feedback precedes metadata');
        assert.equal(await player.locator('video').getAttribute('src'), `/api/${id}.mp4#t=20`);
        assert.equal(await player.locator('video').evaluate(v => v.paused), false, 'native asynchronous playback is already requested');
        const pendingGeometry = await player.evaluate(p => {
          const box = el => {const r = el.getBoundingClientRect(); return {height: r.height, top: r.top};};
          return {controls: box(p.querySelector('.bev-video-controls')), status: box(p.querySelector('[data-video-playback-state]'))};
        });
        await page.keyboard.press('Space');
        assert.equal(await player.getAttribute('data-playback-state'), 'paused');
        await waitReady();
        assert.equal(await player.locator('video').evaluate(v => v.paused), true, 'cancel remains paused after metadata');
        await page.keyboard.press('Space'); await waitPlaying();
        const readyGeometry = await player.locator('.bev-video-controls').boundingBox();
        assert.equal(readyGeometry.height, pendingGeometry.controls.height, 'status updates never reflow the toolbar');
        if (width < 640) assert.ok((await player.locator('[data-video-play]').boundingBox()).height >= 44);
        await page.evaluate(() => {
          const v = detailHeroMediaEl().querySelector('video');
          v._setBevVideoTrack('/api/rapid-one.mp4', '/api/poster.png');
          v._setBevVideoTrack('/api/rapid-two.mp4', '/api/poster.png');
        });
        assert.equal(await player.getAttribute('data-playback-state'), 'waiting');
        await page.keyboard.press('Space');
        assert.equal(await player.getAttribute('data-playback-state'), 'paused');
        await waitReady(); assert.equal(await player.locator('video').evaluate(v => v.paused), true);
        await page.keyboard.press('Space'); await waitPlaying();
        const before = await player.locator('video').evaluate(v => v.currentTime);
        await page.evaluate(() => {
          const v = detailHeroMediaEl().querySelector('video');
          v._setBevVideoTrack('/api/continue-one.mp4'); v._setBevVideoTrack('/api/continue-two.mp4');
        });
        await waitPlaying();
        assert.ok(await player.locator('video').evaluate((v, t) => v.currentTime >= t - .1, before));
        await page.evaluate(lang => applyUiLanguage(lang === 'zh' ? 'en' : 'zh', {persist: false}), lang);
        assert.ok(await player.evaluate(p => p.querySelector('[data-video-playback-state]').textContent === t(`media.state_${p.dataset.playbackState}`)), 'live playback status uses the new locale');
        await page.evaluate(lang => applyUiLanguage(lang, {persist: false}), lang);
        await page.evaluate(({view, id}) => fixtureMount(view, id + '_next'), {view, id});
        await waitPlaying(); // The next Case inherits the last explicit Play choice.
        hero = page.locator(selector); player = hero.locator('[data-bev-video-player]');
        await focus(); await page.keyboard.press('Space');
        await page.evaluate(({view, id}) => fixtureMount(view, id + '_paused'), {view, id});
        await waitReady();
        assert.equal(await hero.locator('video').evaluate(v => v.paused), true);
        assert.equal(await player.getAttribute('data-playback-state'), 'paused');
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        if ((width === 320 && lang === 'en' && theme === 'light') || (width === 1440 && lang === 'zh' && theme === 'dark')) {
          await hero.screenshot({path: path.join(output, `${view}-${width}-${lang}-${theme}.png`)});
        }
        results.push({width, lang, theme, view});
      }
    // Dialog ownership and a late metadata response after navigation away.
    await page.evaluate(() => {bevVideoPlaybackPreference = true; openMedia('video', 0);});
    await page.waitForFunction(() => document.querySelector('#mediaVideoStage video')?.currentTime > 20.02);
    assert.equal(await page.locator('#caseLabelingHeroMedia video').evaluate(v => v.paused), true);
    await page.evaluate(() => switchMediaKind('camera'));
    assert.equal(await page.locator('#mediaVideoStage video').evaluate(v => v.paused), true);
    await page.evaluate(() => switchMediaKind('video'));
    await page.waitForFunction(() => !document.querySelector('#mediaVideoStage video').paused);
    await page.evaluate(() => {
      closeDialog('mediaDialog'); fixtureMount('labeling', 'cn_late_hidden');
      pauseBevVideoPlayers(detailHeroMediaEl());
    });
    await waitReady();
    assert.equal(await page.locator('#caseLabelingHeroMedia video').evaluate(v => v.paused), true);
    assert.deepEqual(errors, []);
    const result = {browser: browser.version(), checks: results.length, results, errors, injectedResponseDelayMs: 500};
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    if (page) await page.screenshot({path: path.join(output, 'failure.png'), fullPage: true});
    console.error('Browser errors:', JSON.stringify(errors)); throw error;
  } finally {
    if (browser) await browser.close(); server.close();
  }
})().catch(error => {console.error(error); server.close(); process.exitCode = 1;});
