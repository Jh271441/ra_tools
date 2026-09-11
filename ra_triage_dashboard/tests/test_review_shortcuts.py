from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_review_tag_group_shortcut_toggles_open_state() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
const summary={focus:()=>{}};
const dropdown={open:true,querySelector:()=>summary};
document={querySelector:()=>dropdown};
CSS={escape:(value)=>value};
closeAllReviewDropdowns=()=>{};
reviewDropdownPanel=()=>({});
resetReviewDropdownPanel=()=>{};
prepareReviewDropdownPanelForMeasure=()=>{};
assert.equal(openReviewTagShortcutGroup('environment'),true);
assert.equal(dropdown.open,false);
assert.equal(openReviewTagShortcutGroup('environment'),true);
assert.equal(dropdown.open,true);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_missing_evidence_shortcut_toggles_open_state() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
const summary={focused:false,focus(){this.focused=true;}};
const dropdown={open:false,querySelector:()=>summary};
document={querySelector:(selector)=>selector.includes('data-missing-evidence-dropdown') ? dropdown : null};
closeAllReviewDropdowns=()=>{};
reviewDropdownPanel=()=>({});
resetReviewDropdownPanel=()=>{};
prepareReviewDropdownPanelForMeasure=()=>{};
assert.equal(REVIEW_MISSING_EVIDENCE_SHORTCUT,'i');
assert.equal(openReviewMissingEvidenceShortcut(),true);
assert.equal(dropdown.open,true);
assert.equal(summary.focused,true);
assert.equal(openReviewMissingEvidenceShortcut(),true);
assert.equal(dropdown.open,false);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_missing_evidence_numeric_shortcut_toggles_option() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
Event=class {constructor(type,options){this.type=type;this.bubbles=options?.bubbles;}};
const input={disabled:false,checked:false,dispatchEvent(event){this.lastEvent=event;}};
const dropdown={querySelector:(selector)=>selector.includes('data-review-dropdown-option-shortcut="1"') ? input : null};
document={querySelector:(selector)=>selector==='#reviewPane .review-dropdown[open]' ? dropdown : null};
CSS={escape:(value)=>value};
assert.equal(toggleOpenReviewDropdownOption('1'),true);
assert.equal(input.checked,true);
assert.equal(input.lastEvent.type,'change');
assert.equal(toggleOpenReviewDropdownOption('1'),true);
assert.equal(input.checked,false);
assert.equal(toggleOpenReviewDropdownOption('q'),false);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_exclude_shortcut_toggles_checkbox() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
Event=class {constructor(type,options){this.type=type;this.bubbles=options?.bubbles;}};
const input={disabled:false,checked:false,dispatchEvent(event){this.lastEvent=event;}};
$=(selector)=>selector==='#reviewExcludeInput' ? input : null;
assert.equal(toggleReviewExcludeShortcut(),true);
assert.equal(input.checked,true);
assert.equal(input.lastEvent.type,'change');
assert.equal(toggleReviewExcludeShortcut(),true);
assert.equal(input.checked,false);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_background_review_upload_keeps_preview_and_restores_it_on_failure() -> None:
    source = (ROOT / "static" / "js" / "review-attachments.js").read_text()
    script = source + r'''
const assert=require('node:assert/strict');
const target={innerHTML:'',querySelectorAll:()=>[]};
const file={name:'evidence.png'};
const preview={id:'preview-1',file,previewUrl:'blob:evidence'};
const task={issueId:'cn1',files:[file],previewItems:[preview],status:'uploading',failed:false};
state={selectedId:'cn1',pendingReviewImages:[],backgroundReviewUploads:new Map([['cn1||',task]])};
$=(selector)=>selector==='#pendingScreenshotList' ? target : null;
escapeHtml=(value)=>String(value);
uiText=(zh)=>zh;
releasePreviewUrlLater=()=>{};
renderPendingReviewImages();
assert.match(target.innerHTML,/正在后台保存 Review 和 1 张截图/);
assert.match(target.innerHTML,/blob:evidence/);
assert.match(target.innerHTML,/上传中/);
task.failed=true;
restoreFailedReviewUploadImages('cn1');
assert.equal(state.backgroundReviewUploads.size,0);
assert.equal(state.pendingReviewImages.length,1);
assert.equal(state.pendingReviewImages[0],preview);
assert.doesNotMatch(target.innerHTML,/正在后台保存/);
assert.match(target.innerHTML,/data-remove-screenshot/);
(async()=>{
  let toast='';
  const successPreview={id:'preview-2',file,previewUrl:'blob:success'};
  const successTask={key:'cn2||',issueId:'cn2',payload:{model_run_id:'',work_split_id:''},files:[file],previewItems:[successPreview],queuedAt:1,failed:false,status:'queued'};
  state={selectedId:'cn2',selectedCase:{issue_id:'cn2',annotations:[]},reviewEditRunId:'',reviewEditBaseAnnotationId:null,reviewFormDirty:true,backgroundReviewUploads:new Map([[successTask.key,successTask]]),pendingReviewImages:[],reviewUploadTail:Promise.resolve()};
  FormData=class {append(){}};
  api=async()=>({change_revision:2,annotation:{id:7,model_run_id:'',notification:{queued:[]}}});
  acknowledgeLocalChange=()=>{};
  readReviewDraft=()=>null;
  clearReviewDraft=()=>{};
  updateReviewHistory=()=>{};
  refreshReviewDerivedData=()=>{};
  refreshReviewAfterSave=async()=>{};
  showToast=(message)=>{toast=message;};
  enqueueBackgroundReviewUpload(successTask);
  renderPendingReviewImages();
  assert.match(target.innerHTML,/等待后台保存|正在后台保存/);
  await state.reviewUploadTail;
  assert.equal(state.backgroundReviewUploads.size,0);
  assert.match(toast,/已保存 Review 和 1 张截图/);
  assert.equal(target.innerHTML,'');
})().catch((error)=>{console.error(error);process.exitCode=1;});
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_successful_review_save_advances_when_current_leaves_filter() -> None:
    source = (ROOT / "static" / "js" / "review-form.js").read_text()
    start = source.index("function reviewSaveNavigationContext")
    end = source.index("const CASE_DETAIL_PREFETCH_TTL_MS", start)
    script = source[start:end] + r'''
