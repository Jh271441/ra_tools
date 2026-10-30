// Real shared player/select/dialog and Cron modules; local fixture media only.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'),original=fs.readFileSync(path.join(root,'index.html'),'utf8');
const clip=process.env.CLOSEUP_TEST_CLIP,poster=process.env.CLOSEUP_TEST_POSTER;
if(!clip||!poster)throw Error('CLOSEUP_TEST_CLIP and CLOSEUP_TEST_POSTER must be local verified fixtures');
const css=[...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m=>m[1]);
const modules=['core-base','i18n-messages','i18n','format-api','planning-constraints','detail-media','media-dialog','daily-cron'];
const html=original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replaceAll('{{RA_TRIAGE_BASE_PATH}}','')
 .replace('</head>',css.map(p=>`<link rel="stylesheet" href="/static/${p}">`).join('')+'</head>')
 .replace('</body>',modules.map(p=>`<script src="/static/js/${p}.js"></script>`).join('')+'</body>');
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/api/broken.mp4')return res.writeHead(404).end();
 let file,type;
 if((url.pathname.endsWith('.mp4')||url.pathname.endsWith('/camera-video'))){file=clip;type='video/mp4';}
 else if(url.pathname.endsWith('.jpg')){file=poster;type='image/jpeg';}
 else if(url.pathname.startsWith('/static/')){file=path.resolve(root,url.pathname.slice(8));if(!file.startsWith(root+'/'))return res.writeHead(404).end();type=file.endsWith('.css')?'text/css; charset=utf-8':'text/javascript; charset=utf-8';}
 else {res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(html);}
 if(!fs.existsSync(file))return res.writeHead(404).end();
 const size=fs.statSync(file).size,range=req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
 res.setHeader('Content-Type',type);res.setHeader('Accept-Ranges','bytes');
 if(range){const start=Number(range[1]),end=Math.min(size-1,range[2]?Number(range[2]):size-1);res.writeHead(206,{'Content-Range':`bytes ${start}-${end}/${size}`,'Content-Length':end-start+1});fs.createReadStream(file,{start,end}).pipe(res);}
 else {res.setHeader('Content-Length',size);fs.createReadStream(file).pipe(res);}
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/daily-cron`);
  await page.evaluate(()=>{
   state.activePage='daily-cron';document.documentElement.dataset.sessionPending='false';
   document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.id!=='dailyCronPage'));
   document.querySelector('#mediaFullscreenButton').addEventListener('click',toggleMediaFullscreen);
   document.querySelector('#mediaDialog').addEventListener('close',cleanupMediaDialog);
   window.fixture={issue_id:'cn_fixture',reference_media:true,assets:{frames:[{url:'/api/full-bev.jpg',offset_ms:0}],video:{url:'/api/bev.mp4',duration_ms:40000,event_time_sec:20,frame_step_ms:100,tracks:[{url:'/api/bev.mp4',label:'BEV 视频'},{url:'/api/assets/cn_fixture/camera-video',label:'Camera102 视频'},{url:'/api/closeup.mp4',source_id:'bev_closeup',label:'局部 BEV 视频',poster_url:'/api/closeup-t0.jpg'}]}},camera:{frames:[{url:'/api/full-camera.jpg',offset_ms:0}]}};
  });
  const pick=async(selector,value)=>{
   const picker=page.locator(selector).locator('..');
   await picker.locator('.ui-select-trigger').scrollIntoViewIfNeeded();
   await picker.locator('.ui-select-trigger').click();
   await picker.locator(`[data-ui-select-value="${value}"]`).click();
  };
  let checks=0;
  for(const width of [1440,390,320])for(const lang of ['zh','en'])for(const theme of ['light','dark']){
   console.log('checking',width,lang,theme);
   await page.setViewportSize({width,height:950});
   await page.evaluate(({lang,theme})=>{
    state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.theme=theme;document.documentElement.dataset.colorTheme=theme;
    renderCloseupCron({state:'collecting',versions:{'0821':{verified:1,queued:1491},'1009':{queued:1480},'1016':{verified:2,queued:1487}}});
    openMedia('video',0,{caseData:window.fixture});
   },{lang,theme});
   const video=page.locator('#mediaVideoStage video');
   await page.waitForFunction(()=>{const v=document.querySelector('#mediaVideoStage video');return v&&v.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-20)<.05;});
   await pick('[data-video-rate]','1.5');
   await page.evaluate(()=>{const v=document.querySelector('#mediaVideoStage video');v.currentTime=23;});
   await page.waitForFunction(()=>!document.querySelector('#mediaVideoStage video').seeking);
   await pick('[data-video-track]','/api/closeup.mp4');
   await page.waitForFunction(()=>{const v=document.querySelector('#mediaVideoStage video');return v.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-23)<.05;});
   assert.equal(await video.getAttribute('poster'),'/api/closeup-t0.jpg');
   assert.equal(await video.evaluate(v=>v.playbackRate),1.5);
   assert.equal(await page.locator('[data-video-track]').locator('..').locator('.ui-select-summary').innerText(),lang==='en'?'Closeup BEV video':'局部 BEV 视频');
   assert.equal(await page.locator('[data-video-status]').isVisible(),false);
   // Changing language retains source, time and rate through the actual refresh hook.
   await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='en'?'zh':'en';refreshBevVideoLanguage(document.querySelector('#mediaVideoStage'));});
   assert.equal(await page.locator('[data-video-track]').inputValue(),'/api/closeup.mp4');
   assert.equal(await video.evaluate(v=>v.currentTime),23);
   const trigger=page.locator('[data-video-track]').locator('..').locator('.ui-select-trigger');
   await trigger.click();
   const panel=page.locator('[data-video-track]').locator('..').locator('.ui-select-panel');
   const bounds=await panel.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=width+1);
   await trigger.press('Escape');assert.equal(await panel.isVisible(),false);
   await trigger.click();await page.locator('#mediaTitle').click();assert.equal(await panel.isVisible(),false);
   await pick('[data-video-track]','/api/assets/cn_fixture/camera-video');
   await page.waitForFunction(()=>document.querySelector('#mediaVideoStage video').readyState>=2);
   assert.equal(await video.getAttribute('poster'),'/api/full-camera.jpg');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),true);
   assert.equal(await page.locator('#mediaDialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),true);
   if(width===1440&&lang==='zh'&&theme==='light'){
    await page.locator('#mediaFullscreenButton').click();
    await page.waitForFunction(()=>Boolean(document.fullscreenElement));
    await pick('[data-video-track]','/api/closeup.mp4');
    await page.evaluate(()=>document.exitFullscreen());
   }
   await page.evaluate(()=>document.querySelector('#mediaDialog').close());
   await page.waitForFunction(()=>document.querySelector('#mediaVideoStage').innerHTML==='');
   assert.equal(await page.locator('#dailyCronCloseupStatus').innerText(),lang==='en'?'Recording':'录制中');
   for(const value of [{state:'blocked_auth',stale:false,versions:{}},{state:'collecting',stale:true,versions:{}},null])await page.evaluate(value=>renderCloseupCron(value),value);
   checks++;
  }
  // A broken optional source retains a usable retry and the other choices.
  await page.evaluate(()=>{openMedia('video',0,{caseData:window.fixture});document.querySelector('#mediaVideoStage video')._setBevVideoTrack('/api/broken.mp4','/api/closeup-t0.jpg');});
  await page.waitForFunction(()=>document.querySelector('[data-bev-video-player]').dataset.loadState==='error');
  assert.equal(await page.locator('[data-video-retry]').isVisible(),true);
  assert.equal(await page.locator('[data-video-track] option').count(),3);
  await page.evaluate(()=>document.querySelector('#mediaDialog').close());
  assert.equal(await page.evaluate(()=>videoPlayerMarkup({url:'/api/closeup.mp4',source_id:'bev_closeup',poster_url:'/api/closeup-t0.jpg',duration_ms:40000,tracks:[]}).includes('data-video-track>')),false);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',layouts:checks,widths:[1440,390,320],languages:['zh','en'],themes:['light','dark'],coverage:['three sources','own poster','time/rate retention','locale refresh','shared picker','Escape/outside close','picker bounds','fullscreen source switch','missing/failed source','Cron stale/auth/empty','no horizontal overflow'],device:'desktop Chromium viewport only'}));
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
