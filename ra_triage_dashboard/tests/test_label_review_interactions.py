"""Behavioral tests for Case/Run editing and discussion boundaries."""
import subprocess
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


class LabelReviewInteractionsTest(unittest.TestCase):
    def test_shortcuts_split_case_and_run_and_case_rationale_survives_drafts(self):
        script = (ROOT / "static/js/review-draft.js").read_text() + "\n" + (ROOT / "static/js/review-form.js").read_text() + r'''
const assert=require('node:assert/strict');
state={activePage:'review',selectedCase:{issue_id:'cn1'},selectedRunId:'run1',session:{username:'alice',verified:true}};
Element=class {closest(){return null}};
const body=new Element(), handlers=[];let active='',draft;
const field=(id,value='')=>({id,value,dataset:{},disabled:false,closest(){return null},focus(){active=id},setSelectionRange(){}});
const note=field('annotationNote','Model-only reason'),rationale=field('combinedCaseRationale','Saved Case reason @bob');
const form={querySelectorAll(){return []}};
const elements={'#annotationNote':note,'#combinedCaseRationale':rationale,'#annotationForm':form,'#issueLabelCommentsButton':field('issueButton')};
$=(selector)=>elements[selector]||null;
document={documentElement:{dataset:{}},querySelector(){return null},addEventListener(type,fn){if(type==='keydown')handlers.push(fn)}};
window={localStorage:{setItem(key,value){draft=JSON.parse(value)},getItem(){return null}}};
closeAllReviewDropdowns=()=>{};
const key=(key,shiftKey=false)=>({key,shiftKey,target:body,preventDefault(){},stopPropagation(){}});
bindReviewComposerShortcuts();const composer=handlers.pop();
composer(key('e'));assert.equal(active,'combinedCaseRationale');
composer(key('E',true));assert.equal(active,'annotationNote');
reviewShortcutHasEditableTarget=()=>false;
let opened=[];openAnalysisDiscussion=(issue,options)=>{opened.push({issue,...options});return Promise.resolve()};
bindReviewDetailActionShortcuts();const actions=handlers.pop();
actions(key('d'));assert.equal(opened[0].kind,'labeling');assert.equal(opened[0].runId,'');assert.equal(opened[0].discussionChannel,'case');
actions(key('D',true));assert.equal(opened[1].source,'review');assert.equal(opened[1].runId,'run1');
let histories=[];toggleHistoryDialog=(kind)=>histories.push(kind);
actions(key('m'));assert.deepEqual(histories,[]);
actions(key('p'));assert.deepEqual(histories,['model']);
actions(key('M',true));assert.deepEqual(histories,['model']);
state.reviewWorkSplitId='task1';state.selectedCase.review_assignment={split_id:'task1',model_run_id:'run1',assigned:false};
actions(key('d'));assert.equal(opened.at(-1).taskId,'task1');assert.equal(opened.at(-1).discussionChannel,'case');
state.selectedCase.review_assignment.model_run_id='wrong-run';actions(key('d'));assert.equal(opened.at(-1).taskId,'');
state.reviewWorkSplitId='';state.selectedCase.review_assignment.model_run_id='run1';actions(key('d'));assert.equal(opened.at(-1).taskId,'');
uiText=(zh,en)=>zh;
assert.equal(modelReviewSubmissionStatus(null),'completed');
assert.equal(modelReviewSubmissionStatus({note:''}),'completed');
assert.equal(modelReviewSubmissionStatus({model_review_status:'completed',note:''}),'completed');
assert.equal(modelReviewSubmissionStatus({model_review_status:'in_progress'}),'in_progress');
assert.equal(modelReviewSubmissionStatus({model_review_status:'blocked_by_label'}),'in_progress');
assert.equal(modelReviewProgressText(null),'待开始');
assert.equal(modelReviewProgressText({id:1,model_review_status:'in_progress'}),'待复核');
assert.equal(modelReviewProgressText({id:1,model_review_status:'completed',note:''}),'已完成');
assert.equal(savedOwnCaseRationale({label_state:{sources:[
{revision_summaries:[{id:1,author:'alice',rationale:'Mine'},{id:2,author:'bob',rationale:'Other'}]},
{method:'adjudication',result_revision_id:3,revision_summaries:[{id:3,author:'alice',rationale:'Judge'}]}
]}}),'Mine');
currentReviewRunId=()=> 'run1';reviewWorkSplitBinding=()=> '';reviewDraftReviewer=()=> 'alice';
persistReviewDraft(state.selectedCase);
assert.equal(draft.case_rationale,'Saved Case reason @bob');assert.equal(draft.note,'Model-only reason');
assert.equal(applyReviewDraft({},draft).case_rationale,'Saved Case reason @bob');
'''
        subprocess.run(["node"], input=script, text=True, check=True, capture_output=True)

    def test_label_summary_shortcut_respects_dialog_and_editing_scope(self):
        script = (ROOT / "static/js/review-tags.js").read_text() + "\n" + (ROOT / "static/js/review-form.js").read_text() + r'''
const assert=require('node:assert/strict');
state={activePage:'review',selectedCase:{issue_id:'cn1'}};
Element=class {constructor(editable=false){this.editable=editable}closest(){return this.editable?{}:null}};
const body=new Element(),handlers=[];
let opens=0,closes=0,hidden=false,otherDialog=false;
const dialog={open:false};const button={disabled:false,closest(){return hidden?{}:null},click(){opens++;dialog.open=true}};
$=(selector)=>selector==='#sharedLabelStateDialog'?dialog:selector==='#reviewSharedLabelState'?{querySelector(){return button}}:null;
document={documentElement:{dataset:{}},addEventListener(type,fn){handlers.push(fn)},querySelector(){return otherDialog?{}:null}};
closeAllReviewDropdowns=()=>{};closeDialog=(id)=>{assert.equal(id,'sharedLabelStateDialog');closes++;dialog.open=false};
bindReviewDetailActionShortcuts();const handler=handlers[0];
function key(options={}){const e={key:'l',target:body,preventDefault(){this.prevented=true},stopPropagation(){},...options};handler(e);return e}
assert.equal(key().prevented,true);assert.equal(opens,1);assert.equal(dialog.open,true);
assert.equal(key().prevented,true);assert.equal(closes,1);assert.equal(dialog.open,false);
for(const flag of ['ctrlKey','metaKey','altKey','shiftKey','isComposing','repeat','defaultPrevented']) assert.notEqual(key({[flag]:true}).prevented,true);
assert.notEqual(key({target:new Element(true)}).prevented,true);
otherDialog=true;assert.notEqual(key().prevented,true);otherDialog=false;
hidden=true;assert.notEqual(key().prevented,true);hidden=false;
button.disabled=true;assert.notEqual(key().prevented,true);button.disabled=false;
state.activePage='labeling';assert.notEqual(key().prevented,true);state.activePage='review';
assert.equal(opens,1);assert.equal(closes,1);
'''
        subprocess.run(["node"], input=script, text=True, check=True, capture_output=True)

    def test_dropdown_natural_width_respects_trigger_floor_and_viewport(self):
        script = (ROOT / "static/js/review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
let summaryWidth=152.5,viewportWidth=1000,naturalWidth=260;
const panel={getBoundingClientRect(){return {width:naturalWidth}},style:{},scrollHeight:1200,classList:{add(){},remove(){}},querySelector(){return null}};
const summary={getBoundingClientRect(){return {width:summaryWidth,left:20,right:20+summaryWidth,top:100,bottom:140}}};
const dropdown={open:true,querySelector(){return summary}};
reviewDropdownPanel=()=>panel;
anchoredViewportBounds=()=>({left:0,right:viewportWidth,width:viewportWidth,top:0,bottom:800,height:800});
for(const width of [152.5,280,420]){
 summaryWidth=width;positionReviewDropdownPanel(dropdown);
 assert.equal(parseFloat(panel.style.width),Math.max(width,naturalWidth,180));
 assert.ok(parseFloat(panel.style.maxHeight)<=784);
 assert.ok(parseFloat(panel.style.maxHeight)>0);
}
naturalWidth=1400;positionReviewDropdownPanel(dropdown);
assert.equal(parseFloat(panel.style.width),984);
viewportWidth=200;summaryWidth=300;positionReviewDropdownPanel(dropdown);
assert.equal(parseFloat(panel.style.width),184);
'''
        subprocess.run(["node"], input=script, text=True, check=True, capture_output=True)
