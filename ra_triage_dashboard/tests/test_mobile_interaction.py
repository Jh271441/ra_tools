"""Phone entry safety and keyboard-aware dropdown geometry using actual JS."""
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "static/js"

class MobileInteractionTest(unittest.TestCase):
    def run_js(self, names, assertions):
        script = "\n".join((ROOT / name).read_text() for name in names) + assertions
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_phone_textarea_enter_never_submits_while_desktop_shortcut_remains(self):
        self.run_js(["review-tags.js"], r'''
const assert = require('node:assert/strict');
let submitted=0, phone=true;
window={matchMedia:()=>({matches:phone})};
submitActiveReviewForm=()=>submitted++;
const textarea={matches:s=>s==='textarea',closest:()=>null};
const event=()=>({key:'Enter',preventDefault(){this.prevented=true},stopPropagation(){}});
let enter=event();
assert.equal(submitReviewFromKeyboard(enter,textarea),false);
assert.equal(enter.prevented,undefined);
assert.equal(submitted,0);
phone=false;enter=event();
assert.equal(submitReviewFromKeyboard(enter,textarea),true);
assert.equal(enter.prevented,true);assert.equal(submitted,1);
assert.equal(submitReviewFromKeyboard({...event(),shiftKey:true},textarea),false);
assert.equal(submitReviewFromKeyboard({...event(),isComposing:true},textarea),false);
''')

    def test_dropdown_tracks_keyboard_viewport_offsets_and_releases_closed_panels(self):
        # Only core before app state: test the production geometry and listeners.
        core=(ROOT/'core-base.js').read_text().split('function normalizeClientBasePath')[0]
        script = core + r'''
const assert=require('node:assert/strict');
const listeners={};
window={innerWidth:390,innerHeight:844,visualViewport:{width:390,height:320,offsetTop:110,offsetLeft:0,addEventListener:(k,fn)=>listeners[k]=fn}};
const classes=new Set();
const panel={isConnected:true,hidden:true,style:{},scrollHeight:600,classList:{add(...v){v.forEach(x=>classes.add(x))},remove(...v){v.forEach(x=>classes.delete(x))}},closest:()=>null};
const anchor={isConnected:true,getBoundingClientRect:()=>({top:260,bottom:304,left:250,width:120})};
openAnchoredPanel(panel,anchor,{minWidth:180});
function bounded(){
 const top=parseInt(panel.style.top),left=parseInt(panel.style.left),h=parseInt(panel.style.maxHeight),w=parseInt(panel.style.width);
 assert.ok(top>=window.visualViewport.offsetTop+8);
 assert.ok(top+h<=window.visualViewport.offsetTop+window.visualViewport.height-8);
 assert.ok(left>=8 && left+w<=382);
}
bounded();assert.equal(anchoredPanelContexts.size,1);
window.visualViewport.height=240;window.visualViewport.offsetTop=150;listeners.resize();bounded();
resetAnchoredPanel(panel);assert.equal(anchoredPanelContexts.size,0);assert.equal(panel.style.top,'');
openAnchoredPanel(panel,anchor);panel.isConnected=false;listeners.scroll();assert.equal(anchoredPanelContexts.size,0);
'''
        result=subprocess.run(["node","-e",script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_combined_review_composer_leaves_phone_newline_untouched(self):
        self.run_js(["review-tags.js", "review-form.js"], r'''
const assert=require('node:assert/strict');
let keydown,submitted=0,phone=true;
class Element { matches(s){return s==='textarea'} }
const note=new Element(),rationale=new Element();
const form={checkValidity:()=>true,requestSubmit:()=>submitted++};
window={matchMedia:()=>({matches:phone})};
document={documentElement:{dataset:{}},querySelector:()=>null,addEventListener:(key,fn)=>{if(key==='keydown')keydown=fn}};
state={activePage:'review',selectedCase:{},savingAnnotation:false};
$=s=>({'#annotationNote':note,'#combinedCaseRationale':rationale,'#annotationForm':form})[s];
bindReviewComposerShortcuts();
const event=target=>({target,key:'Enter',preventDefault(){this.prevented=true},stopPropagation(){}});
for(const target of [note,rationale]) { const e=event(target);keydown(e);assert.equal(e.prevented,undefined); }
assert.equal(submitted,0);
phone=false;const e=event(note);keydown(e);assert.equal(e.prevented,true);assert.equal(submitted,1);
''')
