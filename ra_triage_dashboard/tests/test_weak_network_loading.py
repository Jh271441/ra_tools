from pathlib import Path
import subprocess


def test_weak_network_loading_and_cancellation():
    result = subprocess.run(['node', str(Path(__file__).with_name('weak_network_loading.cjs'))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
