// Actual Gallery modules/CSS with synthetic GET-only data. No production writes.
// NODE_PATH=<directory containing playwright> node this-file.cjs
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../static');
const original = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const styles = [...original.matchAll(/"((?:css\/|vendor\/)[^"\n]+\.css|styles\.css)"/g)].map(m => m[1]);
const modules = fs.readFileSync(path.join(root, 'js/MANIFEST'), 'utf8').split('\n')
  .map(s => s.trim()).filter(s => s && !s.startsWith('#') && s !== 'bind-bootstrap.js');
const ids = Array.from({length:278}, (_, i) => `cn${10000 + i}`);
ids[199] = 'cn35743727'; ids[218] = 'cn35759965'; ids[231] = 'cn35772161';
const pending = [ids[199], ids[218]];
const items = ids.map((issue_id,i) => ({issue_id, baseline_scope:'fixture', gt_label:'无需协助',
  prediction:{label:'误触发'},
  annotation:pending.includes(issue_id)?{}:{id:i+1,author:'fixture',model_run_id:'run',model_review_status:'completed'},
  label_state:pending.includes(issue_id)?{state:'none'}:{state:'resolved',expected_output:'无需协助',sources:[]},
  title:'Long synthetic Issue title for responsive Gallery navigation / 合成测试'}));
const setup = `
(async () => {
  const fixture = new URL(location.href).searchParams;
  state.session = {username:'fixture',verified:true,access_role:'writer',identity_pending:false};
  state.activePage='review'; state.selectedRunId='run'; state.reviewWorkSplitId='task';
  state.selectedBaselineIds=['fixture']; state.baselineCatalog=[{id:'fixture',scope:'fixture',label:'Fixture 0821'}];
  state.config={baselines:state.baselineCatalog,review_tag_catalog:[],missing_evidence_catalog:[],batch_prediction:{enabled:false}};
  state.casePageSize=20; state.casePage=12; state.selectedId='cn35772161';
  state.reviewComparisonStatus='all'; state.reviewTaskProgress=[];
  state.reviewTaskContext={id:'task',name:'Long combined review task name / 联合复核测试',workflow_mode:'model_review_and_case_label',issue_count:278};
  document.documentElement.dataset.sessionPending='false'; document.body.dataset.activePage='review';
  document.querySelectorAll('.app-page').forEach(el => el.classList.toggle('hidden',el.dataset.page!=='review'));
  document.querySelectorAll('.multi-filter').forEach(el => renderMultiFilter(el));
  renderMultiFilter(document.querySelector('#workAssigneeFilter'),{options:[{value:'fixture',label:'Fixture reviewer with a long name'}],selected:['fixture']});
  document.querySelector('#filterForm').classList.add('is-open');
  applyColorTheme(fixture.get('theme') || 'dark',{persist:false});
  applyUiLanguage(fixture.get('lang') || 'zh',{persist:false});
  bindWorkSplitControls(); bindMobileWorkbench();
  document.querySelector('#reviewNavButton').addEventListener('click',event=>{event.preventDefault();navigatePage('review',{loadPageData:false});});
  document.querySelector('#sidebarBrandToggle').addEventListener('click',toggleSidebar);
  const normalApi=api;
  api=(url,options)=>{
    if(url.startsWith('/api/cases/issue-ids') && fixture.get('mode')==='error') return Promise.reject(Error('Synthetic queue read failure'));
    if(url.startsWith('/api/cases/issue-ids') && fixture.get('mode')==='empty') return Promise.resolve({issue_ids:[]});
    return normalApi(url,options);
  };
  await loadCases({keepSelection:true,page:12}); setReviewView(''); persistCurrentReviewRoute({issue:''});
  document.body.dataset.qaReady='true';
})().catch(error=>{document.body.dataset.qaError=error.message; console.error(error);});`;
const html = original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
  .replaceAll('{{RA_TRIAGE_BASE_PATH}}', '')
  .replace('</head>', styles.map(p => `<link rel="stylesheet" href="/static/${p}">`).join('') + '</head>')
  .replace('</body>', modules.map(p => `<script src="/static/js/${p}"></script>`).join('') + `<script>${setup}</script></body>`);
