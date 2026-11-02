// Manual native-player benchmark. CDP simulates bandwidth/latency; no user browser or business writes.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {chromium}=require('playwright');
const root=process.env.STARTUP_SAMPLES;
if(!root)throw Error('Set STARTUP_SAMPLES to a directory of local MP4 benchmark fixtures');
const output=process.env.STARTUP_RESULT||path.join(root,'startup-results.json');
const count=Number(process.env.STARTUP_COUNT||20),mbps=Number(process.env.STARTUP_MBPS||20),latency=Number(process.env.STARTUP_LATENCY||40);
const names=(process.env.STARTUP_NAMES||'original,optimized').split(',');
const playerJs=fs.readFileSync(process.env.STARTUP_PLAYER_JS||path.resolve(__dirname,'../static/js/detail-media.js'),'utf8');
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(!url.pathname.endsWith('.mp4')){res.setHeader('Content-Type','text/html');return res.end('<!doctype html><body><div id="player"></div></body>');}
 const name=path.basename(url.pathname);if(!names.map(n=>n+'.mp4').includes(name)){res.writeHead(404);return res.end();}
 const file=path.join(root,name),size=fs.statSync(file).size,m=req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
 const start=m?Number(m[1]):0,end=m?.[2]?Math.min(size-1,Number(m[2])):size-1;
 res.writeHead(m?206:200,{'Content-Type':'video/mp4','Accept-Ranges':'bytes','Cache-Control':'no-store','Content-Length':end-start+1,...m?{'Content-Range':`bytes ${start}-${end}/${size}`}:{}});
 const stream=fs.createReadStream(file,{start,end});stream.pipe(res);res.once('close',()=>stream.destroy());
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});const results=[];
 try{
 for(const name of names)for(let sample=0;sample<count;sample++){
  const page=await browser.newPage(),session=await page.context().newCDPSession(page);const ranges=[];let received=0;
  await session.send('Network.enable');await session.send('Network.setCacheDisabled',{cacheDisabled:true});
  await session.send('Network.emulateNetworkConditions',{offline:false,latency,downloadThroughput:mbps*1e6/8,uploadThroughput:mbps*1e6/8});
  session.on('Network.requestWillBeSent',e=>{if(e.request.url.includes('.mp4'))ranges.push({range:e.request.headers.Range||e.request.headers.range||'',time:e.timestamp});});
  session.on('Network.dataReceived',e=>{received+=e.encodedDataLength;});
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(()=>{
   window.enhanceDashboardSelects=()=>{};window.bindPlanningConstraint=()=>({refresh(){},dispose(){}});window.uiText=(zh,en)=>en;
   window.escapeHtml=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));window.t=k=>k;window.showToast=msg=>{throw Error(msg);};
   window.safeSameOriginAssetUrl=v=>{const u=new URL(String(v||''),location.origin);return u.origin===location.origin?u.pathname+u.search:'';};
  });
  await page.addScriptTag({content:playerJs});
  await page.evaluate(({name,sample})=>{
   const root=document.querySelector('#player');window.mountedAt=performance.now();window.metrics={events:[]};
   root.innerHTML=videoPlayerMarkup({url:`/api/${name}.mp4?sample=${sample}`,duration_ms:40000});const v=root.querySelector('video');window.video=v;
   for(const event of ['loadedmetadata','loadeddata','canplay','seeking','seeked','playing','waiting','error'])v.addEventListener(event,()=>metrics.events.push({event,ms:performance.now()-mountedAt,time:v.currentTime,ready:v.readyState}));
   function frame(now,meta){if(window.clickedAt && !v.paused && meta.mediaTime>20.01 && !metrics.firstFrameMs){metrics.firstFrameMs=performance.now()-clickedAt;metrics.mediaTime=meta.mediaTime;}else v.requestVideoFrameCallback(frame);}
   v.requestVideoFrameCallback(frame);bindBevVideoPlayers(root);
   root.querySelector('[data-video-play]').addEventListener('click',()=>{window.clickedAt=performance.now();metrics.preClickMs=clickedAt-mountedAt;},true);
   root.querySelector('[data-video-play]').click();
  },{name,sample});
  try{await page.waitForFunction(()=>metrics.firstFrameMs,null,{timeout:75000});}catch(e){console.log('timedout',name);}
  const row=await page.evaluate(()=>({...metrics,time:video.currentTime,paused:video.paused,buffered:Array.from({length:video.buffered.length},(_,i)=>[video.buffered.start(i),video.buffered.end(i)])}));
  results.push({name,sample,received,ranges,...row});console.log(JSON.stringify({name,sample,firstFrameMs:row.firstFrameMs,received}));await page.close();
 }
 const summary=names.map(name=>{const values=results.filter(r=>r.name===name).map(r=>r.firstFrameMs||Infinity).sort((a,b)=>a-b);return{name,n:values.length,p50Ms:values[Math.ceil(values.length*.5)-1],p95Ms:values[Math.ceil(values.length*.95)-1],maxMs:values.at(-1)};});
 const data={browser:browser.version(),network:{mbps,latencyMs:latency,cache:'disabled',click:'immediate after mount'},summary,results};fs.writeFileSync(output,JSON.stringify(data,null,2));console.log(JSON.stringify({summary,output}));
 const budget=Number(process.env.STARTUP_BUDGET_MS||0);
 if(results.some(r=>!Number.isFinite(r.firstFrameMs)) || (budget && summary.some(s=>s.p95Ms>budget)))throw Error('Video startup budget failed');
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(e=>{console.error(e);server.closeAllConnections();server.close();process.exitCode=1;});
