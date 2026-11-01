from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlanningFrontendTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node unavailable')
    def test_panel_keyboard_routes_to_its_owner_and_disposes(self):
        subprocess.run(
            ['node', str(ROOT/'tests/planning_constraint_keyboard.cjs')],
            check=True, capture_output=True, text=True,
        )

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable')
    def test_frame_matching_is_publish_time_causal_and_bounded(self):
        source = (ROOT/'static/js/planning-constraints.js').read_text()
        program = source + '''
const assert = require('node:assert/strict');
const frames = [{timestamp_ms:1000,status:'ready',constraint_id:'raw-id'}, {timestamp_ms:1100,status:'no_constraint'}];
assert.equal(planningConstraintAt(frames, 999), null);
assert.equal(planningConstraintAt(frames, 1099).constraint_id, 'raw-id');
assert.equal(planningConstraintAt(frames, 1100).status, 'no_constraint');
assert.equal(planningConstraintAt(frames, 1250).status, 'no_constraint');
assert.equal(planningConstraintAt(frames, 1251), null);
assert.equal(planningConstraintAt([], 1100), null);
'''
        subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)

    def test_issue_lifecycle_raw_output_and_click_contract(self):
        source = (ROOT/'static/js/planning-constraints.js').read_text()
        self.assertIn("setText('value', copyValue || message)", source)
        self.assertIn("generation !== epoch", source)
        self.assertIn("controller?.abort()", source)
        self.assertIn("panel.remove()", source)
        self.assertIn("event.key === 'Escape'", source)
        self.assertNotIn("video.seeking", source)
        self.assertNotIn("video.readyState", source)
        self.assertNotIn('mouseenter', source)
        self.assertNotIn('model_run', source)
        media = (ROOT/'static/js/detail-media.js').read_text()
        self.assertIn('tracks.length > 1 && !compact', media)
        self.assertIn('planningConstraint.dispose()', media)
        self.assertIn('detailMediaSelectedKind(caseData)', media)
