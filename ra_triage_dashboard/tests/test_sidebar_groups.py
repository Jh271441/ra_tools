from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


FORMAT_API_JS = (
    Path(__file__).resolve().parents[1] / "static" / "js" / "format-api.js"
).read_text(encoding="utf-8")


class SidebarGroupTest(unittest.TestCase):
    def test_open_state_updates_content_and_accessibility(self) -> None:
        start = FORMAT_API_JS.index('const SIDEBAR_NAV_GROUP_PREFS_KEY')
        end = FORMAT_API_JS.index('function isMobileSidebarViewport', start)
        sidebar_js = FORMAT_API_JS[start:end]
        script = f"""
const assert = require('node:assert/strict');
const classes = new Set();
const classList = {{
  toggle(name, force) {{ force ? classes.add(name) : classes.delete(name); }},
  contains(name) {{ return classes.has(name); }},
  add(name) {{ classes.add(name); }},
  remove(name) {{ classes.delete(name); }},
}};
const toggle = {{ attributes: {{}}, setAttribute(name, value) {{ this.attributes[name] = value; }} }};
const items = {{ hidden: false }};
const group = {{
  dataset: {{ sidebarNavGroup: 'review' }},
  hidden: false,
  classList,
  querySelector(selector) {{
    if (selector === '[data-sidebar-nav-group-toggle]') return toggle;
    if (selector === '[data-sidebar-nav-group-items]') return items;
    return null;
  }},
}};
const document = {{
  querySelectorAll(selector) {{
    if (selector === '[data-sidebar-nav-group]') return [group];
    return [];
  }},
}};
const stored = {{}};
const localStorage = {{
  getItem(key) {{ return stored[key] || null; }},
  setItem(key, value) {{ stored[key] = value; }},
}};
const state = {{ activePage: 'review' }};
{sidebar_js}
setSidebarNavGroupOpen('review', false, {{ persist: false }});
assert.equal(group.classList.contains('is-collapsed'), true);
assert.equal(toggle.attributes['aria-expanded'], 'false');
assert.equal(items.hidden, true);
setSidebarNavGroupOpen('review', true);
assert.equal(group.classList.contains('is-collapsed'), false);
assert.equal(toggle.attributes['aria-expanded'], 'true');
assert.equal(items.hidden, false);
assert.deepEqual(JSON.parse(stored[SIDEBAR_NAV_GROUP_PREFS_KEY]), {{ review: true }});
"""
        subprocess.run(["node", "-e", script], check=True, capture_output=True)

    def test_drawer_tablet_keyboard_focus_and_desktop_preference(self) -> None:
        start = FORMAT_API_JS.index('const SIDEBAR_NAV_GROUP_PREFS_KEY')
        end = FORMAT_API_JS.index('function markUiReady', start)
        sidebar_js = FORMAT_API_JS[start:end] + FORMAT_API_JS[FORMAT_API_JS.index('function toggleSidebar()'):]
        script = r"""
const assert = require('node:assert/strict');
class Node {
  constructor() {
    this.dataset = {}; this.attributes = {}; this.handlers = {}; this.hidden = false;
    this.isConnected = true; this.rects = [{}]; this.classes = new Set();
    this.classList = {
      toggle: (key, on) => on ? this.classes.add(key) : this.classes.delete(key),
      contains: key => this.classes.has(key),
      add: key => this.classes.add(key), remove: key => this.classes.delete(key),
    };
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(key, fn) { (this.handlers[key] ||= []).push(fn); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  getClientRects() { return this.rects; }
  focus() { document.activeElement = this; }
  click() { for (const fn of this.handlers.click || []) fn({preventDefault(){}}); }
}
const shell = new Node(), sidebar = new Node(), brand = new Node(), footer = new Node();
const backdrop = new Node(), frame = new Node(), pageInput = new Node(), label = new Node();
const group = new Node(), toggle = new Node(), items = new Node();
group.dataset = {sidebarNavGroup:'daily', sidebarDefaultOpen:'true'};
toggle.dataset.sidebarNavGroupToggle = 'daily';
toggle.querySelector = selector => ({textContent:selector.endsWith('en') ? 'Daily data' : '每日数据'});
group.querySelector = selector => selector.includes('toggle') ? toggle : items;
shell.querySelector = () => frame;
sidebar.querySelectorAll = () => [brand, toggle, footer];
const elements = {'#appShell':shell, '#appSidebar':sidebar, '#sidebarBrandToggle':brand,
  '#sidebarToggle':footer, '#sidebarToggle .sidebar-label':label, '#mobileSidebarBackdrop':backdrop};
const $ = selector => elements[selector];
const document = {
  documentElement:new Node(), activeElement:pageInput, handlers:{},
  querySelectorAll(selector) {
    return selector === '[data-sidebar-nav-group]' ? [group] :
      selector === '[data-sidebar-nav-group-toggle]' ? [toggle] : [];
  },
  addEventListener(key, fn) { this.handlers[key] = fn; },
};
let width = 722, resize;
const window = {matchMedia: query => ({matches: width <= Number(query.match(/\d+/)[0]),
  addEventListener: (key, fn) => {resize = fn;}})};
const stored = {'ra-triage-sidebar-collapsed':'false'};
const localStorage = {getItem:key=>stored[key]||null, setItem:(key,value)=>stored[key]=value};
const state = {activePage:'version-metrics',uiLanguage:'zh',sidebarCollapsed:false,mobileSidebarOpen:false};
const uiText = (zh,en) => state.uiLanguage === 'en' ? en : zh;
__SIDEBAR_JS__
bindSidebarNavigation(); bindSidebarNavigation();
assert.equal(brand.handlers.click.length, 1);
applySidebarState();
assert.equal(shell.classList.contains('sidebar-collapsed'), true);
assert.equal(brand.attributes['aria-expanded'], 'false');
brand.click();
assert.equal(shell.classList.contains('sidebar-mobile-open'), true);
assert.equal(shell.classList.contains('sidebar-collapsed'), false);
assert.equal(sidebar.attributes['aria-modal'], 'true');
assert.equal(frame.inert, true); assert.equal(backdrop.hidden, false);
assert.equal(document.activeElement, brand);
assert.equal(stored['ra-triage-sidebar-collapsed'], 'false');
// Shift+Tab and Tab wrap inside the drawer; Escape restores its opener.
const key = (key, extra={}) => ({key,preventDefault(){this.defaultPrevented=true},...extra});
handleSidebarKeydown(key('Tab',{shiftKey:true})); assert.equal(document.activeElement, footer);
handleSidebarKeydown(key('Tab')); assert.equal(document.activeElement, brand);
handleSidebarKeydown(key('Escape',{isComposing:true})); assert.equal(state.mobileSidebarOpen, true);
handleSidebarKeydown(key('Escape',{defaultPrevented:true})); assert.equal(state.mobileSidebarOpen, true);
handleSidebarKeydown(key('Escape'));
assert.equal(document.activeElement, pageInput); assert.equal(frame.inert, false);
assert.equal(backdrop.hidden, true); assert.equal(sidebar.attributes['aria-modal'], undefined);
// A compact category opens the full drawer and the selected group.
setSidebarNavGroupOpen('daily',false,{persist:false});
toggle.focus(); toggle.click();
assert.equal(state.mobileSidebarOpen,true); assert.equal(items.hidden,false);
assert.equal(document.activeElement,toggle);
backdrop.click(); assert.equal(state.mobileSidebarOpen,false); assert.equal(document.activeElement,toggle);
// Phone, tablet and desktop transitions restore the saved desktop state.
width=390;resize();brand.click();
state.uiLanguage='en';applySidebarState();
assert.equal(brand.attributes['aria-label'],'Close navigation');
assert.equal(toggle.attributes['aria-label'],'Daily data');
width=1440;resize();
assert.equal(state.mobileSidebarOpen,false);assert.equal(frame.inert,false);
assert.equal(shell.classList.contains('sidebar-collapsed'),false);
assert.equal(document.documentElement.classList.contains('mobile-sidebar-open'),false);
brand.click();assert.equal(state.sidebarCollapsed,true);
assert.equal(stored['ra-triage-sidebar-collapsed'],'true');
width=1200;resize();brand.click();width=1201;resize();
assert.equal(shell.classList.contains('sidebar-collapsed'),true);
assert.equal(stored['ra-triage-sidebar-collapsed'],'true');
toggle.click();assert.equal(state.sidebarCollapsed,false);assert.equal(items.hidden,false);
assert.equal(stored['ra-triage-sidebar-collapsed'],'false');
// A removed or hidden opener falls back to the persistent menu button.
width=320;resize();pageInput.focus();brand.click();pageInput.rects=[];backdrop.click();
assert.equal(document.activeElement,brand);
""".replace("__SIDEBAR_JS__", sidebar_js)
        result = subprocess.run(["node"], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
