"""Independent count semantics and bounded display; no service/database writes."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node is required")
class IncrementPresentationTests(unittest.TestCase):
    def run_js(self, code):
        source = (Path(__file__).parents[1] / "static/js/daily-cron.js").read_text()
        prelude = "const state={uiLanguage:'en'}; const document={addEventListener(){}}; const uiText=(zh,en)=>en; const escapeHtml=x=>String(x);"
        return subprocess.check_output(["node", "-e", prelude + source + code], text=True)

    def test_only_successful_all_known_zero_is_idle(self):
        self.run_js("""
const assert=require('node:assert/strict');
const zero={family:'20261009',scan_state:'success',new:0,filled:0,published:0,target_added:0,target_removed:0};
assert.equal(cronIncrementIdle(zero),true);
for(const scan_state of ['failed','unknown',undefined,'running']) assert.equal(cronIncrementIdle({...zero,scan_state}),false);
for(const k of cronIncrementKeys) for(const value of [null,undefined,NaN,-1,'0',1]) assert.equal(cronIncrementIdle({...zero,[k]:value}),false);
assert.equal(cronIncrementStatus([{scan_state:'unknown'},{scan_state:'failed'}])[0],'fail');
""")

    def test_independent_counts_and_unknown_removal_are_visible(self):
        html = self.run_js("""
console.log(cronIncrementBody([{family:'20261016',scan_state:'success',new:22,filled:103,published:103,target_added:37,target_removed:null}]));
""")
        for value in ["22", "103", "37", "Unknown", "Incomplete data", "Targets removed"]:
            self.assertIn(value, html)
        self.assertNotIn("266", html)
        self.assertNotIn("No changes", html)
        self.assertEqual(html.count("<dt>"), 4)

    def test_rounds_sorted_and_limited_without_mutating_history(self):
        self.run_js("""
const assert=require('node:assert/strict');
const items=Array.from({length:20},(_,i)=>[{start_at:i,family:'20261009'},{start_at:i,family:'20261016'}]).flat();
const before=JSON.stringify(items),rounds=cronIncrementRounds(items);
assert.equal(rounds.length,14);assert.equal(rounds[0][0],'19');assert.equal(rounds[13][0],'6');
assert.equal(rounds[0][1].length,2);assert.equal(JSON.stringify(items),before);
assert.equal(cronIncrementFamily({family:'release-next'}),'release-next');
""")
