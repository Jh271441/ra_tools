from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is required')
class ReviewIssueDecisionBehaviorTest(unittest.TestCase):
    def test_summary_entry_keeps_compact_label_and_single_existing_trigger(self):
        source = Path(__file__).resolve().parents[1] / 'static/js/review-label-state.js'
        body = source.read_text().split('if (summaryOnly) {', 1)[1].split('\n  }', 1)[0]
        self.assertIn('ui-lang-zh">汇总</span>', body)
        self.assertIn('ui-lang-en">Summary</span>', body)
        self.assertIn('aria-keyshortcuts="L"', body)
        self.assertEqual(body.count('<button '), 1)

    def test_locale_refresh_relabels_original_controls_without_changing_drafts(self):
        source = Path(__file__).resolve().parents[1] / 'static/js/review-form.js'
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const body=source.slice(source.indexOf('function refreshReviewFormLanguage()'),source.indexOf('function renderReviewSummary('));
const draft={value:'unsaved personal text'},label={textContent:'环境'},creator={dataset:{},setAttribute(k,v){this[k]=v}},shortcut={textContent:'Q'};
const status={value:'in_progress',disabled:true,options:[{value:'in_progress',textContent:'待复核'},{value:'completed',textContent:'已完成'}]};
const dropdown={querySelector:s=>s==='.tag-group-label'?label:s==='[data-open-review-tag-creator]'?creator:shortcut};
let mounted=true,locale='en',placed=0,enhanced=0;
const root={querySelector:s=>s==='#annotationForm'?(mounted?draft:null):s==='#modelReviewStatusInput'?status:null,querySelectorAll:()=>[dropdown]};
Object.assign(global,{$:()=>root,MODEL_REVIEW_STATUS_OPTIONS:[{value:'in_progress',labelZh:'待复核',labelEn:'Needs review'},{value:'completed',labelZh:'已完成',labelEn:'Completed'}],uiText:(zh,en)=>locale==='en'?en:zh,
applyDomI18n:r=>{assert.equal(r,root);label.textContent=locale==='en'?'Environment':'环境'},applyI18nPlaceholders(){},
updateTagSummary(){},updateEvidenceSummary(){},renderCombinedReviewContextStatus(){},
syncReviewTagCreatorPlacement:r=>{assert.equal(r,root);placed++},enhanceNativeUiSelect:n=>{assert.equal(n,status);enhanced++},enhanceDashboardSelects:r=>assert.equal(r,root)});
vm.runInThisContext(body);refreshReviewFormLanguage();
assert.equal(label.textContent,'Environment');assert.equal(creator['aria-label'],'Add Environment tag');assert.equal(status.options[0].textContent,'Needs review');assert.equal(shortcut.title,'Press Q to toggle');
assert.equal(status.value,'in_progress');assert.equal(status.disabled,true);assert.equal(draft.value,'unsaved personal text');assert.equal(placed,1);assert.equal(enhanced,1);
locale='zh';refreshReviewFormLanguage();assert.equal(label.textContent,'环境');assert.equal(status.options[0].textContent,'待复核');
mounted=false;refreshReviewFormLanguage();assert.equal(placed,2);
'''
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_async_ownership_and_original_nodes_survive(self):
        source = Path(__file__).resolve().parents[1] / 'static/js/review-issue-decision.js'
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class Node {
 constructor(name){this.name=name;this.childNodes=[];this.scrollTop=91;this.classes=new Set();this.classList={add:k=>this.classes.add(k),remove:k=>this.classes.delete(k)};}
 replaceChildren(...nodes){for(const n of this.childNodes)n.parentNode=null;this.childNodes=[];for(const n of nodes){if(n.parentNode)n.parentNode.childNodes=n.parentNode.childNodes.filter(x=>x!==n);n.parentNode=this;this.childNodes.push(n);}}
 insertBefore(node,next){const nodes=this.childNodes.filter(x=>x!==node),i=next?nodes.indexOf(next):nodes.length;nodes.splice(i,0,node);this.replaceChildren(...nodes);}
 get nextSibling(){const a=this.parentNode?.childNodes||[];return a[a.indexOf(this)+1]||null;}
}
const pane=new Node('review'),editor=new Node('editor'),parent=new Node('labeling'),next=new Node('sibling');
const reviewForm=new Node('review draft'),labelForm=new Node('label draft'),media=new Node('media');
reviewForm.value='unsaved personal/model rationale';editor.replaceChildren(labelForm);parent.replaceChildren(editor,next);pane.replaceChildren(reviewForm);
const labeling={issueId:'other',pendingImages:['label image'],dirty:true},current={issue_id:'cn1',annotations:['model'],media};
let baseline='0508',epoch=1,writable=true,resolveApi,opens=[],loads=[],aborted=0,focused=0,relabeled=0;
Object.assign(global,{state:{activePage:'review',selectedId:'cn1',selectedCase:current,caseLabeling:labeling,session:{username:'alice'},reviewFormDirty:true,selectedRunId:'run',reviewWorkSplitId:'task',cases:[{issue_id:'cn1'}],caseDetailPrefetch:new Map([['old',{controller:{abort(){aborted++}}}]])},
caseLabelDecisionUi:{saving:false,editor:null,context:{}},$:s=>s==='#reviewPane'?pane:s==='#caseLabelingEditor'?editor:s.includes('data-open-shared')?{focus(){focused++}}:null,
hasDashboardWriteRole:()=>writable,capturePageContext:()=>({epoch}),isPageContextCurrent:c=>c.epoch===epoch,
selectedBaselineQueryValue:()=>baseline,withBaselineQuery:p=>p,api:()=>new Promise(r=>resolveApi=r),
openCaseLabelDecision:data=>{opens.push(data);caseLabelDecisionUi.context={caseData:data}},openSharedLabelStateDialog(){throw Error('unexpected readonly fallback')},showToast(){},renderReviewSummary(){},
refreshReviewFormLanguage(){assert.equal(pane.childNodes[0],reviewForm);relabeled++;},
loadCombinedReviewContext:async(data,options)=>loads.push({data,options})});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const opener={setAttribute(){},removeAttribute(){}};
(async()=>{
 let pending=openReviewIssueDecision(current,opener);epoch++;resolveApi(current);await pending;assert.equal(opens.length,0);
 pending=openReviewIssueDecision(current,opener);baseline='1009';resolveApi(current);await pending;assert.equal(opens.length,0);
 pending=openReviewIssueDecision(current,opener);state.session.username='bob';resolveApi(current);await pending;assert.equal(opens.length,0);
 const first=openReviewIssueDecision(current,opener),releaseFirst=resolveApi;
 pending=openReviewIssueDecision(current,opener);resolveApi(current);await pending;releaseFirst(current);await first;assert.equal(opens.length,1);
 writable=false;await openReviewIssueDecision(current,opener);assert.equal(opens.length,1);writable=true;
 const host=mountReviewDecisionEditor(current);assert.equal(pane.childNodes[0],editor);assert.equal(host.reviewNodes[0],reviewForm);assert.notEqual(state.caseLabeling,labeling);assert.equal(state.caseLabeling.taskId,'');
 editor.replaceChildren(new Node('decision'));restoreReviewDecisionEditor(host);assert.equal(relabeled,1);
 assert.equal(pane.childNodes[0],reviewForm);assert.equal(editor.childNodes[0],labelForm);assert.equal(parent.childNodes[0],editor);assert.equal(parent.childNodes[1],next);assert.equal(reviewForm.value,'unsaved personal/model rationale');assert.equal(state.caseLabeling,labeling);assert.equal(state.reviewFormDirty,true);assert.equal(focused,1);assert.equal(pane.scrollTop,91);
 state.combinedReviewContext={};const fresh={issue_id:'cn1',label_state:{state:'resolved'},exclusion_summary:{is_excluded:false}};
 await refreshReviewDecisionResult(fresh);assert.equal(current.media,media);assert.deepEqual(current.annotations,['model']);assert.equal(state.selectedRunId,'run');assert.equal(state.reviewWorkSplitId,'task');assert.equal(current.exclusion_summary.is_excluded,false);assert.equal(aborted,1);assert.equal(state.caseDetailPrefetch.size,0);assert.equal(loads[0].options.preserveForm,true);assert.equal(reviewForm.value,'unsaved personal/model rationale');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_dialog_cannot_enter_editor_and_review_drafts_are_scoped(self):
        source = Path(__file__).resolve().parents[1] / 'static/js/case-label-decision.js'
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let current=false,baseline='0508',mounted=0;
Object.assign(global,{state:{activePage:'review',selectedId:'cn1',selectedRunId:'run1',reviewWorkSplitId:'task',session:{username:'alice'},caseLabeling:{}},hasDashboardWriteRole:()=>true,isPageContextCurrent:()=>current,selectedBaselineQueryValue:()=>baseline,mountReviewDecisionEditor(){mounted++;throw Error('unexpected mount')}});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const data={issue_id:'cn1'};caseLabelDecisionUi.context={pageContext:{},baselines:'0508',actor:'alice'};
startCaseDecisionEditor(data);current=true;baseline='1009';startCaseDecisionEditor(data);baseline='0508';state.session.username='bob';startCaseDecisionEditor(data);assert.equal(mounted,0);
const key=caseDecisionDraftKey(data);state.selectedRunId='run2';assert.notEqual(caseDecisionDraftKey(data),key);state.selectedRunId='run1';state.activePage='labeling';assert.notEqual(caseDecisionDraftKey(data),key);
'''
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
