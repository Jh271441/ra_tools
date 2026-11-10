"""Keyboard ownership between Review labels, media controls and Escape."""
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / 'static/js'


def run_node(source):
    result = subprocess.run(['node', '-e', source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_media_keys_allow_review_checkboxes_and_yield_to_text_and_label_numbers():
    run_node((ROOT/'text-input.js').read_text() + (ROOT/'bev-video.js').read_text() + (ROOT/'detail-media.js').read_text() + (ROOT/'review-tags.js').read_text() + r'''
const assert=require('node:assert/strict');
const checkbox={matches:()=>true,closest:s=>s.includes('.review-dropdown[open]')?{}:{}};
const text={matches:()=>false,closest:()=>({})};
const otherCheckbox={matches:()=>true,closest:s=>s.includes('.review-dropdown[open]')?null:{}};
assert.equal(mediaShortcutHasEditableTarget(checkbox),false);
assert.equal(mediaShortcutHasEditableTarget(text),true);
assert.equal(mediaShortcutHasEditableTarget(otherCheckbox),true);
let ownZero=false,dialogOpen=false,clicks=[];
state={activePage:'review',selectedCase:{},detailMedia:{kind:'video'}};
document={querySelector:()=>dialogOpen?{}:null};
CSS={escape:String};
let zeroHidden=false;
$=()=>({querySelector:()=>ownZero?{querySelector:()=>({closest:()=>zeroHidden?{}:null})}:null});
const button=name=>({click(){assert.equal(mediaShortcutActivating,true);clicks.push(name);}});
const controls={'[data-video-play]':button('play'),'[data-video-t0]':button('t0'),'[data-video-jump="1"]':button('right')};
detailHeroMediaEl=()=>({querySelector:s=>controls[s]});
detailMediaPane=()=>({querySelector:()=>null});
detailMediaPrefix=()=> 'detail';
const key=(name,extra={})=>({key:name,target:checkbox,preventDefault(){this.defaultPrevented=true;},...extra});
assert.equal(handleDetailMediaShortcut(key(' ')),true);
assert.equal(handleDetailMediaShortcut(key('ArrowRight')),true);
assert.deepEqual(clicks,['play','right']);
assert.equal(mediaShortcutActivating,false,'Activation must not leak into real outside clicks');
ownZero=true;
assert.equal(handleDetailMediaShortcut(key('0')),false,'Tenth label owns its visible 0 binding');
assert.equal(handleDetailMediaShortcut(key('0',{shiftKey:true})),false,'Shift+0 never resets video');
zeroHidden=true;
assert.equal(handleDetailMediaShortcut(key('0')),true,'An option hidden by search does not own 0');
ownZero=false;
assert.equal(handleDetailMediaShortcut(key('0')),true);
assert.deepEqual(clicks,['play','right','t0','t0']);
for(const guard of [{isComposing:true},{keyCode:229},{which:229},{ctrlKey:true},{metaKey:true},{altKey:true},{defaultPrevented:true},{target:text}]) {
  assert.equal(handleDetailMediaShortcut(key('ArrowRight',guard)),false);
}
dialogOpen=true;
assert.equal(handleDetailMediaShortcut(key('ArrowRight')),false);
assert.deepEqual(clicks,['play','right','t0','t0']);
''')


def test_escape_releases_workbench_focus_after_inner_controls_have_handled_it():
    run_node((ROOT/'text-input.js').read_text() + (ROOT/'review-tags.js').read_text() + r'''
const assert=require('node:assert/strict');
let handler,dialog=false,inside=true,blurred=0;
state={activePage:'review'};
const active={closest:()=>inside?{}:null,matches:()=>true,blur(){blurred++;}};
document={documentElement:{dataset:{}},activeElement:active,addEventListener(){},querySelector:()=>dialog?{}:null,querySelectorAll:()=>[]};
window={addEventListener:(name,fn)=>{if(name==='keydown')handler=fn;}};
bindReviewDropdownDismiss();
const escape=extra=>({key:'Escape',target:active,preventDefault(){this.defaultPrevented=true;},...extra});
for(const extra of [{defaultPrevented:true},{isComposing:true},{keyCode:229},{which:229},{ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},{repeat:true}]) handler(escape(extra));
assert.equal(blurred,0);
dialog=true;handler(escape());assert.equal(blurred,0,'An open modal retains Escape');
dialog=false;inside=false;handler(escape());assert.equal(blurred,0,'Other page areas retain focus');
inside=true;state.activePage='intent';handler(escape());assert.equal(blurred,0);
state.activePage='review';const event=escape();handler(event);
assert.equal(blurred,1,'History/action focus can be released');assert.equal(event.defaultPrevented,true);
state.activePage='labeling';handler(escape());assert.equal(blurred,2);
''')
