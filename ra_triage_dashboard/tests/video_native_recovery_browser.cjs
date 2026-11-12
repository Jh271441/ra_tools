// Production native recovery: exact frames, continuous playback and buffered seek reuse.
// Uses already prepared local media; never connects to production or the user's browser.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const nativeRoot=process.env.SEGMENT_NATIVE_ROOT,streamRoot=process.env.SEGMENT_STREAM_ROOT;
if(!nativeRoot||!streamRoot)throw Error('Set SEGMENT_NATIVE_ROOT and SEGMENT_STREAM_ROOT');
const output=process.env.SEGMENT_QA_OUTPUT||path.join(streamRoot,'player-qa.json');
const indexes=JSON.parse(fs.readFileSync(path.join(streamRoot,'candidate-build.json'),'utf8'));
const staticRoot=path.resolve(process.env.PLAYER_STATIC_ROOT||path.join(__dirname,'../static'));const logs=[],faultAttempts=new Map(),brokenNativeServed=new Set();
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost'),name=path.basename(url.pathname,'.mp4'),mode=url.searchParams.get('mode')||'ready';
 if(!url.pathname.endsWith('.mp4')){res.setHeader('Content-Type','text/html');return res.end('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><div id="player"></div><div id="reference"></div>');}
 const manifest=indexes.find(x=>x.name===name)?.manifest;if(!manifest)return res.writeHead(404).end();
 const kind=url.searchParams.get('stream')?'manifest':url.searchParams.get('playback')==='segments-v1'?'segment':'native';
 const row={name,mode,kind,range:req.headers.range||'',finished:false,aborted:false};logs.push(row);
 res.on('finish',()=>row.finished=true);res.on('close',()=>{if(!res.writableFinished)row.aborted=true;});
 if(kind==='manifest'){
  const send=()=>{if(res.destroyed)return;res.setHeader('Content-Type','application/json');
   if(mode==='pending')return res.writeHead(202).end('{"status":"pending"}');
   if(mode==='broken-native'&&!brokenNativeServed.has(name))return res.writeHead(202).end('{"status":"pending"}');
   const value=mode==='malformed'?{...manifest,segments:[]} : manifest;res.end(JSON.stringify(value));};
  return mode==='delay'?setTimeout(send,400):mode==='timeout'?setTimeout(send,2400):send();
 }
 const file=kind==='segment'?path.join(streamRoot,`fragkey-${name}.mp4`):path.join(nativeRoot,`optimized-${name}.mp4`);
 const size=fs.statSync(file).size;if(kind==='segment')assert.equal(size,manifest.size);
 const range=req.headers.range?.match(/^bytes=(\d+)-(\d*)$/),first=range?+range[1]:0,last=range?.[2]?Math.min(size-1,+range[2]):size-1;
 if(first>last)return res.writeHead(416).end();
 const segment=manifest.segments.find(s=>s.first<=first&&first<=s.last);
 const faultKey=`${name}:${mode}:${segment?.start}`;
 const attempt=(faultAttempts.get(faultKey)||0)+1;
 if(kind==='segment')faultAttempts.set(faultKey,attempt);
 if(kind==='segment'&&(mode==='unavailablealways'||(mode==='unavailabletwice'&&segment?.start===20&&attempt<=2))){
  return res.writeHead(503).end();
 }
 if(kind==='native'&&mode==='broken-native'&&!brokenNativeServed.has(name)){
  brokenNativeServed.add(name);return res.writeHead(200,{'Content-Type':'video/mp4'}).end('invalid media');
 }
 const bad=kind==='segment'&&mode==='range200';
 res.writeHead(range&&!bad?206:200,{'Content-Type':'video/mp4','Cache-Control':'no-store','Accept-Ranges':'bytes','Content-Length':last-first+1,
  ...(range&&!bad?{'Content-Range':`bytes ${first}-${last}/${size}`}:{})});
 const cutoff=kind==='segment'&&attempt===1&&((mode==='cutonce'&&segment?.start===20)||(mode==='cutfuture'&&segment?.start===24));
 const stream=fs.createReadStream(file,{start:first,end:cutoff?Math.min(last,first+192*1024-1):last});
 if(cutoff){stream.pipe(res,{end:false});stream.on('end',()=>setTimeout(()=>res.destroy(),50));res.on('close',()=>stream.destroy());return;}
 // Hold optional backward data so readiness cannot accidentally depend on it.
 const delay=kind==='segment'&&mode==='delayprevious'&&[18,36].includes(segment?.start);
 const timer=delay?setTimeout(()=>{if(!res.destroyed)stream.pipe(res);},2000):null;
 if(!delay)stream.pipe(res);
 res.on('close',()=>{if(timer)clearTimeout(timer);stream.destroy();});
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});const results=[],errors=[];
 const makePage=async({mode='ready',unsupported=false,network=null,mount=true}={})=>{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(30000);
  page.on('pageerror',e=>errors.push(e.message));
  if(unsupported)await page.addInitScript(()=>window.MediaSource=undefined);
  if(network){const cdp=await page.context().newCDPSession(page),pending=new Map();page.networkCancellations=[];
   await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
   cdp.on('Network.requestWillBeSent',e=>pending.set(e.requestId,e.request.url));
   cdp.on('Network.loadingFailed',e=>{if(e.canceled)page.networkCancellations.push(pending.get(e.requestId));});
   await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:network.latency,downloadThroughput:network.mbps*1e6/8,uploadThroughput:1e6});}
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(()=>{
   window.enhanceDashboardSelects=()=>{};window.bindPlanningConstraint=()=>({refresh(){},dispose(){}});window.uiText=(zh,en)=>en;window.t=k=>k;window.showToast=msg=>{throw Error(msg);};
   window.escapeHtml=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
   window.safeSameOriginAssetUrl=v=>{const u=new URL(String(v||''),location.origin);return u.origin===location.origin?u.pathname+u.search:'';};
   window.watch=v=>{v._submitted=[];const frame=(_now,m)=>{v._submitted.push(m.mediaTime);v._lastPresented=m.mediaTime;if(v.isConnected)v.requestVideoFrameCallback(frame);};v.requestVideoFrameCallback(frame);};
  });
  await page.addScriptTag({path:path.join(staticRoot,'js/video-segments.js')});await page.addScriptTag({path:path.join(staticRoot,'js/bev-video.js')});await page.addScriptTag({path:path.join(staticRoot,'js/detail-media.js')});
  await page.evaluate(()=>{
   window.mount=(mode,name='current',total=40000)=>{const root=document.querySelector('#player');releaseBevVideoPlayer(root);const url=`/api/assets/cn99999/${name}.mp4?mode=${mode}`;
    root.innerHTML=videoPlayerMarkup({url,duration_ms:total,frame_step_ms:100,tracks:[{url,label:'BEV 视频'},{url:`/api/assets/cn99999/closeup.mp4?mode=${mode}`,label:'局部 BEV 视频',source_id:'bev_closeup'}]},{zoomable:false});window.v=root.querySelector('video');watch(v);bindBevVideoPlayers(root);};
   window.frameHash=async(video,target)=>{
    const seekTarget=Math.min(target,Math.max(0,video.duration-.00001));
    const expected=Math.floor((seekTarget+.000001)*10)/10;
    if(Math.abs(video.currentTime-seekTarget)>.000001){const done=new Promise((r,j)=>{const t=setTimeout(()=>j(Error('seek timeout '+target)),20000);video.addEventListener('seeked',()=>{clearTimeout(t);r();},{once:true});});video.currentTime=seekTarget;await done;}
    const began=performance.now();while(Math.abs((video._lastPresented??-1)-expected)>.001||video.seeking||video.readyState<2){if(performance.now()-began>20000)throw Error('submitted frame timeout '+target+' last '+video._lastPresented);await new Promise(r=>requestAnimationFrame(r));}
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    const c=document.createElement('canvas');c.width=video.videoWidth;c.height=video.videoHeight;const ctx=c.getContext('2d');ctx.drawImage(video,0,0);
    return {mediaTime:video._lastPresented,hash:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',ctx.getImageData(0,0,c.width,c.height).data))).map(x=>x.toString(16).padStart(2,'0')).join('')};
   };
  });
  if(mount)await page.evaluate(mode=>window.mount(mode),mode);return page;
 };
 const ready=page=>page.waitForFunction(()=>v.readyState>=2&&!v.seeking&&!document.querySelector('.video-source-frame'));

 try{
  let page=await makePage();await ready(page);
  assert.equal(await page.evaluate(()=>v.paused&&v.currentTime===20&&!v.src.startsWith('blob:')&&v.preload==='auto'),true);
  assert.equal(logs.some(x=>x.kind!=='native'||x.name==='closeup'),false);
  console.log('initial native state',await page.evaluate(()=>({duration:v.duration,network:v.networkState,buffered:Array.from({length:v.buffered.length},(_,i)=>[v.buffered.start(i),v.buffered.end(i)])})));
  const initial=await page.evaluate(()=>Array.from({length:v.buffered.length},(_,i)=>[v.buffered.start(i),v.buffered.end(i)]));
  await page.evaluate(()=>{const native=document.createElement('video');native.muted=true;native.src='/native/current.mp4';document.querySelector('#reference').append(native);window.reference=native;watch(native);});
  await page.waitForFunction(()=>reference.readyState>=1);
  const pixels=[];
  for(const target of [20.05,19.95,20.15,23.05,2.05,38.95,19,25,20.05]){
   const hashes=await page.evaluate(async target=>({target,native:await frameHash(reference,target),stream:await frameHash(v,target)}),target);
   assert.deepEqual(hashes.stream,hashes.native,'native pixel mismatch at '+target);pixels.push(hashes);
  }
  const buffered=await page.evaluate(()=>Array.from({length:v.buffered.length},(_,i)=>[v.buffered.start(i),v.buffered.end(i)]));
  const source=await page.evaluate(()=>v.src);
  await page.evaluate(()=>{v._submitted=[];document.querySelector('[data-video-play]').click();});
  await page.waitForFunction(()=>v.currentTime>28&&v._lastPresented>27.9&&!v.paused);
  const frames=await page.evaluate(()=>v._submitted.slice());
  assert.ok(frames.every((t,i)=>!i||t>=frames[i-1]-.001),'continuous playback cannot move backward');
  assert.equal(await page.evaluate(()=>v.src),source,'buffer progress cannot rebuild the source');
  await page.locator('[data-video-play]').click();
  results.push({scenario:'native-paused-buffer-pixels-continuous-playback',initial,buffered,pixels,frames});await page.close();
  for(const [from,to,target] of [['current','closeup',20.05],['current','closeup',40],['closeup','current',40]]){
   page=await makePage({mount:false});await page.evaluate(from=>mount('ready',from),from);await ready(page);
   await page.evaluate(target=>v.currentTime=target,target);await ready(page);
   await page.evaluate(to=>v._setBevVideoTrack(`/api/assets/cn99999/${to}.mp4?mode=ready`),to);await ready(page);
   assert.ok(Math.abs(await page.evaluate(()=>v.currentTime)-target)<.001);
   assert.equal(await page.evaluate(()=>v.paused&&!v.src.startsWith('blob:')),true);
   await page.evaluate(to=>{const native=document.createElement('video');native.muted=true;native.src=`/native/${to}.mp4`;document.querySelector('#reference').append(native);window.reference=native;watch(native);},to);
   await page.waitForFunction(()=>reference.readyState>=1);
   const pixels=await page.evaluate(async target=>({native:await frameHash(reference,target),stream:await frameHash(v,target)}),target);
   assert.deepEqual(pixels.stream,pixels.native);
   results.push({scenario:'native-source-switch-position',from,to,target,pixels});await page.close();
  }
  {
  page=await makePage({network:{mbps:2,latency:150}});
  await page.evaluate(()=>{document.querySelector('[data-video-play]').click();document.querySelector('[data-video-play]').click();});
  await ready(page);assert.equal(await page.evaluate(()=>v.paused),true);
  await page.waitForFunction(()=>v.buffered.length&&v.buffered.end(v.buffered.length-1)>=24.5,{},{timeout:90000});
  const requestsAtReady=logs.length;
  await page.evaluate(()=>{v._submitted=[];document.querySelector('[data-video-play]').click();});
  await page.waitForFunction(()=>v.currentTime>24&&v._lastPresented>23.9&&!v.paused);
  const frames=await page.evaluate(()=>v._submitted.slice());
  assert.ok(frames.every((t,i)=>!i||t>=frames[i-1]-.001));
  assert.equal(logs.length,requestsAtReady,'cached continuous playback must not fetch more ranges');
  await page.locator('[data-video-play]').click();
  const source=await page.evaluate(()=>v.src);
  for(const target of [23.05,20.05,23.05,20.05]){await page.evaluate(t=>{const s=document.querySelector('[data-video-seek]');s.value=t;s.dispatchEvent(new Event('change'));},target);await ready(page);}
  assert.equal(await page.evaluate(()=>v.src),source);
  assert.equal(logs.length,requestsAtReady,'repeated hot seeks reuse loaded data');
  results.push({scenario:'weak-network-paused-fill-and-cache-reuse',frames});await page.close();
  }
  assert.equal(logs.some(x=>x.kind!=='native'),false,'production never requests fragmented media or manifests');
  assert.deepEqual(errors,[]);
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({browser:browser.version(),results,errors,logs},null,2));
  console.log(JSON.stringify({scenarios:results.length,pixels:12,errors,initial:results[0].initial,buffered:results[0].buffered,output}));
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(e=>{console.error(e);server.closeAllConnections();server.close();process.exitCode=1;});
