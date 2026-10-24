"""GT is an inline percentage chart; normal summary navigation remains unchanged."""
from pathlib import Path
import shutil
import subprocess
import unittest


class GtQueueFrontendBehaviorTest(unittest.TestCase):
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
 $:get,state:{activePage:'labeling-summary',uiLanguage:'zh',colorTheme:'dark',selectedBaselineIds:['version-20261009'],session:{is_admin:false}},
 document:{getElementById:id=>get('#'+id),querySelectorAll:()=>nav,activeElement:null},
 window:{location:{origin:'http://localhost',pathname:'/manual/labeling-summary',search:'?gt_update=ready&task=task-a&page=2'},clearTimeout(){},history:{state:{},replaceState(_,__,url){const next=new URL(url,'http://localhost');window.location.pathname=next.pathname;window.location.search=next.search;}}},
 PAGE_ROUTES:{'labeling-summary':{path:'/labeling-summary',titleZh:'标注汇总',titleEn:'Labeling summary'},labeling:{path:'/case-labeling'},review:{path:'/review'}},
 withBase:path=>'/manual'+path,ISSUE_QUERY_ID_RE:/^[A-Za-z0-9_-]{3,128}$/,DEFAULT_CASE_PAGE_SIZE:20,CASE_PAGE_SIZES:[10,20,50,100],LABELS:['误触发','正确触发','无需协助'],
 uiText:(zh,en)=>state.uiLanguage==='en'?en:zh,escapeHtml:value=>String(value),formatTime:value=>value,labelBadge:value=>value,tagLabel:value=>value,evidenceLabel:value=>value,
 parseFilterList:value=>Array.isArray(value)?value:String(value||'').split(',').filter(Boolean),joinFilterList:value=>(value||[]).join(','),
 normalizeBaselineIds:value=>value,selectedBaselineQueryValue:()=>state.selectedBaselineIds.join(','),defaultBaselineIdsFromConfig:()=>['0508'],
 populateUiSelect(){},bindUiSelect(){},renderMultiFilter(){},setMultiFilterValues(){},enhanceNativeUiSelect:el=>{assert(el);el.enhanced=true;},showToast(){},t:key=>key,
 bindAnalysisReviewStatusHover:el=>assert(el),bindAnalysisConfusionHover:el=>assert(el),bindAnalysisPieHover:el=>assert(el),clearAnalysisPieEnterAnimations:el=>assert(el),
});
vm.runInThisContext(fs.readFileSync(process.argv[3],'utf8'));
vm.runInThisContext(`bindAnalysisReviewStatusHover=()=>{};bindAnalysisConfusionHover=()=>{};bindAnalysisPieHover=()=>{};clearAnalysisPieEnterAnimations=()=>{};`);
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
vm.runInThisContext(fs.readFileSync(process.argv[2],'utf8'));
vm.runInThisContext(`
(async()=>{
restoreLabelSummaryRoute();
assert.equal(labelSummaryFilters.taskId,'task-a');assert.equal('gtUpdate' in labelSummaryFilters,false);
refreshLabelSummaryLanguage();assert.equal(labelSummaryFilters.taskId,'task-a');
const readyUrl=new URL(pageUrl('labeling-summary',labelSummaryRouteOptions()),'http://localhost');
assert.equal(readyUrl.searchParams.has('gt_update'),false);assert.equal(readyUrl.searchParams.get('page'),'2');assert.equal(readyUrl.searchParams.get('baselines'),'version-20261009');
const data={gt_update_counts:{all:7,ready:3,blocked:3},annotated:7,page:1,page_size:20,items:[{issue_id:'cn101',label_state:'resolved',gt_label:'正确触发',expected_output:'误触发',rationales:['evidence']}]};
assert.deepEqual(labelSummaryGtChartItems(data).map(item=>item.count),[3,3,1]);
const markup=labelSummaryGtChartMarkup(data);
assert.match(markup,/42.9%/);assert.match(markup,/14.3%/);assert.match(markup,/GT 待更新/);
const empty=labelSummaryGtChartMarkup({gt_update_counts:{all:0,ready:0,blocked:0}});
assert.match(empty,/—/);assert.doesNotMatch(empty,/NaN|Infinity/);
renderLabelingSummary(data);
assert.match($('#labelSummaryContent').innerHTML,/id="labelSummaryGtChart"/);
assert.match($('#labelSummaryContent').innerHTML,/id="labelSummaryCaseList"/);
assert.match($('#labelSummaryContent').innerHTML,/analysis-cluster-grid/);
assert.match($('#labelSummaryContent').innerHTML,/GT × 标注结果/);
assert.doesNotMatch($('#labelSummaryContent').innerHTML,/data-gt-update-view/);
assert.equal($('#labelSummaryPageSize').enhanced,true);
state.uiLanguage='en';labelSummaryTasks=[{id:'task-a',name:'Task A'}];labelSummaryData=data;refreshLabelSummaryLanguage();
assert.match($('#labelSummaryContent').innerHTML,/Matches GT/);assert.equal(labelSummaryFilters.taskId,'task-a');
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
        result = subprocess.run(["node", "-e", script, str(root / "routing.js"), str(root / "labeling-summary.js"), str(root / "analysis.js"), str(root.parent / "index.html")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
