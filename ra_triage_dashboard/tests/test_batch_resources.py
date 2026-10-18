from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ra_triage_dashboard.app.batch_resources import BatchResourceGuard
from ra_triage_dashboard.app.batch_prediction_runner import BatchPredictionRunner


def policy(**updates):
    values = {
        "DASHBOARD_BATCH_RESOURCE_GUARD": "true",
        "DASHBOARD_BATCH_RSS_BYTES": str(256 * 1024**2),
        "DASHBOARD_BATCH_ADDRESS_SPACE_BYTES": str(512 * 1024**2),
        "DASHBOARD_BATCH_SCRATCH_BYTES": str(16 * 1024**2),
        "DASHBOARD_BATCH_MIN_FREE_BYTES": "1",
        "DASHBOARD_BATCH_MAX_WORKERS": "1",
    }
    values.update(updates)
    return values


pytestmark = pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="Linux resource guard")


def test_invalid_policy_rejects_before_spawn(tmp_path):
    with patch.dict(os.environ, policy(DASHBOARD_BATCH_RSS_BYTES="bad")):
        with pytest.raises(RuntimeError, match="RSS_BYTES"):
            BatchResourceGuard(tmp_path)


def test_cross_runner_lock(tmp_path):
    with patch.dict(os.environ, policy()), BatchResourceGuard(tmp_path):
        with pytest.raises(BlockingIOError):
            with BatchResourceGuard(tmp_path):
                pytest.fail("second runner acquired shared scratch")
    with patch.dict(os.environ, policy()), BatchResourceGuard(tmp_path):
        pass


def test_existing_scratch_and_low_free_space_prevent_launch(tmp_path):
    (tmp_path / "existing").write_bytes(b"x" * 2048)
    with patch.dict(os.environ, policy(DASHBOARD_BATCH_SCRATCH_BYTES="1024")):
        with pytest.raises(RuntimeError, match="scratch"):
            with BatchResourceGuard(tmp_path):
                pytest.fail("overfull scratch accepted")
    with patch.dict(os.environ, policy()), patch(
        "ra_triage_dashboard.app.batch_resources.shutil.disk_usage",
        return_value=SimpleNamespace(free=0),
    ):
        with pytest.raises(RuntimeError, match="磁盘"):
            with BatchResourceGuard(tmp_path):
                pytest.fail("low disk accepted")


def runner_script(tmp_path, source):
    scripts = tmp_path / "app/scripts"
    scripts.mkdir(parents=True)
    (scripts / "run_batch_worker.sh").write_text(
        'exec "$DASHBOARD_PYTHON_BIN" - <<\'PY\'\n' + source + "\nPY\n"
    )
    settings = SimpleNamespace(
        ra_auto_triage_root=tmp_path / "ra", batch_bag_cache_dir=tmp_path / "cache",
        app_root=tmp_path / "app", jobs_dir=tmp_path / "jobs", batch_job_timeout_seconds=10,
    )
    return BatchPredictionRunner(settings, None)


@pytest.mark.parametrize("close_output", [False, True])
def test_runner_kills_memory_hog_even_after_stdout_eof(tmp_path, close_output):
    source = "import os,time\n"
    if close_output:
        source += "os.close(1);os.close(2)\n"
    source += "if os.fork() == 0:\n data = bytearray(64*1024**2)\n time.sleep(30)\nelse:\n time.sleep(30)"
    runner = runner_script(tmp_path, source)
    with patch.dict(os.environ, policy(DASHBOARD_BATCH_RSS_BYTES=str(32*1024**2))):
        with pytest.raises(RuntimeError, match="进程组内存"):
            runner._run_worker(job_id="memory", action="inspect", payload={})
    assert runner._active_process.poll() is not None


def test_runner_kills_scratch_hog(tmp_path):
    runner = runner_script(tmp_path, "import os,time\nfrom pathlib import Path\nPath(os.environ['TMPDIR'],'huge').write_bytes(b'x'*4096)\ntime.sleep(30)")
    with patch.dict(os.environ, policy(DASHBOARD_BATCH_SCRATCH_BYTES="2048")):
        with pytest.raises(RuntimeError, match="scratch"):
            runner._run_worker(job_id="disk", action="inspect", payload={})


def test_guard_environment_and_symlink_refusal(tmp_path):
    with patch.dict(os.environ, policy()), BatchResourceGuard(tmp_path) as guard:
        env = guard.environment()
        assert env["DASHBOARD_BATCH_MAX_WORKERS"] == "1"
        assert int(env["DASHBOARD_BATCH_ADDRESS_SPACE_KIB"]) == 512 * 1024
    (tmp_path / ".worker-tmp").rmdir()
    (tmp_path / ".worker-tmp").symlink_to(tmp_path / "elsewhere")
    with patch.dict(os.environ, policy()), BatchResourceGuard(tmp_path) as guard:
        with pytest.raises((RuntimeError, FileExistsError)):
            guard.environment()


def test_launcher_hard_memory_limit(tmp_path):
    scripts = Path(__file__).parents[1] / "scripts/run_batch_worker.sh"
    setup = tmp_path / "setup.sh"
    setup.write_text(f'"{sys.executable}" -c "bytearray(128*1024**2)"\n')
    (tmp_path / "vlm").mkdir()
    result = subprocess.run(["bash", str(scripts)], env={
        **os.environ, "DASHBOARD_BATCH_ADDRESS_SPACE_KIB": str(64 * 1024),
        "VOYAGER_SETUP_SCRIPT": str(setup), "RA_AUTO_TRIAGE_ROOT": str(tmp_path),
        "DASHBOARD_PYTHON_BIN": sys.executable,
    }, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert b"MemoryError" in result.stderr
