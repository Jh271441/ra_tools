const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const {execFileSync} = require('node:child_process');
const baseScope = 'work_split_id=task&work_assignee=jasperchen&model_run_id=run&baselines=scope&label_state=conflict';
const allIds = Array.from({length: 40}, (_, i) => `cn${i + 1}`);
const state = {};
let scope, epoch = 0, calls, pages, messages, located, routes, apiImpl, loadImpl, paints, queueIds, pendingIds;
const button = {hidden: false, disabled: false, textContent: '', title: ''};
const sandbox = {
  state, console, URLSearchParams, Set, Promise,
  $: id => id === '#reviewNextPendingTaskButton' ? button : null,
  selectedCombinedTaskProgress: () => state.reviewTaskProgress,
  isCombinedTaskProgressFilter: () => true,
  capturePageContext: () => epoch,
  isPageContextCurrent: value => value === epoch,
  uiText: (zh, en) => en,
  showToast: message => messages.push(message),
  api: (url, options) => { calls.push({url, options}); return apiImpl(url); },
  selectCase: () => assert.fail('Gallery locate must never open Issue detail'),
  persistCurrentReviewRoute: options => routes.push({...options, page: state.casePage, pageSize: state.casePageSize}),
};
vm.createContext(sandbox);
const source = process.env.NEXT_PENDING_TEST_REF
  ? execFileSync('git', ['show', `${process.env.NEXT_PENDING_TEST_REF}:ra_triage_dashboard/static/js/review-gallery.js`], {encoding: 'utf8'})
  : fs.readFileSync(path.join(__dirname, '../static/js/review-gallery.js'), 'utf8');
vm.runInContext(source, sandbox);
sandbox.renderCases = () => paints.push(sandbox.reviewPendingGalleryTargetId());
sandbox.renderCasePagination = () => {};
sandbox.loadCases = async options => {
  pages.push(options.page); state.casePage = options.page; state.caseListRequestSeq++;
  await loadImpl(options);
};
sandbox.highlightPendingGalleryTarget = id => located.push(id);
sandbox.currentReviewGalleryExportParams = () => new URLSearchParams(scope + '&format=xlsx&gallery_scope=true');

function reset() {
  Object.assign(state, {activePage: 'review', reviewTaskContext: {id: 'task'}, reviewTaskContextLoading: false,
    reviewTaskContextError: null, reviewTaskProgress: [], selectedId: '', casePage: 1, casePageSize: 10,
    caseTotal: 40, cases: allIds.slice(0, 10).map(issue_id => ({issue_id})), caseListRequestSeq: 0,
    savingAnnotation: false, reviewPendingGalleryTarget: null, reviewPendingJumpBusy: false, pageNavigationEpoch: 0});
  scope = baseScope; calls = []; pages = []; messages = []; located = []; routes = []; paints = [];
  queueIds = allIds; pendingIds = ['cn1', 'cn3', 'cn22', 'cn23'];
  apiImpl = async url => ({issue_ids: new URL(url, 'http://fixture').searchParams.has('task_progress')
    ? pendingIds : queueIds});
  loadImpl = async ({page}) => {state.cases = queueIds.slice((page - 1) * state.casePageSize, page * state.casePageSize)
    .map(issue_id => ({issue_id}));};
}
const defer = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};};

