// Exercise the real panel lifecycle without requiring a browser or source reads.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
class Element {
  constructor() { this.events = new Map(); this.children = []; this.dataset = {}; this.style = {}; this.attrs = {}; this.textContent = ''; this.hidden = false; this.classList = { toggle() {} }; }
  addEventListener(name, listener) { if (!this.events.has(name)) this.events.set(name, new Set()); this.events.get(name).add(listener); }
  removeEventListener(name, listener) { this.events.get(name)?.delete(listener); }
  fire(name, event = {}) { for (const listener of this.events.get(name) || []) listener(event); }
  setAttribute(name, value) { this.attrs[name] = value; }
  append(child) { this.children.push(child); }
  contains(target) { return target === this || this.children.some(child => child.contains(target)); }
  closest() { return this.editable ? this : null; }
  focus() { document.activeElement = this; }
  click() { this.clicks = (this.clicks || 0) + 1; this.fire('click'); }
  remove() { this.removed = true; }
  getBoundingClientRect() { return { left: 20, top: 700, width: 460, height: 300 }; }
  getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }
}
const document = new Element();
document.body = new Element();
document.createElement = () => {
  const panel = new Element();
  const fields = new Map();
  panel.querySelector = selector => {
    if (!fields.has(selector)) { const field = new Element(); fields.set(selector, field); panel.append(field); }
    return fields.get(selector);
  };
  return panel;
};
const timers = new Set();
(async () => {
let targetTime = 20;
const requests = [];
const context = {
  Element, document, AbortController, console,
  window: { innerWidth: 1440, innerHeight: 950, setTimeout: () => 1, clearTimeout() {}, setInterval: fn => { timers.add(fn); return fn; }, clearInterval: fn => timers.delete(fn) },
  uiText: zh => zh, withBase: value => value,
  navigator: { clipboard: { writeText: async () => {} } },
  fetch: async url => {
    const bucket = Number(new URL(url, 'http://fixture').searchParams.get('offset_ms')) / 8000;
    requests.push(bucket);
    return { ok: true, json: async () => ({ status: 'ready', bucket, anchor_ms: 1000,
      frames: [{ timestamp_ms: 1000 + bucket * 8000, status: 'ready',
        constraint_id: `raw-id-${bucket}`, object_id: 0, raw: `Complete raw text ${bucket}` }] }) };
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../static/js/text-input.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../static/js/planning-constraints.js'), 'utf8'), context);
const player = new Element(), trigger = new Element(), left = new Element(), right = new Element(), dialog = new Element();
const triggerLabel = new Element();
trigger.querySelector = () => triggerLabel;
dialog.append(player);
let activeDialog = dialog, pickerOpen = false;
document.querySelector = selector => selector === 'dialog[open]' ? activeDialog : pickerOpen ? new Element() : null;
player.dataset = { planningIssue: 'cn_fixture', startOffsetSec: '-20' };
player.append(trigger);
player.closest = selector => selector === 'dialog' ? dialog : null;
player.querySelector = selector => ({ '[data-planning-constraint]': trigger, '[data-video-jump="-1"]': left, '[data-video-jump="1"]': right }[selector]);
const video = { currentTime: 0, readyState: 0, seeking: true, paused: true, duration: 40 };
const binding = context.bindPlanningConstraint(player, video, () => targetTime), panel = dialog.children[1];
assert(panel, 'The expanded panel must remain in its dialog top layer');
const key = (target, name, extra = {}) => {
  const event = { target, key: name, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...extra };
  document.fire('keydown', event);
  return event;
};
assert.equal(key(document.body, 'g').defaultPrevented, true, 'G opens the active player from page focus');
assert.equal(panel.hidden, false);
assert.equal(document.activeElement, panel, 'Opening releases focus from the opener');
assert.equal(triggerLabel.textContent, '规划约束');
assert.equal(trigger.attrs.title, '展开或收起规划约束（G）');
for (const extra of [{ repeat: true }, { ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true }, { isComposing: true }, { keyCode: 229 }, { defaultPrevented: true }]) key(panel, 'g', extra);
assert.equal(panel.hidden, false, 'G ignores held, modified and composition keys');
const input = new Element(); input.editable = true;
assert.equal(key(input, 'g').defaultPrevented, false, 'G never steals text input');
activeDialog = new Element();
assert.equal(key(document.body, 'g').defaultPrevented, false, 'Unrelated modal keeps keyboard ownership');
activeDialog = null;
assert.equal(key(document.body, 'g').defaultPrevented, false, 'A player in a closed modal cannot take G');
activeDialog = dialog;
pickerOpen = true;
assert.equal(key(document.body, 'g').defaultPrevented, false, 'Open shared pickers retain key handling');
pickerOpen = false;
trigger.hidden = true;
assert.equal(key(document.body, 'g').defaultPrevented, false, 'Hidden players cannot take G');
trigger.hidden = false;
await new Promise(setImmediate);
binding.refresh();
assert.equal(key(panel, 'G').defaultPrevented, true);
assert.equal(panel.hidden, true, 'G closes the panel');
assert.equal(document.activeElement, trigger, 'G close restores its opener');
key(trigger, 'g');
assert.equal(panel.hidden, false, 'G reopens from its button');
await new Promise(setImmediate);
binding.refresh();
assert.deepEqual(requests, [0], 'Initial t0 uses the intended timeline, not the undecoded video at zero');
assert.equal(panel.querySelector('[data-pc-value]').textContent, 'raw-id-0', 'Cached text displays before video metadata/decoded frames');
assert.equal(panel.querySelector('[data-pc-object-value]').textContent, '0');
assert.equal(panel.querySelector('[data-pc-raw]').textContent, 'Complete raw text 0');
assert.equal(panel.querySelector('[data-pc-details]').hidden, false);
video.error = { code: 2 };
binding.refresh();
assert.equal(panel.querySelector('[data-pc-value]').textContent, 'raw-id-0', 'A stalled/failed decoder does not hide independent text');
targetTime = 20.3;
binding.refresh();
assert.equal(panel.querySelector('[data-pc-raw]').textContent, '', 'Removing the decoder gate must not bridge missing source frames');
assert.equal(panel.querySelector('[data-pc-facts]').hidden, true);
targetTime = 28;
binding.refresh();
await new Promise(setImmediate);
binding.refresh();
assert.deepEqual(requests, [0, 1]);
assert.equal(panel.querySelector('[data-pc-value]').textContent, 'raw-id-1', 'A pending seek uses its requested window while old video frames remain');
assert.equal(video.currentTime, 0, 'The test never decodes/seeks the video to obtain text');
assert.equal(key(panel, 'ArrowRight').defaultPrevented, true);
assert.equal(right.clicks, 1, 'One key invokes the owning seek control once');
assert.equal(document.activeElement, player);
assert.equal(panel.hidden, false, 'Seeking keeps the panel open');
key(panel.querySelector('[data-pc-copy]'), 'ArrowLeft');
assert.equal(left.clicks, 1, 'Arrows work from the copy control');
for (const extra of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { shiftKey: true }, { isComposing: true }, { keyCode: 229 }, { defaultPrevented: true }]) key(panel, 'ArrowRight', extra);
assert.equal(right.clicks, 1, 'Modified and composition keys retain their native behavior');
const editable = panel.querySelector('[data-fixture-editable]'); editable.editable = true;
assert.equal(key(editable, 'ArrowRight').defaultPrevented, false);
assert.equal(key(new Element(), 'ArrowRight').defaultPrevented, false, 'Other players and page controls are outside this handler');
key(panel.querySelector('[data-pc-close]'), 'Escape');
assert.equal(panel.hidden, true);
assert.equal(trigger.attrs['aria-expanded'], 'false');
assert.equal(document.activeElement, trigger);
key(trigger, 'ArrowRight');
assert.equal(right.clicks, 2, 'Restoring the opener must not trap arrows after closing');
binding.dispose();
assert.equal(panel.removed, true);
assert.equal(timers.size, 0);
key(trigger, 'ArrowRight');
assert.equal(right.clicks, 2, 'Disposal detaches the keyboard handler');
assert.equal(document.events.get('keydown').size, 0);
console.log('PASS G toggle, dialog/visibility/picker/input guards, independent planning text, pending timeline, causal gaps, focus, owner seeking, Escape and disposal');
})().catch(error => { console.error(error); process.exitCode = 1; });
