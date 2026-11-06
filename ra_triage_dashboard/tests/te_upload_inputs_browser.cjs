// Exercise real synthetic preview endpoints. No Trail updates are enabled.
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=process.env.TE_PREVIEW_URL||'http://127.0.0.1:50269';
const out=path.resolve(__dirname,'../../reports/te_correction_preview_20261106');
(async()=>{
 const browser=await chromium.launch({headless:true});const errors=[],checks=[];
 try{
  const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
  const fits=async()=>assert.ok(await page.evaluate(()=>Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)<=innerWidth+1),'page overflow');
  const start=async()=>{await page.goto(base+'/rd-results?baselines=version-20261016&mode=te-correction');await page.waitForFunction(()=>rdResults.data&&!rdResults.loading&&!rdTERefreshing());};
  const choose=async name=>{const picker=page.waitForEvent('filechooser');await page.locator('[data-rd-action="import-excel"]').click();await (await picker).setFiles(path.join(out,name));};
  for(const [width,lang,theme] of [[1440,'zh','dark'],[390,'en','dark'],[320,'en','light']]){
   await page.setViewportSize({width,height:1000});await start();
   await page.evaluate(({lang,theme})=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;localStorage.setItem('te-preview-language',lang);applyColorTheme(theme);renderRdResults();},{lang,theme});
   await page.locator('#rdSearch').fill('cn35655704\ncn35655705\ncn35655704');
   if(width===1440)await page.locator('#rdSearch').press('Enter');
   else {
    const before=page.url();await page.locator('#rdSearch').press('Enter');assert.equal(page.url(),before);
    assert.ok((await page.locator('#rdSearch').inputValue()).includes('\n'));
    await page.locator('#rdFilters button[type="submit"]').click();
   }
   await page.waitForFunction(()=>rdResults.data?.total===2&&!rdResults.loading);
   assert.equal(new URL(page.url()).searchParams.get('q'),'cn35655704,cn35655705');
   assert.deepEqual(await page.locator('[data-rd-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.rdId)),['cn35655704','cn35655705']);
   await page.reload();await page.waitForFunction(()=>rdResults.data?.total===2&&!rdResults.loading);
   await page.locator('#rdSearch').fill('cn35655704, INVALID');await page.locator('#rdFilters button[type="submit"]').click();
   assert.ok(await page.locator('.rd-notice.is-error').count());assert.equal(await page.evaluate(()=>rdResults.data.total),2);
   await page.locator('#rdSearch').fill('');await page.locator('#rdFilters button[type="submit"]').click();await page.waitForFunction(()=>rdResults.data?.total===84&&!rdResults.loading);
   await choose('synthetic-te-targets.xlsx');
   assert.equal(await page.locator('[data-rd-action="preview"]').isEnabled(),true);
   assert.equal(await page.locator('[data-rd-id]:enabled').count(),0);
   assert.equal(await page.evaluate(()=>rdResults.excelFile.name),'synthetic-te-targets.xlsx');
   await page.locator('#rdMode-te-correction').focus();await page.keyboard.press('ArrowLeft');
   assert.equal(await page.evaluate(()=>rdResults.mode),'te-correction');
   assert.equal(await page.evaluate(()=>rdResults.excelFile.name),'synthetic-te-targets.xlsx');
   await page.keyboard.press('End');
   await page.evaluate(()=>{state.uiLanguage=state.uiLanguage==='zh'?'en':'zh';document.documentElement.dataset.uiLang=state.uiLanguage;renderRdResults();});
   assert.equal(await page.evaluate(()=>rdResults.excelFile.name),'synthetic-te-targets.xlsx');
   await page.evaluate(lang=>{state.uiLanguage=lang;document.documentElement.dataset.uiLang=lang;renderRdResults();},lang);
   assert.equal(await page.locator('#rdOverwrite').count(),0);await fits();
   await page.locator('[data-rd-action="preview"]').click();await page.waitForSelector('#rdResultsPreview');
   const frozen=await page.evaluate(()=>rdResults.preview);
   assert.equal(frozen.scope.source.kind,'xlsx');assert.equal(frozen.scope.source.duplicates,1);assert.equal(frozen.items.length,4);
   assert.equal(frozen.items.find(r=>r.issue_id==='cn35655705').desired,'无需协助');
   assert.equal(frozen.items.find(r=>r.issue_id==='cn35655705').eligible,true); // Manual says 正确触发.
   assert.equal(frozen.items.find(r=>r.issue_id==='cn35655704').eligible,true); // Manual is stale.
   assert.equal(frozen.items.find(r=>r.issue_id==='cn35655697').eligible,true);
   assert.notEqual(frozen.items.find(r=>r.issue_id==='cn35655697').rd_current,frozen.items.find(r=>r.issue_id==='cn35655697').desired);
   assert.equal(await page.locator('[data-rd-action="commit"]').isDisabled(),true);
   assert.ok((await page.locator('.rd-preview-overview').innerText()).includes('synthetic-te-targets.xlsx'));
   assert.ok((await page.locator('.rd-preview-details th').allTextContents()).includes(lang==='zh'?'文件期望输出':'File expected output'));
   await fits();await page.screenshot({path:path.join(out,`xlsx-preview-${width}-${lang}-${theme}.png`),fullPage:true});
   await page.reload();await page.waitForSelector('#rdResultsPreview');
   assert.equal(await page.evaluate(()=>rdResults.preview.id),frozen.id);assert.equal(await page.evaluate(()=>rdResults.preview.items[3].desired),frozen.items[3].desired);
   await page.locator('[data-rd-action="close"]').click();
   assert.equal(await page.evaluate(()=>rdResults.excelFile),null);
   await choose('synthetic-te-invalid.xlsx');await page.locator('[data-rd-action="preview"]').click();await page.waitForFunction(()=>Boolean(rdResults.error)&&!rdResults.busy);
   assert.ok((await page.locator('.rd-notice.is-error').innerText()).includes('Row 2'));assert.equal(await page.locator('#rdResultsPreview').count(),0);await fits();
   await choose('synthetic-te-outside.xlsx');await page.locator('[data-rd-action="preview"]').click();await page.waitForFunction(()=>Boolean(rdResults.error)&&!rdResults.busy);
   assert.ok((await page.locator('.rd-notice.is-error').innerText()).includes('cn999999999'));await fits();
   await page.locator('[data-rd-action="clear-excel"]').click();assert.equal(await page.evaluate(()=>rdResults.excelFile),null);
   await choose('synthetic-te-targets.xlsx');
   await page.locator('#rdMode-te-correction').focus();await page.keyboard.press('Home');await page.keyboard.press('Enter');await page.waitForFunction(()=>rdResults.data?.mode==='rd'&&!rdResults.loading);
   assert.equal(await page.evaluate(()=>rdResults.excelFile),null);assert.equal(await page.locator('[data-rd-action="import-excel"]').count(),0);
   await fits();checks.push({width,lang,theme});
  }
  assert.deepEqual(errors,[]);
  const result={checks,coverage:['multi-Issue exact filter','duplicate IDs removed','URL reload','mobile Enter newline','invalid IDs retain scope','XLSX chooser','tab focus preserves selected file','file label overrides Manual','RD disagreement does not block file target','duplicate workbook rows','file source visible','preview reload','invalid workbook row','out-of-version blocked','mode activation clears file'],errors};
  fs.writeFileSync(path.join(out,'xlsx-browser-results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
