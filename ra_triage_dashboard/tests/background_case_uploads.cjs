const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = require('node:path').join(__dirname,'../static/js/');
const storage = new Map(), nodes = {};
const state = {activePage:'review',selectedCase:{issue_id:'A'},selectedId:'A',selectedRunId:'run',reviewWorkSplitId:'task',session:{username:'alice',verified:true},backgroundCaseUploads:new Map(),caseRationaleImages:new Map(),reviewUploadTail:Promise.resolve(),savingAnnotation:false};
let calls=[], deferred=[], contextReads=0, draft={case_rationale:'sent',saved_at:10}, failRefresh=false;
const s={state,console,Promise,Date,Map,Set,JSON,URL:{revokeObjectURL(){}},crypto:{randomUUID:()=> 'stable-key'},globalThis:null,
 window:{localStorage:{setItem(k,v){storage.set(k,v);draft=JSON.parse(v)},getItem:k=>storage.get(k)||null},setTimeout:fn=>fn()},
 document:{querySelectorAll:()=>[]},$:(id)=>nodes[id]||null,uiText:(zh,en)=>en,escapeHtml:String,showToast:()=>{},
 currentReviewRunId:()=>state.selectedRunId,reviewDraftReviewer:()=>state.session.username,
 reviewDraftStorageKey:(...x)=>x.join('|'),REVIEW_DRAFT_FIELDS:['case_rationale','note'],
 readReviewDraft:()=>draft,clearReviewDraft:()=>{draft=null},persistReviewDraft:()=>{},annotationTimestamp:()=>100,
 releasePreviewUrlLater:()=>{},acknowledgeLocalChange:()=>{},renderCombinedReviewContextStatus:()=>{},
 loadCombinedReviewContext:async()=>{contextReads++;if(failRefresh)throw new Error('refresh only')},
 FormData:class{constructor(){this.entries=[]}append(...x){this.entries.push(x)}},
 api:(path,options)=>{calls.push({path,options});return new Promise((resolve,reject)=>deferred.push({resolve,reject}))},
};s.globalThis=s;vm.createContext(s);
vm.runInContext(fs.readFileSync(root+'review-attachments.js','utf8'),s);
const tick=()=>new Promise(r=>setImmediate(r));
function task(issue='A'){
 const image={id:'image-'+issue,file:{name:'e.png'},previewUrl:'blob:'+issue};
 const t={key:[issue,'run','task','alice'].join('|'),issueId:issue,action:'combined-review',payload:{rationale:'sent',model_run_id:'run',campaign_id:'task'},headers:{'Idempotency-Key':'stable-key'},imageItems:[image],draftScope:[issue,'run','task','alice'],draft:{case_rationale:'sent',saved_at:10}};
 state.caseRationaleImages.set(t.key,[image]);state.backgroundCaseUploads.set(t.key,t);return t;
}
(async()=>{
 // Queue returns without a page-wide submit lock and duplicate enqueue is ignored.
 let t=task();let pending=s.enqueueCaseRationaleUpload(t);s.enqueueCaseRationaleUpload(t);await tick();
 assert.equal(state.savingAnnotation,false);assert.equal(calls.length,1);assert.equal(t.status,'uploading');
 // Switch Issue while uploading: no late context refresh, no overwrite of current form.
 state.selectedCase={issue_id:'B'};state.selectedId='B';state.reviewFormDirty=true;
 deferred.shift().resolve({combined_review:{model_review:{}}});await pending;
 assert.equal(contextReads,0);assert.equal(state.reviewFormDirty,true);assert.equal(state.selectedId,'B');assert(!state.backgroundCaseUploads.has(t.key));
 // A different Run/task/actor never inherits the original upload indicator.
 state.selectedCase={issue_id:'A'};state.selectedId='A';draft={case_rationale:'sent',saved_at:10};t=task();pending=s.enqueueCaseRationaleUpload(t);await tick();
 for(const field of ['selectedRunId','reviewWorkSplitId']){const old=state[field];state[field]='other';assert.equal(s.caseRationaleUploadTask(),null);state[field]=old}
 state.session.username='bob';assert.equal(s.caseRationaleUploadTask(),null);state.session.username='alice';
 // Failure retains files and frozen payload; retry must reuse its original idempotency key.
 deferred.shift().reject(new Error('response lost'));await pending;
 assert.equal(t.status,'failed');assert.equal(state.caseRationaleImages.get(t.key).length,1);
 draft={case_rationale:'new edit',saved_at:11};state.caseRationaleImages.get(t.key).push({id:'new',file:{name:'new.png'}});
 failRefresh=true;pending=s.enqueueCaseRationaleUpload(t);await tick();
 assert.equal(calls.at(-1).options.headers['Idempotency-Key'],'stable-key');
 assert.equal(JSON.parse(calls.at(-1).options.body.entries[0][1]).rationale,'sent');
 deferred.shift().resolve({combined_review:{model_review:{}}});await pending;
 assert.equal(t.status,'saved');assert.equal(draft.case_rationale,'new edit');assert(draft.saved_at>100);
 assert.equal(state.reviewFormDirty,true);assert.equal(state.caseRationaleImages.get(t.key)[0].id,'new');assert(!state.backgroundCaseUploads.has(t.key));
 // Changed-page callback does not refresh or navigate, even for the same Issue.
 failRefresh=false;draft={case_rationale:'sent',saved_at:10};t=task();pending=s.enqueueCaseRationaleUpload(t);await tick();
 state.activePage='labeling';const before=contextReads;deferred.shift().resolve({});await pending;assert.equal(contextReads,before);assert.equal(state.activePage,'labeling');
 // 409 is retained as conflict, exposing refresh rather than blind retries.
 state.activePage='review';draft={case_rationale:'sent',saved_at:10};t=task();pending=s.enqueueCaseRationaleUpload(t);await tick();deferred.shift().reject(Object.assign(new Error('conflict'),{status:409}));await pending;
 assert(t.conflict);assert.match(s.caseRationaleUploadMarkup(t),/data-refresh-case-upload/);assert.doesNotMatch(s.caseRationaleUploadMarkup(t),/data-retry-case-upload/);
 // Exercise the actual form entry: snapshot queued, no global lock, duplicate submit rejected.
 state.backgroundCaseUploads.clear();draft={case_rationale:'sent',saved_at:10};
 const image={id:'entry',file:{name:'e.png'}};state.caseRationaleImages.set('A|run|task|alice',[image]);
 vm.runInContext(fs.readFileSync(root+'review-form.js','utf8'),s);
 s.combinedReviewContextKey=()=> 'ctx';s.combinedReviewCampaignBinding=()=> 'task';s.reviewWorkSplitBinding=()=> 'task';s.expectedOutputSelectionState=()=>({selectedValue:'误触发'});s.reviewSaveNavigationContext=()=>({});s.modelReviewSubmissionStatus=()=> 'completed';s.renderCombinedReviewContextStatus=()=>{};
 state.combinedReviewContext={issue:{issue_id:'A'},campaign:{id:'task',evaluation_run_id:'run'},case_revision_id:4,model_review_storage_id:5};state.combinedReviewLoad={key:'ctx',status:'ready'};
 await s.saveCombinedReview({});assert.equal(state.savingAnnotation,false);assert.equal(state.backgroundCaseUploads.size,1);await tick();const count=calls.length;await s.saveCombinedReview({});assert.equal(calls.length,count);
 state.activePage='labeling';deferred.shift().resolve({});await state.reviewUploadTail;
 // Case-only images also use the queue and the Case endpoint, without inventing Run attribution.
 state.activePage='review';state.selectedRunId='';state.reviewWorkSplitId='';
 state.combinedReviewContext.campaign={id:'',evaluation_run_id:''};
 s.combinedReviewCampaignBinding=()=> '';s.reviewWorkSplitBinding=()=> '';
 state.caseRationaleImages.set('A|||alice',[{id:'case-only',file:{name:'e.png'}}]);
 await s.saveCombinedReview({});await tick();
 assert.equal(state.savingAnnotation,false);
 assert.match(calls.at(-1).path,/case-label-from-review-with-attachments$/);
 assert.equal(JSON.parse(calls.at(-1).options.body.entries[0][1]).model_run_id,undefined);
 state.activePage='labeling';deferred.shift().resolve({case_label:{}});await state.reviewUploadTail;
 console.log('Background Case uploads: nonblocking form, duplicate suppression, scope ownership, retained failure, stable-key retry, newer edits/images, conflict and refresh failure passed');
})().catch(e=>{console.error(e);process.exitCode=1});
