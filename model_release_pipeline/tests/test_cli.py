"""Tests for CLI selection helpers."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from model_release_pipeline.config import default_config
from model_release_pipeline.onboard.export import (
    run_export,
    select_candidate,
    select_manual_epoch_candidate,
)
from model_release_pipeline.onboard.upload import validate_upload_binding
from model_release_pipeline.output import format_pick_result, format_record_result
from model_release_pipeline.services.experiment import ExperimentInspector
from model_release_pipeline.state_store import StateStore
import model_release_pipeline.steps.runner as runner_module
from model_release_pipeline.steps.runner import (
    _run_apply_handoff,
    _run_dcl,
    _run_ifx_convert,
    _run_offboard,
    _run_sim_plan,
)


class CliSelectionTest(unittest.TestCase):
    def test_selects_recommended_epoch_for_requested_task(self) -> None:
        pick_result = {
            "per_task": {
                "stuck_detect": {
                    "recommended_epoch": 0,
                    "all_candidates": [{"epoch": 0, "task": "stuck_detect"}],
                },
                "stuck_detect_neg_no_assist": {
                    "recommended_epoch": 41,
                    "all_candidates": [
                        {"epoch": 41, "task": "stuck_detect_neg_no_assist"}
                    ],
                },
            },
            "recommended_epoch": None,
            "all_candidates": [],
        }

        selected = select_candidate(
            pick_result,
            "/tmp/exp",
            epoch=None,
            task="stuck_detect_neg_no_assist",
        )

        self.assertEqual(selected["epoch"], 41)
        self.assertEqual(selected["task"], "stuck_detect_neg_no_assist")

    def test_requires_task_or_epoch_for_multi_task(self) -> None:
        pick_result = {
            "per_task": {
                "task_a": {"recommended_epoch": 0, "all_candidates": []},
                "task_b": {"recommended_epoch": 1, "all_candidates": []},
            },
            "recommended_epoch": None,
            "all_candidates": [],
        }

        with self.assertRaisesRegex(RuntimeError, "--task or --epoch"):
            select_candidate(pick_result, "/tmp/exp", epoch=None)

    def test_formats_pick_result_without_full_json_dump(self) -> None:
        pick_result = {
            "policy": "precision_first",
            "top_n": 1,
            "tasks": ["stuck_detect"],
            "recommended_epoch": 3,
            "notes": [],
            "per_task": {
                "stuck_detect": {
                    "recommended_epoch": 3,
                    "candidates": [
                        {
                            "epoch": 3,
                            "precision": 0.8,
                            "recall": 0.7,
                            "pr_auc": 0.9,
                            "roc_auc": 0.95,
                        }
                    ],
                    "all_candidates": [
                        {
                            "epoch": 3,
                            "precision": 0.8,
                            "recall": 0.7,
                            "pr_auc": 0.9,
                            "roc_auc": 0.95,
                        }
                    ],
                }
            },
        }

        text = format_pick_result(pick_result)

        self.assertIn("===== stuck_detect: Top 1 by roc_auc =====", text)
        self.assertIn("Recommended epoch: 003", text)
        self.assertNotIn("checkpoint_path", text)

    def test_select_manual_epoch_candidate_uses_checkpoint_directly(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "exp"
            (root / "checkpoints" / "version_0").mkdir(parents=True)
            (root / "log" / "version_0").mkdir(parents=True)
            checkpoint = root / "checkpoints" / "version_0" / "epoch=007.pth"
            checkpoint.write_text("", encoding="utf-8")
            experiment = ExperimentInspector().inspect(root)

            selected = select_manual_epoch_candidate(experiment, str(root), 7)

            self.assertEqual(selected["epoch"], 7)
            self.assertEqual(selected["sources"], ["manual_epoch"])
            self.assertEqual(selected["checkpoint_path"], checkpoint)

    def test_formats_export_record_as_human_summary(self) -> None:
        record = {
            "release_id": "run123",
            "stage": "export_failed",
            "status": "failed",
            "experiment": {"name": "exp_a"},
            "selection": {
                "selected_epoch": 7,
                "selection_source": "manual_epoch",
            },
            "export": {
                "local_onnx_file": "/tmp/vectorized_scenario_remote_assist_model.onnx",
                "remote_onnx_file": "/nfs/exp/export/epoch=007/model.onnx",
                "export": {
                    "returncode": 1,
                    "stderr": "line1\nModuleNotFoundError: No module named 'utils'",
                },
                "scp": {
                    "returncode": None,
                    "stderr": "Skipped because remote export failed.",
                },
            },
        }

        text = format_record_result(record)

        self.assertIn("release_id: run123", text)
        self.assertIn("selected epoch: 007", text)
        self.assertIn("remote export: FAILED(1)", text)
        self.assertIn("scp onnx: SKIPPED", text)
        self.assertIn("ModuleNotFoundError", text)
        self.assertNotIn('"checkpoints"', text)

    def test_draft_export_dry_run_does_not_create_release_record(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            exp = root / "exp"
            (exp / "checkpoints" / "version_0").mkdir(parents=True)
            (exp / "log" / "version_0").mkdir(parents=True)
            (exp / "checkpoints" / "version_0" / "epoch=004.pth").write_text(
                "",
                encoding="utf-8",
            )
            (exp / "log" / "version_0" / "hparams.yaml").write_text(
                "trained_model_relative_path: old.pth\n",
                encoding="utf-8",
            )
            config = default_config()
            config.runs_dir = root / "runs"
            store = StateStore(config.runs_dir)

            class FakeRunner:
                def __init__(self, _config):
                    pass

                def export_onnx(self, **kwargs):
                    return {
                        "local_onnx_file": str(kwargs["local_output_dir"] / "model.onnx"),
                        "export": {"returncode": None, "stderr": "dry-run"},
                        "scp": {"returncode": None, "stderr": "dry-run"},
                    }

            args = argparse.Namespace(
                experiment=str(exp),
                remote=None,
                remote_python=None,
                epoch=4,
                policy=None,
                top_n=None,
                loss_tolerance_pct=None,
                task=None,
                desc="preview",
                dry_run=True,
                yes=True,
                json=True,
            )

            record = run_export(
                args,
                config,
                store,
                progress=lambda *_args: None,
                confirm=lambda _prompt, _yes: True,
                format_epoch=lambda epoch: f"{int(epoch):03d}",
                luban_runner_cls=FakeRunner,
            )

            self.assertEqual(record["release_id"], "__dry_run_export__")
            self.assertEqual(record["stage"], "export_dry_run")
            self.assertEqual(store.list_records(), [])

    def test_upload_binding_rejects_version_change_without_replace(self) -> None:
        record = {
            "ifx": {
                "onnx": {
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 65,
                }
            }
        }
        args = argparse.Namespace(version=66, replace_upload=False)

        with self.assertRaisesRegex(RuntimeError, "version 65; requested version 66"):
            validate_upload_binding(args, record)

    def test_upload_binding_allows_explicit_replace(self) -> None:
        record = {"ifx": {"onnx": {"name": "model.onnx", "version": 65}}}
        args = argparse.Namespace(version=66, replace_upload=True)

        validate_upload_binding(args, record)

    def test_upload_binding_ignores_previous_dry_run_binding(self) -> None:
        record = {
            "stage": "ifx_upload_dry_run",
            "ifx": {
                "onnx": {"name": "model.onnx", "version": 0},
                "truck_runner": {"selected": "dry_run"},
            },
        }
        args = argparse.Namespace(version=None, replace_upload=False)

        validate_upload_binding(args, record)

    def test_apply_handoff_without_branch_applies_all_configured_branches(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            config.ifx.truck_docker_container = "voyager-dev"
            config.voyager.branches = config.voyager.branches[:2]
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["experiment"] = {"name": "exp"}
            record["selection"] = {"selected_epoch": 7}
            record["ifx"] = {
                "ifx_mapping": {
                    "onnx": {"name": "model.onnx", "version": 65},
                    "fp32_x86": {"name": "model.ifxmodel", "version": 1},
                }
            }
            store.save(record)
            calls = []

            class FakeService:
                def __init__(self, _config):
                    pass

                def apply_to_docker(self, **kwargs):
                    calls.append(kwargs["branch"])
                    return {
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                        "branch": kwargs["branch"],
                        "checkout_branch": kwargs["branch"],
                        "dcl_commands": [f"dcl diff {kwargs['branch']}"],
                    }

            original_service = runner_module.VoyagerHandoffService
            original_confirm = runner_module._confirm
            try:
                runner_module.VoyagerHandoffService = FakeService
                runner_module._confirm = lambda _prompt, _yes: True
                args = argparse.Namespace(
                    branch=None,
                    yes=True,
                    json=True,
                    desc="",
                    docker="",
                    dry_run=False,
                    no_commit=False,
                    allow_dirty=False,
                    allow_append=False,
                )

                updated = _run_apply_handoff(args, config, store, record)
            finally:
                runner_module.VoyagerHandoffService = original_service
                runner_module._confirm = original_confirm

            self.assertEqual(calls, ["master", "gen4_release_20260403"])
            self.assertEqual(updated["apply_handoff"]["returncode"], 0)
            self.assertEqual(len(updated["apply_handoff"]["results"]), 2)

    def test_dcl_uses_temporary_branch_override(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            store.save(record)
            captured = {}

            class FakeService:
                def __init__(self, voyager_config):
                    captured["voyager_config"] = voyager_config

                def dcl_to_docker(self, **kwargs):
                    branch = captured["voyager_config"].branches[0]
                    return {
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                        "branch": kwargs["branch"],
                        "checkout_branch": branch.checkout_branch,
                        "update_diff_ids": branch.effective_diff_ids(),
                        "command": "dcl diff -n -u 123 --nolint",
                    }

            original_service = runner_module.VoyagerHandoffService
            original_confirm = runner_module._confirm
            try:
                runner_module.VoyagerHandoffService = FakeService
                runner_module._confirm = lambda _prompt, _yes: True
                args = argparse.Namespace(
                    branch="master",
                    yes=True,
                    json=True,
                    docker="",
                    dry_run=True,
                    lint=False,
                    allow_dirty=True,
                    checkout_branch="jasperchen/tmp_release",
                    update_diff_ids="123",
                    sim_plan="sim_tmp",
                )

                updated = _run_dcl(args, config, store, record)
            finally:
                runner_module.VoyagerHandoffService = original_service
                runner_module._confirm = original_confirm

            self.assertEqual(updated["dcl"]["checkout_branch"], "jasperchen/tmp_release")
            self.assertEqual(updated["dcl"]["update_diff_ids"], [123])
            self.assertIn("dcl diff -n -u 123 --nolint", updated["dcl"]["command"])

    def test_dcl_pins_to_apply_handoff_commit(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            config.voyager.branches = config.voyager.branches[:2]
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["stage"] = "apply_handoff_complete"
            record["apply_handoff"] = {
                "returncode": 0,
                "results": [
                    {
                        "branch": "master",
                        "checkout_branch": "jasperchen/2026Q1_test_scenario_dnn_dev",
                        "commit": "d9d1b574779",
                    },
                    {
                        "branch": "gen4_release_20260403",
                        "checkout_branch": "jasperchen/gen4_release_20260403/scenario_dnn_dev",
                        "stdout": (
                            "[jasperchen/gen4_release_20260403/scenario_dnn_dev "
                            "075e24f0729] V74. exp\n"
                        ),
                    },
                ],
            }
            store.save(record)
            calls = []

            class FakeService:
                def __init__(self, _config):
                    pass

                def dcl_to_docker(self, **kwargs):
                    calls.append(kwargs)
                    return {
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                        "branch": kwargs["branch"],
                        "source_commit": kwargs["source_commit"],
                        "temp_branch": kwargs["temp_branch"],
                        "command": "dcl diff",
                    }

            original_service = runner_module.VoyagerHandoffService
            original_confirm = runner_module._confirm
            try:
                runner_module.VoyagerHandoffService = FakeService
                runner_module._confirm = lambda _prompt, _yes: True
                args = argparse.Namespace(
                    branch=None,
                    yes=True,
                    json=True,
                    docker="",
                    dry_run=True,
                    lint=False,
                    allow_dirty=True,
                    checkout_branch="",
                    update_diff_ids="",
                    sim_plan="",
                )

                updated = _run_dcl(args, config, store, record)
            finally:
                runner_module.VoyagerHandoffService = original_service
                runner_module._confirm = original_confirm

            self.assertEqual(calls[0]["source_commit"], "d9d1b574779")
            self.assertIn(record["release_id"], calls[0]["temp_branch"])
            self.assertIn("master", calls[0]["temp_branch"])
            self.assertEqual(calls[1]["source_commit"], "075e24f0729")
            self.assertEqual(updated["dcl"]["results"][0]["source_commit"], "d9d1b574779")

    def test_sim_plan_uses_single_dcl_revision_for_multiple_plans(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["stage"] = "dcl_complete"
            record["dcl"] = {
                "returncode": 0,
                "results": [
                    {
                        "branch": "gen4_release_20260206",
                        "update_diff_ids": [6106765],
                    }
                ],
            }
            store.save(record)
            calls = []

            class FakeSimPlanClient:
                def __init__(self, _config):
                    pass

                def trigger(self, **kwargs):
                    calls.append(kwargs)
                    return {
                        "returncode": 0,
                        "request": {"trigger_param": {"revision_id": kwargs["revision_id"]}},
                        "response": {"data": {"context_id": len(calls)}},
                        "plan_id": len(calls),
                        "context_id": len(calls),
                    }

            original_client = runner_module.SimPlanClient
            try:
                runner_module.SimPlanClient = FakeSimPlanClient
                args = argparse.Namespace(
                    branch="gen4_release_20260206",
                    revision_id=None,
                    plan=None,
                    priority=None,
                    time_sensitive_hour=None,
                    dry_run=False,
                    yes=True,
                    json=True,
                )

                updated = _run_sim_plan(args, config, store, record)
            finally:
                runner_module.SimPlanClient = original_client

            self.assertEqual(updated["stage"], "sim_plan_triggered")
            self.assertEqual([call["revision_id"] for call in calls], [6106765, 6106765])
            self.assertEqual(
                [call["plan"].name for call in calls],
                [
                    "lxh_ra_stuck_release_20260206-openloop",
                    "lxh_ra_stuck_20260206_reviewed-openloop",
                ],
            )

    def test_ifx_convert_dry_run_does_not_persist_preview(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["ifx"] = {
                "onnx": {
                    "module": "planner.model-files",
                    "name": "vectorized_scenario_remote_assist_model.onnx",
                    "version": 66,
                },
                "precision_test_arg": (
                    "ifx-precision-test ifx_fp32_after_scaling_pos1e1_5.zip -v 1"
                ),
            }
            store.save(record)

            class FakePipeline:
                def __init__(self, _config):
                    pass

                def convert(self, **_kwargs):
                    return {
                        "jenkins": {
                            "params": {
                                "truck_py_arguments_of_onnx": (
                                    "planner.model-files "
                                    "vectorized_scenario_remote_assist_model.onnx -v 66"
                                )
                            }
                        },
                        "ifx_mapping": {"onnx": {"version": 66}},
                        "label": None,
                    }

            original_pipeline = runner_module.IfxPipeline
            try:
                runner_module.IfxPipeline = FakePipeline
                args = argparse.Namespace(
                    run_id=record["release_id"],
                    yes=True,
                    dry_run=True,
                    json=True,
                )

                preview = _run_ifx_convert(args, config, store)
            finally:
                runner_module.IfxPipeline = original_pipeline

            persisted = store.load(record["release_id"])
            self.assertEqual(preview["stage"], "ifx_convert_dry_run")
            self.assertEqual(persisted["stage"], "created")
            self.assertNotIn("ifx_mapping", persisted["ifx"])

    def test_offboard_uses_run_id_experiment_and_selected_epoch(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/nfs/exp", description="")
            record["experiment"] = {"name": "exp", "remote_host": "luban_2_card"}
            record["selection"] = {"selected_epoch": 19}
            store.save(record)
            calls = []

            class FakeExperiment:
                remote_host = "luban_2_card"

                def checkpoint_for_epoch(self, epoch):
                    self.epoch = epoch
                    return Path(f"/nfs/exp/checkpoints/version_0/epoch={epoch:03d}.pth")

            class FakeInspector:
                def __init__(self, *args, **kwargs):
                    pass

                def inspect(self, *args, **kwargs):
                    return FakeExperiment()

            class FakeRunner:
                def __init__(self, _config):
                    pass

                def run_offboard_test(self, **kwargs):
                    calls.append(kwargs)
                    return {
                        "host": kwargs["remote_host"],
                        "temp_config": "/nfs/repo/configs/scenario_dnn_finetune_test.release_offboard_epoch=019.yaml",
                        "checkpoint_path": str(kwargs["checkpoint_path"]),
                        "command": "ssh luban_2_card ...",
                        "returncode": 0,
                        "stdout": "",
                        "stderr": "",
                    }

            original_runner = runner_module.LubanRunner
            original_inspector = runner_module.ExperimentInspector
            original_confirm = runner_module._confirm
            try:
                runner_module.LubanRunner = FakeRunner
                runner_module.ExperimentInspector = FakeInspector
                runner_module._confirm = lambda _prompt, _yes: True
                args = argparse.Namespace(
                    run_id=record["release_id"],
                    experiment=None,
                    remote="luban_2_card",
                    remote_python=None,
                    epoch=None,
                    desc="",
                    dry_run=False,
                    json=True,
                    yes=True,
                )

                record = _run_offboard(args, config, store, store.load(record["release_id"]))
            finally:
                runner_module.LubanRunner = original_runner
                runner_module.ExperimentInspector = original_inspector
                runner_module._confirm = original_confirm

            self.assertEqual(record["stage"], "offboard_complete")
            self.assertEqual(record["offboard"]["branch"], "offboard")
            self.assertEqual(record["offboard"]["source"], "run_id")
            self.assertEqual(len(record["offboard_branches"]), 1)
            self.assertEqual(
                str(calls[0]["checkpoint_path"]),
                "/nfs/exp/checkpoints/version_0/epoch=019.pth",
            )
            self.assertEqual(calls[0]["remote_host"], "luban_2_card")

    def test_offboard_dry_run_with_run_id_does_not_persist_branch(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config = default_config()
            config.runs_dir = Path(tmp_dir)
            store = StateStore(config.runs_dir)
            record = store.create(experiment_path="/tmp/exp", description="")
            record["stage"] = "apply_handoff_complete"
            record["status"] = "completed"
            record["selection"] = {"selected_epoch": 19}
            store.save(record)

            class FakeExperiment:
                remote_host = "luban_2_card"

                def checkpoint_for_epoch(self, epoch):
                    return Path(f"/tmp/exp/checkpoints/version_0/epoch={epoch:03d}.pth")

            class FakeInspector:
                def __init__(self, *args, **kwargs):
                    pass

                def inspect(self, *args, **kwargs):
                    return FakeExperiment()

            class FakeRunner:
                def __init__(self, _config):
                    pass

                def run_offboard_test(self, **kwargs):
                    return {
                        "host": kwargs["remote_host"],
                        "temp_config": "/nfs/repo/configs/scenario_dnn_finetune_test.release_offboard_epoch=019.yaml",
                        "checkpoint_path": str(kwargs["checkpoint_path"]),
                        "command": "ssh luban_2_card ...",
                        "returncode": None,
                        "stdout": "",
                        "stderr": "",
                    }

            original_runner = runner_module.LubanRunner
            original_inspector = runner_module.ExperimentInspector
            original_confirm = runner_module._confirm
            try:
                runner_module.LubanRunner = FakeRunner
                runner_module.ExperimentInspector = FakeInspector
                runner_module._confirm = lambda _prompt, _yes: True
                args = argparse.Namespace(
                    run_id=record["release_id"],
                    experiment=None,
                    remote="luban_2_card",
                    remote_python=None,
                    epoch=None,
                    desc="",
                    dry_run=True,
                    json=True,
                    yes=True,
                )

                preview = _run_offboard(args, config, store, store.load(record["release_id"]))
            finally:
                runner_module.LubanRunner = original_runner
                runner_module.ExperimentInspector = original_inspector
                runner_module._confirm = original_confirm

            persisted = store.load(record["release_id"])
            self.assertEqual(preview["stage"], "offboard_dry_run")
            self.assertEqual(persisted["stage"], "apply_handoff_complete")
            self.assertNotIn("offboard_branches", persisted)


if __name__ == "__main__":
    unittest.main()