const assert=require('node:assert/strict');
window={scrollY:321};
let selected=[];let loads=0;let notices=[];
state={activePage:'review',selectedId:'b',cases:[{issue_id:'a'},{issue_id:'b'},{issue_id:'c'}],casePage:1,casePageSize:20,caseTotal:3};
loadCases=async()=>{loads++;state.cases=[{issue_id:'a'},{issue_id:'c'}];state.caseTotal=2;};
selectCase=async(id,options)=>{selected.push([id,options]);state.selectedId=id;};
renderCaseNavigation=()=>{};clearDetail=()=>{};showPage=()=>{};
uiIn=0;
uiText=(zh)=>zh;showToast=(message)=>notices.push(message);
const context=reviewSaveNavigationContext('b');
(async()=>{
  assert.equal(context.index,1);assert.equal(context.hadNext,true);
  assert.equal(await reconcileReviewQueueAfterSave(context),true);
  assert.equal(loads,1);assert.equal(selected[0][0],'c');
  assert.equal(selected[0][1].historyMode,'replace');assert.equal(selected[0][1].preserveScrollY,321);
  assert.match(notices[0],/下一个筛选结果/);
  state.selectedId='user-chosen';loads=0;
  assert.equal(await reconcileReviewQueueAfterSave(context),false);
  assert.equal(loads,0);
  state.selectedId='b';state.reviewQueueStale=false;notices=[];
  loadCases=async()=>{throw new Error('queue failed');};
  refreshReviewDerivedData=()=>{};
  await refreshReviewAfterSave(context);
  assert.equal(state.reviewQueueStale,true);
  assert.match(notices[0],/Review 已保存，但筛选队列刷新失败/);
})().catch((error)=>{console.error(error);process.exitCode=1;});
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_open_review_dropdown_uses_arrows_for_navigation_and_enter_for_save() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
class MockElement {}
Element=MockElement;
Event=class {constructor(type,options){this.type=type;this.bubbles=options?.bubbles;}};
const labels=[];
const inputs=[0,1,2].map(()=>{
  const label={scrollIntoView:()=>{}}; labels.push(label);
  return Object.assign(new MockElement(),{
    disabled:false,checked:false,focused:false,
    focus(){this.focused=true;},
    closest(selector){return selector==='label' ? label : null;},
    matches(selector){return selector==='input[type="checkbox"]';},
    dispatchEvent(event){this.lastEvent=event;},
  });
});
const dropdown=Object.assign(new MockElement(),{open:true,querySelectorAll:()=>inputs});
const form={requestSubmit:(button)=>{form.submittedWith=button;}};
const saveButton={id:'reviewSaveButton'};
state={savingAnnotation:false};
$=(selector)=>selector==='#annotationForm' ? form : selector==='#reviewSaveButton' ? saveButton : null;
const summary=Object.assign(new MockElement(),{
  closest(selector){return selector.includes('.review-dropdown') ? dropdown : null;},
  matches(){return false;},
});
const arrow={target:summary,key:'ArrowDown',ctrlKey:false,metaKey:false,altKey:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
assert.equal(handleReviewDropdownKeyboard(arrow),true);
assert.equal(inputs[0].focused,true);
inputs[0].closest=(selector)=>selector.includes('.review-dropdown') ? dropdown : selector==='label' ? labels[0] : null;
const enter={target:inputs[0],key:'Enter',ctrlKey:false,metaKey:false,altKey:false,preventDefault(){},stopPropagation(){}};
assert.equal(submitReviewFromDropdown(enter,inputs[0]),true);
assert.equal(inputs[0].checked,false);
assert.equal(form.submittedWith,saveButton);
form.submittedWith=null;
const summaryEnter={target:summary,key:'Enter',ctrlKey:false,metaKey:false,altKey:false,preventDefault(){},stopPropagation(){}};
assert.equal(submitReviewFromDropdown(summaryEnter,summary),true);
assert.equal(form.submittedWith,saveButton);
const space={target:inputs[0],key:' ',ctrlKey:false,metaKey:false,altKey:false,preventDefault(){},stopPropagation(){}};
assert.equal(handleReviewDropdownKeyboard(space),true);
assert.equal(inputs[0].checked,true);
assert.equal(inputs[0].lastEvent.type,'change');
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_enter_submits_review_from_general_detail_focus() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
const form={requestSubmit:(button)=>{form.submittedWith=button;}};
const saveButton={id:'reviewSaveButton'};
state={savingAnnotation:false};
$=(selector)=>selector==='#annotationForm' ? form : selector==='#reviewSaveButton' ? saveButton : null;
const surface={closest:()=>null};
const enter={key:'Enter',shiftKey:false,isComposing:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
assert.equal(submitReviewFromKeyboard(enter,surface),true);
assert.equal(enter.prevented,true);
assert.equal(form.submittedWith,saveButton);
const shiftEnter={key:'Enter',shiftKey:true,isComposing:false,preventDefault(){},stopPropagation(){}};
assert.equal(submitReviewFromKeyboard(shiftEnter,surface),false);
const button={closest:(selector)=>selector.includes('button') ? {} : null};
assert.equal(submitReviewFromKeyboard({...enter,preventDefault(){},stopPropagation(){}},button),false);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_arrow_focused_option_keeps_all_dropdown_shortcuts_available() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
const tagDropdown={};
const evidenceDropdown={};
const tagCheckbox={
  matches:(selector)=>selector==='input[type="checkbox"]',
  closest:(selector)=>selector==='.review-dropdown[open]' ? tagDropdown : null,
};
const evidenceCheckbox={
  matches:(selector)=>selector==='input[type="checkbox"]',
  closest:(selector)=>selector==='.review-dropdown[open]' ? evidenceDropdown : null,
};
const textarea={
  matches:()=>false,
  closest:(selector)=>selector.includes('input, textarea') ? {} : null,
};
reviewShortcutHasEditableTarget=(target)=>target===tagCheckbox || target===evidenceCheckbox || target===textarea;
assert.equal(reviewDropdownShortcutAllowed(tagCheckbox),true);
assert.equal(reviewDropdownShortcutAllowed(evidenceCheckbox),true);
assert.equal(reviewDropdownShortcutAllowed(textarea),false);
assert.equal(reviewDropdownShortcutAllowed(null),true);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_video_t0_shortcut_targets_twenty_second_player_position() -> None:
    source = (ROOT / "static" / "js" / "detail-media.js").read_text()
    assert 'player.querySelector("[data-video-t0]").addEventListener("click"' in source
    assert "videoT0PlayerPosition(0, duration())" in source
    script = source + r'''
const assert=require('node:assert/strict');
escapeHtml=(value)=>String(value);
t=(key)=>key;
const markup=videoPlayerMarkup({url:'video.mp4',start_offset_sec:-20,event_time_sec:0,duration_ms:40000});
assert.match(markup,/data-start-offset-sec="-20"/);
assert.match(markup,/data-t0-player-sec="20"/);
assert.doesNotMatch(markup,/data-event-time-sec/);
assert.equal(videoT0PlayerPosition(40,39),20);
assert.equal(videoT0PlayerPosition(0,40),20);
assert.match(markup,/data-video-t0/);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_ra_event_relative_time_uses_review_media_t0() -> None:
    script = (
        (ROOT / "static" / "js" / "format-api.js").read_text()
        + (ROOT / "static" / "js" / "detail-media.js").read_text()
        + r'''
const assert=require('node:assert/strict');
state={raEventDialog:{t0TimestampMs:0}};
const caseData={
  assets:{capture:{timestamp_ms:200000}},
  camera:{capture:{timestamp_ms:300000}},
  external_links:{ares_timestamp_ms:400000},
};
assert.equal(reviewCaseT0TimestampMs(caseData),200000);
assert.equal(reviewCaseT0TimestampMs({external_links:{ares_timestamp_ms:400000}}),400000);
assert.equal(formatRaEventRelativeTime(200000,200000),'t0');
assert.equal(formatRaEventRelativeTime(81895,200000),'t−118.105s');
assert.equal(formatRaEventRelativeTime(201401,200000),'t+1.401s');
assert.equal(formatRaEventRelativeTime(null,200000),'—');
'''
    )
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_review_history_shortcut_toggle_closes_matching_dialog() -> None:
    script = (ROOT / "static" / "js" / "detail-media.js").read_text() + r'''
const assert=require('node:assert/strict');
const dialog={open:true,dataset:{historyKind:'review'}};
$=(selector)=>selector==='#historyDialog' ? dialog : null;
closeDialog=()=>{dialog.open=false;};
assert.equal(toggleHistoryDialog('review',{}),false);
assert.equal(dialog.open,false);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_blind_review_form_keeps_current_author_while_history_keeps_peers() -> None:
    script = (ROOT / "static" / "js" / "review-draft.js").read_text() + r'''
const assert=require('node:assert/strict');
const state={selectedRunId:'run-1',session:{username:'Alice'}};
const data={review_assignment:{blind_active:true},annotations:[
  {id:3,model_run_id:'run-1',author:'bob'},
  {id:2,model_run_id:'run-1',author:'alice'},
  {id:1,model_run_id:'run-0',author:'alice'},
]};
assert.deepEqual(reviewAnnotationsForCurrentRun(data).map((item)=>item.id),[2]);
assert.deepEqual(reviewAnnotationsForAllRuns(data).map((item)=>item.id),[3,2,1]);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)
