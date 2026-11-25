import subprocess
import unittest
from pathlib import Path


class VideoPerformanceTest(unittest.TestCase):
    def test_media_lifecycle_and_progressive_loading(self):
        root = Path(__file__).resolve().parents[2]
        subprocess.run(['node', 'ra_triage_dashboard/tests/video_performance.cjs'], cwd=root, check=True, capture_output=True)
