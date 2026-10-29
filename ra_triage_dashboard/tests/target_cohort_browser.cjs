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
    for(const width of (process.env.FILTER_QA_WIDTH ? [Number(process.env.FILTER_QA_WIDTH)] : [1920,1440,1180,1025,1024,768,390,320]))for(const lang of ['zh','en'])for(const theme of ['dark','light'])for(const view of ['review','labeling']){
      await page.setViewportSize({width,height:1000});
      await page.evaluate(({view,lang,theme})=>{
        closeAllUiSelects();state.activePage=view;state.uiLanguage=lang;
        document.documentElement.dataset.uiLang=lang;document.documentElement.dataset.colorTheme=theme;
        document.documentElement.dataset.sessionPending='false';document.body.dataset.activePage=view;
        document.querySelectorAll('.app-page').forEach(p=>p.classList.toggle('hidden',p.dataset.page!==view));
        document.querySelector('#filterForm').classList.add('is-open');document.querySelector('#caseLabelingFilterForm').classList.add('is-open');
        applyDomI18n(document);enhanceDashboardSelects();state.reviewTargetGroup='';state.caseLabeling.targetGroup='';
        renderReviewTargetGroupPicker();renderCaseLabelingStatusPicker();
      },{view,lang,theme});
      const selector=view==='review'?'#reviewTargetGroupPicker':'#caseLabelingTargetGroupPicker';
      const trigger=page.locator(selector+' .ui-select-trigger');
      // Desktop search uses two equal units; other fields use one, in two filled rows.
      for(const progress of [false,true]) for(const mode of [false,true]) {
        const layout=await page.evaluate(({view,progress,mode})=>{
          document.querySelector('#reviewTaskProgressField').hidden=!progress;
          document.querySelector('#reviewWorkflowModeField').hidden=!mode;
          const form=document.querySelector(view==='review'?'#filterForm':'#caseLabelingFilterForm');
          const wide='.filter-model-run,.filter-search,.review-task-filter,.review-workflow-mode,.case-labeling-search,.case-labeling-task';
          const fields=[...form.children].filter(e=>e.getBoundingClientRect().width&&e.tagName!=='BUTTON');
          return {gap:parseFloat(getComputedStyle(form).columnGap),fields:fields.map(e=>({
            width:e.getBoundingClientRect().width,bottom:e.getBoundingClientRect().bottom,wide:e.matches(wide),search:e.matches('.filter-search,.case-labeling-search')
          }))};
        },{view,progress,mode});
        const normal=layout.fields.filter(e=>width>=1025?!e.search:!e.wide);
        const unit=normal[0].width;
        assert.ok(normal.every(e=>Math.abs(e.width-unit)<1),JSON.stringify({width,view,layout}));
        if(width>=1025){
          assert.ok(layout.fields.filter(e=>e.search).every(e=>Math.abs(e.width-(2*unit+layout.gap))<1));
          assert.equal(new Set(layout.fields.map(e=>Math.round(e.bottom))).size,2,JSON.stringify({width,view,lang,progress,mode,layout}));
          const rows=await page.evaluate(view=>{
            const form=document.querySelector(view==='review'?'#filterForm':'#caseLabelingFilterForm');
            const gap=parseFloat(getComputedStyle(form).columnGap), groups=new Map();
            [...form.children].filter(e=>e.getBoundingClientRect().width).forEach(e=>{const r=e.getBoundingClientRect(),key=Math.round(r.bottom);if(!groups.has(key))groups.set(key,[]);groups.get(key).push({x:r.x,right:r.right});});
            return [...groups.values()].map(row=>({gaps:row.slice(1).map((r,i)=>r.x-row[i].right),gap}));
          },view);
          assert.equal(rows.length,2);
          assert.ok(rows.every(row=>row.gaps.every(g=>Math.abs(g-row.gap)<1)),JSON.stringify(rows));
        }
      }
      await page.evaluate(()=>{document.querySelector('#reviewTaskProgressField').hidden=false;document.querySelector('#reviewWorkflowModeField').hidden=false;});
      if(view==='review'){
        await page.evaluate(()=>{
          state.reviewTaskContext={name:'0821 · ODD2联合复核',issue_count:740,id:'fixture-task',workflow_mode:'model_review_and_case_label'};
          reviewTaskOptions=[{split_id:'fixture-task',name:'0821 · ODD2联合复核',completed_count:185,assignment_count:740}];
          renderReviewWorkSplitPicker('fixture-task',{load:false});
          renderReviewTaskContext();
          document.querySelector('#reviewTaskProgressField').hidden=false;
          reviewTaskOptionsLoadedAt=Date.now();reviewTaskOptions=[];reviewTaskOptionsError='';renderReviewTaskPickerHint();
        });
        const info=page.locator('#reviewTaskInfo .ui-info-button');
        const summary=page.locator('#reviewTaskSummary');
        await page.mouse.move(0,0);await page.evaluate(()=>{document.activeElement?.blur();closeUiInfoPopovers(document);});
        assert.equal(await summary.isVisible(),false);
        const height=await info.evaluate(e=>({height:e.getBoundingClientRect().height,font:parseFloat(getComputedStyle(e).fontSize)}));
        if(width>=1025)assert.ok(Math.abs(height.height-height.font)<1);
        if(width<640)assert.ok(height.height>=44);
        await info.focus();
        await page.waitForTimeout(160);
        assert.equal(await summary.isVisible(),true);
        assert.ok((await summary.innerText()).includes('740'));
        const tip=await page.locator('#reviewTaskInfoPanel').boundingBox();
        assert.ok(tip.x>=0&&tip.x+tip.width<=width+1&&tip.y>=0&&tip.y+tip.height<=1001);
        assert.ok((await page.locator('#reviewTaskPickerHint').innerText()).includes(lang==='zh'?'暂无':'No active'));
        if(width===1440&&lang==='zh'&&theme==='dark')await page.screenshot({path:'/tmp/two-row-filter-info.png'});
        await page.evaluate(()=>{reviewTaskOptionsError='fixture error';renderReviewTaskPickerHint();});
        assert.ok((await page.locator('#reviewTaskPickerHint').innerText()).includes(lang==='zh'?'加载失败':'Failed to load'));
        await page.keyboard.press('Escape');
        assert.equal(await info.getAttribute('aria-expanded'),'false');
        await page.evaluate(()=>{document.activeElement?.blur();});
      }
      await trigger.scrollIntoViewIfNeeded();
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      await page.waitForTimeout(200); // Let focus/scroll dismissal settle before opening another control.
      await trigger.click();
      const panel=page.locator(selector+' .ui-select-panel');
      const box=await panel.boundingBox();assert.ok(box&&box.x>=0&&box.x+box.width<=width+1&&box.y>=0&&box.y+box.height<=1001,JSON.stringify({width,lang,theme,view,box}));
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
