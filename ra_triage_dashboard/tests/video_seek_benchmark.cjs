// Manual warm-seek benchmark: isolate input-to-visible-frame overhead from
// network/encoding. Uses local media and a private headless Chromium instance.
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const samples = process.env.SEEK_SAMPLES;
if (!samples) throw Error('Set SEEK_SAMPLES to local prepared MP4 fixtures');
const names = (process.env.SEEK_NAMES || 'optimized-current,optimized-closeup').split(',');
const count = Number(process.env.SEEK_COUNT || 20);
const output = process.env.SEEK_RESULT || path.join(samples, 'seek-results.json');
const root = path.resolve(__dirname, '../static');
const playerJs = fs.readFileSync(process.env.SEEK_PLAYER_JS || path.join(root, 'js/bev-video.js'), 'utf8');
const shell = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = JSON.parse('[' + shell.match(/const stylesheetPaths = \[([\s\S]*?)\];/)[1].trim().replace(/,$/, '') + ']');
const html = '<!doctype html><html><head><meta charset="utf-8">'
  + styles.map(name => `<link rel="stylesheet" href="/static/${name}">`).join('')
  + '</head><body style="padding:12px"><div id="player" style="width:781px"></div></body></html>';
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  let file;
  if (url.pathname.startsWith('/static/')) {
    file = path.resolve(root, url.pathname.slice(8));
    if (!file.startsWith(root + path.sep)) return res.writeHead(404).end();
  } else if (names.some(name => url.pathname === `/api/${name}.mp4`)) {
    file = path.join(samples, path.basename(url.pathname));
  } else {
    res.setHeader('Content-Type', 'text/html');return res.end(html);
  }
  const size = fs.statSync(file).size, range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
  const start = range ? Number(range[1]) : 0, end = range?.[2] ? Math.min(size - 1, Number(range[2])) : size - 1;
  res.writeHead(range ? 206 : 200, {'Content-Type': file.endsWith('.mp4') ? 'video/mp4' : 'text/css',
    'Accept-Ranges':'bytes','Cache-Control':'no-store','Content-Length':end - start + 1,
    ...range ? {'Content-Range':`bytes ${start}-${end}/${size}`} : {}});
  const stream = fs.createReadStream(file, {start, end});stream.pipe(res);res.once('close', () => stream.destroy());
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;const results = [];
  try {
    browser = await chromium.launch({headless:true});
    for (const name of names) {
      const page = await browser.newPage({viewport:{width:1440,height:1000}});
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.evaluate(() => {
        window.enhanceDashboardSelects = () => {};
        window.bindPlanningConstraint = () => ({refresh(){},dispose(){}});
        window.uiText = (_zh, en) => en;window.escapeHtml = value => String(value);
        window.t = key => key;window.showToast = msg => {throw Error(msg);};
        window.safeSameOriginAssetUrl = value => {const u=new URL(value,location.origin);return u.origin === location.origin ? u.pathname+u.search : '';};
      });
      await page.addScriptTag({content:playerJs});
      await page.evaluate(name => {
        const root = document.querySelector('#player');
        root.innerHTML = videoPlayerMarkup({url:`/api/${name}.mp4`,duration_ms:40000}, {zoomable:false,compact:true});
        bindBevVideoPlayers(root);window.v = root.querySelector('video');
        // Benchmark only: warm the whole local clip to exclude network stalls.
        v.preload = 'auto';
      }, name);
      await page.waitForFunction(() => v.readyState >= 2 && !v.seeking
        && Array.from({length:v.buffered.length}, (_,i) => v.buffered.end(i)).some(end => end >= 39.8));
      for (let sample=0;sample<count;sample++) {
        const row = await page.evaluate(direction => new Promise((resolve, reject) => {
          const player = v.closest('[data-bev-video-player]'), target = v.currentTime + direction;
          let submitted = false, frameId, rafId, copies = 0, finished = false;
          const observer = new MutationObserver(records => {
            copies += records.flatMap(record => [...record.addedNodes]).filter(node => node.classList?.contains('video-source-frame')).length;
          });
          observer.observe(player,{childList:true,subtree:true});
          const cleanup = () => {finished=true;clearTimeout(timeout);cancelAnimationFrame(rafId);v.cancelVideoFrameCallback(frameId);observer.disconnect();};
          const frame = (_now, metadata) => {
            if (Math.abs(metadata.mediaTime - target) < 0.02) submitted = true;
            else frameId = v.requestVideoFrameCallback(frame);
          };
          frameId = v.requestVideoFrameCallback(frame);
          const start = performance.now();
          const timeout = setTimeout(() => {cleanup();reject(Error('seek never became visible'));}, 10000);
          const check = () => {
            if (finished) return;
            if (submitted && !v.seeking && v.readyState >= 2 && !player.querySelector('.video-source-frame')) {
              const result = {ms:performance.now()-start,target,time:v.currentTime,paused:v.paused,copies};
              cleanup();resolve(result);
            } else rafId = requestAnimationFrame(check);
          };
          rafId = requestAnimationFrame(check);
          player.dispatchEvent(new KeyboardEvent('keydown',{key:direction > 0 ? 'ArrowRight' : 'ArrowLeft',bubbles:true,cancelable:true}));
        }), sample % 2 ? -1 : 1);
        assert.equal(row.time,row.target);assert.equal(row.paused,true);
        results.push({name,sample,...row});
      }
      await page.close();
    }
    const percentile = (values,p) => [...values].sort((a,b)=>a-b)[Math.ceil(values.length*p)-1];
    const summary = names.map(name => {const rows=results.filter(row=>row.name===name), values=rows.map(row=>row.ms);
      return {name,n:rows.length,p50Ms:percentile(values,.5),p95Ms:percentile(values,.95),maxMs:Math.max(...values),canvasCopies:rows.reduce((sum,row)=>sum+row.copies,0)};});
    fs.writeFileSync(output,JSON.stringify({browser:browser.version(),scope:'fully buffered local media; paused1s keyboard jumps',summary,results},null,2));
    console.log(JSON.stringify({summary,output}));
  } finally {if (browser) await browser.close();server.closeAllConnections();server.close();}
})().catch(error => {console.error(error);server.closeAllConnections();server.close();process.exitCode=1;});
