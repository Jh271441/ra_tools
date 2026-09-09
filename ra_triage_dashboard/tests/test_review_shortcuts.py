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


def test_open_review_dropdown_supports_arrow_and_enter_selection() -> None:
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
const summary=Object.assign(new MockElement(),{
  closest(selector){return selector==='.review-dropdown[open]' ? dropdown : null;},
  matches(){return false;},
});
const arrow={target:summary,key:'ArrowDown',ctrlKey:false,metaKey:false,altKey:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
assert.equal(handleReviewDropdownKeyboard(arrow),true);
assert.equal(inputs[0].focused,true);
inputs[0].closest=(selector)=>selector==='.review-dropdown[open]' ? dropdown : selector==='label' ? labels[0] : null;
const enter={target:inputs[0],key:'Enter',ctrlKey:false,metaKey:false,altKey:false,preventDefault(){},stopPropagation(){}};
assert.equal(handleReviewDropdownKeyboard(enter),true);
assert.equal(inputs[0].checked,true);
assert.equal(inputs[0].lastEvent.type,'change');
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_arrow_focused_tag_option_keeps_group_shortcuts_available() -> None:
    script = (ROOT / "static" / "js" / "review-tags.js").read_text() + r'''
const assert=require('node:assert/strict');
const dropdown={};
const tagCheckbox={
  matches:(selector)=>selector==='input[type="checkbox"]',
  closest:(selector)=>selector.includes('.review-tag-dropdown') ? dropdown : {},
};
const textarea={
  matches:()=>false,
  closest:(selector)=>selector.includes('input, textarea') ? {} : null,
};
reviewShortcutHasEditableTarget=(target)=>target===tagCheckbox || target===textarea;
assert.equal(reviewTagGroupShortcutAllowed(tagCheckbox),true);
assert.equal(reviewTagGroupShortcutAllowed(textarea),false);
assert.equal(reviewTagGroupShortcutAllowed(null),true);
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True)


def test_video_t0_shortcut_targets_twenty_second_player_position() -> None:
    script = (ROOT / "static" / "js" / "detail-media.js").read_text() + r'''
const assert=require('node:assert/strict');
escapeHtml=(value)=>String(value);
t=(key)=>key;
const markup=videoPlayerMarkup({url:'video.mp4',start_offset_sec:-20,duration_ms:40000});
assert.match(markup,/data-start-offset-sec="-20"/);
assert.match(markup,/data-event-time-sec="20"/);
assert.match(markup,/data-video-t0/);
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
