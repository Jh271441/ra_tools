import shutil
import subprocess
import unittest
from pathlib import Path


class VersionLoadingTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_filter_reads_and_cache_lifecycle(self):
        result = subprocess.run(['node', 'ra_triage_dashboard/tests/version_loading.cjs'],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
