const fs = require('fs'), vm = require('vm'), assert = require('assert'), path = require('path');
const task = 'campaign-combined', root = path.join(__dirname, '../static/js');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {dataset:{}, values:[], value:'', hidden:false, textContent:'', title:'', querySelector:()=>null});
  return elements.get(id);
}
const state = {activePage:'review', reviewWorkSplitId:task, reviewTaskView:'targets',
  reviewTaskProgress:['pending'], reviewWorkflowMode:'model_review_and_case_label',
  reviewTaskContext:{id:task,workflow_mode:'model_review_and_case_label'},
  selectedBaselineIds:['0508'], session:{verified:true,username:'jasperchen'}, reviewAnalysis:{}};
let renders = 0, reloads = 0;
const s = {state, URL, URLSearchParams, console, t:x=>x, uiText:(zh,en)=>state.uiLanguage==='en'?en:zh,
  window:{location:{origin:'http://fixture.test',pathname:'/review',search:''},history:{replaceState:()=>{}}},
  PAGE_ROUTES:{review:{path:'/review'}}, withBase:x=>x,
  $:element, getMultiFilterValues:e=>e?.values||[], setMultiFilterValues:(e,v)=>{if(e)e.values=v||[];},
  parseFilterList:x=>Array.isArray(x)?x:String(x||'').split(',').filter(Boolean),
  joinFilterList:x=>(x||[]).join(','), comparisonStatusParam:x=>x||'all',
  LABELS:[], MODEL_LABELS:[], CASE_PAGE_SIZES:[20], DEFAULT_CASE_PAGE_SIZE:20,
  ISSUE_QUERY_ID_RE:/^cn\d+$/, selectedBaselineQueryValue:()=> '0508',
  defaultBaselineIdsFromConfig:()=>['0508'], normalizeBaselineIds:x=>x||['0508'],
  renderMultiFilter:(e,opts)=>{renders++;e.options=opts.options;e.values=opts.selected;e.change=opts.onChange;},
  relabelMultiFilter:(e,options)=>{if(JSON.stringify(e.options?.map(x=>x.value))!==JSON.stringify(options.map(x=>x.value)))return false;e.options=options;return true;},
  scheduleReviewFilterReload:()=>{reloads++;}, bindUiInfoPopovers:()=>{},
};
vm.createContext(s);
for(const file of ['routing.js','runs.js','work-split.js','review-assignments.js','import-refresh.js']) vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),s);
s.renderReviewProgressFilter();
assert.equal(element('#reviewTaskProgressLabel').textContent,'任务状态');
assert.deepEqual([...element('#reviewTaskProgressFilter').values],['pending']);
assert.deepEqual([...s.selectedModelReviewStatuses()],[]);
assert(s.pageUrl('review',{workSplitId:task,taskProgress:['pending']}).includes('task_progress=pending'));
assert(!s.pageUrl('review',{}).includes('status='));
const firstRenders=renders;
state.uiLanguage='en';s.renderReviewProgressFilter();
assert.equal(renders,firstRenders,'locale/async context refresh keeps the same popup and focus');
assert.equal(element('#reviewTaskProgressLabel').textContent,'Task status');
element('#reviewStatusFilter').values=['in_progress'];
element('#reviewTaskProgressFilter').values=['completed'];element('#reviewTaskProgressFilter').change(['completed']);
assert.deepEqual([...state.reviewTaskProgress],['completed']);assert.equal(reloads,1);
assert.deepEqual([...s.selectedModelReviewStatuses()],['in_progress']);
const independent = new URL(s.pageUrl('review',{}),s.window.location.origin).searchParams;
assert.equal(independent.get('status'),'in_progress');assert.equal(independent.get('task_progress'),'completed');
element('#reviewTaskProgressFilter').change([]);assert.equal(s.selectedCombinedTaskProgress().length,0);
assert.deepEqual([...s.selectedModelReviewStatuses()],['in_progress']);
const entry=s.reviewAssignmentRouteOptions({split_id:task,workflow_mode:'model_review_and_case_label',appendable:true,assigned_to_me:true},'review');
assert.equal(entry.taskView,'targets');assert.deepEqual([...entry.taskProgress],['pending']);
assert.deepEqual([...entry.workAssignee],['jasperchen']);
const route=s.normalizedReviewRouteFilters(new URLSearchParams('work_split='+task+'&task_view=pending'));
assert.equal(route.taskView,'targets');assert.deepEqual([...route.taskProgress],['pending']);
assert.deepEqual([...s.normalizedReviewRouteFilters(new URLSearchParams('work_split='+task+'&task_progress=completed')).taskProgress],['completed']);
// Reset must clear context and progress before any async reload; it must not
// leave the model picker locked or resurrect URL-backed owners.
Object.assign(s,{renderReviewTargetGroupPicker:()=>{},renderReviewWorkSplitPicker:()=>{}, persistReviewerFilterRoute:()=>{},persistWorkAssigneeFilterRoute:()=>{},
  setReviewComparisonStatus:()=>{}, renderAnalysisRunFilter:()=>{}, renderActiveRun:()=>{},renderRunManager:()=>{},
  reloadReviewGallery:async()=>{},showToast:()=>{}});
(async()=>{
  await s.resetReviewFilters();
  assert.equal(state.reviewWorkSplitId,'');assert.equal(state.reviewTaskView,'');
  assert.equal(state.reviewTaskContext,null);assert.equal(state.reviewTaskProgress.length,0);
  assert.equal(element('#reviewTaskProgressField').hidden,true);
  assert.equal(element('#reviewStatusFilter').values.length,0);
  element('#reviewStatusFilter').values=['in_progress'];
  assert.deepEqual([...s.selectedModelReviewStatuses()],['in_progress']);
  assert.equal(s.selectedCombinedTaskProgress().length,0);
  assert(!s.pageUrl('review',{}).includes('task_progress'));
  assert(!fs.readFileSync(path.join(root,'../index.html'),'utf8').includes('reviewTaskViewToggle'));
  console.log('Combined progress controls, domain isolation, entry, locale, URL and reset passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
