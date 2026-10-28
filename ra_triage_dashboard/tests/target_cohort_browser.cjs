// Actual shell/styles/shared controls; synthetic state and read-only request capture.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../static'), original=fs.readFileSync(path.join(root,'index.html'),'utf8');
const css=[...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m=>m[1]);
const modules=['core-base','i18n-messages','i18n','format-api','session-config','routing','runs','work-split','review-gallery','review-form','case-labeling'];
const html=original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replaceAll('{{RA_TRIAGE_BASE_PATH}}','')
  .replace('</head>',css.map(p=>`<link rel="stylesheet" href="/static/${p}">`).join('')+'</head>')
  .replace('</body>',modules.map(p=>`<script src="/static/js/${p}.js"></script>`).join('')+'</body>');
const server=http.createServer((req,res)=>{
  if(req.method!=='GET')return res.writeHead(405).end();
  const url=new URL(req.url,'http://localhost');
  if(!url.pathname.startsWith('/static/')){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(html);}
  const file=path.resolve(root,url.pathname.slice(8));
  if(!file.startsWith(root+'/')||!fs.existsSync(file))return res.writeHead(404).end();
  res.setHeader('Content-Type',file.endsWith('.css')?'text/css; charset=utf-8':'text/javascript; charset=utf-8');res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage(),errors=[],results=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/review`);
    await page.evaluate(()=>{
      state.config={baselines:[{id:'version-20261009',scope:'fixture',label:'1009'}]};
      state.baselineCatalog=state.config.baselines;state.selectedBaselineIds=['version-20261009'];
      document.querySelectorAll('.multi-filter').forEach(root=>renderMultiFilter(root));
      enhanceDashboardSelects();
      window.scheduleReviewFilterReload=()=>{
        history.replaceState({},'',pageUrl('review'));
        window.fixtureParams=currentReviewGalleryExportParams().toString();
      };
      loadCaseLabelingCases=async()=>{window.fixtureParams=caseLabelingListParams().toString();persistCaseLabelingRoute();};
      bindCaseLabelingEvents();
    });
    const columnWidths = new Map();
    for(const width of [1920,1440,1180,1025,1024,768,390,320])for(const lang of ['zh','en'])for(const theme of ['dark','light'])for(const view of ['review','labeling']){
      await page.setViewportSize({width,height:1000});
      await page.evaluate(({view,lang,theme})=>{
        closeAllUiSelects();state.activePage=view;state.uiLanguage=lang;
        document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;
        document.documentElement.dataset.sessionPending='false';document.body.dataset.activePage=view;
        document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!==view));
        document.querySelector('#filterForm').classList.add('is-open');document.querySelector('#caseLabelingFilterForm').classList.add('is-open');
        applyDomI18n(document);state.reviewTargetGroup='';state.caseLabeling.targetGroup='';
        renderReviewTargetGroupPicker();renderCaseLabelingStatusPicker();
      },{view,lang,theme});
      const selector=view==='review'?'#reviewTargetGroupPicker':'#caseLabelingTargetGroupPicker';
      const trigger=page.locator(selector+' .ui-select-trigger');
      // Both galleries use the same unit; context fields span exactly two units.
      for(const progress of [false,true]) {
        const layout=await page.evaluate(({view,progress})=>{
          document.querySelector('#reviewTaskProgressField').hidden=!progress;
          const form=document.querySelector(view==='review'?'#filterForm':'#caseLabelingFilterForm');
          const wide='.filter-model-run,.filter-search,.review-task-filter,.review-workflow-mode,.case-labeling-search,.case-labeling-task';
          const fields=[...form.children].filter(e=>e.getBoundingClientRect().width&&e.tagName!=='BUTTON');
          return {gap:parseFloat(getComputedStyle(form).columnGap),fields:fields.map(e=>({
            width:e.getBoundingClientRect().width,bottom:e.getBoundingClientRect().bottom,wide:e.matches(wide)
          }))};
        },{view,progress});
        const normal=layout.fields.filter(e=>!e.wide);
        const unit=normal[0].width;
        assert.ok(normal.every(e=>Math.abs(e.width-unit)<1),JSON.stringify({width,view,layout}));
        if(width>=1025){
          assert.ok(unit>=140);
          assert.ok(layout.fields.filter(e=>e.wide).every(e=>Math.abs(e.width-(unit*2+layout.gap))<1));
          const key=`${width}-${lang}-${theme}`;
          if(columnWidths.has(key))assert.ok(Math.abs(columnWidths.get(key)-unit)<1,`cross-page column width: ${key}`);
          columnWidths.set(key,unit);
        }
        if(width===1920)assert.ok(new Set(layout.fields.map(e=>Math.round(e.bottom))).size<=2,JSON.stringify({width,view,lang,progress,layout}));
      }
      await page.evaluate(()=>{document.querySelector('#reviewTaskProgressField').hidden=true;});
      await trigger.scrollIntoViewIfNeeded();
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      await trigger.click();
      const panel=page.locator(selector+' .ui-select-panel');
      const box=await panel.boundingBox();assert.ok(box&&box.x>=0&&box.x+box.width<=width+1&&box.y>=0&&box.y+box.height<=1001);
      await page.locator(selector+' [data-ui-select-value="sample"]').click();
      assert.equal(new URL(page.url()).searchParams.get('target_group'),'sample');
      assert.equal(new URLSearchParams(await page.evaluate(()=>window.fixtureParams)).get('target_group'),'sample');
      await trigger.click();await page.locator(selector+' [data-ui-select-value="low"]').click();
      assert.equal(new URL(page.url()).searchParams.get('target_group'),'low');
      assert.equal(await page.locator(selector+' select').inputValue(),'low');
      // Relabeling a live widget must retain its selection and URL.
      await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';document.documentElement.dataset.uiLang=state.uiLanguage;renderReviewTargetGroupPicker();renderCaseLabelingStatusPicker();});
      assert.equal(await page.locator(selector+' select').inputValue(),'low');
      assert.equal(new URL(page.url()).searchParams.get('target_group'),'low');
      await page.evaluate(lang=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;renderReviewTargetGroupPicker();renderCaseLabelingStatusPicker();},lang);
      assert.equal(await page.locator(selector+' .ui-select-summary').innerText(),lang==='zh'?'低置信度（不含抽样）':'Low confidence (excluding samples)');
      await trigger.scrollIntoViewIfNeeded();
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      await trigger.press('ArrowDown');await page.keyboard.press('Escape');
      assert.equal(await trigger.getAttribute('aria-expanded'),'false');
      assert.equal(await page.locator(selector+' select').isVisible(),false);
      const bounds=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert.ok(bounds.scroll<=width+1);
      if(width<640)assert.ok((await trigger.boundingBox()).height>=44);
      if(([1440,1920].includes(width)&&lang==='zh'&&theme==='dark')||(width===320&&lang==='en'&&theme==='light'))await page.screenshot({path:`/tmp/target-cohort-${view}-${width}.png`});
      if(width===1440&&lang==='zh'&&theme==='dark')await page.locator(view==='review'?'#filterForm':'#caseLabelingFilterForm').screenshot({path:`/tmp/equal-filter-${view}.png`});
      await trigger.click();await page.locator(selector+' [data-ui-select-value=""]').click();
      assert.equal(new URL(page.url()).searchParams.has('target_group'),false);
      if(view==='labeling'){
        await trigger.click();await page.locator(selector+' [data-ui-select-value="sample"]').click();
        await page.locator('#caseLabelingReset').click();
        assert.deepEqual(errors,[]);
        assert.equal(await page.locator(selector+' select').inputValue(),'');
        assert.equal(new URL(page.url()).searchParams.has('target_group'),false);
      }
      results.push({width,lang,theme,view});
    }
    assert.deepEqual(errors,[]);console.log(JSON.stringify({checks:results.length,errors,results}));
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
