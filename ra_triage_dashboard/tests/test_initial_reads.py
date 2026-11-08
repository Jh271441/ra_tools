from pathlib import Path
import subprocess


def test_initial_reads_keep_normal_authentication_and_retry_guards():
    result = subprocess.run(['node', str(Path(__file__).with_name('initial_reads.cjs'))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
