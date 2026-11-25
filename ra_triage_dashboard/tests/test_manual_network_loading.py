"""Exercise foreground requests and background media lifecycle in actual JS."""
from pathlib import Path
import subprocess


def test_manual_network_loading_lifecycle():
    script = Path(__file__).with_name('manual_network_loading.cjs')
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
