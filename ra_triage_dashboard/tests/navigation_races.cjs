const fs = require('fs'), vm = require('vm'), assert = require('assert');
const {execFileSync} = require('child_process');
const root = 'ra_triage_dashboard/static/js/';
const defer = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};};
const tick = () => new Promise(r => setImmediate(r));
function fixture(page = 'review') {
  const calls = {pages: [], paints: [], polls: 0};
  const timers = new Map(); let timerId = 0;
  const element = () => ({value: '', options: [], innerHTML: '', textContent: '', classList: {contains: () => false, add() {}, remove() {}, toggle() {}}, querySelector: () => null, querySelectorAll: () => []});
  const elements = new Map();
  const location = {origin: 'https://example.test', pathname: '/manual/' + (page === 'labeling' ? 'case-labeling' : page), search: '', hash: ''};
  const state = {activePage: page, pageNavigationEpoch: 1, selectedId: '', selectedRunId: '', selectedCase: null,
    selectedBaselineIds: ['0821'], reviewReloadSeq: 0, caseListRequestSeq: 0, caseRequestSeq: 0,
    cases: [], casePage: 1, casePageSize: 20, caseTotal: 40, reviewAnalysis: {requestSeq: 0, page: 1},
    reviewAssignments: {}, reviewTaskContext: null, reviewWorkSplitId: '', pendingReviewImages: [],
    caseLabeling: {page: 1, pageSize: 20, detailSeq: 0, requestSeq: 0, tasks: [], issueId: '', issueIds: []},
    trailUpdate: {tab: 'issue'}, config: {}, session: {is_admin: true, identity_pending: false, can_write: true, can_view_intent: true}};
  const s = {state, PAGE_ROUTES: {review: {}, 'labeling-summary': {}, labeling: {}}, URL, URLSearchParams, console, AbortController, Map, Set, Number,
    window: {location, setTimeout(fn) {timers.set(++timerId, fn); return timerId;}, clearTimeout(id) {timers.delete(id);}, addEventListener() {}, scrollTo() {}, requestAnimationFrame() {}, history: {state: {}}},
    document: {body: {dataset: {}}, readyState: 'loading', getElementById: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], documentElement: {dataset: {}}},
    localStorage: {getItem: () => null},
    $: key => {if (!elements.has(key)) elements.set(key, element()); return elements.get(key);},
    selectedBaselineQueryValue: () => state.selectedBaselineIds.join(','),
    parseFilterList: x => Array.isArray(x) ? x : String(x || '').split(',').filter(Boolean), joinFilterList: x => (x || []).join(','),
    getMultiFilterValues: () => [], selectedModelReviewStatuses: () => [], selectedCombinedTaskProgress: () => [],
    selectedReviewIssueTags: () => state.reviewIssueTags || [],
    renderReviewProgressFilter() {}, isCombinedTaskProgressFilter: () => false,
    selectedReviewDiscussionFilter: () => 'all', selectedReviewComparisonStatus: () => 'all',
    appendBaselineParams: () => {}, clearPendingReviewImages() {}, renderCases: d => calls.paints.push(d), clearDetail: () => calls.paints.push('cleared'),
    uiText: x => x, showToast() {}, renderCaseNavigation() {}, updateIssueQueryButton() {},
    loadClusters: async () => {}, loadWorkAssignees: async () => {}, loadOverview: async () => {}, loadReviewers: async () => {},
    persistCurrentReviewRoute() {}, persistCurrentAnalysisRoute() {}, analysisRequestOptions: () => ({}),
    DEFAULT_CASE_PAGE_SIZE: 20, CASE_PAGE_SIZES: [10, 20, 50, 100], ISSUE_QUERY_ID_RE: /^cn\d+$/, LABELS: [],
    hasDashboardWriteRole: () => Boolean(state.session.can_write), canAccessCaseLabelingPreview: () => Boolean(state.session.can_write),
  };
  vm.createContext(s);
  function load(name) {
    const source = process.env.NAV_TEST_REF
      ? execFileSync('git', ['show', `${process.env.NAV_TEST_REF}:${root}${name}`], {encoding: 'utf8'})
      : fs.readFileSync(root + name, 'utf8');
    vm.runInContext(source, s, {filename: name});
  }
  load('text-input.js');
  if (!process.env.NAV_TEST_REF) { load('bev-video.js'); load('detail-trail.js'); }
  load('detail-media.js');
  load('routing.js');
  s.persistCurrentReviewRoute = () => {}; s.persistCurrentAnalysisRoute = () => {};
  function navigate(nextPage, search = '') {
    state.pageNavigationEpoch++;
    state.activePage = nextPage;
    location.pathname = '/manual/' + (nextPage === 'labeling' ? 'case-labeling' : nextPage);
    location.search = search;
  }
  s.actualShowPage = s.showPage;
  s.renderPageChrome = () => {}; s.setReviewView = () => {};
  s.showPage = (nextPage, options = {}) => {calls.pages.push(nextPage); navigate(nextPage);};
  return {s, state, calls, timers, elements, load, navigate};
}
async function navigationEpochTracksRealPageCommits() {
  const f = fixture(); const before = f.s.capturePageContext();
  f.s.actualShowPage('labeling-summary', {loadPageData: false, preserveScroll: true});
  assert.equal(f.state.pageNavigationEpoch, 2); assert(!f.s.isPageContextCurrent(before));
  const current = f.s.capturePageContext(); assert(f.s.isPageContextCurrent(current));
  f.s.actualShowPage('labeling-summary', {loadPageData: false, preserveScroll: true});
  assert(!f.s.isPageContextCurrent(current), 'a new route commit invalidates the prior visit');
}
async function loadersStartAfterCanonicalRouteCommit() {
  const f = fixture();
  f.s.parsePageRoute = () => ({page: f.state.activePage});
  f.s.pageUrl = page => '/manual/' + (page === 'labeling' ? 'case-labeling' : page);
  const commit = (_state, _title, url) => {const parsed = new URL(url, f.s.window.location.origin); f.s.window.location.pathname = parsed.pathname; f.s.window.location.search = parsed.search;};
  f.s.history = {pushState: commit, replaceState: commit}; f.s.window.history = f.s.history;
  let labelingContext, summaryContext;
  f.s.enterCaseLabeling = async () => {labelingContext = f.s.capturePageContext();};
  f.s.loadLabelingSummary = async () => {summaryContext = f.s.capturePageContext();};
  f.s.actualShowPage('labeling', {historyMode: 'push', preserveScroll: true});
  assert.equal(labelingContext.url, '/manual/case-labeling'); assert(f.s.isPageContextCurrent(labelingContext));
  f.s.actualShowPage('labeling-summary', {historyMode: 'push', preserveScroll: true});
  assert.equal(summaryContext.url, '/manual/labeling-summary'); assert(f.s.isPageContextCurrent(summaryContext));
}
async function delayedReviewReloadCannotReclaimLabeling() {
  for (const target of ['labeling', 'labeling-summary']) {
    const f = fixture(); f.load('import-refresh.js');
    const pending = defer(); f.s.loadCases = () => pending.promise;
    const request = f.s.reloadReviewGallery();
    f.navigate(target, '?q=cn32511483'); pending.resolve(); await request;
    assert.equal(f.state.activePage, target, 'late Review filter response stole the current page');
    assert.equal(f.calls.pages.length, 0);
    assert.equal(f.s.window.location.search, '?q=cn32511483');
  }
}
async function debounceCannotFireAfterDepartureOrRoundTrip() {
  const f = fixture(); f.load('bind-bootstrap.js'); let reloads = 0;
  f.s.reloadReviewGallery = async () => {reloads++;};
  f.s.scheduleReviewFilterReload(280);
  const callback = [...f.timers.values()].at(-1);
  f.navigate('labeling'); f.navigate('review'); callback(); await tick();
  assert.equal(reloads, 0, 'a timer from a previous visit must be inert');
  f.navigate('labeling-summary'); f.s.scheduleReviewFilterReload();
  assert.equal(f.timers.size, 1, 'off-page changes must not schedule a Review reload');
  const a = fixture('analysis'); a.load('analysis.js'); a.s.analysisRequestOptions = () => ({}); let analysisReloads = 0;
  a.s.reloadReviewAnalysis = async () => {analysisReloads++;};
  a.s.scheduleAnalysisFilterReload(220); const analysisCallback = [...a.timers.values()].at(-1);
  a.navigate('labeling-summary'); analysisCallback(); await tick(); assert.equal(analysisReloads, 0);
}
async function listPaginationAndPollingIgnoreObsoleteViews() {
  const cancellable = fixture(); cancellable.load('review-gallery.js');
  cancellable.s.renderCases = d => cancellable.calls.paints.push(d);
  const reads = [];
  cancellable.s.api = (_url, options) => {
    let resolve, reject;
    const promise = new Promise((a, b) => {resolve = a; reject = b;});
    reads.push({resolve, signal: options.signal});
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('obsolete'), {name: 'AbortError'})), {once: true});
    return promise;
  };
  const oldRead = cancellable.s.loadCases(), newRead = cancellable.s.loadCases({page: 2});
  assert.equal(reads[0].signal.aborted, true, 'new filters cancel obsolete transfer, not just its paint');
  await oldRead;
  reads[1].resolve({items: [{issue_id: 'current'}], total: 40}); await newRead;
  assert.equal(cancellable.calls.paints[0].items[0].issue_id, 'current');
  const f = fixture(); f.load('review-gallery.js'); f.s.renderCases = d => f.calls.paints.push(d); const pending = defer(); f.s.api = () => pending.promise;
  const request = f.s.loadCases(); f.navigate('labeling'); f.navigate('review');
  pending.resolve({items: [{issue_id: 'old'}], total: 1}); await request;
  assert.equal(f.calls.paints.length, 0, 'away-and-back must invalidate an old list response');
  const current = await f.s.loadCases(); assert.equal(f.calls.paints[0].items[0].issue_id, 'old', 'current response should still render');
  const pagination = defer(); f.s.loadCases = () => pagination.promise;
  const paging = f.s.changeCasePage(1); f.navigate('labeling-summary'); pagination.resolve(); await paging;
  assert.equal(f.calls.pages.length, 0);
  const p = fixture(); p.load('format-api.js'); const data = defer(); let selected = 0;
  p.s.loadConfig = async () => {}; p.s.loadRuns = async () => {}; p.s.loadCases = () => data.promise;
  p.s.selectCase = async () => {selected++;}; p.state.selectedId = 'cn1';
  const refresh = p.s.refreshChangedDataNow(); p.navigate('labeling'); data.resolve(); await refresh;
  assert.equal(selected, 0, 'late collaboration refresh must not reopen Review detail');
}
async function lateTaskContextCannotRewriteLabelingUrl() {
  const f = fixture(); f.load('work-split.js'); const pending = defer(); f.s.api = () => pending.promise;
  f.s.renderReviewTaskLoading = () => {}; f.s.renderReviewTaskContext = () => {};
  const request = f.s.loadReviewTaskContext('campaign-old');
  f.navigate('labeling-summary', '?q=keep-me');
  pending.resolve({task: {id: 'campaign-old', model_run_id: 'run-old', baseline_ids: ['old-scope']}});
  assert.equal(await request, null); assert.equal(f.s.window.location.pathname, '/manual/labeling-summary');
  assert.equal(f.s.window.location.search, '?q=keep-me'); assert.equal(f.state.selectedBaselineIds[0], '0821');
}
function bootstrapFixture(page) {
  const f = fixture(page); f.load('bind-bootstrap.js');
  const route = () => ({page: f.state.activePage, runId: 'none', search: f.s.window.location.search, analysisFilters: {}, runsFilters: {}, labelingFilters: {}, intentDatasetIds: []});
  Object.assign(f.s, {parsePageRoute: route, applyColorTheme() {}, applyUiLanguage() {}, applySidebarState() {}, markUiReady() {}, bindMobileFilterDrawers() {}, bindMobileWorkbench() {}, bindEvents() {}, updateImportFields() {}, applyReviewRouteControls() {}, setReviewComparisonStatus() {}, normalizedReviewComparisonStatus: x => x || 'all', renderAnalysisRunFilter() {}, renderActiveRun() {}, renderRunManager() {},
    loadConfig: async () => {}, loadRuns: async () => {}, loadCases: async () => {}, loadLabelingSummary: async () => {},
    resolveSessionInBackground: async () => {}, startChangePolling: () => {f.calls.polls++;},
    settleInitialRequests: requests => Promise.allSettled(requests.map(x => x && x.promise || x)),
  });
  return f;
}
async function bootstrapNeverReplaysInitialRouteOverNewNavigation() {
  const f = bootstrapFixture('review'); const pending = defer(); f.s.loadCases = () => pending.promise;
  const boot = f.s.bootstrap(); await tick();
  f.navigate('labeling-summary', '?q=cn32511483'); pending.resolve(); await boot;
  assert.equal(f.state.activePage, 'labeling-summary'); assert.deepEqual(f.calls.pages, ['review']); assert.equal(f.calls.polls, 1);
  const early = bootstrapFixture('review'); const config = defer(); early.s.loadConfig = () => config.promise;
  const earlyBoot = early.s.bootstrap(); early.navigate('labeling', '?q=current'); config.resolve(); await earlyBoot;
  assert.equal(early.state.activePage, 'labeling'); assert.equal(early.calls.polls, 1);
}
async function cronPaintDoesNotWaitForSharedBootstrap() {
  const f = bootstrapFixture('daily-cron');
  const config = defer(), runs = defer(), overview = defer();
  let cronReads = 0, runReads = 0;
  f.s.loadDailyCron = async () => { cronReads++; f.calls.paints.push('cron'); };
  f.s.loadConfig = () => config.promise;
  f.s.loadRuns = () => { runReads++; return runs.promise; };
  f.s.loadOverview = () => overview.promise;
  const boot = f.s.bootstrap(); await tick();
  assert.equal(cronReads, 1, 'Cron starts while configuration is unresolved');
  assert.deepEqual(f.calls.paints, ['cron']);
  assert.equal(runReads, 0);
  config.resolve(); await tick();
  assert.equal(runReads, 1, 'shared Run metadata remains available for subsequent navigation');
  assert.equal(cronReads, 1);
  runs.resolve(); await tick(); overview.resolve(); await boot;
  assert.equal(cronReads, 1, 'completed first snapshot is reused at final bootstrap');

  const leave = bootstrapFixture('daily-cron'), delayedConfig = defer();
  let laterRuns = 0;
  leave.s.loadDailyCron = async () => {};
  leave.s.loadConfig = () => delayedConfig.promise;
  leave.s.loadRuns = async () => { laterRuns++; };
  const pending = leave.s.bootstrap(); await tick();
  leave.navigate('labeling-summary', '?q=keep'); delayedConfig.resolve(); await pending;
  assert.equal(laterRuns, 0);
  assert.equal(leave.state.activePage, 'labeling-summary');
  assert.equal(leave.s.window.location.search, '?q=keep');
}
async function bootstrapRunDependenciesMatchTheVisiblePage() {
  const independent = {
    status: 'loadStatus', users: 'loadAccessUsers', 'rd-results': 'loadRdResults',
    'review-assignments': 'loadReviewAssignments', 'trail-history': 'loadTrailHistory',
    prediction: 'loadPredictionBatches', campaigns: 'loadCampaigns',
    intent: 'loadIntentLabeling', 'intent-experiments': 'loadIntentExperimentAdmin',
    'intent-summary': 'loadIntentSummary',
  };
  const dependent = {review: 'loadCases', analysis: 'loadReviewReasonAnalysis',
    comparison: 'loadRunComparison', 'run-collections': 'loadRunCollectionsWorkbench'};
  for (const [page, loader] of Object.entries({...independent, ...dependent})) {
    const f = bootstrapFixture(page), runs = defer();
    let reads = 0, overviewReads = 0, completed = false;
    f.state.intentLabeling = {};
    Object.assign(f.s, {
      loadMentionUsers: async () => {}, loadPredictionConfig: async () => {},
      applyAnalysisRouteControls() {}, applyRunComparisonRoute() {},
      normalizedAnalysisComparisonStatus: () => 'all',
      loadRuns: () => runs.promise,
      loadOverview: async () => {overviewReads++;},
      [loader]: async () => {reads++;},
      showToast: message => {throw new Error(message);},
    });
    const boot = f.s.bootstrap().then(() => {completed = true;}); await tick();
    assert.equal(reads, page in independent ? 1 : 0, page + ': only Run-dependent content waits');
    assert.equal(overviewReads, 0, 'shared overview must use the resolved Run scope');
    assert.equal(completed, false, 'final route commit must not invalidate pending Run metadata');
    runs.resolve(); await boot;
    assert.equal(reads, 1, page + ': exactly one page load');
    assert.equal(overviewReads, 1);
    assert.equal(f.calls.polls, 1);
  }
  const f = bootstrapFixture('campaigns'), runs = defer(); let overviewReads = 0;
  f.s.loadRuns = () => runs.promise; f.s.loadCampaigns = async () => {};
  f.s.loadOverview = async () => {overviewReads++;};
  const boot = f.s.bootstrap(); await tick();
  f.navigate('labeling-summary', '?q=keep'); runs.resolve(); await boot;
  assert.equal(overviewReads, 0, 'late catalog must not start an overview read on another page');
  assert.equal(f.state.activePage, 'labeling-summary');
  assert.equal(f.s.window.location.search, '?q=keep');
}
async function bootstrapResumesPendingCombinedContext() {
  for (const status of ['loading', 'ready', 'error']) {
    const f = bootstrapFixture('review'); let resumed = 0;
    f.s.loadCases = async () => {
      f.state.selectedCase = {issue_id:'cn1'};
      f.state.combinedReviewLoad = {key:'cn1/run/actor',status};
    };
    f.s.combinedReviewContextKey = () => 'cn1/run/actor';
    f.s.loadCombinedReviewContext = async data => {
      assert.equal(data.issue_id,'cn1');
      assert.equal(f.calls.pages.length,2, 'resume after final route commit');
      resumed++;
    };
    await f.s.bootstrap();
    assert.equal(resumed,status === 'loading' ? 1 : 0);
  }
}
async function summaryWaitsForIdentityInsteadOfFallingBackToReview() {
  const f = bootstrapFixture('labeling-summary'); const identity = defer(); let loaded = 0;
  f.state.session = {identity_pending: true, can_write: false};
  f.s.resolveSessionInBackground = () => identity.promise;
  f.s.loadLabelingSummary = async () => {loaded++;};
  const boot = f.s.bootstrap(); await tick();
  assert.equal(f.state.activePage, 'labeling-summary'); assert.deepEqual(f.calls.pages, ['labeling-summary']);
  assert.equal(loaded, 0, 'protected requests should wait for verified identity');
  f.state.session = {is_admin: true, can_write: true, identity_pending: false}; identity.resolve(); await boot;
  assert.equal(f.state.activePage, 'labeling-summary'); assert(!f.calls.pages.includes('review')); assert.equal(loaded, 1);
  const denied = bootstrapFixture('labeling-summary'); const deniedIdentity = defer(); let protectedReads = 0;
  denied.state.session = {identity_pending: true, can_write: false};
  denied.s.resolveSessionInBackground = () => deniedIdentity.promise;
  denied.s.loadLabelingSummary = async () => {protectedReads++;};
  const deniedBoot = denied.s.bootstrap(); await tick();
  denied.state.session = {identity_pending: false, is_admin: false, can_write: false};
  deniedIdentity.resolve(); await deniedBoot;
  assert.equal(denied.state.activePage, 'review', 'confirmed lack of permission must still be enforced');
  assert.equal(protectedReads, 0);
}
async function assignmentAccessWaitsForWriterAndAvoidsAdminRequests() {
  for (const role of ['writer', 'admin', 'viewer']) {
    const f = bootstrapFixture('review-assignments'), identity = defer(); let loaded = 0;
    f.state.session = {identity_pending: true, can_write: false};
    f.s.resolveSessionInBackground = () => identity.promise;
    f.s.loadReviewAssignments = async () => {loaded++;};
    f.s.loadAccessUsers = () => {throw new Error('bootstrap must let assignment loader own admin-only users');};
    const boot = f.s.bootstrap(); await tick();
    assert.equal(loaded, 0);
    f.state.session = {identity_pending: false, is_admin: role === 'admin', can_write: role !== 'viewer'};
    identity.resolve(); await boot;
    assert.equal(f.state.activePage, role === 'viewer' ? 'review' : 'review-assignments');
    assert.equal(loaded, role === 'viewer' ? 0 : 1);
  }
  const f = fixture('review'); f.s.PAGE_ROUTES['review-assignments'] = {};
  f.state.session = {identity_pending: false, is_admin: false, can_write: true};
  f.s.actualShowPage('review-assignments', {loadPageData: false, preserveScroll: true});
  assert.equal(f.state.activePage, 'review-assignments', 'writer navigation must not bounce');
  f.state.session.can_write = false;
  f.s.actualShowPage('review-assignments', {loadPageData: false, preserveScroll: true});
  assert.equal(f.state.activePage, 'review', 'viewer denial must remain');
}
async function labelingEntryAndSummaryResponsesStayScoped() {
  const f = fixture('labeling'); f.load('case-labeling.js'); const tasks = defer(); let listed = 0;
  f.s.loadCaseLabelingTasks = () => tasks.promise; f.s.restoreCaseLabelingRouteState = () => ({});
  f.s.loadCaseLabelingCases = async () => {listed++;};
  const entry = f.s.enterCaseLabeling(); f.navigate('labeling-summary', '?q=summary'); tasks.resolve(); await entry;
  assert.equal(listed, 0); f.s.persistCaseLabelingRoute(); assert.equal(f.s.window.location.pathname, '/manual/labeling-summary');
  const a = fixture('labeling-summary'); a.load('labeling-summary.js'); const pending = defer(); let requests = 0;
  a.s.api = () => {requests++; return pending.promise;};
  const summary = a.s.loadLabelingSummary();
  assert.equal(requests, 2, 'task directory and summary start together');
  a.navigate('labeling'); a.navigate('labeling-summary'); pending.resolve({items: []}); await summary;
  assert.equal(requests, 2, 'stale response must not issue further queries for a later visit');
}
async function labelingBackgroundRefreshKeepsTrailHydration() {
  for (const editing of [false, true]) {
    const f = fixture('labeling');
    f.load('format-api.js'); f.load('review-navigation.js'); f.load('case-labeling.js');
    const location = f.s.window.location;
    location.search = '?issue=cn37162905&baselines=0821';
    const commit = (_state, _title, url) => {
      const next = new URL(url, location.origin);
      location.pathname = next.pathname; location.search = next.search;
    };
    f.s.window.history = {state: {}, pushState: commit, replaceState: commit};
    f.s.pageUrl = (_page, options) => '/manual/case-labeling?' + new URLSearchParams({
      ...(options.issue ? {issue: options.issue} : {}), baselines: '0821',
    });
    Object.assign(f.s, {
      caseLabelDecisionUi: {}, structuredClone,
      withBaselineQuery: value => value, withBase: value => value,
      escapeHtml: value => String(value ?? ''), showToast() {},
      clearPendingCaseLabelingImages() {}, renderCaseLabelingEditor() {},
      renderCaseLabelingDetailMedia(data) {
        f.s.$('#caseLabelingExternalLinks').innerHTML = f.s.detailExternalLinksMarkup(data);
      },
      selectedActiveLabelingBaselineIds: () => ['0821'],
      caseLabelingListParams: () => 'baselines=0821',
      renderCaseLabelingAuthorPicker() {}, renderCaseLabelingAssigneePicker() {},
      renderCaseLabelingList() {}, loadCaseLabelingClusters: async () => {},
      loadCaseLabelingSnapshotReferences: async () => {}, loadCaseLabelingTasks: async () => {},
      loadConfig: async () => {}, refreshCaseExclusionSummary() {},
    });
    const metadata = defer(); let reads = 0;
    f.s.api = async url => {
      if (url.includes('/trail-metadata')) { reads++; return metadata.promise; }
      if (url.includes('/media')) return {assets: {}, camera: {}};
      if (url.includes('/api/labeling/cases/')) return {issue_id: 'cn37162905'};
      return {items: [], page: 1, labelers: [], assignees: []};
    };
    await f.s.selectCaseLabelingIssue('cn37162905', {updateRoute: false});
    f.state.caseLabeling.dirty = editing;
    const initialCase = f.state.caseLabeling.caseData;
    const draft = f.s.$('#caseLabelingRationale'); draft.value = 'Unsaved label rationale';
    const originalUrl = location.pathname + location.search;
    if (editing) {
      // The response can arrive after a collaboration refresh while typing.
      [...f.timers.values()][0](); await tick();
    }
    await f.s.refreshChangedDataNow();
    assert.equal(location.pathname + location.search, originalUrl,
      'background list refresh must keep the selected Issue route');
    if (!editing) [...f.timers.values()].forEach(callback => callback());
    metadata.resolve({issue_id: 'cn37162905', status: 'ready', external_links: {
      ra_recording_url: 'https://fixture.test/recording', ra_events: [{event: 'start'}],
    }});
    for (let i = 0; i < 6; i++) await tick();
    assert.equal(reads, 1, 'dwell and in-flight consumers must share one metadata read');
    assert.equal(f.state.caseLabeling.caseData.trail_metadata_status, 'ready');
    assert.ok(f.s.$('#caseLabelingExternalLinks').innerHTML.includes('RA Event'));
    assert.ok(!f.s.$('#caseLabelingExternalLinks').innerHTML.includes('data-trail-metadata-pending'));
    assert.equal(f.s.$('#caseLabelingRationale'), draft);
    assert.equal(draft.value, 'Unsaved label rationale');
    if (editing) assert.equal(f.state.caseLabeling.caseData, initialCase,
      'collaboration updates must retain an editor with an unsaved draft');
  }
}
async function optionalDirectoryDoesNotBlockIdentityOrOverwriteAnotherSession() {
  const f = fixture('users'); f.load('session-config.js');
  const directory = defer(); let ready = false;
  f.state.mentionUsers = [];
  f.s.renderSession = () => {}; f.s.renderMentionUsers = () => {};
  f.s.api = endpoint => endpoint === '/api/session'
    ? Promise.resolve({username: 'alice', authenticated: true, verified: true, is_admin: true})
    : directory.promise;
  const session = f.s.loadSession().then(() => {ready = true;});
  await tick();
  assert.equal(ready, true, 'permissions are ready while directory is pending');
  f.state.session = {username: 'bob', verified: true};
  f.state.mentionUsers = [{username: 'current-directory'}];
  directory.resolve({items: [{username: 'obsolete-directory'}]});
  await session; await tick();
  assert.equal(f.state.mentionUsers[0].username, 'current-directory');
}
async function delayedOverviewCannotReplaceNewScopeCounts() {
  const f = fixture(); f.load('session-config.js');
  const first = defer(), second = defer(); let requests = 0;
  f.s.api = () => (++requests === 1 ? first.promise : second.promise);
  f.s.renderOverview = data => f.calls.paints.push(data.issues);
  const oldRead = f.s.loadOverview(); f.state.selectedBaselineIds = ['0206'];
  const newRead = f.s.loadOverview(); second.resolve({issues: 42}); await newRead;
  first.resolve({issues: 99}); await oldRead;
  assert.deepEqual(f.calls.paints, [42]);
}
async function delayedAnalysisFacetCannotReplaceNewRunOptions() {
  const f = fixture('analysis'); f.load('work-split.js');
  const first = defer(), second = defer(); let requests = 0;
  f.s.api = () => (++requests === 1 ? first.promise : second.promise);
  f.s.renderAnalysisWorkSplitPicker = () => {};
  f.state.selectedRunId = 'old'; const oldRead = f.s.loadAnalysisWorkSplits();
  f.state.selectedRunId = 'new'; const newRead = f.s.loadAnalysisWorkSplits();
  second.resolve({items: [{split_id: 'new-options'}]}); await newRead;
  first.resolve({items: [{split_id: 'old-options'}]}); await oldRead;
  assert.equal(f.state.reviewAnalysis.workSplitOptions[0].split_id, 'new-options');
}
(async () => {
  for (const test of [bootstrapRunDependenciesMatchTheVisiblePage, labelingBackgroundRefreshKeepsTrailHydration, optionalDirectoryDoesNotBlockIdentityOrOverwriteAnotherSession, delayedOverviewCannotReplaceNewScopeCounts, delayedAnalysisFacetCannotReplaceNewRunOptions, cronPaintDoesNotWaitForSharedBootstrap,bootstrapResumesPendingCombinedContext,assignmentAccessWaitsForWriterAndAvoidsAdminRequests,delayedReviewReloadCannotReclaimLabeling, navigationEpochTracksRealPageCommits, loadersStartAfterCanonicalRouteCommit, debounceCannotFireAfterDepartureOrRoundTrip, listPaginationAndPollingIgnoreObsoleteViews, lateTaskContextCannotRewriteLabelingUrl, bootstrapNeverReplaysInitialRouteOverNewNavigation, summaryWaitsForIdentityInsteadOfFallingBackToReview, labelingEntryAndSummaryResponsesStayScoped]) {
    await test(); console.log('PASS ' + test.name);
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
