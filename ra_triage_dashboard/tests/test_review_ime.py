from pathlib import Path
import subprocess
import unittest


class ReviewImeTest(unittest.TestCase):
    def test_ime_and_focused_form_survive_shortcuts_and_collaboration(self):
        subprocess.run(["node", str(Path(__file__).with_name("review_ime.cjs"))], check=True)
