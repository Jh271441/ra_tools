"""RA Event dismissal releases only its own restored trigger focus."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ra_event_escape_and_close_focus_boundaries():
    script = (ROOT / 'static/js/detail-media.js').read_text() + r'''
const assert = require('node:assert/strict');
const handlers = {}, frames = [], keys = [];
let open = false, blurs = 0;
const trigger = {matches:s=>s==='[data-open-ra-event]',blur(){blurs++;document.activeElement=null}};
const input = {matches:()=>false,blur(){throw Error('must preserve input focus')}};
const dialog = {dataset:{},addEventListener(type,fn){handlers[type]=fn}};
$=()=>dialog;
document={activeElement:trigger,querySelector:()=>open?{}:null,addEventListener(type,fn){keys.push(fn)}};
window={requestAnimationFrame:fn=>frames.push(fn)};
bindRaEventDialogFocus();bindRaEventDialogFocus();assert.equal(keys.length,1);
function escape(extra={}) {const e={key:'Escape',preventDefault(){this.prevented=true},stopPropagation(){},...extra};keys[0](e);return e}
assert.equal(escape().prevented,true);assert.equal(blurs,1);
// Open dialogs own Escape; do not intercept native cancellation or nested dialogs.
open=true;document.activeElement=trigger;assert.equal(escape().prevented,undefined);assert.equal(blurs,1);
// Native Escape, T-toggle, close button and backdrop all emit close after restoring focus.
for (const cause of ['Escape','T','close button','backdrop']) {
  open=false;document.activeElement=trigger;handlers.close();frames.shift()();
  assert.equal(document.activeElement,null,cause);
}
assert.equal(blurs,5);
// A new input focus or another modal before the animation frame must survive.
handlers.close();document.activeElement=input;frames.shift()();assert.equal(document.activeElement,input);
handlers.close();document.activeElement=trigger;open=true;frames.shift()();assert.equal(blurs,5);open=false;
for (const flag of ['defaultPrevented','isComposing','ctrlKey','metaKey','altKey','shiftKey']) {
  assert.equal(escape({[flag]:true}).prevented,undefined);assert.equal(document.activeElement,trigger);
}
assert.equal(escape({key:'Enter'}).prevented,undefined);
document.activeElement=input;assert.equal(escape().prevented,undefined);
assert.equal(document.activeElement,input);
'''
    subprocess.run(['node'], input=script, text=True, capture_output=True, check=True)
    assert 'bindRaEventDialogFocus();' in (ROOT / 'static/js/bind-bootstrap.js').read_text()
