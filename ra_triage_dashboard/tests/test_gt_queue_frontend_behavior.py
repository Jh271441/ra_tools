"""GT is an inline percentage chart; normal summary navigation remains unchanged."""
from pathlib import Path
import shutil
import subprocess
import unittest


class GtQueueFrontendBehaviorTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_open_status_filter_relabels_without_rebuilding_or_changing_selection(self):
        root = Path(__file__).resolve().parents[1] / "static/js"
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const inputs=[{value:'incomplete',checked:true,dataset:{label:'Submitted · Incomplete'},nextElementSibling:{textContent:'Submitted · Incomplete'}}];
const root={dataset:{optionsFingerprint:'old'},classList:{contains:()=>true},querySelectorAll:()=>inputs,querySelector:()=>({})};
let updates=0;
Object.assign(global,{$:()=>root,updateMultiFilterSummary:()=>updates++,renderMultiFilter:()=>{throw new Error('must not rebuild')},setMultiFilterValues:()=>{throw new Error('must preserve selection')}});
function load(file,name){const text=fs.readFileSync(process.argv[1]+'/'+file,'utf8');const start=text.indexOf('function '+name+'(');const end=text.indexOf('\n}',start)+2;assert(start>=0);vm.runInThisContext(text.slice(start,end));}
load('core-base.js','relabelMultiFilter');
load('case-labeling.js','renderCaseLabelingMultiPicker');
load('labeling-summary.js','renderLabelSummaryMultiPicker');
const identity=inputs[0];
renderCaseLabelingMultiPicker('#status',[{value:'incomplete',label:'已提交 · 待补齐'}],['incomplete'],'status');
assert.equal(inputs[0],identity);assert.equal(inputs[0].checked,true);assert.equal(inputs[0].nextElementSibling.textContent,'已提交 · 待补齐');
renderLabelSummaryMultiPicker('#status',[{value:'incomplete',label:'Submitted · Incomplete'}],['incomplete'],'status');
assert.equal(inputs[0],identity);assert.equal(inputs[0].checked,true);assert.equal(inputs[0].dataset.label,'Submitted · Incomplete');assert.equal(updates,2);
assert.equal(relabelMultiFilter(root,[{value:'resolved',label:'Confirmed'}]),false);
assert.equal(inputs[0].dataset.label,'Submitted · Incomplete');
'''
        result = subprocess.run(["node", "-e", script, str(root)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_queue_rendering_routes_language_and_stale_responses(self):
        root = Path(__file__).resolve().parents[1] / "static/js"
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
function node(id){return {id,dataset:{},innerHTML:'',value:'',textContent:'',disabled:false,attrs:{},handlers:{},classList:{toggle(){},contains(){return false;}},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},addEventListener(k,fn){this.handlers[k]=fn;},querySelectorAll(){return [];},querySelector(){return null;}};}
const nodes=new Map(),missing=new Set();
const get=id=>missing.has(id)?null:(nodes.has(id)?nodes.get(id):(nodes.set(id,node(id)),nodes.get(id)));
const matrix=node('matrix');get('#labelSummaryConfusionMatrix').querySelector=()=>matrix;
const nav=[node('labelingSummaryNavButton')];
Object.assign(global,{
 $:get,state:{activePage:'labeling-summary',uiLanguage:'zh',colorTheme:'dark',selectedBaselineIds:['version-20261009'],session:{is_admin:false},reviewAnalysis:{page:2,pageSize:20}},
 document:{getElementById:id=>get('#'+id),querySelectorAll:()=>nav,activeElement:null},
 window:{location:{origin:'http://localhost',pathname:'/manual/labeling-summary',search:'?gt_update=ready&task=task-a&page=2'},clearTimeout(){},history:{state:{},replaceState(_,__,url){const next=new URL(url,'http://localhost');window.location.pathname=next.pathname;window.location.search=next.search;}}},
 getMultiFilterValues:()=>[],parseIssueIdsInput:()=>({ids:[]}),PAGE_ROUTES:{analysis:{path:'/review-analysis'},'labeling-summary':{path:'/labeling-summary',titleZh:'标注汇总',titleEn:'Labeling summary'},labeling:{path:'/case-labeling'},review:{path:'/review'}},
 withBase:path=>'/manual'+path,ISSUE_QUERY_ID_RE:/^[A-Za-z0-9_-]{3,128}$/,DEFAULT_CASE_PAGE_SIZE:20,CASE_PAGE_SIZES:[10,20,50,100],LABELS:['误触发','正确触发','无需协助'],
 uiText:(zh,en)=>state.uiLanguage==='en'?en:zh,escapeHtml:value=>String(value),formatTime:value=>value,labelBadge:value=>value,tagLabel:value=>value,evidenceLabel:value=>value,
 parseFilterList:value=>Array.isArray(value)?value:String(value||'').split(',').filter(Boolean),joinFilterList:value=>(value||[]).join(','),
 normalizeBaselineIds:value=>value,selectedBaselineQueryValue:()=>state.selectedBaselineIds.join(','),defaultBaselineIdsFromConfig:()=>['0508'],
 populateUiSelect(){},bindUiSelect(){},bindUiInfoPopovers(){},renderMultiFilter(){},relabelMultiFilter(){return false;},setMultiFilterValues(){},enhanceNativeUiSelect:el=>{assert(el);el.enhanced=true;},showToast(){},t:key=>key,
 buildAnalysisQueryParams:()=>new URLSearchParams({comparison:'all'}),
 bindAnalysisReviewStatusHover:el=>assert(el),bindAnalysisConfusionHover:el=>assert(el),bindAnalysisPieHover:el=>assert(el),clearAnalysisPieEnterAnimations:el=>assert(el),
});
vm.runInThisContext(fs.readFileSync(process.argv[3],'utf8'));
vm.runInThisContext(`bindAnalysisReviewStatusHover=()=>{};bindAnalysisConfusionHover=()=>{};bindAnalysisPieHover=()=>{};clearAnalysisPieEnterAnimations=()=>{};`);
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const filterHelper=fs.readFileSync(process.argv[5],'utf8');
const helperStart=filterHelper.indexOf('function renderLabelGtFilter(');
assert.ok(helperStart>=0);
vm.runInThisContext(filterHelper.slice(helperStart,filterHelper.indexOf('\n}',helperStart)+2));
vm.runInThisContext(fs.readFileSync(process.argv[2],'utf8'));
vm.runInThisContext(`
(async()=>{
restoreLabelSummaryRoute();
assert.equal(labelSummaryFilters.taskId,'task-a');assert.equal('gtUpdate' in labelSummaryFilters,false);
assert.deepEqual(normalizedCaseLabelingRouteFilters(new URLSearchParams('status=pending')).status,['unannotated','incomplete']);
assert.deepEqual(normalizedCaseLabelingRouteFilters(new URLSearchParams('status=incomplete,conflict,bad')).status,['incomplete','conflict']);
assert.deepEqual(labelingStatusFilterOptions().map(item=>item.value),['unannotated','incomplete','resolved','conflict']);
assert.deepEqual(labelingStatusFilterOptions({submittedOnly:true}).map(item=>item.value),['incomplete','resolved','conflict']);
const initialSearch=window.location.search;
window.location.search='?status=pending&author=alice';restoreLabelSummaryRoute({force:true});
assert.deepEqual(labelSummaryFilters.status,['incomplete']);
assert.equal(labelSummaryFilterPayload().status,'incomplete');
assert.equal(new URL(labelSummaryCaseUrl(), 'http://localhost').searchParams.get('status'),'incomplete');
window.location.search=initialSearch;restoreLabelSummaryRoute({force:true});
refreshLabelSummaryLanguage();assert.equal(labelSummaryFilters.taskId,'task-a');
const readyUrl=new URL(pageUrl('labeling-summary',labelSummaryRouteOptions()),'http://localhost');
assert.equal(readyUrl.searchParams.has('gt_update'),false);assert.equal(readyUrl.searchParams.get('page'),'2');assert.equal(readyUrl.searchParams.get('baselines'),'version-20261009');
const data={gt_update_counts:{all:7,ready:3,blocked:3},total:8,annotated:7,page:1,page_size:20,
  pairs:[{gt:'误触发',label:'误触发',count:1},{gt:'正确触发',label:'误触发',count:2}],
  matrix_exclusions:{missing_gt:1,unsupported_gt:1,no_final_label:3},
  matrix_gt_exclusions:[{label:null,count:1},{label:'out_of_scope',count:1}],
  items:[{issue_id:'cn101',label_state:'resolved',gt_label:'正确触发',expected_output:'误触发',rationales:['evidence']}]};
assert.deepEqual(labelSummaryGtChartItems(data).map(item=>item.count),[3,3,1]);
assert.deepEqual(labelSummaryGtChartItems(data).map(item=>item.color),['var(--chart-blue)','var(--chart-indigo)','var(--chart-teal)']);
const markup=labelSummaryGtChartMarkup(data);
assert.match(markup,/42.9%/);assert.match(markup,/14.3%/);assert.match(markup,/GT 待更新/);
assert.match(markup,/section-heading analysis-review-status-heading/);
assert.match(markup,/标注尚未齐备、来源冲突/);
const analysisMarkup=analysisGtChartMarkup(data,{prefix:'analysis'});
for(const [html,page] of [[markup,'case-labeling'],[analysisMarkup,'review']]){
 const links=Array.from(html.matchAll(/class="chart-detail-link"[^>]* href="([^"]+)"/g),m=>new URL(m[1],'http://localhost'));
 assert.deepEqual(links.map(u=>(page==='review'?new URLSearchParams(u.searchParams.get('analysis_scope')):u.searchParams).get('chart_gt')),['ready','blocked','aligned']);
 for(const u of links){
   assert.equal(u.pathname,'/manual/'+page);assert.equal(u.hash,'');
   assert.equal(u.searchParams.get('baselines'),'version-20261009');
   assert.equal(u.searchParams.has('page'),false);
   if(page==='case-labeling')assert.equal(u.searchParams.get('task'),'task-a');
 }
}
// Zero states must not shift the remaining slices onto another legend color.
for (const [ready,blocked,aligned] of [[281,0,374],[0,3,4],[3,4,0],[0,0,7],[0,7,0],[7,0,0],[0,0,0]]) {
  const sample={gt_update_counts:{all:ready+blocked+aligned,ready,blocked}};
  const items=analysisGtChartItems(sample);
  const svg=renderAnalysisPieSvg(items,{palette:items.map(item=>item.color),animatePies:false});
  for(const item of items){
    const path=[...svg.matchAll(/<path [^>]*>/g)].map(match=>match[0]).find(path=>path.includes('data-pie-key="'+item.key+'"'));
    if(item.count) {assert.ok(path);assert.ok(path.includes('fill="'+item.color+'"'));}
    else assert.equal(path,undefined);
  }
}
const categorical=renderAnalysisPieSvg([{key:'zero',count:0},{key:'b',count:1},{key:'c',count:2}],{palette:['red','green','blue']});
assert.match(categorical,/data-pie-key="b"[^>]*fill="green"/);
assert.match(categorical,/data-pie-key="c"[^>]*fill="blue"/);
renderAnalysisGtStatus(data);
assert.equal($('#analysisGtCardMount').innerHTML,analysisMarkup);
assert.equal(typeof $('#analysisGtRules').handlers.click,'function');

const empty=labelSummaryGtChartMarkup({gt_update_counts:{all:0,ready:0,blocked:0}});
assert.match(empty,/—/);assert.doesNotMatch(empty,/NaN|Infinity/);
renderLabelingSummary(data);
assert.match($('#labelSummaryContent').innerHTML,/id="labelSummaryGtChart"/);
assert.match($('#labelSummaryContent').innerHTML,/id="labelSummaryCaseList"/);
assert.match($('#labelSummaryContent').innerHTML,/analysis-cluster-grid/);
assert.match($('#labelSummaryContent').innerHTML,/GT × 标注结果/);
assert.ok($('#labelSummaryContent').innerHTML.includes('可比较 3 / 8 · 一致 1'));
assert.match($('#labelSummaryContent').innerHTML,/<span class="label-summary-matrix-counts">/);
assert.match($('#labelSummaryContent').innerHTML,/aria-expanded="false" aria-controls="labelSummaryMatrixInfo"/);
const matrixPopover=$('#labelSummaryContent').innerHTML.split('id="labelSummaryMatrixInfo"')[1];
assert.match(matrixPopover,/未纳入 5/);
for(const [label,count] of [['Null',1],['Out of scope',1],['无最终标注',3]]) {
  assert.ok(matrixPopover.includes('<span>'+label+'</span><b>'+count+'</b>'));
}
state.uiLanguage='en';
assert.match(labelSummaryMatrixCardMarkup(data),/Excluded 5/);
assert.match(labelSummaryMatrixCardMarkup(data),/No final label/);
assert.ok(labelSummaryMatrixCardMarkup({total:0}).includes('Comparable 0 / 0 · Matches 0'));
assert.doesNotMatch(labelSummaryMatrixCardMarkup({total:0}),/labelSummaryMatrixInfo/);
state.uiLanguage='zh';
assert.doesNotMatch($('#labelSummaryContent').innerHTML,/data-gt-update-view/);
assert.equal($('#labelSummaryPageSize').enhanced,true);
state.uiLanguage='en';labelSummaryTasks=[{id:'task-a',name:'Task A'}];labelSummaryData=data;refreshLabelSummaryLanguage();
assert.equal(labelingStatusFilterOptions()[1].label,'Submitted · Incomplete');
assert.match($('#labelSummaryContent').innerHTML,/Matches GT/);assert.equal(labelSummaryFilters.taskId,'task-a');
renderAnalysisGtStatus(data);
assert.match($('#analysisGtCardMount').innerHTML,/Matches GT/);
assert.match($('#analysisGtCardMount').innerHTML,/Current filters · 7 Issue annotations/);
assert.doesNotMatch($('#analysisGtCardMount').innerHTML,/需确认/);
assert.equal(state.activePage,'labeling-summary');

assert.equal('gt_update' in labelSummaryFilterPayload(),false);
const originalLoader=loadLabelingSummary;loadLabelingSummary=async()=>{};
$('#labelSummaryReset').handlers.click();loadLabelingSummary=originalLoader;
assert.equal(labelSummaryFilters.taskId,'');
window.location.search='?gt_update=ready&q=cn101';restoreLabelSummaryRoute({force:true});
assert.equal(labelSummaryFilters.search,'cn101');assert.equal('gtUpdate' in labelSummaryFilters,false);
assert.doesNotMatch(fs.readFileSync(process.argv[4],'utf8'),/id="gtUpdatesNavButton"/);
let resolveSummary;
api=async path=>path.includes('/tasks?')?{items:[]}:new Promise(resolve=>resolveSummary=resolve);
const loading=loadLabelingSummary();await new Promise(setImmediate);
state.activePage='labeling';$('#labelSummaryContent').innerHTML='newer page';resolveSummary(data);await loading;
assert.equal($('#labelSummaryContent').innerHTML,'newer page');
})().catch(error=>{console.error(error);process.exitCode=1;});
`);
'''
        result = subprocess.run(["node", "-e", script, str(root / "routing.js"), str(root / "labeling-summary.js"), str(root / "analysis-charts.js"), str(root.parent / "index.html"), str(root / "session-config.js")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
