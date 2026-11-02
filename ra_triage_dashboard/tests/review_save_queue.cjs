const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture({ids = ['a', 'b', 'c', 'd', 'e'], selected = 'd', page = 1} = {}) {
  let pending = [...ids], all = ['a', 'b', 'c', 'd', 'e'], scope = 'task_progress=pending&work_split_id=task&work_assignee=alice&model_run_id=run&baselines=scope';
  const state = {activePage:'review', selectedId:selected, casePage:page, casePageSize:2,
    caseTotal:pending.length, cases:pending.slice((page-1)*2,page*2).map(issue_id=>({issue_id})),
    selectedRunId:'run', reviewWorkSplitId:'task', session:{username:'alice'}, pendingReviewImages:[],
    reviewFormDirty:false, pageNavigationEpoch:0};
  const selectedIds = [], calls = [], messages = [];
  let cleared = false, beforeLoad = () => {}, queueFailure = false;
  const s = {state, console, URLSearchParams, AbortController, Set, Map, Promise, window:{scrollY:123},
    currentReviewGalleryExportParams:() => new URLSearchParams(scope+'&format=xlsx&gallery_scope=true'),
    capturePageContext:() => ({epoch:state.pageNavigationEpoch}),
    isPageContextCurrent:context => context.epoch === state.pageNavigationEpoch,
    api:async url => {
      calls.push(url);
      if(queueFailure) throw new Error('queue offline');
      return {issue_ids:new URL(url,'http://fixture').searchParams.has('task_progress') ? [...pending] : [...all]};
    },
    loadCases:async({page}) => {
      beforeLoad();
      state.caseTotal = pending.length;
      state.casePage = Math.min(page,Math.max(1,Math.ceil(pending.length/state.casePageSize)));
      state.cases = pending.slice((state.casePage-1)*2,state.casePage*2).map(issue_id=>({issue_id}));
    },
    selectCase:async(id,options) => {selectedIds.push({id,options});state.selectedId=id;},
    renderCaseNavigation() {}, clearDetail() {cleared=true;}, showPage() {},
    uiText:(zh,en)=>en, showToast:message=>messages.push(message), refreshReviewDerivedData() {},
    caseRationalePendingImages:()=>[],
  };
  vm.createContext(s);
  const select = s.selectCase;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/review-form.js'),'utf8'),s);
  s.selectCase = select;
  return {s,state,selectedIds,calls,messages,
    complete:() => {pending=pending.filter(id=>id!==selected);},
    setPending:ids=>{pending=[...ids];},
    changeScope:()=>{scope+='&search=new';},
    onLoad:fn=>{beforeLoad=fn;},
    failQueue:()=>{queueFailure=true;},
    cleared:()=>cleared};
}

(async() => {
  // Shared Issue links need not include the page containing that Issue.
  let f = fixture(), context = await f.s.reviewSaveNavigationContext('d');
  f.complete();
  assert.equal(await f.s.reconcileReviewQueueAfterSave(context),true);
  assert.equal(f.selectedIds[0].id,'e','an off-page saved Issue must advance to its actual successor');
  assert.equal(f.state.casePage,2);
  assert.equal(f.selectedIds[0].options.preserveScrollY,123);
  for(const call of f.calls) {
    const q = new URL(call,'http://fixture').searchParams;
    for(const [key,value] of [['work_split_id','task'],['work_assignee','alice'],['model_run_id','run'],['baselines','scope']]) assert.equal(q.get(key),value);
    assert(!q.has('format') && !q.has('gallery_scope'));
  }

  // An already refreshed pending list may have removed the saved anchor.
  f=fixture({ids:['a','b','c','e']});context=await f.s.reviewSaveNavigationContext('d');
  await f.s.reconcileReviewQueueAfterSave(context);
  assert.equal(f.selectedIds[0].id,'e','recover a removed anchor from the same task order');

  // Removing the sole item on the final page must select the prior page's last item.
  f=fixture({selected:'e',page:3});context=await f.s.reviewSaveNavigationContext('e');f.complete();
  await f.s.reconcileReviewQueueAfterSave(context);
  assert.equal(f.selectedIds[0].id,'d');assert.equal(f.state.casePage,2);

  f=fixture({selected:'b'});context=await f.s.reviewSaveNavigationContext('b');
  assert.equal(f.calls.length,0,'on-page saves should not add a queue-position request');
  await f.s.reconcileReviewQueueAfterSave(context);
  assert.equal(f.selectedIds.length,0,'keep the Issue if it remains in the filter');

  f=fixture({ids:['d'],selected:'d'});context=await f.s.reviewSaveNavigationContext('d');f.complete();
  await f.s.reconcileReviewQueueAfterSave(context);assert(f.cleared());assert.equal(f.selectedIds.length,0);

  for(const change of [f=>f.changeScope(),f=>f.state.pageNavigationEpoch++,f=>f.state.selectedId='user-choice']) {
    f=fixture({selected:'b'});context=await f.s.reviewSaveNavigationContext('b');f.complete();
    f.onLoad(()=>change(f));await f.s.reconcileReviewQueueAfterSave(context);
    assert.equal(f.selectedIds.length,0,'late save cannot reclaim a changed page/filter/Issue');
  }

  f=fixture({selected:'b'});context=await f.s.reviewSaveNavigationContext('b');f.complete();
  f.onLoad(()=>{f.state.reviewFormDirty=true;});await f.s.reconcileReviewQueueAfterSave(context);
  assert.equal(f.selectedIds.length,0,'edits made during the save/queue refresh must remain visible');
  assert(f.state.reviewFormDirty);

  f=fixture();f.failQueue();context=await f.s.reviewSaveNavigationContext('d');
  assert(context,'queue-position failure must not reject a label submission');
  f.s.loadCases=async()=>{throw new Error('queue offline');};
  await f.s.refreshReviewAfterSave(context);
  assert(f.state.reviewQueueStale);assert.match(f.messages.at(-1),/saved.*queue/i);
  console.log('Review save queue: deep links, removed anchors, final page, empty/filter membership, stale scopes, newer drafts and failure isolation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
