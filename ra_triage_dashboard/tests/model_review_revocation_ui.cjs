const fs=require('fs'), vm=require('vm'), assert=require('assert');
const sandbox={
 state:{session:{username:'alice'},selectedId:'cn1',caseRequestSeq:1,caseDetailPrefetch:new Map(),reviewFormDirty:false},
 annotationExpectedOutput:()=>'',hasDashboardWriteRole:()=>true,
 escapeHtml:String,reviewStatusLabel:String,reviewRunLabel:String,formatTime:String,
 labelBadge:String,uiText:(x)=>x,window:{confirm:()=>true},
 reviewAnnotationsForAllRuns:(c)=>c.annotations,currentReviewAnnotation:(c)=>c.annotations[0],
 acknowledgeLocalChange:()=>{},caseCorePath:()=>'/api/cases/cn1',
 clearReviewDraft:()=>{},currentReviewRunId:()=> 'run', reviewWorkSplitBinding:()=> 'task',
 syncReviewFormFromCase:()=>{},effectiveReviewWorkflowMode:()=> 'model_review_only',
 updateReviewHistory:()=>{},showToast:()=>{},refreshReviewDerivedData:()=>{},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/review-history.js','utf8'),sandbox);
// Override DOM-dependent helpers only after loading real history rendering/handlers.
sandbox.updateReviewHistory=()=>{};sandbox.refreshReviewDerivedData=()=>{};
const a={id:4000000000000001,author:'alice',model_run_id:'run',campaign_id:'task',reference_id:'ref',review_domain:'model_review',created_at:'now'};
assert(sandbox.annotationHistory([a]).includes('data-delete-annotation'));
sandbox.state.session.username='bob';assert(!sandbox.annotationHistory([a]).includes('data-delete-annotation'));
sandbox.state.session.is_admin=true;assert(sandbox.annotationHistory([a]).includes('data-delete-annotation'));
sandbox.state.session={username:'alice'};
assert(!sandbox.annotationHistory([{...a,legacy_read_only:true}]).includes('data-delete-annotation'));
(async()=>{
 let calls=[];
 sandbox.api=async (path,options)=>{
  calls.push({path,options});
  sandbox.state.selectedId='cn2'; // user switches while request is in flight
  return {revoked:{}};
 };
 const button={isConnected:true};
 await sandbox.revokeModelReviewVersion({issue_id:'cn1',annotations:[a]},a,button);
 assert.equal(calls.length,1);
 assert(calls[0].path.endsWith('/model-reviews/4000000000000001/revoke'));
 assert.equal(JSON.parse(calls[0].options.body).expected_head_id,a.id);
 assert.equal(sandbox.state.selectedCase,undefined);
 assert.equal(sandbox.state.savingAnnotation,false);
 console.log('owner/admin UI and navigation race passed');
})().catch(e=>{console.error(e);process.exitCode=1});
(async()=>{
 const root={dataset:{},addEventListener:()=>{}};
 let shown, change, destination;
 const task={split_id:'my-task',name:'0821-review-task',model_run_id:'task-run',baselines:['0821','extra'],completed_count:2,assignment_count:312};
 const ui={
  state:{reviewWorkSplitId:'',availableReviewWorkSplitId:''},
  $:(selector)=>selector==='#reviewTaskPicker'?root:null,
  api:async(path)=>{assert.equal(path,'/api/review-work-splits?all_baselines=true&assigned_to_me=true');return {items:[task]};},
  uiText:(x)=>x,populateUiSelect:(_root,options)=>{shown=options;},
  bindUiSelect:(_root,options)=>{change=options.onChange;},
  reviewAssignmentRouteOptions:(item,page)=>{assert.equal(page,'review');assert.deepEqual(Array.from(item.baseline_ids),task.baselines);return item;},
  pageUrl:(_page,options)=>`/review?work_split=${options.split_id}&run=${options.model_run_id}`,
  window:{location:{assign:(url)=>{destination=url;}}},
 };
 vm.createContext(ui);
 vm.runInContext(fs.readFileSync('ra_triage_dashboard/static/js/work-split.js','utf8'),ui);
 await ui.loadReviewTaskOptions();
 assert.equal(shown.length,2);assert(shown[1].label.includes('0821-review-task'));
 change('my-task');assert.equal(destination,'/review?work_split=my-task&run=task-run');
 console.log('task discovery and task-card navigation passed');
})().catch(e=>{console.error(e);process.exitCode=1});
