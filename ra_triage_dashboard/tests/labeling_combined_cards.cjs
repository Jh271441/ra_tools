const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
let writes = 0, html = '', reply, fail = false;
const list = {dataset: {}, contains: () => false, querySelectorAll: () => [],
  get innerHTML() { return html; }, set innerHTML(value) { html = value; writes++; }};
const count = {}, status = {};
const context = {URLSearchParams, console, document: {activeElement: null},
  state: {uiLanguage:'zh',session:{username:'alice',verified:true}},
  $: selector => ({'#labelingCombinedTaskList':list,'#labelingCombinedTaskCount':count,'#labelingCombinedTaskStatus':status})[selector],
  escapeHtml: value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  uiText: (zh,en) => context.state.uiLanguage === 'zh' ? zh : en,
  formatTime: value => value || '—', versionDatasetTime: value => value || '—',
  withBase: value => '/manual'+value,
  pageUrl: (page, args) => '/manual/'+page+'?'+new URLSearchParams({run:args.runId,work_split:args.workSplitId,baselines:args.baselines.join(','),task_view:args.taskView}),
  api: async () => { if (fail) throw Error('offline'); return reply; }};
vm.createContext(context);
for (const name of ['review-assignments.js','labeling-combined-tasks.js'])
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js',name),'utf8'),context);
const item = {split_id:'campaign-a',campaign_name:'0821 very long task <name>',model_run_id:'run-a',
  workflow_mode:'model_review_and_case_label',is_current:true,lifecycle:'active',baseline_ids:['0821'],
  assignment_count:12,completed_count:3,completion_ratio:.25,total_count:12,
  members:[{username:'alice',assigned_count:12,completed_count:3,pending_count:9,completion_ratio:.25}]};
const version = {...item,split_id:'campaign-v',appendable:true,release_family:'20261009',baseline_ids:['version-20261009']};
(async () => {
  reply = {items:[version,item]};
  await context.loadLabelingCombinedTasks();
  // Identical shared card markup; only detail navigation differs from the owning page.
  const expected = [version,item].map(task=>context.renderReviewAssignmentBatch(task,{
    detailHref:'/manual/review-assignments?'+new URLSearchParams({lifecycle:'current',split:task.split_id})})).join('');
  assert.equal(html,expected);
  assert.ok(html.includes('3 / 12 · 25%'));
  assert.ok(html.includes('9 条待处理'));
  assert.ok(!html.includes('data-open-review-assignment='));
  assert.ok(html.includes('0821 very long task &lt;name>'));
  assert.equal(count.textContent,'2');
  const unchanged = writes;
  await context.loadLabelingCombinedTasks();
  assert.equal(writes,unchanged,'unchanged refresh must preserve all card nodes');
  fail = true; await context.loadLabelingCombinedTasks();
  assert.equal(writes,unchanged); assert.ok(status.textContent.includes('失败'));
  context.state.uiLanguage='en'; context.renderLabelingCombinedTasks();
  assert.ok(html.includes('Start combined review')); assert.ok(html.includes('View task detail'));
  assert.ok(html.includes('Combined review progress')); assert.ok(html.includes('9 pending'));
  fail = false; reply = {items:[]}; await context.loadLabelingCombinedTasks();
  assert.equal(count.textContent,'0'); assert.ok(html.includes('No active combined review tasks.'));
  context.state.session.username='bob'; fail=true; await context.loadLabelingCombinedTasks();
  assert.equal(count.textContent,'—'); assert.equal(html,'');
})().catch(error=>{console.error(error);process.exitCode=1;});
