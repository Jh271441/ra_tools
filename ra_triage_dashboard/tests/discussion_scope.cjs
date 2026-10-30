const fs = require('fs'), vm = require('vm'), assert = require('node:assert/strict');
const elements = new Map();
function element(key) {
  if (!elements.has(key)) elements.set(key, {
    value: '', innerHTML: '', textContent: '', hidden: false, disabled: false, dataset: {}, handlers: {},
    addEventListener(type, fn) { this.handlers[type] = fn; },
    querySelector(selector) {
      if (selector.startsWith('option[') || selector.startsWith('.ui-lang-')) return element(key + selector);
      if (selector === '[data-cancel-comment-reply]' && this.innerHTML.includes('data-cancel-comment-reply')) return element('cancelReply');
      return null;
    },
    querySelectorAll() { return []; }, focus() {}, setSelectionRange() {}, scrollIntoView() {},
    showModal() { this.open = true; },
    setAttribute() {}, removeAttribute() {},
  });
  return elements.get(key);
}
const state = { selectedRunId: '', epoch: 1, session: { username: 'alice', can_write: true, is_admin: false }, caseLabeling: { caseData: { issue_id: 'cn1' } } };
const s = {
  state, $: element, URL, FormData, AbortController, encodeURIComponent,
  enhanceDashboardSelects() {}, // Real DOM adapter covered by dropdown_components.cjs.
  document: { querySelectorAll: () => [] },
  window: { location: { origin: 'https://example.test', pathname: '/review', search: '?issue=cn1&run=run1&baselines=scope&work_split=task1' }, setTimeout, clearTimeout },
  PAGE_ROUTES: { review: { path: '/review' }, labeling: { path: '/case-labeling' }, campaigns: { path: '/campaigns' } },
  withBase: path => '/manual' + path,
  capturePageContext: () => ({epoch:state.epoch,url:s.window.location.pathname+s.window.location.search}),
  isPageContextCurrent: (context,{matchUrl=true}={}) => context.epoch===state.epoch && (!matchUrl || context.url===s.window.location.pathname+s.window.location.search),
  uiText: zh => zh, escapeHtml: String, formatTime: String,
  reviewMentionDisplayName: name => name, reviewCommentBodyMarkup: body => body,
  disposeReviewMentionComposer() {}, bindReviewMentionComposer() {}, updateReviewMentionComposer() {}, campaignLabel: value => value,
  acknowledgeLocalChange() {}, showToast() {}, selectedBaselineQueryValue: () => 'scope',
};
vm.createContext(s); vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/text-input.js', 'utf8'), s); vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/analysis.js', 'utf8'), s);
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise, resolve, reject}; }
const caseComment = { id: 1, discussion_channel: 'case', author: 'bob', body: 'public-body' };
const taskComment = { id: 2, discussion_channel: 'campaign', campaign_id: 'task1', author: 'bob', body: 'task-body' };
const result = (id='task1', comments=[caseComment, taskComment], read_only=false) => ({comments, task: {id, name:'October task', read_only}, count: comments.length});
async function open(options={}) { return s.openAnalysisDiscussion('cn1', {kind:'labeling',taskId:'task1', ...options}); }
async function main() {
  let requested=[];
  s.api=async path=>{requested.push(path);return result();};
  await open({taskId:'closed-task',runId:'missing-run'});
  assert.equal(state.analysisDiscussion.kind,'issue');
  assert.equal(requested.at(-1),'/api/cases/cn1/discussion');
  assert(!element('#analysisDiscussionSubmit').disabled);
  assert(element('#analysisDiscussionViewField').hidden);
  assert(element('#analysisDiscussionChannelField').hidden);
  assert(element('#analysisDiscussionThread').innerHTML.includes('public-body'));
  assert(element('#analysisDiscussionThread').innerHTML.includes('task-body'));
  assert(s.canReplyToAnalysisDiscussion(taskComment));
  s.beginAnalysisDiscussionReply(2);
  element('#analysisDiscussionNote').value='reply to a historical task';
  let post;
  s.api=async(path,options)=>{post={path,body:JSON.parse(options.body)};return {comment:{id:3,body:'reply',author:'alice'}};};
  await s.saveAnalysisDiscussion({preventDefault(){}});
  assert.equal(post.path,'/api/cases/cn1/discussion');
  assert.equal(post.body.reply_to_id,2);assert.equal(post.body.task_id,undefined);assert.equal(post.body.model_run_id,undefined);
  assert.equal(element('#analysisDiscussionNote').value,'');
  const share=new URL(s.analysisDiscussionShareUrl(2));
  assert.equal(share.searchParams.get('issue'),'cn1');assert.equal(share.searchParams.get('comment'),'2');
  for(const key of ['run','task','work_split','campaign','baselines']) assert(!share.searchParams.has(key));
  const originalSearch=s.window.location.search;
  for (const key of ['run','task','work_split','campaign','baselines']) {
    s.api=async()=>result();await open();element('#analysisDiscussionNote').value='retained Issue conversation';
    const next=new URL(s.window.location.origin+s.window.location.pathname+s.window.location.search);
    next.searchParams.set(key,'different');s.window.location.search=next.search;state.epoch++;
    let posts=0;s.api=async()=>{posts++;return {comment:{id:4,body:'saved'}};};
    await s.saveAnalysisDiscussion({preventDefault(){}});assert.equal(posts,1);assert.equal(element('#analysisDiscussionNote').value,'');
    s.window.location.search=originalSearch;
  }
  // Only an actual switch to another Issue invalidates this Issue modal.
  s.api=async()=>result();await open();element('#analysisDiscussionNote').value='keep my draft';
  s.window.location.search=originalSearch.replace('cn1','cn2');let posts=0;s.api=async()=>{posts++;};
  await s.saveAnalysisDiscussion({preventDefault(){}});assert.equal(posts,0);assert.equal(element('#analysisDiscussionNote').value,'keep my draft');
  assert(element('#analysisDiscussionSubmitStatus').innerHTML.includes('Issue has changed'));
  s.window.location.search=originalSearch;
  // Requests from a closed/replaced modal cannot overwrite its replacement.
  let first=deferred();s.api=()=>first.promise;const pending=open();
  s.closeAnalysisDiscussion();s.api=async()=>result('task2',[]);await open({taskId:'task2'});
  element('#analysisDiscussionNote').value='new modal draft';first.resolve(result());await pending;
  assert.equal(state.analysisDiscussion.comments.length,0);assert.equal(element('#analysisDiscussionNote').value,'new modal draft');
  s.api=async()=>{throw Error('offline');};await open();assert.equal(state.analysisDiscussion.status,'error');
  element('#analysisDiscussionNote').value='preserved';s.api=async()=>result();await s.loadAnalysisDiscussion(state.analysisDiscussion);
  assert.equal(state.analysisDiscussion.status,'ready');assert.equal(element('#analysisDiscussionNote').value,'preserved');
  state.session.read_only=true;s.updateAnalysisDiscussionComposerAccess();assert(element('#analysisDiscussionComposer').hidden);
  assert(!s.canReplyToAnalysisDiscussion(caseComment));delete state.session.read_only;s.updateAnalysisDiscussionComposerAccess();
  s.bindAnalysisDiscussionEnterSubmit();let submitted=0;element('#analysisDiscussionForm').requestSubmit=()=>submitted++;
  const key=opts=>{const e={key:'Enter',preventDefault(){this.defaultPrevented=true;},...opts};element('#analysisDiscussionNote').handlers.keydown(e);return e;};
  key({});assert.equal(submitted,0);key({ctrlKey:true});key({metaKey:true});assert.equal(submitted,2);key({ctrlKey:true,isComposing:true});assert.equal(submitted,2);
  console.log('Unified Issue thread: legacy task/Run visibility, replies, taskless writes, Bot route normalization, ownership races and keyboard passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
