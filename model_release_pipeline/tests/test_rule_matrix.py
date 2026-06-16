"""Tests for the Rule Patch matrix workflow."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from model_release_pipeline.config import default_config
from model_release_pipeline.onboard import rule_matrix
from model_release_pipeline.rule_patch_cache import get_cached_cr
from model_release_pipeline.services.voyager_handoff import (
    VoyagerHandoffService,
    extract_revision_id,
)
from model_release_pipeline.state_store import StateStore


def _noop_progress(*_args, **_kwargs) -> None:
    pass


def _yes(_prompt: str, _assume_yes: bool) -> bool:
    return True


class ExtractRevisionTest(unittest.TestCase):
    def test_parses_revision_link(self) -> None:
        stdout = (
            "Waiting for git push to complete\n"
            "Dcl call kunpeng API to create or update your revision\n"
            "Your revision link: https://kunpeng.xiaojukeji.com/view/revision/6239029\n"
        )
        self.assertEqual(extract_revision_id(stdout), "6239029")

    def test_no_revision_returns_empty(self) -> None:
        self.assertEqual(extract_revision_id("nothing here"), "")


class RuleSetupTest(unittest.TestCase):
    def test_setup_builds_matrix_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = default_config()
            config.runs_dir = Path(tmp) / "runs"
            store = StateStore(config.runs_dir)
            args = argparse.Namespace(
                revision_id="6231959",
                rule_name="FN_forcing_recall",
                branch_prefix="jasperchen",
                release=["gen4_release_20260508", "gen4_release_20260515"],
                releases=None,
                desc="",
                workflow_type="rule_patch",
                yes=True,
                dry_run=True,
            )
            record = rule_matrix.run_rule_setup(
                args, config, store, None, progress=_noop_progress, confirm=_yes
            )
            self.assertEqual(record["metadata"]["workflow_type"], "rule_patch")
            self.assertEqual(record["rule_patch"]["revision_id"], "6231959")
            self.assertEqual(len(record["releases"]), 2)
            self.assertEqual(
                record["releases"][0]["working_branch"],
                "jasperchen/gen4_release_20260508/FN_forcing_recall",
            )
            # Persisted to disk and reloadable.
            reloaded = store.load(record["release_id"])
            self.assertEqual(len(reloaded["releases"]), 2)


class RuleReleaseTest(unittest.TestCase):
    def _stub_service(self):
        class StubService:
            def __init__(self, _voyager):
                pass

            def branch_prep_to_docker(self, **kwargs):
                return {"returncode": 0, "dry_run": kwargs.get("dry_run"), "stdout": "", "stderr": ""}

            def dcl_patch_to_docker(self, **kwargs):
                return {
                    "returncode": 0,
                    "dry_run": kwargs.get("dry_run"),
                    "revision_id": kwargs["revision_id"],
                    "stdout": "",
                    "stderr": "",
                }

            def rule_dcl_diff_to_docker(self, **kwargs):
                rev = kwargs.get("test_cr_revision") or ""
                if rev:
                    cmd = f"dcl diff -n -u {rev} --nolint"
                    rid = rev
                else:
                    cmd = f"dcl diff -c -n -d {kwargs['base_branch']} --nolint"
                    rid = "" if kwargs.get("dry_run") else "6239029"
                return {
                    "returncode": 0,
                    "dry_run": kwargs.get("dry_run"),
                    "command": cmd,
                    "revision_id": rid,
                    "stdout": "",
                    "stderr": "",
                }

        return StubService

    def test_validate_creates_then_reuses_cr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = default_config()
            config.runs_dir = Path(tmp) / "runs"
            store = StateStore(config.runs_dir)
            setup_args = argparse.Namespace(
                revision_id="6231959", rule_name="rule", branch_prefix="jc",
                release=["gen4_release_20260508"], releases=None, desc="",
                workflow_type="rule_patch", yes=True, dry_run=True,
            )
            record = rule_matrix.run_rule_setup(
                setup_args, config, store, None, progress=_noop_progress, confirm=_yes
            )
            stub = self._stub_service()

            # First validate (real): creates the CR and caches the revision.
            v1 = argparse.Namespace(
                run_id=record["release_id"], release="gen4_release_20260508",
                release_index=None, docker="c", dry_run=False, yes=True,
            )
            record = rule_matrix.run_rule_release(
                v1, config, store, store.load(record["release_id"]),
                progress=_noop_progress, confirm=_yes, service_cls=stub,
            )
            entry = record["releases"][0]
            self.assertIn("-c -n -d gen4_release_20260508", entry["dcl"]["command"])
            self.assertEqual(entry["test_cr_revision"], "6239029")
            self.assertEqual(entry["status"], "completed")
            self.assertEqual(get_cached_cr(config.runs_dir, "gen4_release_20260508"), "6239029")

            # Second validate (real): reuses the cached revision via -u.
            v2 = argparse.Namespace(
                run_id=record["release_id"], release="gen4_release_20260508",
                release_index=None, docker="c", dry_run=False, yes=True,
            )
            record = rule_matrix.run_rule_release(
                v2, config, store, store.load(record["release_id"]),
                progress=_noop_progress, confirm=_yes, service_cls=stub,
            )
            self.assertIn("-n -u 6239029", record["releases"][0]["dcl"]["command"])


class RuleDclDiffServiceTest(unittest.TestCase):
    def test_command_shape_and_revision_capture(self) -> None:
        captured = {}

        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            captured["command"] = list(command)
            return subprocess.CompletedProcess(
                args=list(command),
                returncode=0,
                stdout="Your revision link: https://k/view/revision/6239069\n",
                stderr="",
            )

        config = default_config()
        config.ifx.truck_docker_container = "voyager-dev"
        service = VoyagerHandoffService(config.voyager, command_runner=fake_runner)
        result = service.rule_dcl_diff_to_docker(
            ifx_config=config.ifx,
            base_branch="gen4_release_20260515",
            working_branch="jc/gen4_release_20260515/rule",
            test_cr_revision="",
            container="voyager-dev",
            dry_run=False,
        )
        joined = " ".join(captured["command"])
        self.assertIn("git checkout jc/gen4_release_20260515/rule", joined)
        self.assertIn("dcl diff -c -n -d gen4_release_20260515 --nolint", joined)
        self.assertEqual(result["revision_id"], "6239069")


if __name__ == "__main__":
    unittest.main()
