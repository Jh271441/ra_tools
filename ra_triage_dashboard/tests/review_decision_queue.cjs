const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture({selected = 'cn2', page = 1, ids = ['cn1', 'cn2', 'cn3'], dirty = false} = {}) {
  let remaining = [...ids], scope = 'model_run_id=run&baselines=0821-odd2&label_state=conflict';
  const calls = [], messages = [], selectedIds = [], contextLoads = [];
  const state = {activePage:'review', selectedId:selected, selectedCase:{issue_id:selected, media:{}},
    cases:remaining.slice((page - 1) * 2, page * 2).map(issue_id => ({issue_id})),
    casePage:page, casePageSize:2, caseTotal:remaining.length, session:{username:'alice'},
    selectedRunId:'run', reviewWorkSplitId:'', pageNavigationEpoch:0, pendingReviewImages:[],
    reviewFormDirty:dirty, caseLabeling:{pendingImages:[]}, combinedReviewContext:{}};
  const controls = {form:{querySelectorAll:() => []}, error:{textContent:''},
    confirm:{checked:true}, rationale:{value:'Decision rationale'}};
  let failPost = false, failQueue = false, holdContext = false, beforeLoad = () => {};
  const data = {issue_id:selected, label_state:{state:'conflict', source_fingerprint:'before'}};
  const s = {state, console, URLSearchParams, AbortController, Map, Set, Promise,
    window:{scrollY:123}, document:{},
    $:id => ({'#caseLabelingForm':controls.form, '#caseDecisionEditorError':controls.error,
      '#caseDecisionConfirmExclusion':controls.confirm, '#caseDecisionReviewRationale':controls.rationale})[id] || null,
    uiText:(zh, en) => en, showToast:message => messages.push(message),
    selectedBaselineQueryValue:() => '0821-odd2', withBaselineQuery:p => p,
    hasDashboardWriteRole:() => true, enhanceDashboardSelects() {}, acknowledgeLocalChange() {},
    caseExclusionErrorMessage:e => e.message,
    caseLabelingFormPayload:() => ({expected_output:'误触发', tags:[], rationale:'Label rationale', is_excluded:false}),
    caseLabelingOutputValidation:() => ({conflict:false}),
    currentReviewGalleryExportParams:() => new URLSearchParams(scope + '&format=xlsx&gallery_scope=true'),
    capturePageContext:() => ({epoch:state.pageNavigationEpoch}),
    isPageContextCurrent:c => c.epoch === state.pageNavigationEpoch,
    caseRationalePendingImages:() => [], renderReviewSummary() {}, renderCaseNavigation() {},
    refreshCaseLabelDecisionLanguage() {}, refreshReviewDerivedData() {},
    clearDetail:() => {state.selectedId=''; state.selectedCase=null;}, showPage() {},
    selectCase:async(id, options) => {selectedIds.push({id, options}); state.selectedId=id; state.selectedCase={issue_id:id};},
    loadCases:async(options) => {
      calls.push({kind:'list', options}); beforeLoad();
      if (failQueue) throw new Error('Queue offline');
      const visible=scope.includes('label_state=conflict') ? remaining : ['cn1', 'cn2', 'cn3'];
      state.caseTotal=visible.length;
      state.casePage=Math.min(options.page, Math.max(1, Math.ceil(visible.length / 2)));
      state.cases=visible.slice((state.casePage - 1) * 2, state.casePage * 2).map(issue_id => ({issue_id}));
    },
    loadCombinedReviewContext:async(data, options) => {
      contextLoads.push({data, options});
      if (holdContext) await new Promise(() => {});
    },
    api:async(url, options = {}) => {
      calls.push({kind:options.method === 'POST' ? 'post' : 'get', url, options});
      if (options.method === 'POST') {
        if (failPost) throw new Error('409 sources changed');
        remaining=remaining.filter(id => id !== selected);
        return {decision:{id:9}};
      }
      if (url.includes('/issue-ids?')) {
        if (failQueue) throw new Error('Queue offline');
        const params=new URL(url, 'http://fixture').searchParams;
        return {issue_ids:params.has('label_state') ? [...remaining] : ['cn1', 'cn2', 'cn3']};
      }
      if (url.startsWith('/api/labeling/cases/')) return {...data, label_state:{state:'resolved'}};
      throw new Error(`Unexpected API ${url}`);
    },
  };
  vm.createContext(s);
  for (const file of ['review-submit', 'case-label-decision', 'review-issue-decision']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, `../static/js/${file}.js`), 'utf8'), s);
  }
  s.exitCaseDecisionEditor = () => {
    vm.runInContext('caseLabelDecisionUi.editor=null', s);
    state.reviewFormDirty=dirty;
  };
  vm.runInContext(`caseLabelDecisionUi.editor={key:'draft', data:${JSON.stringify(data)},
    pageContext:capturePageContext(), baselines:'0821-odd2', actor:'alice',
    images:[], retained:[], adoptedId:7, ordinary:{}, reviewHost:{}}`, s);
  return {s, state, calls, messages, selectedIds, contextLoads, controls,
    failPost:() => {failPost=true;}, failQueue:() => {failQueue=true;},
    holdContext:() => {holdContext=true;}, beforeLoad:fn => {beforeLoad=fn;},
    allFilter:() => {scope=scope.replace('&label_state=conflict', '');},
  };
}

