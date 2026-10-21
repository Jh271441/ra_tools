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
    querySelectorAll() { return []; }, focus() {}, setSelectionRange() {},
    showModal() { this.open = true; },
    setAttribute() {}, removeAttribute() {},
  });
  return elements.get(key);
}
const state = { selectedRunId: '', epoch: 1, session: { username: 'alice', can_write: true, is_admin: false }, caseLabeling: { caseData: { issue_id: 'cn1' } } };
const s = {
  state, $: element, URL, FormData, encodeURIComponent,
  document: { querySelectorAll: () => [] },
  window: { location: { origin: 'https://example.test' } },
  PAGE_ROUTES: { review: { path: '/review' }, labeling: { path: '/case-labeling' }, campaigns: { path: '/campaigns' } },
  withBase: path => '/manual' + path,
  capturePageContext: () => state.epoch, isPageContextCurrent: epoch => epoch === state.epoch,
  uiText: zh => zh, escapeHtml: String, formatTime: String,
  reviewMentionDisplayName: name => name, reviewCommentBodyMarkup: body => body,
  bindReviewMentionComposer() {}, updateReviewMentionComposer() {}, campaignLabel: value => value,
  acknowledgeLocalChange() {}, showToast() {}, selectedBaselineQueryValue: () => 'scope',
};
vm.createContext(s); vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/analysis.js', 'utf8'), s);
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise, resolve, reject}; }
const caseComment = { id: 1, discussion_channel: 'case', author: 'bob', body: 'public-body' };
const taskComment = { id: 2, discussion_channel: 'campaign', campaign_id: 'task1', author: 'bob', body: 'task-body' };
const result = (id='task1', comments=[caseComment, taskComment], read_only=false) => ({comments, task: {id, name:'October task', read_only}, count: comments.length});
async function open(options={}) { return s.openAnalysisDiscussion('cn1', {kind:'labeling',taskId:'task1', ...options}); }
async function main() {
  s.api = async path => { assert(path.includes('channel=both')); return result(); };
  await open();
  let c = state.analysisDiscussion;
  assert.equal(c.channel, 'case'); assert.equal(c.viewChannel, 'both');
  assert(!element('#analysisDiscussionSubmit').disabled); assert(!element('#analysisDiscussionComposer').hidden);
  assert(element('#analysisDiscussionThread').innerHTML.includes('public-body'));
  assert(element('#analysisDiscussionThread').innerHTML.includes('task-body'));
  assert(!element('#analysisDiscussionThread').innerHTML.includes('Campaign'));
  // Viewing scope changes actual rows, without moving a draft's destination.
  element('#analysisDiscussionNote').value = 'draft';
  element('#analysisDiscussionView').value = 'case'; element('#analysisDiscussionView').onchange();
  assert(!element('#analysisDiscussionThread').innerHTML.includes('task-body'));
  assert.equal(c.channel, 'case'); assert.equal(element('#analysisDiscussionNote').value, 'draft');
  element('#analysisDiscussionView').value = 'campaign'; element('#analysisDiscussionView').onchange();
  assert(!element('#analysisDiscussionThread').innerHTML.includes('public-body'));
  assert(element('#analysisDiscussionThread').innerHTML.includes('task-body'));
  // Reply is locked to its original scope, and cancellation restores the prior choice.
  element('#analysisDiscussionChannel').value = 'campaign'; element('#analysisDiscussionChannel').onchange();
  s.beginAnalysisDiscussionReply(1); assert.equal(c.channel, 'case'); assert(element('#analysisDiscussionChannel').disabled);
  s.beginAnalysisDiscussionReply(2); assert.equal(c.preReplyChannel, 'campaign');
  element('cancelReply').handlers.click(); assert.equal(c.replyTo, null); assert.equal(c.channel, 'campaign'); assert(!element('#analysisDiscussionChannel').disabled);
  s.beginAnalysisDiscussionReply(1); element('#analysisDiscussionNote').value = 'reply';
  let post = deferred(), posts = 0;
  s.api = async (path, options) => { posts++; const body=JSON.parse(options.body); assert.equal(body.task_id, ''); assert.equal(body.reply_to_id,1); return post.promise; };
  const saved = s.saveAnalysisDiscussion({preventDefault(){}});
  await s.saveAnalysisDiscussion({preventDefault(){}}); assert.equal(posts,1);
  post.resolve({comment:{id:3, body:'new-reply', discussion_channel:'case',author:'alice'},comment_count:2}); await saved;
  assert.equal(c.replyTo,null); assert.equal(c.channel,'campaign'); assert(!element('#analysisDiscussionChannel').disabled);
  assert.equal(c.viewChannel,'both'); assert.equal(element('#analysisDiscussionNote').value,'');
  // Reopen clears the reply lock even for the same Issue.
  s.api = async () => result(); s.beginAnalysisDiscussionReply(2); await open(); assert(!element('#analysisDiscussionChannel').disabled);
  // Same-Issue requests must also be owned by the exact task/Run/dialog instance.
  let first = deferred(), second = deferred();
  s.api = path => path.includes('task_id=task1') ? first.promise : second.promise;
  const firstOpen = open(); const secondOpen = open({taskId:'task2'});
  second.resolve(result('task2',[{id:5,body:'task2-body',discussion_channel:'campaign',campaign_id:'task2'}])); await secondOpen;
  first.resolve(result()); await firstOpen;
  assert.equal(state.analysisDiscussion.taskId,'task2'); assert.equal(state.analysisDiscussion.comments[0].id,5);
  first=deferred(); second=deferred(); s.api=path=>path.includes('model_run_id=run1')?first.promise:second.promise;
  const r1=s.openAnalysisDiscussion('cn1',{runId:'run1'}), r2=s.openAnalysisDiscussion('cn1',{runId:'run2'});
  second.resolve({comments:[{id:6,body:'run2-body'}]}); await r2; first.resolve({comments:[{id:7,body:'run1-body'}]}); await r1;
  assert.equal(state.analysisDiscussion.runId,'run2'); assert.equal(state.analysisDiscussion.comments[0].id,6);
  // A failed read preserves a draft and can retry. Page navigation/close reject late results.
  s.api=async()=>{throw Error('offline');}; await open(); c=state.analysisDiscussion; assert.equal(c.status,'error'); assert(element('#analysisDiscussionSubmit').disabled);
  element('#analysisDiscussionNote').value='preserved'; s.api=async()=>result(); await s.loadAnalysisDiscussion(c); assert.equal(c.status,'ready'); assert.equal(element('#analysisDiscussionNote').value,'preserved');
  first=deferred(); s.api=()=>first.promise; const late=open(); c=state.analysisDiscussion; state.epoch++; first.resolve(result()); await late; assert.equal(c.status,'loading');
  first=deferred(); s.api=()=>first.promise; const closed=open(); s.closeAnalysisDiscussion(); first.resolve(result()); await closed; assert.equal(state.analysisDiscussion,null);
  // A saved old dialog cannot erase a newer dialog's draft or overwrite its rows.
  s.api=async()=>result(); await open(); element('#analysisDiscussionNote').value='old'; post=deferred(); s.api=()=>post.promise;
  const oldSave=s.saveAnalysisDiscussion({preventDefault(){}}); s.api=async()=>result('task2',[]); await open({taskId:'task2'}); element('#analysisDiscussionNote').value='new draft';
  post.resolve({comment:{id:8,body:'saved elsewhere',discussion_channel:'case'}}); await oldSave;
  assert.equal(element('#analysisDiscussionNote').value,'new draft'); assert.equal(state.analysisDiscussion.comments.length,0);
  // Historical tasks allow public discussion, never task replies; the scope picker remains outside the composer.
  s.api=async()=>result('task1',[caseComment,taskComment],true); await open({discussionChannel:'campaign'});
  assert(element('#analysisDiscussionComposer').hidden); assert(!element('#analysisDiscussionChannelField').hidden); assert(!s.canReplyToAnalysisDiscussion(taskComment));
  element('#analysisDiscussionChannel').value='case'; element('#analysisDiscussionChannel').onchange(); assert(!element('#analysisDiscussionComposer').hidden); assert(s.canReplyToAnalysisDiscussion(caseComment));
  state.session.read_only=true; s.updateAnalysisDiscussionComposerAccess(); s.renderAnalysisDiscussionThread(); assert(element('#analysisDiscussionComposer').hidden); assert(!s.canReplyToAnalysisDiscussion(caseComment)); delete state.session.read_only;
  // Existing task-page admin policy is preserved; writers can use public discussion.
  s.api=async()=>({case_comments:[caseComment],campaign_comments:[taskComment],task:{id:'task1',name:'Task',read_only:false},run_comments:[{id:9,discussion_channel:'model_review',evaluation_run_id:'run-special'}]});
  await open({kind:'campaign',campaignId:'task1',taskId:'',discussionChannel:'both'});
  assert(!s.canReplyToAnalysisDiscussion(taskComment)); assert(s.canReplyToAnalysisDiscussion(caseComment));
  assert(s.analysisDiscussionShareUrl(9).includes('/manual/review?')); assert(s.analysisDiscussionShareUrl(9).includes('run=run-special'));
  // Markdown gets normal newlines; only Ctrl/Cmd+Enter posts, respecting IME and mention handling.
  s.bindAnalysisDiscussionEnterSubmit(); let requested=0; element('#analysisDiscussionForm').requestSubmit=()=>requested++;
  const key=opts=>{const e={key:'Enter',preventDefault(){this.defaultPrevented=true;},...opts};element('#analysisDiscussionNote').handlers.keydown(e);return e;};
  assert(!key({}).defaultPrevented); assert.equal(requested,0); assert(key({ctrlKey:true}).defaultPrevented); assert.equal(requested,1);
  key({metaKey:true}); assert.equal(requested,2); key({ctrlKey:true,isComposing:true}); key({ctrlKey:true,shiftKey:true}); key({ctrlKey:true,defaultPrevented:true}); assert.equal(requested,2);
  console.log('Discussion scope, reply lifecycle, ownership races, retry, roles, shares and keyboard passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
