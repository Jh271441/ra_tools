// Full-quality MSE: exact frame pixels, target-first requests, cancellation and native recovery.
// Uses already prepared local media; never connects to production or the user's browser.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const nativeRoot=process.env.SEGMENT_NATIVE_ROOT,streamRoot=process.env.SEGMENT_STREAM_ROOT;
if(!nativeRoot||!streamRoot)throw Error('Set SEGMENT_NATIVE_ROOT and SEGMENT_STREAM_ROOT');
const output=process.env.SEGMENT_QA_OUTPUT||path.join(streamRoot,'player-qa.json');
const indexes=JSON.parse(fs.readFileSync(path.join(streamRoot,'candidate-build.json'),'utf8'));
const staticRoot=path.resolve(__dirname,'../static');const logs=[];
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
   const value=mode==='malformed'?{...manifest,segments:[]} : manifest;res.end(JSON.stringify(value));};
  return mode==='delay'?setTimeout(send,400):mode==='timeout'?setTimeout(send,2400):send();
 }
 const file=kind==='segment'?path.join(streamRoot,`fragkey-${name}.mp4`):path.join(nativeRoot,`optimized-${name}.mp4`);
 const size=fs.statSync(file).size;if(kind==='segment')assert.equal(size,manifest.size);
 const range=req.headers.range?.match(/^bytes=(\d+)-(\d*)$/),first=range?+range[1]:0,last=range?.[2]?Math.min(size-1,+range[2]):size-1;
 if(first>last)return res.writeHead(416).end();
 const bad=kind==='segment'&&mode==='range200';
 res.writeHead(range&&!bad?206:200,{'Content-Type':'video/mp4','Cache-Control':'no-store','Accept-Ranges':'bytes','Content-Length':last-first+1,
  ...(range&&!bad?{'Content-Range':`bytes ${first}-${last}/${size}`}:{})});
 const stream=fs.createReadStream(file,{start:first,end:last});
 // Hold optional backward data so readiness cannot accidentally depend on it.
 const segment=manifest.segments.find(s=>s.first===first);
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
  assert.equal(await page.evaluate(()=>v.paused&&v.currentTime===20&&v.src.startsWith('blob:')),true);
  assert.equal(logs.filter(x=>x.kind==='segment')[0].range,(()=>{const s=indexes.find(x=>x.name==='current').manifest.segments.find(s=>s.start<=20&&s.end>20);return`bytes=${s.first}-${s.last}`;})());
  assert.equal(logs.some(x=>x.kind==='native'||x.name==='closeup'),false);
  await page.evaluate(()=>{const native=document.createElement('video');native.muted=true;native.width=320;native.src='/native/current.mp4';document.querySelector('#reference').append(native);window.reference=native;watch(native);});
  await page.waitForFunction(()=>reference.readyState>=1);
  const pixels=[];
  for(const target of [20.05,19.95,20.15,23.05,2.05,38.95,19,25,20.05]){
   const hashes=await page.evaluate(async target=>({target,native:await frameHash(reference,target),stream:await frameHash(v,target)}),target);
   assert.equal(hashes.stream.mediaTime,hashes.native.mediaTime);assert.equal(hashes.stream.hash,hashes.native.hash,'pixel mismatch at '+target);pixels.push(hashes);
  }
  const buffered=await page.evaluate(()=>Array.from({length:v.buffered.length},(_,i)=>[v.buffered.start(i),v.buffered.end(i)]));
  assert.ok(buffered.reduce((n,[a,b])=>n+b-a,0)<=20.01);
  await page.evaluate(()=>{const rate=document.querySelector('[data-video-rate]');rate.value='1.5';rate.dispatchEvent(new Event('change'));v._setBevVideoTrack('/api/assets/cn99999/closeup.mp4?mode=ready');});
  await ready(page);assert.equal(await page.evaluate(()=>v.paused&&Math.abs(v.currentTime-20.05)<.001&&v.playbackRate===1.5&&videoCanonicalAssetUrl(videoElementAssetUrl(v)).includes('closeup')),true);
  await page.evaluate(()=>{v._setBevVideoTrack('/api/assets/cn99999/current.mp4?mode=ready');v._setBevVideoTrack('/api/assets/cn99999/closeup.mp4?mode=ready');v._setBevVideoTrack('/api/assets/cn99999/current.mp4?mode=ready');});await ready(page);
  assert.equal(await page.evaluate(()=>v.paused&&Math.abs(v.currentTime-20.05)<.001&&videoElementAssetUrl(v).includes('/current.mp4')),true);
  await page.evaluate(()=>document.querySelector('[data-video-play]').click());await page.waitForFunction(()=>!v.paused&&v.currentTime>20.3);await page.evaluate(()=>document.querySelector('[data-video-play]').click());assert.equal(await page.evaluate(()=>v.paused),true);
  await page.evaluate(()=>{document.querySelector('[data-video-play]').click();v._setBevVideoTrack('/api/assets/cn99999/closeup.mp4?mode=delay');});
  await page.waitForFunction(()=>!v.paused&&v.currentTime>20.5&&!document.querySelector('.video-source-frame'));
  await page.evaluate(()=>{v._setBevVideoTrack('/api/assets/cn99999/current.mp4?mode=delay');document.querySelector('[data-video-play]').click();});await ready(page);
  assert.equal(await page.evaluate(()=>v.paused),true);
  await page.evaluate(()=>{v.currentTime=39.95;document.querySelector('[data-video-play]').click();});await page.waitForFunction(()=>v.ended);
  await page.evaluate(()=>document.querySelector('[data-video-play]').click());await page.waitForFunction(()=>!v.paused&&v.currentTime<2&&v.currentTime>.1);
  await page.evaluate(()=>document.querySelector('[data-video-play]').click());
  results.push({scenario:'paused-t0-pixels-seek-buffer-source-rate-play',pixels,buffered});await page.close();
  for(const name of ['big','closeup']){
   page=await makePage({mount:false});await page.evaluate(name=>mount('ready',name),name);await ready(page);
   await page.evaluate(name=>{const native=document.createElement('video');native.muted=true;native.width=320;native.src=`/native/${name}.mp4`;document.querySelector('#reference').append(native);window.reference=native;watch(native);},name);
   await page.waitForFunction(()=>reference.readyState>=1);const comparisons=[];
   for(const target of [19.95,20.05,21.95,23.05,23.95]){const row=await page.evaluate(async target=>({target,native:await frameHash(reference,target),stream:await frameHash(v,target)}),target);assert.deepEqual(row.stream,row.native);comparisons.push(row);}
   results.push({scenario:'full-quality-pixels',name,comparisons});await page.close();
  }
  for(const [from,to,target,mode] of [
   ['current','closeup',39.9,'ready'],['current','closeup',40,'ready'],['closeup','current',40,'ready'],
   ['current','closeup',40,'pending'],['closeup','current',40,'pending'],
   ['current','closeup',40,'delayprevious'],['closeup','current',40,'delayprevious'],
   ['current','closeup',21.95,'delayprevious'],['closeup','current',21.95,'delayprevious'],
  ]){
   page=await makePage({mount:false});await page.evaluate(from=>mount('ready',from),from);await ready(page);
   await page.evaluate(target=>v.currentTime=target,target);await ready(page);
   const start=logs.length;
   await page.evaluate(({to,mode})=>v._setBevVideoTrack(`/api/assets/cn99999/${to}.mp4?mode=${mode}`),{to,mode});
   await ready(page);
   const state=await page.evaluate(()=>({time:v.currentTime,frame:v._lastPresented,paused:v.paused,rate:v.playbackRate,source:v.src}));
   assert.equal(state.paused,true);
   assert.ok(Math.abs(state.time-target)<.001);
   assert.equal(state.frame,target===40?39.9:Math.floor((target+.000001)*10)/10);
   if(target===40)assert.ok(state.time<40,'source replacement must request a displayable final frame');
   assert.equal(state.source.startsWith('blob:'),mode!=='pending');
   const requests=logs.slice(start),manifest=indexes.find(x=>x.name===to).manifest;
   const at=manifest.segments.findIndex(s=>Math.min(target,39.99999)<s.end);
   if(mode!=='pending'){
    const segment=requests.find(x=>x.kind==='segment'),s=manifest.segments[at];
    assert.equal(segment?.range,`bytes=${s.first}-${s.last}`,'switch starts with the target GOP, including the exclusive clip end');
   }
   if(mode==='delayprevious'){
    const backward=manifest.segments[at-1];
    assert.equal(requests.some(x=>x.kind==='segment'&&x.range===`bytes=${backward.first}-${backward.last}`&&x.finished),false,
     'target presentation must not wait for optional backward data');
    if(target!==40){const next=manifest.segments[at+1];assert.equal(requests.filter(x=>x.kind==='segment')[1]?.range,`bytes=${next.first}-${next.last}`);}
   }
   await page.evaluate(to=>{const native=document.createElement('video');native.muted=true;native.src=`/native/${to}.mp4`;document.querySelector('#reference').append(native);window.reference=native;watch(native);},to);
   await page.waitForFunction(()=>reference.readyState>=1);
   const pixels=await page.evaluate(async target=>({native:await frameHash(reference,target),stream:await frameHash(v,target)}),target);
   assert.deepEqual(pixels.stream,pixels.native,'end/source target pixels must match unchanged native media');
   results.push({scenario:'source-boundary-and-forward-priority',from,to,target,mode,state,pixels,requests});await page.close();
  }
  for(const mode of ['delay','pending','malformed','range200','timeout','unsupported']){
   const start=logs.length;page=await makePage({mode,unsupported:mode==='unsupported'});
   await page.evaluate(()=>{document.querySelector('[data-video-play]').click();document.querySelector('[data-video-play]').click();});await ready(page);
   const state=await page.evaluate(()=>({paused:v.paused,time:v.currentTime,source:v.src,playback:document.querySelector('[data-bev-video-player]').dataset.playbackState}));
   assert.equal(state.paused,true);assert.equal(state.time,20);assert.equal(state.playback,'paused');
   assert.equal(state.source.startsWith('blob:'),mode==='delay');
   assert.equal(logs.slice(start).filter(x=>x.kind==='manifest').length,mode==='unsupported'?0:1);
   results.push({scenario:'cancel-and-recovery',mode,state,requests:logs.slice(start)});await page.close();
  }
  page=await makePage({mode:'delay'});await page.evaluate(()=>{const seek=document.querySelector('[data-video-seek]');seek.value='7.05';seek.dispatchEvent(new Event('change'));});await ready(page);
  assert.ok(Math.abs(await page.evaluate(()=>v.currentTime)-7.05)<.001);results.push({scenario:'seek-before-manifest',time:await page.evaluate(()=>v.currentTime)});await page.close();
  page=await makePage({mode:'delay'});await page.locator('[data-bev-video-player]').press('ArrowRight');await ready(page);
  assert.equal(await page.evaluate(()=>v.currentTime),21);await page.evaluate(()=>document.querySelector('[data-video-play]').click());
  await page.waitForFunction(()=>v.currentTime>21.3&&Number(document.querySelector('[data-video-seek]').value)>21.1);
  results.push({scenario:'arrow-before-manifest-and-live-timeline'});await page.close();
  for(const mode of ['ready','pending']){page=await makePage({mount:false});await page.evaluate(mode=>mount(mode,'current',0),mode);await ready(page);assert.equal(await page.evaluate(()=>v.currentTime),20);results.push({scenario:'unknown-descriptor-duration',mode});await page.close();}
  page=await makePage({mode:'delayprevious'});await ready(page);
  await page.evaluate(()=>document.querySelector('[data-video-play]').click());
  await page.waitForFunction(()=>!v.paused&&v.currentTime>=20.8);
  const rewind=await page.evaluate(()=>{
   const from=v.currentTime,target=from-1;
   const player=document.querySelector('[data-bev-video-player]');
   player.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true}));
   return {from,target,frames:v._submitted.length};
  });
  assert.ok(rewind.target<20,'rewind crosses the start of the cached range');
  await page.waitForFunction(({from,target})=>{
   const seek=document.querySelector('[data-video-seek]');
   return v.paused&&v.currentTime>=from&&Math.abs(Number(seek.value)-target)<.06;
  },rewind);
  await page.waitForFunction(({frames,target})=>!v.paused&&v.currentTime>target+.15
   &&v._submitted.slice(frames).some(t=>Math.abs(t-target)<.11),rewind);
  assert.equal(await page.locator('[data-video-play]').getAttribute('aria-pressed'),'true');
  results.push({scenario:'playing-backward-across-cold-boundary',target:rewind.target});
  await page.close();
  const current=indexes.find(x=>x.name==='current').manifest;
  for(const [firstKey,returnKey,step,target] of [
   ['ArrowLeft','ArrowRight',1,19],['ArrowRight','ArrowLeft',5,25],
  ]){
   page=await makePage({network:{mbps:2,latency:150}});await ready(page);
   await page.waitForFunction(()=>v.buffered.length&&v.buffered.end(v.buffered.length-1)>=23.99);
   await page.evaluate(step=>document.querySelector('[data-video-step]').value=String(step),step);
   const player=page.locator('[data-bev-video-player]');
   const segment=current.segments.find(row=>row.start<=target&&target<row.end);
   const start=logs.length;
   await player.press(firstKey);
   await page.waitForFunction(({start,target})=>{
    for(let i=0;i<v.buffered.length;i++){
     const end=v.buffered.end(i);
     if(v.buffered.start(i)<=start+.001&&end>start+.1&&end<target) return true;
    }
    return false;
   },{start:segment.start,target});
   await player.press(returnKey);
   await page.waitForFunction(()=>v.currentTime===20&&!v.seeking);
   await player.press(firstKey);
   await page.waitForFunction(target=>v.paused&&!v.seeking&&v._lastPresented===target,target);
   const ranges=logs.slice(start).filter(row=>row.kind==='segment')
    .map(row=>row.range.match(/^bytes=(\d+)-(\d+)$/))
    .filter(match=>match&&Number(match[2])===segment.last);
   assert.equal(ranges.length,2);
   assert.equal(Number(ranges[0][1]),segment.first);
   assert.ok(Number(ranges[1][1])>segment.first,'returning to a cold target downloads only the missing suffix');
   assert.ok(page.networkCancellations.some(url=>url?.includes('playback=segments-v1')));
   const native=pixels.find(row=>row.target===target).native;
   const stream=await page.evaluate(target=>frameHash(v,target),target);
   assert.deepEqual(stream,native,'resuming a partial fragment must preserve the exact frame pixels');
   results.push({scenario:'resume-interrupted-cold-seek',target,
    resumedBytes:Number(ranges[1][1])-segment.first,pixels:{native,stream}});
   await page.close();
  }
  const start=logs.length;page=await makePage({network:{mbps:2,latency:150}});await ready(page);
  await page.evaluate(()=>{v.currentTime=2.05;setTimeout(()=>v.currentTime=38.05,200);setTimeout(()=>v.currentTime=6.05,400);setTimeout(()=>v.currentTime=6.15,500);setTimeout(()=>v.currentTime=6.25,600);});
  await page.waitForFunction(()=>!v.seeking&&v.readyState>=2&&Math.abs(v.currentTime-6.25)<.001);
  const six=current.segments.find(x=>x.start<=6&&x.end>6);
  assert.equal(logs.slice(start).filter(x=>x.kind==='segment'&&x.range===`bytes=${six.first}-${six.last}`).length,1);
  // CDP throttles delivery after the loopback server can finish writing. Check
  // cancellation at the client, where the obsolete response is still pending.
  assert.ok(page.networkCancellations.some(url=>url?.includes('playback=segments-v1')));
  await page.evaluate(()=>v._pauseBevPlayback());const count=logs.length;await new Promise(r=>setTimeout(r,500));assert.equal(logs.length,count);
  await page.evaluate(()=>v._resumeBevPlayback());await ready(page);assert.equal(await page.evaluate(()=>v.paused),true);
  await page.evaluate(()=>releaseBevVideoPlayer(document.querySelector('#player')));const disposedCount=logs.length;await new Promise(r=>setTimeout(r,500));assert.equal(logs.length,disposedCount);
  results.push({scenario:'weak-network-cancel-same-gop-suspend-resume-dispose',requests:logs.slice(start),cancellations:page.networkCancellations});await page.close();
  assert.deepEqual(errors,[]);
  const pixelComparisons=results.reduce((count,row)=>count+(row.comparisons?.length
   ?? (Array.isArray(row.pixels)?row.pixels.length:Number(Boolean(row.pixels)))),0);
  fs.writeFileSync(output,JSON.stringify({browser:browser.version(),results,errors,requests:logs},null,2));console.log(JSON.stringify({output,scenarios:results.length,pixelComparisons,errors}));
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(e=>{console.error(e);fs.writeFileSync(output+'.failure.json',JSON.stringify({error:e.message,requests:logs},null,2));server.closeAllConnections();server.close();process.exitCode=1;});
