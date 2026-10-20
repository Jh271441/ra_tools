const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root='ra_triage_dashboard/static/js/';
const elements={combinedReviewContextStatus:{dataset:{},innerHTML:'',querySelector(){return this.innerHTML.includes('data-retry-combined-context')?{addEventListener:(_type,fn)=>{this.retry=fn;}}:null;}},reviewSaveButton:{disabled:false},annotationForm:{dataset:{}}};
const state={activePage:'review',pageNavigationEpoch:1,selectedRunId:'run',reviewWorkSplitId:'campaign',session:{username:'liangxianghui',verified:true,access_role:'writer'},reviewFormDirty:false};
const data={issue_id:'cn1',review_assignment:{assigned:true,split_id:'campaign',purpose:'model_review',workflow_mode:'model_review_and_case_label',model_run_id:'run'}};state.selectedCase=data;
const context={issue:{issue_id:'cn1'},campaign:{id:'campaign',evaluation_run_id:'run'},assigned:true};
const s={state,URLSearchParams,URL,window:{location:{pathname:'/manual/review',search:'?issue=cn1'}},$:key=>elements[key.slice(1)]||null,uiText:x=>x,escapeHtml:String,hasDashboardWriteRole:()=>true,showToast:()=>{}};
vm.createContext(s);for(const name of ['routing.js','review-draft.js','review-form.js'])vm.runInContext(fs.readFileSync(root+name,'utf8'),s);
let paints=0;s.populateCombinedCaseLabel=()=>{paints++;};
(async()=>{
 let resolve;s.api=()=>new Promise(r=>{resolve=r;});
 let pending=s.loadCombinedReviewContext(data);assert(elements.reviewSaveButton.disabled);assert.equal(state.combinedReviewLoad.status,'loading');
 resolve({context});await pending;assert.equal(paints,1);assert(!elements.reviewSaveButton.disabled);assert(elements.combinedReviewContextStatus.hidden);
 // A failed read stays blocked and explains the actual failure, with a working retry.
 s.api=async()=>{throw new Error('请求超时');};
 await assert.rejects(s.loadCombinedReviewContext(data),/请求超时/);
 assert.equal(state.combinedReviewLoad.status,'error');assert.equal(state.combinedReviewContext,null);
 assert(elements.reviewSaveButton.disabled);assert(elements.combinedReviewContextStatus.innerHTML.includes('请求超时'));assert.equal(typeof elements.combinedReviewContextStatus.retry,'function');
 // Retry preserves typed or restored draft fields, but refreshes optimistic-lock context.
 state.reviewFormDirty=true;s.api=async()=>({context});
 await elements.combinedReviewContextStatus.retry();await new Promise(r=>setImmediate(r));
 assert.equal(state.combinedReviewContext,context);assert.equal(paints,1);assert(!elements.reviewSaveButton.disabled);
 elements.annotationForm.dataset.expectedOutputConflict='1';s.renderCombinedReviewContextStatus();assert(elements.reviewSaveButton.disabled);elements.annotationForm.dataset.expectedOutputConflict='0';
 // Namespace and navigation changes must reject late success/failure.
 for(const change of [()=>{state.reviewWorkSplitId='other';},()=>{state.session.username='jasperchen';},()=>{state.pageNavigationEpoch++;state.activePage='labeling';}]){
   state.reviewWorkSplitId='campaign';state.session.username='liangxianghui';state.activePage='review';
   s.api=()=>new Promise(r=>{resolve=r;});pending=s.loadCombinedReviewContext(data);change();resolve({context});await pending;
   assert.equal(state.combinedReviewContext,null);assert.equal(paints,1);
 }
 state.activePage='review';state.reviewWorkSplitId='campaign';state.session.username='liangxianghui';
 // A mismatched assignment must report the problem rather than perform an unbound request.
 state.selectedCase={...data,review_assignment:{...data.review_assignment,assigned:false}};
 let calls=0;s.api=async()=>{calls++;};await assert.rejects(s.loadCombinedReviewContext(state.selectedCase),/未分配/);assert.equal(calls,0);assert.equal(state.combinedReviewLoad.status,'error');
 // Valid out-of-task submissions keep their separate namespace.
 state.reviewWorkSplitId='';state.selectedCase=data;state.reviewFormDirty=false;
 s.api=async path=>{assert(!path.includes('campaign_id='));return {context:{...context,campaign:{...context.campaign,id:''}}};};
 await s.loadCombinedReviewContext(data);assert.equal(paints,2);assert(!elements.reviewSaveButton.disabled);
 console.log('combined context loading, error/retry, draft preservation, ownership and free-mode passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
