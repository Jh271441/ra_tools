// Cold Review deep links using the actual shell/API decoder/native player and
// synthetic read-only API/media. DISCOVERY_TEST_REF compares a prior Git SHA.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),zlib=require('node:zlib'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'),ref=process.env.DISCOVERY_TEST_REF;
const clip=process.env.DISCOVERY_CLIP;if(!clip)throw Error('Set DISCOVERY_CLIP to a local 40s H264 fixture');
const read=name=>ref?execFileSync('git',['show',`${ref}:ra_triage_dashboard/static/${name}`],{maxBuffer:8e6}):fs.readFileSync(path.join(root,name));
const shell=read('index.html').toString().replaceAll('{{RA_TRIAGE_BASE_PATH}}','/manual');
const modules=read('js/MANIFEST').toString().split('\n').map(s=>s.trim()).filter(s=>s&&!s.startsWith('#'));
const bundle=Buffer.from(modules.map(n=>read('js/'+n).toString()).join('\n;\n'));
const styles=JSON.parse('['+shell.match(/const stylesheetPaths = \[([\s\S]*?)\];/)[1].replace(/,\s*$/,'')+']');
const css=Buffer.from(styles.map(n=>read(n).toString()).join('\n\n'));
let logs=[];const size=fs.statSync(clip).size;
const video={url:'/api/assets/cn99999/bev-video-0',duration_ms:40000,frame_step_ms:100,tracks:[
 {url:'/api/assets/cn99999/bev-video-0',label:'BEV 视频'},
 {url:'/api/assets/cn99999/bev-closeup-video',label:'局部 BEV 视频',source_id:'bev_closeup'}]};
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost'),endpoint=url.pathname.replace('/manual/api/','');
 const row={path:url.pathname,kind:url.searchParams.get('kind'),at:Date.now(),finished:false};logs.push(row);
 res.on('finish',()=>{row.finished=true;row.finishedAt=Date.now();});
 if(req.method!=='GET')return res.writeHead(405).end();
 const send=(body,mime)=>{if(res.destroyed)return;body=Buffer.isBuffer(body)?body:Buffer.from(body);res.setHeader('Content-Type',mime);
  res.setHeader('Cache-Control',mime==='text/html'||mime==='application/json'?'no-store':'private, max-age=300');
  if(req.headers['accept-encoding']?.includes('gzip')&&body.length>=1024){body=zlib.gzipSync(body);res.setHeader('Content-Encoding','gzip');}
  res.end(body);};
 if(endpoint.startsWith('assets/')){
  assert.equal(endpoint,'assets/cn99999/bev-video-0','unselected video must not download');
  assert.notEqual(url.searchParams.get('playback'),'segments-v1');assert.equal(url.searchParams.has('stream'),false);
  const range=req.headers.range?.match(/^bytes=(\d+)-(\d*)$/),first=range?+range[1]:0,last=range?.[2]?Math.min(size-1,+range[2]):size-1;
  res.writeHead(range?206:200,{'Content-Type':'video/mp4','Accept-Ranges':'bytes','Cache-Control':'private, max-age=300','Content-Length':last-first+1,...range?{'Content-Range':`bytes ${first}-${last}/${size}`}:{}});
  const stream=fs.createReadStream(clip,{start:first,end:last});stream.pipe(res);res.on('close',()=>stream.destroy());return;
 }
 if(url.pathname.startsWith('/manual/api/')){
  const data=endpoint==='dashboard-config'?{baselines:[{id:'0508',label:'0508',scope:'fixture',issue_count:1}],default_baseline_ids:['0508'],tag_catalog:[],case_labeling:{active_baseline_ids:['0508']}}
   :endpoint==='session'?{username:'fixture',authenticated:true,verified:true,is_admin:true,access_role:'admin',can_write:true}
   :endpoint==='model-runs'?{items:[],default_model_run_id:null}
   :endpoint==='cases/cn99999'?{issue_id:'cn99999',gt_label:'绕行',assets:{frames:[]},camera:{frames:[]},annotations:[],media_status:'pending'}
   :endpoint==='cases/cn99999/media'?{issue_id:'cn99999',media_status:'ready',assets:row.kind==='video'?{available:true,video,frames:[]}:{available:false,frames:[]},camera:{frames:[]}}
   :endpoint==='cases'?{items:[],total:0,page:1,page_size:20}
   :endpoint==='change-revision'?{revision:0,poll_after_ms:60000}:{items:[]};
  const delay=endpoint==='cases/cn99999/media'?(row.kind==='images'?1400:350):150;
  return setTimeout(()=>send(JSON.stringify(data),'application/json'),delay);
 }
 if(url.pathname.endsWith('/app-bundle.js'))return send(bundle,'text/javascript');
 if(url.pathname.endsWith('/app-bundle.css'))return send(css,'text/css');
 if(url.pathname.startsWith('/manual/static/')){
  const file=url.pathname.slice('/manual/static/'.length);try{return send(read(file),file.endsWith('.css')?'text/css':'text/javascript');}catch{return res.writeHead(404).end();}
 }
 send(shell,'text/html');
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});const results=[];
 try{
  const trials=Number(process.env.DISCOVERY_TRIALS||3),mbps=Number(process.env.DISCOVERY_MBPS||20),latency=150;
  for(let trial=0;trial<trials;trial++){
   const context=await browser.newContext({viewport:{width:Number(process.env.DISCOVERY_WIDTH||1440),height:1000}}),page=await context.newPage(),errors=[];
   page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(45000);logs=[];
   await context.addInitScript(lang=>{localStorage.setItem('ra-triage-ui-language',lang);localStorage.setItem('ra-triage-color-theme',lang==='en'?'light':'dark');},process.env.DISCOVERY_LANG||'zh');
   const cdp=await context.newCDPSession(page);await cdp.send('Network.enable');
   await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
   await cdp.send('Network.emulateNetworkConditions',{offline:false,latency,downloadThroughput:mbps*1e6/8,uploadThroughput:1e6});
   await page.addInitScript(()=>{
    window.playerFrames=[];window.coldVideo=null;
    new MutationObserver(()=>{const v=document.querySelector('#detailHeroMedia video');if(!v||window.coldVideo)return;window.coldVideo=v;
     const record=(_t,m)=>{playerFrames.push(m.mediaTime);if(m.mediaTime>=20&&!window.t0ReadyMs)window.t0ReadyMs=performance.now();if(v.isConnected)v.requestVideoFrameCallback(record);};v.requestVideoFrameCallback(record);
    }).observe(document,{childList:true,subtree:true});
   });
   await page.goto(`http://127.0.0.1:${server.address().port}/manual/review?issue=cn99999&run=none&baselines=0508`,{waitUntil:'domcontentloaded'});
   await page.waitForFunction(()=>window.t0ReadyMs&&coldVideo.readyState>=2&&!coldVideo.seeking);
   const initial=await page.evaluate(()=>({firstFrameMs:t0ReadyMs,time:coldVideo.currentTime,paused:coldVideo.paused,source:coldVideo.src}));
   assert.equal(initial.paused,true);assert.equal(initial.time,20);assert.ok(!initial.source.startsWith('blob:'));
   // Image discovery completes later but must retain the existing decoder.
   await page.waitForFunction(()=>state.caseMediaController===null);
   assert.equal(await page.evaluate(()=>coldVideo===document.querySelector('#detailHeroMedia video')),true);
   await page.locator('#detailHeroMedia [data-video-play]').click();
   await page.waitForFunction(()=>coldVideo.currentTime>22&&playerFrames.at(-1)>21.9&&!coldVideo.paused);
   const played=await page.evaluate(()=>({time:coldVideo.currentTime,frames:playerFrames,source:coldVideo.src}));
   assert.equal(played.source,initial.source);
   assert.ok(played.frames.every((t,i)=>!i||t>=played.frames[i-1]-.001),'continuous playback cannot rewind');
   const media=logs.filter(r=>r.path.endsWith('/media')&&r.kind==='video'),core=logs.find(r=>r.path==='/manual/api/cases/cn99999');
   assert.equal(media.length,1,'early discovery is consumed exactly once');
   assert.ok(logs.find(r=>r.path.includes('/assets/')).at>=core.finishedAt,'only a current core may mount video');
   if(!ref)assert.ok(media[0].at<core.at,'video discovery must overlap bootstrap dependencies');
   assert.deepEqual(errors,[]);
   results.push({trial,mbps,latency,...initial,playedTo:played.time,descriptorBeforeCoreMs:core.at-media[0].at,errors});
   console.log(JSON.stringify(results.at(-1)));
   if(process.env.DISCOVERY_SCREENSHOT)await page.screenshot({path:process.env.DISCOVERY_SCREENSHOT,fullPage:true});
   await context.close();
  }
  const output=process.env.DISCOVERY_OUTPUT||'/tmp/video-discovery-browser.json';fs.writeFileSync(output,JSON.stringify({ref:ref||'working-tree',browser:browser.version(),results},null,2));
 }finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(e=>{console.error(e);server.closeAllConnections();server.close();process.exitCode=1;});
