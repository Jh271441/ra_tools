"""Review cards display only the current shared Issue conclusion in every mode."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ReviewHumanLabelGalleryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_shared_conclusion_and_mode_and_refresh_behavior(self):
        script=Path(__file__).with_name('review_human_label_gallery.cjs')
        result=subprocess.run(['node',str(script)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
