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
    def exercise(self, fail_transfer=False):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[0] == "scp" and fail_transfer:
                raise subprocess.CalledProcessError(1, args)
            command = args[-1]
            out = ""
            if command.endswith(" status"):
                out = "api RUNNING\nworker RUNNING\nweb RUNNING\n"
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
        self.assertFalse(any(" start " in c for c in self.exercise()))

    def test_transfer_failure_before_target_attempt_resumes_source(self):
        self.assertTrue(any(" start " in c for c in self.exercise(fail_transfer=True)))


if __name__ == "__main__":
    unittest.main()
