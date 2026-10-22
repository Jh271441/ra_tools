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
actions(key('M',true));assert.deepEqual(histories,['model']);
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
