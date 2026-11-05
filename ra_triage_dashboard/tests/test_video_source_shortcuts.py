"""Exercise source shortcuts against the player's native media-fragment URLs."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_video_source_shortcuts_ignore_start_fragment_and_keep_guards() -> None:
    script = (ROOT / "static/js/text-input.js").read_text() + (ROOT / "static/js/bev-video.js").read_text() + (ROOT / "static/js/detail-media.js").read_text() + r'''
const assert = require('node:assert/strict');
const origin = 'https://triage.test';
safeSameOriginAssetUrl = value => {
  if (!value) return '';
  const url = new URL(value, origin);
  return url.origin === origin && url.pathname.startsWith('/manual/api/')
    ? url.pathname + url.search : '';
};
uiText = (zh, en) => en;
populateUiSelect = () => {};
enhanceNativeUiSelect = () => {};
detailMediaKindOptions = () => [];
ensureDetailMediaState = () => ({});
detailMediaSelectedKind = () => 'video';
detailMediaPrefix = () => 'detail';
const original = {url:'/manual/api/assets/cn1/bev-video?v=1',label:'BEV 视频'};
const camera = {url:'/manual/api/assets/cn1/camera-video',label:'Camera102 视频'};
const closeup = {url:'/manual/api/assets/cn1/bev-closeup-video?v=2',source_id:'bev_closeup',poster_url:'/manual/api/closeup-poster'};
const descriptor = {...original,tracks:[original,camera,closeup]};
videoWithFramePosters = () => descriptor;
mediaVideo = () => descriptor;
let inDialog, src, changes, toasts, blocked;
const video = {getAttribute:()=>src};
const setSource = url => {
  src = videoPlaybackSourceUrl(url,23);
  changes.push(url);
  if (inDialog) state.media.snapshot.videoTrack = url;
  else state.detailMedia.videoTrack = state.detailMedia.preferredVideoTrack = url;
};
const inlineSelect = {options:[{value:'video'},{value:`track:${closeup.url}`},{value:`track:${camera.url}`}],
  dispatchEvent(){setSource(this.value==='video' ? original.url : this.value.slice(6));}};
const dialogSelect = {options:descriptor.tracks.map(t=>({value:t.url})),dispatchEvent(){setSource(this.value);}};
const stage = {querySelector:s=>s==='video' ? video : s==='[data-video-track]' ? dialogSelect : null};
const pane = {querySelector:s=>s==='video' ? video : s==='.detail-hero-media' ? {} : s==='#detailMediaKindSelect' ? inlineSelect : null};
detailMediaPane = () => pane;
$ = selector => selector==='#mediaDialog' ? {open:inDialog} : selector==='#mediaVideoStage' ? stage : null;
document = {querySelector:()=>blocked ? {} : null};
showToast = text => toasts.push(text);
function mount(view,initial) {
  inDialog=view==='dialog';src=videoPlaybackSourceUrl(initial,20);changes=[];toasts=[];blocked=false;
  state={activePage:view==='labeling'?'labeling':'review',selectedCase:{},caseLabeling:{caseData:{}},
    detailMedia:{kind:'video',videoTrack:initial,preferredVideoTrack:initial},
    media:{kind:'video',snapshot:{videoTrack:initial}}};
}
function press(key='V',extra={}) {
  const event={key,shiftKey:key==='V',target:{closest:()=>null},preventDefault(){this.defaultPrevented=true;},...extra};
  assert.equal(handleVideoSourceShortcut(event),true);
  return event;
}
for (const view of ['review','labeling','dialog']) {
  mount(view,original.url);
  press(); assert.equal(changes.at(-1),closeup.url);
  press(); assert.equal(changes.at(-1),original.url,'Second Shift+V returns from fragment-bearing closeup');
  press(); assert.equal(changes.at(-1),closeup.url);
  press('v'); assert.equal(changes.length,3,'V keeps the selected source without reloading');
  press('o'); assert.equal(changes.at(-1),original.url);
  press('o'); assert.equal(changes.length,4,'O keeps an already selected original without reloading');
  // Absolute currentSrc-style URLs and query parameters identify the same source.
  src=origin+videoPlaybackSourceUrl(closeup.url,7.5);
  press(); assert.equal(changes.at(-1),original.url);
  mount(view,camera.url);
  press(); assert.equal(changes.at(-1),closeup.url);
  press(); assert.equal(changes.at(-1),original.url,'Camera is excluded from the BEV toggle');
  const before=changes.length;
  for(const guard of [{repeat:true},{ctrlKey:true},{altKey:true},{metaKey:true},{isComposing:true},
    {keyCode:229},{defaultPrevented:true},{target:{closest:()=>({})}}]) {
    press('V',guard);press('C',{shiftKey:true,...guard});
  }
  blocked=true;press();press('C',{shiftKey:true});blocked=false;
  assert.equal(changes.length,before,'Typing, IME, repeats, modifiers and conflicting UI keep the source');
  mount(view,original.url);
  press('C',{shiftKey:true});assert.equal(changes.at(-1),camera.url,'Shift+C opens Camera video');
  press('C',{shiftKey:true});assert.equal(changes.length,1,'Shift+C does not reload the current Camera video');
  press('v');assert.equal(changes.at(-1),original.url,'V returns from Shift+C to the last BEV source');
  press('v');assert.equal(changes.length,2,'Repeated V keeps the BEV source without reloading');
  press();assert.equal(changes.at(-1),closeup.url);
  press('C',{shiftKey:true});assert.equal(changes.at(-1),camera.url);
  press('v');assert.equal(changes.at(-1),closeup.url,'Camera must not overwrite the last closeup BEV choice');
  const plainC={key:'c',target:{closest:()=>null},preventDefault(){throw Error('C belongs to Camera images');}};
  assert.equal(handleVideoSourceShortcut(plainC),false);
  press('o');assert.equal(changes.at(-1),original.url,'O still returns from Camera video to original BEV');
}
for (const view of ['review','dialog']) {
  mount(view,closeup.url);
  descriptor.url=closeup.url;descriptor.source_id='bev_closeup';descriptor.tracks=[closeup];
  press();assert.equal(changes.length,0);assert.match(toasts.at(-1),/No original BEV video/);
  press('o');assert.equal(changes.length,0);assert.match(toasts.at(-1),/No original BEV video/);
  press('C',{shiftKey:true});assert.equal(changes.length,0);assert.match(toasts.at(-1),/No Camera video/);
}
for (const view of ['review','labeling','dialog']) {
  descriptor.url=camera.url;descriptor.label=camera.label;delete descriptor.source_id;descriptor.tracks=[camera];
  mount(view,camera.url);
  state.detailMedia.preferredBevVideoTrack=closeup.url;state.media.snapshot.preferredBevVideoTrack=closeup.url;
  press('v');assert.equal(changes.length,0);assert.match(toasts.at(-1),/No BEV video/,'An unavailable remembered BEV must not fall back to Camera');
}
'''
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
