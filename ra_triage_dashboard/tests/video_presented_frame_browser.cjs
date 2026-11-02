// Manual compositor regression. FRAME_TEST_DIR contains two distinct-color
// 40s MP4s and their t0 posters: bev.mp4/png and closeup.mp4/png.
// closeup frame0 is green, t0 is magenta,23s is cyan; BEV is blue.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const fixtures = process.env.FRAME_TEST_DIR;
if (!fixtures) throw Error('Set FRAME_TEST_DIR to local color-coded video fixtures');
const output = process.env.FRAME_QA_OUTPUT || path.join(fixtures, 'compositor');
fs.mkdirSync(output, {recursive: true});
const root = path.resolve(__dirname, '../static');
const shell = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = [...shell.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = fs.readFileSync(path.join(root, 'js/MANIFEST'), 'utf8').split('\n')
  .map(s => s.trim()).filter(s => s && !s.startsWith('#') && s !== 'bind-bootstrap.js');
const html = shell.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '').replaceAll('{{RA_TRIAGE_BASE_PATH}}', '')
  .replace('</head>', styles.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('') + '</head>')
  .replace('</body>', modules.map(p => `<script src="/static/js/${p}"></script>`).join('') + '</body>');
const requests = [];
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost'); requests.push(url.pathname);
  let file, delay = 0;
  if (url.pathname.startsWith('/api/')) {
    const name = path.basename(url.pathname);
    if (!['bev.mp4', 'bev.png', 'closeup.mp4', 'closeup.png'].includes(name)) return res.writeHead(404).end();
    file = path.join(fixtures, name); delay = url.searchParams.has('cold') ? 1500 : name === 'closeup.mp4' ? 350 : 0;
  } else if (url.pathname.startsWith('/static/')) {
    file = path.resolve(root, url.pathname.slice(8));
    if (!file.startsWith(root + path.sep)) return res.writeHead(404).end();
  } else {
    res.setHeader('Content-Type', 'text/html; charset=utf-8'); return res.end(html);
  }
  const size = fs.statSync(file).size, range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
  const start = range ? Number(range[1]) : 0, end = range?.[2] ? Math.min(size - 1, Number(range[2])) : size - 1;
  setTimeout(() => {
    if (res.destroyed) return;
    const type = file.endsWith('.mp4') ? 'video/mp4' : file.endsWith('.png') ? 'image/png'
      : file.endsWith('.css') ? 'text/css' : 'text/javascript';
    res.writeHead(range ? 206 : 200, {'Content-Type': type, 'Content-Length': end - start + 1,
      'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store',
      ...range ? {'Content-Range': `bytes ${start}-${end}/${size}`} : {}});
    const stream = fs.createReadStream(file, {start, end}); stream.pipe(res); res.once('close', () => stream.destroy());
  }, delay);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser; const results = [], frames = [], errors = [];
  try {
    browser = await chromium.launch({headless: true});
    for (const width of (process.env.FRAME_WIDTHS || '320,390,1440').split(',').map(Number)) for (const view of ['review', 'labeling']) {
      const context = await browser.newContext({viewport: {width, height: 1000}}), page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`http://127.0.0.1:${server.address().port}/review`);
      const before = requests.length;
      await page.evaluate(({view, width}) => {
        window.presented = [];
        const requestFrame = HTMLVideoElement.prototype.requestVideoFrameCallback;
        HTMLVideoElement.prototype.requestVideoFrameCallback = function(callback) {
          return requestFrame.call(this, (now, metadata) => {presented.push({time:this.currentTime,frame:metadata.mediaTime,seeking:this.seeking,ready:this.readyState});callback(now, metadata);});
        };
        api = async () => ({}); state.config = {baselines: []};
        state.session = {username: 'fixture', verified: true, access_role: 'writer'};
        document.documentElement.dataset.sessionPending = 'false';
        state.activePage = view; document.body.dataset.activePage = view;
        applyColorTheme(width === 320 ? 'light' : 'dark', {persist: false});
        applyUiLanguage(width === 320 ? 'en' : 'zh', {persist: false});
        document.querySelectorAll('.app-page').forEach(p => p.classList.toggle('hidden', p.dataset.page !== view));
        setReviewView('cn_frames'); document.querySelector('#caseLabelingDetail').classList.remove('hidden');
        document.querySelector('#caseLabelingGalleryView').classList.add('hidden');
        const data = {issue_id: 'cn_frames', assets: {frames: [{url: '/api/bev.png', offset_ms: 0}], video: {
          url: '/api/bev.mp4', duration_ms: 40000, frame_step_ms: 100,
          tracks: [{url: '/api/bev.mp4', label: 'BEV 视频'},
            {url: '/api/closeup.mp4', source_id: 'bev_closeup', label: '局部 BEV 视频', poster_url: '/api/closeup.png'}]}}, camera: {frames: []}};
        state.selectedCase = data; state.selectedId = data.issue_id;
        state.caseLabeling = {issueId: data.issue_id, caseData: data};
        const pane = detailMediaPane(); pane.innerHTML = detailMediaCommandMarkup(data) + heroMediaSection(data); bindDetailMedia(data);
        window.v = detailHeroMediaEl().querySelector('video');
      }, {view, width});
      const ready = () => page.waitForFunction(() => v.readyState >= 2 && !v.seeking && !detailHeroMediaEl().querySelector('.video-source-frame'));
      await ready(); await page.waitForTimeout(150);
      const initialRequests = requests.slice(before).filter(p => p.startsWith('/api/'));
      assert(initialRequests.every(p => !p.includes('closeup')), 'initial entry must not load the unselected closeup video or poster');
      assert.equal(await page.evaluate(() => v.paused), true);
      assert.equal(await page.evaluate(() => v.currentTime), 20);
      await page.evaluate(() => {const seek = detailHeroMediaEl().querySelector('[data-video-seek]');seek.value = '23';seek.dispatchEvent(new Event('change'));});
      await ready();
      await page.locator(view === 'review' ? '#detailHeroMedia video' : '#caseLabelingHeroMedia video').scrollIntoViewIfNeeded();
      const cdp = await context.newCDPSession(page); let phase = '', phaseFrames = [];
      cdp.on('Page.screencastFrame', event => {
        const name = `${view}-${width}-${phase}-${frames.length}.png`;
        fs.writeFileSync(path.join(output, name), Buffer.from(event.data, 'base64'));
        const item = {name, phase, view, width, metadata: event.metadata}; frames.push(item); phaseFrames.push(item);
        cdp.send('Page.screencastFrameAck', {sessionId: event.sessionId}).catch(() => {});
      });
      const record = async (name, action, expected) => {
        phase = name; phaseFrames = [];
        const rect = await page.evaluate(() => {const r = v.getBoundingClientRect();return {x:r.x + r.width / 2, y:r.y + r.height / 2};});
        await cdp.send('Page.startScreencast', {format: 'png', everyNthFrame: 1});
        const begin = Date.now(); await action();
        try { await ready(); } catch (error) {
          console.error(JSON.stringify({view,width,phase,state:await page.evaluate(() => ({time:v.currentTime,ready:v.readyState,seeking:v.seeking,held:Boolean(detailHeroMediaEl().querySelector('.video-source-frame')),presented}))}));
          throw error;
        }
        await page.waitForTimeout(180);
        await cdp.send('Page.stopScreencast');
        assert(phaseFrames.length, 'compositor frames were captured');
        results.push({view, width, phase: name, ms: Date.now() - begin, point: rect, expected,
          frames: phaseFrames.map(f => f.name), paused: await page.evaluate(() => v.paused), time: await page.evaluate(() => v.currentTime), initialRequests});
      };
      await record('source-at23', () => page.evaluate(() => v._setBevVideoTrack('/api/closeup.mp4', '/api/closeup.png')), ['bev', 'target23']);
      assert.equal(await page.evaluate(() => v.currentTime), 23);
      await record('back-to20', () => page.evaluate(() => {const s = detailHeroMediaEl().querySelector('[data-video-seek]');s.value = '20';s.dispatchEvent(new Event('change'));}), ['target23', 't0']);
      await record('rapid-sources', () => page.evaluate(() => {v._setBevVideoTrack('/api/bev.mp4', '/api/bev.png');v._setBevVideoTrack('/api/closeup.mp4', '/api/closeup.png');}), ['t0']);
      await record('switch-before-metadata', () => page.evaluate(() => {
        const pane = detailMediaPane(); releaseBevVideoPlayer(pane);
        const data = structuredClone(state.selectedCase);data.issue_id = 'cn_cold_frames';data.assets.video.url = '/api/bev.mp4?cold=1';
        state.selectedCase = data;state.caseLabeling.caseData = data;
        pane.innerHTML = detailMediaCommandMarkup(data) + heroMediaSection(data);bindDetailMedia(data);
        v = detailHeroMediaEl().querySelector('video');
        const s = detailHeroMediaEl().querySelector('[data-video-seek]');s.value = '23';s.dispatchEvent(new Event('change'));
        v._setBevVideoTrack('/api/closeup.mp4', '/api/closeup.png');
      }), ['t0', 'neutral', 'target23']);
      assert.equal(await page.evaluate(() => v.currentTime), 23);
      await record('new-closeup-player', () => page.evaluate(() => {
        const pane = detailMediaPane();releaseBevVideoPlayer(pane);
        const data = structuredClone(state.selectedCase);data.issue_id = 'cn_closeup_frames';
        data.assets.video = {...data.assets.video,...data.assets.video.tracks.find(t => t.source_id === 'bev_closeup')};
        state.selectedCase = data;state.caseLabeling.caseData = data;
        pane.innerHTML = detailMediaCommandMarkup(data) + heroMediaSection(data);bindDetailMedia(data);
        v = detailHeroMediaEl().querySelector('video');
      }), ['target23', 't0']);
      assert.equal(await page.evaluate(() => v.currentTime), 20);
      await record('seek-to-end', () => page.evaluate(() => {
        const s = detailHeroMediaEl().querySelector('[data-video-seek]');s.value = '40';s.dispatchEvent(new Event('change'));
      }), ['t0', 'target23']);
      assert.equal(await page.evaluate(() => v.currentTime), 40);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      await context.close();
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({browser: browser.version(), results, frames, errors}, null, 2));
    const checked = require('node:child_process').spawnSync(process.env.FRAME_PYTHON || 'python3',
      [path.join(__dirname, 'verify_video_presented_frames.py'), output], {encoding: 'utf8'});
    assert.equal(checked.status, 0, checked.stderr || checked.stdout);process.stdout.write(checked.stdout);
    console.log(JSON.stringify({scenarios: results.length, compositorFrames: frames.length, errors, output}));
  } finally {
    if (browser) await browser.close(); server.closeAllConnections(); server.close();
  }
})().catch(error => {console.error(error);server.closeAllConnections();server.close();process.exitCode = 1;});
