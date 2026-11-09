const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourceRoot = process.env.REVIEW_QUEUE_SOURCE_ROOT || path.join(__dirname, '../static/js');
const tick = async() => {for (let i=0; i<30; i++) await Promise.resolve();};

function fixture({selected='cn2', page=1, ids=['cn1','cn2','cn3','cn4','cn5']}={}) {
  let remaining=[...ids], epoch=0, failPage=false, omitPageId='';
  const requests=[], held=[], messages=[];
  const state={activePage:'review',selectedId:selected,selectedCase:{issue_id:selected},
    casePage:page,casePageSize:2,caseTotal:ids.length,caseListRequestSeq:0,
    cases:ids.slice((page-1)*2,page*2).map(issue_id=>({issue_id})),
    selectedRunId:'run',session:{username:'alice'},reviewFormDirty:false,pendingReviewImages:[]};
  const s={state,console,Map,Set,Promise,URLSearchParams,AbortController,window:{scrollY:123},
    $:selector=>selector==='#modelRunFilter'?{options:[]}:{value:''},
    capturePageContext:()=>({epoch}),isPageContextCurrent:c=>c.epoch===epoch,
    currentReviewGalleryExportParams:()=>new URLSearchParams('model_run_id=run&baselines=scope&label_state=conflict'),
    joinFilterList:values=>values.join(','),getMultiFilterValues:()=>[],parseFilterList:values=>values||[],
    selectedModelReviewStatuses:()=>[],selectedReviewLabelStates:()=>['conflict'],
    selectedCombinedTaskProgress:()=>[],selectedReviewGtRelations:()=>[],selectedReviewIssueTags:()=>[],
    selectedReviewDiscussionFilter:()=> 'all',selectedReviewComparisonStatus:()=> 'all',
    appendBaselineParams:p=>p.set('baselines','scope'),caseRationalePendingImages:()=>[],
    uiText:(zh,en)=>en,showToast:message=>messages.push(message),refreshReviewDerivedData(){},
    renderCaseNavigation(){},clearDetail(){state.selectedId='';state.selectedCase=null;},showPage(){epoch++;},
    api:async(url,options)=>{
      const parsed=new URL(url,'http://fixture'),q=parsed.searchParams;
      requests.push({path:parsed.pathname,q,options});
      if(parsed.pathname.endsWith('/issue-ids'))return {issue_ids:[...remaining]};
      assert.equal(parsed.pathname,'/api/cases');
      if(failPage)throw Error('Page offline');
      const subset=q.get('issue_ids')?.split(',').filter(Boolean);
      const matching=remaining.filter(id=>(!subset||subset.includes(id))&&id!==omitPageId);
      const page=Number(q.get('page')),size=Number(q.get('page_size'));
      const response={total:matching.length,items:matching.slice((page-1)*size,page*size).map(issue_id=>({issue_id}))};
      if(subset||!requests.some(r=>r.path==='/api/cases'&&r.q.has('issue_ids')))
        return new Promise(resolve=>held.push(()=>resolve(response)));
      return response;
    },
  };
  vm.createContext(s);
  for(const file of ['review-gallery.js','review-submit.js'])vm.runInContext(fs.readFileSync(path.join(sourceRoot,file),'utf8'),s);
  s.currentReviewGalleryExportParams=()=>new URLSearchParams('model_run_id=run&baselines=scope&label_state=conflict');
  s.renderCases=data=>{state.cases=data.items;state.caseTotal=data.total;};
  s.selectCase=async(id,options)=>{state.selectedId=id;state.selectedCase={issue_id:id};epoch++;state.lastNavigation=options;};
  return {s,state,requests,messages,
    complete:()=>{remaining=remaining.filter(id=>id!==selected);},
    release:()=>{held.splice(0).forEach(resolve=>resolve());},
    failPage:()=>{failPage=true;},omitPage:id=>{omitPageId=id;},
  };
}

(async()=>{
  let f=fixture(),context=await f.s.reviewSaveNavigationContext('cn2');f.complete();
  const saving=f.s.reconcileReviewQueueAfterSave(context);await tick();
  assert.equal(f.state.selectedId,'cn3','A slow gallery/thumbnail response cannot delay the next detail');
  assert.equal(f.requests[0].path,'/api/cases/issue-ids','Read authoritative membership once before gallery data');
  assert.equal(f.requests.filter(r=>r.path.endsWith('/issue-ids')).length,1);
  const page=f.requests.find(r=>r.path==='/api/cases');
  assert.equal(page.q.get('issue_ids'),'cn1,cn3','Revalidate only the confirmed page IDs');
  assert.equal(page.q.get('label_state'),'conflict');assert.equal(page.q.get('model_run_id'),'run');
  assert.equal(page.q.get('baselines'),'scope');assert.equal(page.options.cache,'no-store');
  const nextContext=await f.s.reviewSaveNavigationContext('cn3');
  assert.equal(nextContext.index,1,'Fast consecutive saves use the confirmed queue rather than stale gallery rows');
  assert.equal(nextContext.previousId,'cn1');assert.equal(nextContext.absoluteIndex,1);assert(nextContext.hadNext);
  await saving;assert(f.state.reviewQueueStale);f.release();await tick();
  assert.equal(f.state.caseTotal,4);assert.equal(f.state.cases[1].issue_id,'cn3');assert.equal(f.state.reviewQueueStale,false);
  assert.equal(f.state.lastNavigation.historyMode,'replace');assert.equal(f.state.lastNavigation.preserveScrollY,123);

  f=fixture({selected:'cn4'});context=await f.s.reviewSaveNavigationContext('cn4');f.complete();
  await f.s.reconcileReviewQueueAfterSave(context);
  assert.equal(f.state.selectedId,'cn5');assert.equal(f.state.casePage,2);
  const subset=f.requests.filter(r=>r.path==='/api/cases').at(-1);
  assert.equal(subset.q.get('page'),'1');assert.equal(subset.q.get('issue_ids'),'cn3,cn5');
  f.release();await tick();assert.equal(f.state.casePage,2);assert.equal(f.state.caseTotal,4);

  f=fixture();context=await f.s.reviewSaveNavigationContext('cn2');f.complete();f.failPage();
  await f.s.refreshReviewAfterSave(context);await tick();
  assert.equal(f.state.selectedId,'cn3','A background gallery failure cannot undo successful navigation');
  assert(f.state.reviewQueueStale);assert.match(f.messages.join(' '),/saved.*queue/i);

  f=fixture();context=await f.s.reviewSaveNavigationContext('cn2');f.complete();f.omitPage('cn1');
  await f.s.reconcileReviewQueueAfterSave(context);f.release();await tick();
  assert(f.requests.some(r=>r.path==='/api/cases'&&!r.q.has('issue_ids')),'A changed page snapshot must recover a full fresh page');
  assert.equal(f.state.caseTotal,3);
  console.log('Review queue latency: navigate before slow gallery, one full membership read, bounded page revalidation, URL/total, background failure and snapshot races passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
