from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BackgroundCaseUploadTest(unittest.TestCase):
    def test_deferred_save_retry_scoping_and_newer_drafts(self):
        result = subprocess.run(["node", str(ROOT / "tests/background_case_uploads.cjs")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
