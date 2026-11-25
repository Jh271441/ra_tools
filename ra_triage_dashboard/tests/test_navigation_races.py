"""Deterministic deferred responses reproduce cross-page frontend navigation races."""
import subprocess
from pathlib import Path


def test_async_view_ownership_and_slow_session_navigation():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(["node", str(Path(__file__).with_name("navigation_races.cjs"))], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
