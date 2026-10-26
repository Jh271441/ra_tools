from pathlib import Path
import subprocess


def test_trail_history_detail_ui():
    subprocess.run(['node', str(Path(__file__).with_name('trail_history_detail_ui.cjs'))], check=True)
