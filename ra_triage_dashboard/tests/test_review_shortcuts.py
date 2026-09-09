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
