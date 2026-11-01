const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root='ra_triage_dashboard/static/js/';
const elements={combinedReviewContextStatus:{dataset:{},innerHTML:'',querySelector(){return this.innerHTML.includes('data-retry-combined-context')?{addEventListener:(_type,fn)=>{this.retry=fn;}}:null;}},reviewSaveButton:{disabled:false},reviewExcludeInput:{checked:false,disabled:true},annotationForm:{dataset:{},querySelectorAll:()=>[]}};
const state={activePage:'review',pageNavigationEpoch:1,selectedRunId:'run',reviewWorkSplitId:'campaign',session:{username:'liangxianghui',verified:true,access_role:'writer'},reviewFormDirty:false};
const data={issue_id:'cn1',review_assignment:{assigned:true,split_id:'campaign',purpose:'model_review',workflow_mode:'model_review_and_case_label',model_run_id:'run'}};state.selectedCase=data;
const context={issue:{issue_id:'cn1'},campaign:{id:'campaign',evaluation_run_id:'run'},assigned:true};
const s={state,URLSearchParams,URL,window:{location:{pathname:'/manual/review',search:'?issue=cn1'}},$:key=>elements[key.slice(1)]||null,uiText:x=>x,escapeHtml:String,hasDashboardWriteRole:()=>true,showToast:()=>{}};
vm.createContext(s);for(const name of ['routing.js','review-draft.js','review-attachments.js','review-form.js'])vm.runInContext(fs.readFileSync(root+name,'utf8'),s);
let draft=null;s.reviewDraftForCase=()=>draft;
let paints=0;s.populateCombinedCaseLabel=(_context,_data,options)=>{if(!options?.preserveFields?.has('tags'))paints++;};
(async()=>{
 let resolve;s.api=()=>new Promise(r=>{resolve=r;});
 let pending=s.loadCombinedReviewContext(data);assert(elements.reviewSaveButton.disabled);assert.equal(state.combinedReviewLoad.status,'loading');
 resolve({context});await pending;assert.equal(paints,1);assert(!elements.reviewSaveButton.disabled);assert(!elements.reviewExcludeInput.disabled);assert(elements.combinedReviewContextStatus.hidden);
 // A failed read stays blocked and explains the actual failure, with a working retry.
 s.api=async()=>{throw new Error('请求超时');};
 await assert.rejects(s.loadCombinedReviewContext(data),/请求超时/);
 assert.equal(state.combinedReviewLoad.status,'error');assert.equal(state.combinedReviewContext,null);
 assert(elements.reviewSaveButton.disabled);assert(elements.reviewExcludeInput.disabled);assert(elements.combinedReviewContextStatus.innerHTML.includes('请求超时'));assert.equal(typeof elements.combinedReviewContextStatus.retry,'function');
 // Retry preserves typed or restored draft fields, but refreshes optimistic-lock context.
 state.reviewFormDirty=true;s.api=async()=>({context});
 await elements.combinedReviewContextStatus.retry();await new Promise(r=>setImmediate(r));
 assert.equal(state.combinedReviewContext,context);assert.equal(paints,1);assert(!elements.reviewSaveButton.disabled);
 assert(!elements.reviewExcludeInput.disabled);
 // Early edits without a Case flag still hydrate the server's true exclusion.
 context.case_revision={is_excluded:true};draft={note:'early edit'};
 await s.loadCombinedReviewContext(data);assert(elements.reviewExcludeInput.checked);assert(!elements.reviewExcludeInput.disabled);
 // Restored false and true Case drafts survive; unrelated fields are never repainted.
 for(const value of [false,true]) {
   draft={case_is_excluded:value,note:'retain note'};
   await s.loadCombinedReviewContext(data);assert.equal(elements.reviewExcludeInput.checked,value);assert(!elements.reviewExcludeInput.disabled);assert.equal(paints,1);
 }
 // Loading, failed reads and readonly roles block both mouse and K activation.
 state.session.read_only=true;s.renderCombinedReviewContextStatus();assert(elements.reviewExcludeInput.disabled);
 state.session.read_only=false;s.hasDashboardWriteRole=()=>false;s.renderCombinedReviewContextStatus();assert(elements.reviewExcludeInput.disabled);
 s.hasDashboardWriteRole=()=>true;s.renderCombinedReviewContextStatus();assert(!elements.reviewExcludeInput.disabled);
 draft=null;
 elements.annotationForm.dataset.expectedOutputConflict='1';s.renderCombinedReviewContextStatus();assert(elements.reviewSaveButton.disabled);elements.annotationForm.dataset.expectedOutputConflict='0';
 // Namespace and navigation changes must reject late success/failure.
 for(const change of [()=>{state.reviewWorkSplitId='other';},()=>{state.session.username='jasperchen';},()=>{state.pageNavigationEpoch++;state.activePage='labeling';}]){
   state.reviewWorkSplitId='campaign';state.session.username='liangxianghui';state.activePage='review';
   s.api=()=>new Promise(r=>{resolve=r;});pending=s.loadCombinedReviewContext(data);assert(elements.reviewExcludeInput.disabled);change();resolve({context});await pending;
   assert.equal(state.combinedReviewContext,null);assert.equal(paints,1);
 }
 state.activePage='review';state.reviewWorkSplitId='campaign';state.session.username='liangxianghui';
 // Known non-assignees may supplement in the free stream; broken scope cannot.
 state.selectedCase={...data,review_assignment:{...data.review_assignment,assigned:false}};
 s.api=async path=>{assert(!path.includes('campaign_id='));return {context:{...context,campaign:{...context.campaign,id:''}}};};
 await s.loadCombinedReviewContext(state.selectedCase);assert.equal(state.combinedReviewContext.campaign.id,'');
 // Submission retains the page task while writing the separate free namespace.
 let submitted;
 s.reviewSaveNavigationContext=()=>({});s.acknowledgeLocalChange=()=>{};s.refreshReviewAfterSave=async()=>{};s.renderReview=()=>{};
 s.expectedOutputSelectionState=()=>({selectedValue:'误触发',conflictKind:''});s.document={querySelectorAll:()=>[]};
 s.api=async (path,options)=>{
  if(options?.method==='POST'){submitted=JSON.parse(options.body);return {combined_review:{}};}
  return {context:{...context,campaign:{...context.campaign,id:''}}};
 };
 elements.reviewSaveButton.setAttribute=()=>{};elements.reviewSaveButton.removeAttribute=()=>{};
 await s.saveCombinedReview({});assert.equal(submitted.campaign_id,'');assert.equal(submitted.work_split_id,'');assert.equal(submitted.author,'liangxianghui');assert.equal(state.reviewWorkSplitId,'campaign');
 state.selectedCase={...data,review_assignment:{...data.review_assignment,assigned:false,model_run_id:'wrong'}};
 let calls=0;s.api=async()=>{calls++;};await assert.rejects(s.loadCombinedReviewContext(state.selectedCase),/上下文/);assert.equal(calls,0);assert.equal(state.combinedReviewLoad.status,'error');
 // Valid out-of-task submissions keep their separate namespace.
 state.reviewWorkSplitId='';state.selectedCase=data;state.reviewFormDirty=false;
 s.api=async path=>{assert(!path.includes('campaign_id='));return {context:{...context,campaign:{...context.campaign,id:''}}};};
 await s.loadCombinedReviewContext(data);assert.equal(paints,3);assert(!elements.reviewSaveButton.disabled);
 console.log('combined context loading, error/retry, draft preservation, ownership and free-mode passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
