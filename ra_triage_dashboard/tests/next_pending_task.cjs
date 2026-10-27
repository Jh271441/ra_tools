const fs = require('fs'), vm = require('vm'), assert = require('assert'), path = require('path');
const state = {activePage:'review', reviewTaskContext:{id:'task'}, reviewTaskProgress:[], selectedId:'cn1', casePage:1, casePageSize:2, cases:[{issue_id:'cn1'},{issue_id:'cn2'}]};
let scope='work_split_id=task&work_assignee=jasperchen&model_run_id=run&baselines=scope&label_state=conflict', epoch=0;
let calls=[], selected=[], pages=[], messages=[], apiImpl;
const button={hidden:false,disabled:false,textContent:'',title:''};
const sandbox={state,console,URLSearchParams,Set,Promise,
  $:id=>id==='#reviewNextPendingTaskButton'?button:null,
  selectedCombinedTaskProgress:()=>state.reviewTaskProgress,isCombinedTaskProgressFilter:()=>true,
  capturePageContext:()=>epoch,isPageContextCurrent:value=>value===epoch,
  renderCaseNavigation:()=>{},uiText:(zh,en)=>en,showToast:message=>messages.push(message),
  window:{scrollY:123},api:url=>{calls.push(url);return apiImpl(url);},
  loadCases:async({page})=>{pages.push(page);state.casePage=page;state.cases=[{issue_id:'cn3'},{issue_id:'cn4'}];},
  selectCase:async(id,options)=>{selected.push({id,options});state.selectedId=id;},
};
vm.createContext(sandbox);
const loadCases=sandbox.loadCases;
vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/review-gallery.js'),'utf8'),sandbox);
sandbox.renderCaseNavigation=()=>{};sandbox.loadCases=loadCases;
sandbox.currentReviewGalleryExportParams=()=>new URLSearchParams(scope+'&format=xlsx&gallery_scope=true');
function reset(){Object.assign(state,{activePage:'review',reviewTaskContext:{id:'task'},reviewTaskContextLoading:false,reviewTaskContextError:null,reviewTaskProgress:[],selectedId:'cn1',casePage:1,cases:[{issue_id:'cn1'},{issue_id:'cn2'}],savingAnnotation:false});calls=[];selected=[];pages=[];messages=[];
  apiImpl=async url=>({issue_ids:new URL(url,'http://fixture').searchParams.has('task_progress')?['cn1','cn3']:['cn1','cn2','cn3','cn4']});
}
(async()=>{
  reset();sandbox.renderNextPendingTaskButton();assert.equal(button.hidden,false);assert.equal(button.textContent,'Next pending');
  state.reviewTaskProgress=['pending'];sandbox.renderNextPendingTaskButton();assert.equal(button.hidden,true);
  reset();await sandbox.jumpToNextPendingTask();
  assert.equal(selected[0].id,'cn3');assert.deepEqual(pages,[2]);assert.equal(selected[0].options.preserveScrollY,123);
  assert.deepEqual(state.reviewTaskProgress,[],'jump never changes selected filters');
  for(const url of calls){const q=new URL(url,'http://fixture').searchParams;assert.equal(q.get('work_assignee'),'jasperchen');assert.equal(q.get('work_split_id'),'task');assert.equal(q.get('label_state'),'conflict');assert(!q.has('format'));}
  reset();state.selectedId='';await sandbox.jumpToNextPendingTask();assert.equal(selected[0].id,'cn1');assert.equal(selected[0].options.historyMode,'push');
  reset();state.selectedId='cn4';state.casePage=2;state.cases=[{issue_id:'cn3'},{issue_id:'cn4'}];await sandbox.jumpToNextPendingTask();assert.equal(selected.length,0);assert.equal(messages.length,1);
  for(const progress of [['pending'],['completed']]){reset();state.reviewTaskProgress=progress;await sandbox.jumpToNextPendingTask();assert.equal(calls.length,0);}
  reset();state.reviewTaskProgress=['completed','pending'];assert(sandbox.reviewShowsAllTaskProgress());
  for(const flag of ['reviewTaskContextLoading','reviewTaskContextError','savingAnnotation']){reset();state[flag]=true;await sandbox.jumpToNextPendingTask();assert.equal(calls.length,0);}
  reset();let duplicates=[];apiImpl=()=>new Promise(r=>{duplicates.push(r);});
  const held=sandbox.jumpToNextPendingTask();await sandbox.jumpToNextPendingTask();assert.equal(calls.length,2,'duplicate click is ignored');
  // Resolve both requests, then change page before either may navigate.
  epoch++;duplicates.forEach(r=>r({issue_ids:[]}));await held;assert.equal(selected.length,0);
  reset();let releases=[];apiImpl=()=>new Promise(r=>releases.push(r));const stale=sandbox.jumpToNextPendingTask();
  scope+='&search=new';releases.forEach(r=>r({issue_ids:['cn3']}));await stale;assert.equal(selected.length,0);
  reset();apiImpl=async()=>{throw Error('offline');};await assert.rejects(sandbox.jumpToNextPendingTask(),/offline/);assert.equal(state.reviewPendingJumpBusy,false);
  reset();sandbox.loadCases=async()=>{epoch++;};await sandbox.jumpToNextPendingTask();assert.equal(selected.length,0,'late cross-page result cannot navigate');
  assert(!fs.readFileSync(path.join(__dirname,'../static/js/review-form.js'),'utf8').includes('reviewShowsAllTaskProgress'), 'detail Next and its shortcut stay unchanged');
  console.log('Next pending task: scope, cross-page, empty, duplicate, stale and error guards passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
