const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.join(__dirname,'../static/js'), elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{values:[],value:'',dataset:{},querySelector:()=>null});return elements.get(id);}
const state={activePage:'review',reviewIssueTags:['construction_change','intent_u_turn'],selectedBaselineIds:['0508'],reviewAnalysis:{},session:{}};
const s={state,console,URL,URLSearchParams, window:{location:{origin:'http://fixture.test',pathname:'/review',search:''},history:{replaceState(){}}},
 PAGE_ROUTES:{review:{path:'/review'}},withBase:x=>x,$:element,
 getMultiFilterValues:e=>e?.values||[],setMultiFilterValues:(e,v)=>{if(e)e.values=v||[];},
 parseFilterList:x=>Array.isArray(x)?[...new Set(x)]:[...new Set(String(x||'').split(',').filter(Boolean))],joinFilterList:x=>(x||[]).join(','),
 comparisonStatusParam:x=>x||'all', GT_FILTER_VALUES:['out_of_scope'],MODEL_LABELS:[],CASE_PAGE_SIZES:[20],DEFAULT_CASE_PAGE_SIZE:20,
 selectedBaselineQueryValue:()=> '0508',normalizeBaselineIds:x=>x||['0508'],defaultBaselineIdsFromConfig:()=>['0508'],uiText:(zh,en)=>state.uiLanguage==='en'?en:zh,t:x=>x};
vm.createContext(s);
for(const file of ['routing.js','runs.js','work-split.js','review-gallery.js','review-assignments.js','import-refresh.js'])vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),s);
s.selectedCombinedTaskProgress=()=>[];s.selectedModelReviewStatuses=()=>[];s.selectedReviewComparisonStatus=()=> 'all';
const url=s.pageUrl('review',s.currentReviewRouteOptions());
const route=s.normalizedReviewRouteFilters(new URL(url,'http://fixture.test').searchParams);
assert.deepEqual([...route.issueTags],state.reviewIssueTags);
assert.equal(s.currentReviewFilterPayload().issue_tags,'construction_change,intent_u_turn');
assert.equal(s.currentReviewGalleryExportParams().get('issue_tags'),'construction_change,intent_u_turn');
assert(!s.reviewAssignmentRouteOptions({},'review').issueTags.length,'fresh task must not inherit tag filter');
assert(new URL(s.reviewAssignmentSourceHref({issue_tags:['gate']}),'http://fixture.test').searchParams.get('issue_tags')==='gate');
// Exact URL keys survive catalog arrival; unknown values must not become an unfiltered link.
const independent=s.normalizedReviewRouteFilters(new URLSearchParams('issue_tags=not-loaded,gate&gt=out_of_scope'));
assert.deepEqual([...independent.issueTags],['not-loaded','gate']);
assert.deepEqual([...independent.gtLabel],['out_of_scope']);
Object.assign(s,{persistReviewerFilterRoute(){},persistWorkAssigneeFilterRoute(){},setReviewComparisonStatus(){},
 showToast(){},clearReviewTaskContext(){},renderAnalysisRunFilter(){},renderActiveRun(){},renderRunManager(){},reloadReviewGallery:async()=>{}});
(async()=>{await s.resetReviewFilters();assert.equal(state.reviewIssueTags.length,0);assert(!s.currentReviewGalleryExportParams().has('issue_tags'));console.log('PASS Issue tag route, export, assignment and reset');})().catch(e=>{console.error(e);process.exitCode=1;});
