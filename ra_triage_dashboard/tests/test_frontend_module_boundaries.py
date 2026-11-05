"""Keep classic-script ownership and the shipped loader aligned."""
import collections
import json
import re
import shutil
import subprocess
import unittest

from frontend_js import JS_DIR, MANIFEST_PATH, load_app_entry_js, load_app_js


def manifest_names():
    return [
        line.strip()
        for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class FrontendModuleBoundariesTest(unittest.TestCase):
    def test_every_product_module_is_registered_exactly_once(self):
        names = manifest_names()
        self.assertEqual(len(names), len(set(names)), "duplicate script execution")
        self.assertEqual(set(names), {path.name for path in JS_DIR.glob("*.js")})
        for name in names:
            self.assertRegex(name, r"^[a-z][a-z0-9-]+\.js$")

    def test_shared_global_declarations_have_one_owner(self):
        owners = collections.defaultdict(list)
        declaration = re.compile(
            r"^(?:(?:async )?function|class|const|let|var)\s+([A-Za-z_$][\w$]*)",
            re.MULTILINE,
        )
        for name in manifest_names():
            for symbol in declaration.findall((JS_DIR / name).read_text(encoding="utf-8")):
                owners[symbol].append(name)
        duplicates = {symbol: paths for symbol, paths in owners.items() if len(paths) > 1}
        self.assertEqual(duplicates, {}, "a later script must not override another module")

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_entry_loads_one_classic_bundle_under_both_base_paths(self):
        payload = json.dumps({
            "entry": load_app_entry_js(),
            "body": load_app_js(),
        })
        script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const {entry, body} = JSON.parse(fs.readFileSync(0, 'utf8'));
new vm.Script(body, {filename: 'ordered-frontend.js'});
const version = entry.match(/const CACHE_VERSION = "([^"]+)"/)[1];
for (const base of ['', '/manual']) {
  const events = [];
  const document = {
    createElement: tag => ({tag}),
    head: {appendChild: node => events.push(node)},
    body: {appendChild: node => events.push(node)},
  };
  vm.runInNewContext(entry, {window: {__RA_TRIAGE_BASE__: base}, document});
  assert.equal(events.length, 1, 'module extraction must not add startup requests');
  assert.deepEqual(events[0], {tag: 'script', src: `${base}/static/app-bundle.js?v=${version}`, async: false});
}
"""
        result = subprocess.run(["node", "-e", script], input=payload, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
