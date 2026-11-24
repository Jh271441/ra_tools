"""Ensure a failed migration cannot resume both sets of writers."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import migrate


class FailureRecoveryTests(unittest.TestCase):
    def exercise(
        self,
        fail_transfer=False,
        status_output="api RUNNING\nworker RUNNING\nrelease-worker RUNNING\nlabel-worker RUNNING\nevaluation-worker RUNNING\nweb RUNNING\npostgres RUNNING\nredis RUNNING\n",
    ):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[0] == "scp" and fail_transfer:
                raise subprocess.CalledProcessError(1, args)
            command = args[-1]
            out = ""
            if command.endswith(" status"):
                out = status_output
            elif command.endswith(" backup"):
                out = "/srv/source/backups/test.sql\n"
            elif "tarfile" in command:
                out = "/srv/source/backups/source.tar.gz\n"
            return SimpleNamespace(stdout=out)

        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "source.json"
            config.write_text(json.dumps({"ssh": "example", "root": "/srv/source"}))
            with (
                patch.object(migrate.subprocess, "run", side_effect=run),
                patch.object(
                    migrate,
                    "deploy",
                    side_effect=RuntimeError("target partially started"),
                ),
            ):
                with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                    migrate.main(config, "target.json")
        return [a[-1] for a in calls if a[0] == "ssh"]

    def test_partial_target_failure_keeps_source_frozen(self):
        commands = self.exercise()
        self.assertFalse(any(" start " in c for c in commands))
        stop_cmd = next(c for c in commands if " stop " in c)
        for prog in ("api", "worker", "release-worker", "label-worker", "evaluation-worker", "web"):
            self.assertIn(prog, stop_cmd)
        self.assertNotIn("postgres", stop_cmd)
        self.assertNotIn("redis", stop_cmd)

    def test_transfer_failure_before_target_attempt_resumes_source(self):
        commands = self.exercise(fail_transfer=True)
        start_cmd = next(c for c in commands if " start " in c)
        for prog in ("api", "release-worker", "label-worker", "evaluation-worker", "web"):
            self.assertIn(prog, start_cmd)


if __name__ == "__main__":
    unittest.main()
