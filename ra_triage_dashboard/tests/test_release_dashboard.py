"""Local one-command Dashboard release entrypoint tests."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "release_dashboard",
    Path(__file__).parents[1] / "scripts/release_dashboard.py",
)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ReleaseDashboardTests(unittest.TestCase):
    def test_default_action_runs_exact_origin_master_release(self):
        target = "a" * 40
        deployer = b"print('versioned deployer')\n"
        with patch.object(r, "resolve_target", return_value=target) as resolve, \
             patch.object(r, "exact_deployer", return_value=deployer), \
             patch.object(r, "run_remote", return_value=0) as remote:
            self.assertEqual(r.main([]), 0)

        resolve.assert_called_once_with(None)
        self.assertEqual(
            remote.call_args.args,
            (r.DEFAULT_HOST, r.DEFAULT_REMOTE_REPO, ["--sha", target], deployer),
        )

    def test_prepare_and_promote_arguments_are_explicit(self):
        target = "b" * 40
        prepare = r.parse_args(["--prepare", "--allow-additive-migrations"])
        self.assertEqual(
            r.deployer_args(prepare, target),
            ["--sha", target, "--prepare", "--allow-additive-migrations"],
        )
        promote = r.parse_args(["--promote", "20260916T073312Z-bbbbbbbbbbbb"])
        self.assertEqual(
            r.deployer_args(promote, target),
            ["--sha", target, "--promote", "20260916T073312Z-bbbbbbbbbbbb"],
        )

    def test_local_deployer_must_match_pushed_version(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            local = repo / r.DEPLOYER_PATH
            local.parent.mkdir(parents=True)
            local.write_bytes(b"local")
            with patch.object(r, "REPO", repo), patch.object(r, "git_bytes", return_value=b"remote"):
                with self.assertRaises(r.ReleaseError):
                    r.exact_deployer("a" * 40)

    def test_destination_rejects_ssh_option_and_parent_escape(self):
        for host, path in (("-oProxyCommand=bad", r.DEFAULT_REMOTE_REPO), (r.DEFAULT_HOST, "/volume/../tmp")):
            with self.assertRaises(r.ReleaseError):
                r.validate_destination(host, path)

    def test_remote_bootstrap_executes_a_real_temporary_file(self):
        deployer = b"import pathlib, sys\nprint(pathlib.Path(__file__).is_file(), sys.argv[1:])\n"
        with tempfile.TemporaryDirectory() as temp:
            completed = subprocess.run(
                [sys.executable, "-c", r.REMOTE_BOOTSTRAP, temp, "--sha", "a" * 40],
                input=deployer,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(completed.stdout.decode().strip(), "True ['--sha', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa']")


if __name__ == "__main__":
    unittest.main()