(async () => {
  reset(); sandbox.renderNextPendingTaskButton();
  assert.equal(button.hidden, false); assert.equal(button.textContent, 'Next pending');
  assert.match(button.title, /page size/);
  // Returning from detail used to clear selectedId and repeat cn1. Gallery now owns its cursor.
  for (const expected of ['cn1', 'cn3', 'cn22', 'cn23']) {
    await sandbox.jumpToNextPendingTask();
    assert.equal(located.at(-1), expected);
    assert.equal(state.selectedId, '');
    assert.equal(sandbox.reviewPendingGalleryTargetId(), expected);
    assert.equal(state.casePageSize, 10);
    assert.deepEqual(state.reviewTaskProgress, []);
  }
  assert.deepEqual(located, ['cn1', 'cn3', 'cn22', 'cn23']);
  assert.deepEqual(pages, [3]); assert.deepEqual(paints, located);
  assert(routes.every(route => route.issue === '' && route.pageSize === 10));
  assert.equal(routes.at(-1).page, 3);
  await sandbox.jumpToNextPendingTask();
  assert.equal(located.length, 4, 'End must not wrap to the first pending Issue');
  assert.match(messages[0], /No further/);
  for (const {url, options} of calls) {
    const q = new URL(url, 'http://fixture').searchParams;
    for (const [key, value] of new URLSearchParams(baseScope)) assert.equal(q.get(key), value);
    assert(!q.has('format')); assert(!q.has('gallery_scope'));
    assert.equal(options.cache, 'no-store', 'Request fresh HTTP completion status');
  }
  reset(); state.casePage = 2; await loadImpl({page: 2});
  await sandbox.jumpToNextPendingTask(); assert.equal(located[0], 'cn1', 'A first click must include pending Issues before the visible page');
  // Reported scope: 278 Issues, unfinished #200/#219, with completed #232 retained
  // from detail on page 12. Initial lookup must recover #200 on page 10.
  reset();
  queueIds = Array.from({length: 278}, (_, i) => `fixture${i + 1}`);
  queueIds[199] = 'cn35743727'; queueIds[218] = 'cn35759965'; queueIds[231] = 'cn35772161';
  pendingIds = ['cn35743727', 'cn35759965'];
  Object.assign(state, {casePage: 12, casePageSize: 20, caseTotal: 278, selectedId: 'cn35772161'});
  await loadImpl({page: 12});
  assert.equal(sandbox.reviewPendingGalleryTargetId(), '', 'Detail selection must not become the Gallery locate cursor');
  await sandbox.jumpToNextPendingTask();
  assert.equal(located.at(-1), 'cn35743727'); assert.equal(state.casePage, 10);
  assert.equal(state.cases.length, 20); assert.equal(state.caseTotal, 278);
  assert.equal(routes.at(-1).issue, ''); assert.equal(routes.at(-1).page, 10);
  await sandbox.jumpToNextPendingTask();
  assert.equal(located.at(-1), 'cn35759965'); assert.equal(state.casePage, 11);
  assert.equal(state.cases.length, 20); assert.equal(state.casePageSize, 20);
  state.pageNavigationEpoch++;
  assert.equal(sandbox.reviewPendingGalleryTargetId(), '', 'A new Gallery visit retires its old cursor');
  await sandbox.jumpToNextPendingTask();
  assert.equal(located.at(-1), 'cn35743727', 'Re-entry must recover earlier unfinished work again');
  assert.equal(state.casePage, 10);
  reset(); await sandbox.jumpToNextPendingTask(); scope += '&search=new';
  assert.equal(sandbox.reviewPendingGalleryTargetId(), '', 'Filter changes clear the old selection');
  await sandbox.jumpToNextPendingTask(); assert.equal(located.at(-1), 'cn1');
  for (const change of [() => {state.casePage = 2;}, () => {state.casePageSize = 20;}]) {
    reset(); await sandbox.jumpToNextPendingTask(); change();
    assert.equal(sandbox.reviewPendingGalleryTargetId(), '', 'Page/page-size changes invalidate the cursor');
  }
  reset(); await sandbox.jumpToNextPendingTask();
  state.cases = state.cases.filter(item => item.issue_id !== 'cn1');
  assert.equal(sandbox.reviewPendingGalleryTargetId(), '', 'Removed cards cannot remain selected');
  for (const progress of [['pending'], ['completed']]) {
    reset(); state.reviewTaskProgress = progress; sandbox.renderNextPendingTaskButton();
    assert.equal(button.hidden, true); await sandbox.jumpToNextPendingTask(); assert.equal(calls.length, 0);
  }
  reset(); state.reviewTaskProgress = ['completed', 'pending']; assert(sandbox.reviewShowsAllTaskProgress());
  for (const flag of ['reviewTaskContextLoading', 'reviewTaskContextError', 'savingAnnotation', 'reviewPendingJumpBusy']) {
    reset(); state[flag] = true; await sandbox.jumpToNextPendingTask(); assert.equal(calls.length, 0);
  }
  // Navigation, filters, pagination and overlapping list loads retire an older pending search.
  for (const invalidate of [() => epoch++, () => {scope += '&search=new';},
    () => state.casePage++, () => {state.casePageSize = 20;}, () => state.caseListRequestSeq++,
    () => {state.selectedId = 'cn9';}]) {
    reset(); const held = defer(); apiImpl = () => held.promise;
    const jump = sandbox.jumpToNextPendingTask(); await sandbox.jumpToNextPendingTask();
    assert.equal(calls.length, 2, 'Duplicate click is ignored');
    sandbox.renderNextPendingTaskButton(); assert.equal(button.disabled, true);
    invalidate(); held.resolve({issue_ids: allIds}); await jump;
    assert.equal(located.length, 0); assert.equal(routes.length, 0); assert.equal(state.reviewPendingJumpBusy, false);
  }
  reset(); state.casePage = 2; await loadImpl({page: 2});
  loadImpl = async () => {epoch++;}; await sandbox.jumpToNextPendingTask();
  assert.equal(located.length, 0, 'Late cross-page result cannot locate or write the URL');
  reset(); state.casePage = 2; await loadImpl({page: 2});
  loadImpl = async () => {state.caseListRequestSeq++;}; await sandbox.jumpToNextPendingTask();
  assert.equal(located.length, 0, 'A newer list read owns the gallery');
  reset(); state.casePage = 2; await loadImpl({page: 2});
  loadImpl = async () => {state.cases = [];}; await sandbox.jumpToNextPendingTask();
  assert.match(messages[0], /list changed/); assert.equal(located.length, 0);
  reset(); await sandbox.jumpToNextPendingTask(); await sandbox.jumpToNextPendingTask();
  const normalLoad = loadImpl;
  loadImpl = async () => {throw Error('page offline');};
  await assert.rejects(sandbox.jumpToNextPendingTask(), /page offline/);
  assert.equal(state.casePage, 1, 'A failed cross-page read restores the page still on screen');
  assert.equal(sandbox.reviewPendingGalleryTargetId(), 'cn3', 'Failure preserves the last valid cursor');
  assert.equal(state.reviewPendingJumpBusy, false);
  loadImpl = normalLoad; await sandbox.jumpToNextPendingTask();
  assert.equal(located.at(-1), 'cn22', 'Retry continues past the same cursor');
  reset(); apiImpl = async () => {throw Error('offline');};
  await assert.rejects(sandbox.jumpToNextPendingTask(), /offline/); assert.equal(state.reviewPendingJumpBusy, false);
  reset(); apiImpl = async () => ({issue_ids: []}); await sandbox.jumpToNextPendingTask();
  assert.equal(located.length, 0); assert.match(messages[0], /No further/);
  console.log('Next pending gallery: earliest unfinished Issue, #200 before retained #232, new visits, repeated clicks, scope/size/URL, end, errors and races passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
