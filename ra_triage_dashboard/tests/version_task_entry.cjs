const fs = require('fs'), vm = require('vm'), assert = require('assert'), path = require('path');
const root = path.join(__dirname, '../static/js');
const task = 'campaign-version-20261016-odd2';
const state = {activePage:'review', selectedBaselineIds:['version-20261016'], reviewAnalysis:{}, reviewWorkSplitId:task, reviewTaskView:'pending'};
const s = {state, URL, URLSearchParams, console, t:x=>x,
  window:{location:{origin:'https://example.test', pathname:'/review', search:''}},
  PAGE_ROUTES:{review:{path:'/review'}, analysis:{path:'/review-analysis'}}, withBase:x=>x,
  $:()=>null, getMultiFilterValues:()=>[], LABELS:[], MODEL_LABELS:[], ISSUE_QUERY_ID_RE:/^cn\d+$/,
  CASE_PAGE_SIZES:[20], DEFAULT_CASE_PAGE_SIZE:20,
  parseFilterList:x=>Array.isArray(x)?x:String(x||'').split(',').filter(Boolean),
  joinFilterList:x=>(x||[]).join(','), comparisonStatusParam:x=>x,
};
vm.createContext(s);
for (const file of ['routing.js','format-api.js','runs.js']) vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),s);
const url = s.pageUrl('review',{workSplitId:task,taskView:'pending',workAssignee:['jasperchen'],runId:'run1'});
const parsed = new URL(url,s.window.location.origin).searchParams;
const route = s.normalizedReviewRouteFilters(parsed);
assert.equal(route.workSplitId,task);
assert.equal(route.taskView,'targets');
assert.deepEqual([...route.taskProgress],['pending']);
assert.equal(route.workAssignee[0],'jasperchen');
assert.equal(s.normalizedAnalysisRouteFilters(new URLSearchParams('work_split='+task+'&task_view=targets')).workSplitId,task);
assert.equal(s.normalizedAnalysisRouteFilters(new URLSearchParams('work_split='+task+'&task_view=targets')).taskView,'targets');
assert(!s.pageUrl('review',{workSplitId:'',taskView:'pending'}).includes('task_view'));
assert.equal(s.appendBaselineParams(new URLSearchParams('work_split_id='+task)).get('task_view'),'pending');
assert.equal(s.appendBaselineParams(new URLSearchParams()).get('task_view'),null);
assert.equal(s.appendBaselineParams(new URLSearchParams('work_split_id=campaign-other')).get('task_view'),null);
state.activePage='labeling';
assert.equal(s.appendBaselineParams(new URLSearchParams('work_split_id='+task)).get('task_view'),null);
state.activePage='analysis'; state.reviewAnalysis={workSplitId:task, taskView:'targets'};
assert.equal(s.appendBaselineParams(new URLSearchParams('work_split_id='+task)).get('task_view'),'targets');
state.activePage='review';
const notification={issue:'cn123',runId:'run1',workSplitId:task,baselines:['version-20261016']};
s.window.location.search='?issue=cn123&run=run1&work_split='+task+'&baselines=version-20261016&comments=1&channel=case&source=combined_review&comment=117';
const target=new URL(s.pageUrl('review',notification),s.window.location.origin);
assert.equal(target.searchParams.get('comment'),'117');
assert.equal(target.searchParams.get('channel'),'case');
// Replacement/refresh and browser history reconstruct the same exact target.
s.window.location.search=target.search;
assert.equal(new URL(s.pageUrl('review',notification),s.window.location.origin).searchParams.get('comment'),'117');
for(const override of [{issue:'cn456'},{runId:'run2'},{workSplitId:''},{baselines:['other']}]) {
  const changed=new URL(s.pageUrl('review',{...notification,...override}),s.window.location.origin);
  assert.equal(changed.searchParams.get('comments'),null);
  assert.equal(changed.searchParams.get('source'),null);
}
s.window.location.search=s.window.location.search.replace('combined_review','untrusted');
assert.equal(new URL(s.pageUrl('review',notification),s.window.location.origin).searchParams.get('comments'),null);
console.log('Version task routing and API scope passed');