(async() => {
  let f=fixture(); await f.s.adjudicateIssueLabel();
  assert.equal(f.state.selectedId, 'cn3', 'A confirmed decision must leave the conflict filter immediately');
  assert(!f.state.cases.some(item => item.issue_id === 'cn2'));
  assert.equal(f.state.caseTotal, 2);
  assert.equal(f.selectedIds[0].options.historyMode, 'replace');
  assert.equal(f.selectedIds[0].options.preserveScrollY, 123);
  assert.equal(f.state.selectedRunId, 'run');
  const post=f.calls.find(call => call.kind === 'post');
  assert.equal(JSON.parse(post.options.body).model_run_id, undefined, 'Decision stays Issue-bound');
  assert(f.calls.filter(call => call.kind === 'list').every(call => call.options.fresh));
  assert.equal(f.contextLoads.length, 0, 'Do not read the old Issue context after advancing');

  f=fixture({selected:'cn3'}); await f.s.adjudicateIssueLabel();
  assert.equal(f.state.selectedId, 'cn2', 'An off-page final Issue returns to its predecessor');
  assert(f.calls.findIndex(call => call.url?.includes('/issue-ids?')) < f.calls.findIndex(call => call.kind === 'post'));

  f=fixture({ids:['cn2']}); await f.s.adjudicateIssueLabel();
  assert.equal(f.state.selectedId, '', 'An empty conflict queue returns to Gallery');

  f=fixture({ids:['cn1', 'cn3']}); await f.s.adjudicateIssueLabel();
  assert.equal(f.state.selectedId, 'cn3', 'Recover an already-removed conflict anchor from the same ordered scope');

  f=fixture(); f.allFilter(); await f.s.adjudicateIssueLabel();
  assert.equal(f.state.selectedId, 'cn2', 'An all-state filter retains the saved Issue');
  assert.equal(f.state.selectedCase.label_state.state, 'resolved');
  assert.equal(f.contextLoads[0].options.preserveForm, true);
  assert(f.calls.find(call => call.url?.startsWith('/api/labeling/cases/')).options.signal);

  f=fixture({dirty:true}); f.holdContext();
  const saving=f.s.adjudicateIssueLabel();
  for (let i=0; i<20; i++) await Promise.resolve();
  assert(!f.state.cases.some(item => item.issue_id === 'cn2'), 'A slow detail/context read cannot delay queue refresh');
  assert.equal(f.state.selectedId, 'cn2', 'Preserve ordinary unsaved drafts');
  assert(f.state.reviewFormDirty);
  assert.equal(f.contextLoads[0].options.preserveForm, true);
  assert.equal(f.contextLoads[0].options.fresh, true);
  void saving;

  for (const change of [f => f.state.pageNavigationEpoch++, f => {f.state.selectedId='cn1';},
    f => {f.state.session.username='bob';}, f => f.allFilter()]) {
    f=fixture(); f.beforeLoad(() => change(f)); await f.s.adjudicateIssueLabel();
    assert.equal(f.selectedIds.length, 0, 'An obsolete decision callback cannot reclaim navigation');
  }

  f=fixture(); f.failPost(); await f.s.adjudicateIssueLabel();
  assert.equal(f.state.selectedId, 'cn2'); assert.equal(f.calls.filter(call => call.kind === 'list').length, 0);
  assert.match(f.controls.error.textContent, /409/);
  assert(vm.runInContext("caseLabelDecisionUi.drafts.has('draft')", f.s));

  f=fixture(); f.failQueue(); await f.s.adjudicateIssueLabel();
  assert.equal(f.calls.filter(call => call.kind === 'post').length, 1, 'A refresh failure cannot repeat a committed decision');
  assert.equal(f.state.reviewQueueStale, true);
  assert.match(f.messages.join(' '), /Decision saved.*queue/);
  console.log('Review decision queue: filtered removal, deep links, final/empty queues, drafts, slow context, races and failure isolation passed');
})().catch(error => {console.error(error); process.exitCode=1;});
