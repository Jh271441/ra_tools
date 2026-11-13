const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
let writes = 0, html = '', reply, fail = false;
const list = {dataset: {}, contains: () => false, querySelectorAll: () => [],
  get innerHTML() { return html; }, set innerHTML(value) { html = value; writes++; }};
const count = {}, status = {};
const context = {URLSearchParams, console, document: {activeElement: null},
  state: {uiLanguage:'zh',session:{username:'alice',verified:true}},
  $: selector => ({'#labelingCombinedTaskList':list,'#labelingCombinedTaskCount':count,'#labelingCombinedTaskStatus':status,
    '#reviewAssignmentList':list,'#reviewAssignmentListStatus':status})[selector],
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
  // Exercise both real list entrypoints: appendable version cards bypass the
  // ordinary task renderer and must not fall back to the pre-1106 combined name.
  const sampling={...version,split_id:'campaign-version-20261106-odd2-sampling',release_family:'20261106',
    baseline_ids:['version-20261106'],role_cohort:'sampling',total_count:7,assignment_count:14};
  const low={...sampling,split_id:'campaign-version-20261106-odd2-low',role_cohort:'low',total_count:20,assignment_count:20};
  fail=false;
  for(const language of ['zh','en']) {
    context.state.uiLanguage=language;
    reply={items:[sampling,low]};await context.loadLabelingCombinedTasks();
    const combined=html;
    context.state.reviewAssignments={splits:reply.items,lifecycle:'versions'};
    context.renderReviewAssignmentList();
    for(const markup of [combined,html]) {
      assert.ok(markup.includes(language==='zh'?'1106 · 抽样集':'1106 · Sampling'));
      assert.ok(markup.includes(language==='zh'?'1106 · 低置信集':'1106 · Low confidence'));
      assert.ok(markup.includes(language==='zh'?'RD＋TE 交叉标注':'RD + TE cross-review'));
      assert.ok(markup.includes(language==='zh'?'不含抽样 · RD 单人标注':'Excludes sampling · One RD per case'));
      assert.ok(!markup.includes('Single owner · No overlap')&&!markup.includes('低置信＋抽样'));
      assert.ok(markup.includes('work_split='+sampling.split_id)&&markup.includes('work_split='+low.split_id));
      assert.ok(markup.includes('3 / 14')&&markup.includes('3 / 20'));
    }
    assert.equal(status.textContent,language==='zh'?'2 个任务':'2 tasks');
    const legacy=context.renderReviewAssignmentBatch({...version,release_family:'20261030'});
    assert.ok(legacy.includes(language==='zh'?'1030 · 版本联合复核':'1030 · Version combined review'));
    assert.ok(legacy.includes(language==='zh'?'低置信＋抽样 · 单人负责 · 无交叉':'Low confidence + sample · Single owner · No overlap'));
  }
  fail = false; reply = {items:[]}; await context.loadLabelingCombinedTasks();
  assert.equal(count.textContent,'0'); assert.ok(html.includes('No active combined review tasks.'));
  context.state.session.username='bob'; fail=true; await context.loadLabelingCombinedTasks();
  assert.equal(count.textContent,'—'); assert.equal(html,'');
})().catch(error=>{console.error(error);process.exitCode=1;});