let writes=0;
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  const json=data=>{res.setHeader('Content-Type','application/json'); res.end(JSON.stringify(data));};
  if(req.method!=='GET'){writes++; return res.writeHead(405).end();}
  if(url.pathname==='/api/cases/issue-ids') return json({issue_ids:url.searchParams.get('task_progress')==='pending'?pending:ids});
  if(url.pathname==='/api/cases'){
    const page=Number(url.searchParams.get('page'))||1, size=Number(url.searchParams.get('page_size'))||20;
    return json({items:items.slice((page-1)*size,page*size),total:items.length});
  }
  if(url.pathname.startsWith('/api/')) return json({});
  if(url.pathname.startsWith('/static/')){
    const file=path.resolve(root,url.pathname.slice(8));
    if(!file.startsWith(root+path.sep)||!fs.existsSync(file)) return res.writeHead(404).end();
    res.setHeader('Content-Type',file.endsWith('.css')?'text/css':'text/javascript'); return res.end(fs.readFileSync(file));
  }
  res.setHeader('Content-Type','text/html; charset=utf-8'); res.end(html);
});
(async()=>{
  const output=process.env.NEXT_PENDING_QA_OUTPUT || '/tmp/next-pending-gallery-751';
  fs.mkdirSync(output,{recursive:true});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin=`http://127.0.0.1:${server.address().port}`;
  const errors=[], results=[];
  let browser;
  try{
    browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROME_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROME_EXECUTABLE}:{})});
    for(const width of [320,390,1440]) for(const lang of ['zh','en']) for(const theme of ['dark','light']){
      const screenshotCase=(width===320&&lang==='en'&&theme==='light')||(width===1440&&lang==='zh'&&theme==='dark');
      const page=await browser.newPage({viewport:{width,height:1000},reducedMotion:screenshotCase?'reduce':'no-preference'});
      page.on('pageerror',error=>errors.push(error.message));
      await page.goto(`${origin}/review?lang=${lang}&theme=${theme}`);
      await page.waitForSelector('body[data-qa-ready="true"]');
      assert.equal(await page.locator('#issueList .selected').count(),0,'Old detail must not appear as a located card');
      for(const [issue,number] of [[ids[199],10],[ids[218],11]]){
        await page.locator('#reviewNextPendingTaskButton').click();
        await page.waitForFunction(id=>document.querySelector('#issueList .selected')?.dataset.issueId===id,issue);
        const check=await page.evaluate(()=>({page:state.casePage,size:state.casePageSize,total:state.caseTotal,
          count:document.querySelectorAll('#issueList article[data-issue-id]').length,
          gallery:!document.querySelector('#reviewGalleryView').classList.contains('hidden'),
          issue:new URL(location.href).searchParams.get('issue'),urlPage:new URL(location.href).searchParams.get('page'),
          overflow:document.documentElement.scrollWidth>innerWidth+1,
          targetHeight:document.querySelector('#reviewNextPendingTaskButton').getBoundingClientRect().height}));
        assert.equal(check.page,number); assert.equal(check.size,20); assert.equal(check.total,278); assert.equal(check.count,20);
        assert(check.gallery); assert(!check.issue); assert.equal(check.urlPage,String(number)); assert(!check.overflow);
        if(width<500) assert(check.targetHeight>=44);
      }
      // A real navigation event starts a new Gallery visit and clears old highlight.
      if(width<500) await page.locator('#sidebarBrandToggle').click();
      await page.locator('#reviewNavButton').click();
      if(width<500) await page.locator('#sidebarBrandToggle').click();
      assert.equal(await page.locator('#issueList .selected').count(),0);
      await page.locator('#reviewNextPendingTaskButton').click();
      await page.waitForFunction(()=>document.querySelector('#issueList .selected')?.dataset.issueId==='cn35743727');
      if(screenshotCase){
        await page.locator('#issueList article.selected').scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(output,`${width}-${lang}-${theme}.png`)});
      }
      results.push({width,lang,theme,sequence:['#200/page10','#219/page11','new visit','#200/page10'],passed:true});
      await page.close();
    }
    for(const mode of ['error','empty']){
      const page=await browser.newPage({viewport:{width:320,height:1000}});
      page.on('pageerror',error=>errors.push(error.message));
      await page.goto(`${origin}/review?lang=en&theme=light&mode=${mode}`);
      await page.waitForSelector('body[data-qa-ready="true"]');
      await page.locator('#reviewNextPendingTaskButton').click();
      await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('hidden'));
      assert.equal(await page.locator('#issueList .selected').count(),0);
      assert(await page.locator('#reviewNextPendingTaskButton').isEnabled());
      const toast=await page.locator('#toast').innerText();
      assert.match(toast,mode==='error'?/Synthetic queue read failure/:/No further pending/);
      results.push({width:320,lang:'en',theme:'light',mode,passed:true});
      await page.close();
    }
    assert.deepEqual(errors,[]); assert.equal(writes,0);
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({results,errors,writes},null,2));
    console.log(`PASS ${results.length} synthetic browser scenarios; #200 recovered before retained #232; zero writes. ${output}`);
  }finally{if(browser) await browser.close(); await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
