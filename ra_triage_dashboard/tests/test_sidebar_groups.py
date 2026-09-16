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
