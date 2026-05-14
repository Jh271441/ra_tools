"""Configuration for the model release pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_RUNS_DIR = PACKAGE_ROOT / ".runs"
DEFAULT_TEMPLATE_PATH = PACKAGE_ROOT / "templates" / "release_config.example.yaml"


@dataclass
class LubanConfig:
    host_alias: str = "luban_2_card"
    python_bin: str = (
        "/home/luban/miniconda3/bin/conda run --no-capture-output "
        "-n scen_dnn python"
    )
    remote_python_bin: str = (
        "/home/luban/miniconda3/bin/conda run --no-capture-output "
        "-n scen_dnn python"
    )
    train_repo: str = (
        "/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/stuck_assist_model"
    )
    export_script: str = "scenario_dnn/export/export_scenario_dnn.py"
    offboard_config_path: str = "configs/scenario_dnn_finetune_test.yaml"
    offboard_entry_script: str = "scenario_dnn/train_test/ra_model_pipeline.py"


@dataclass
class IfxConfig:
    enabled: bool = True
    method: str = "jenkins"
    truck_module: str = "planner.model-files"
    truck_cmd: str = "truck.py"
    truck_runner: str = "auto"
    # local
    truck_local_shell: str = "/bin/zsh"
    truck_local_workdir: str = ""
    truck_local_setup: str = ""
    # docker
    truck_docker_container: str = ""
    truck_docker_container_env: str = "CONTAINER_NAME_GEN4"
    truck_docker_shell: str = "/bin/zsh"
    truck_docker_workdir: str = "/home/didi/workspace/voyager"
    truck_docker_setup: str = (
        "git checkout master-Release_CN-a6d66b30c89 && "
        "source /home/didi/workspace/voyager/bazel/scripts/setup.sh"
    )
    truck_docker_stage_dir: str = "/tmp/model_release_pipeline_artifacts"
    # cloud_server
    truck_ssh_host: str = "cloud_server"
    truck_ssh_shell: str = "/bin/zsh"
    truck_ssh_workdir: str = "/home/didi/workspace/voyager"
    truck_ssh_setup: str = "source /home/didi/workspace/voyager/bazel/scripts/setup.sh"
    truck_ssh_stage_dir: str = "/tmp/model_release_pipeline_artifacts"
    jenkins_base_url: str = "http://10.79.18.51:8088"
    jenkins_job_name: str = (
        "voyager_ifxruntime_trt_cached_engines_generator_ov23_trt10_dev"
    )
    jenkins_http_method: str = "POST"
    jenkins_token: str = "ONNX2IFX_DEV"
    jenkins_use_crumb: bool = True
    username: str = "jasperchen"
    max_batch: int = 0
    x86_convert: str = "openvino"
    precision_convert: str = "FP16"
    use_label: bool = False
    label_prefix: str = "scenario_dnn_release_"
    precision_test_truck_arg: str = ""
    precision_test_local_path: str = "~/utils/ifx/ifx_fp32_after_scaling_pos1e1_5.zip"
    precision_test_module: str = "ifx-precision-test"
    expected_platforms: List[str] = field(
        default_factory=lambda: [
            "fp32_x86",
            "fp16_6000",
            "fp16_3060",
            "fp16_gen4",
            "fp16_thor",
        ]
    )
    poll_interval_sec: int = 30
    timeout_sec: int = 7200
    local_script_path: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)
    trail_base_url: str = "https://voyager.intra.xiaojukeji.com"
    trail_query_app_id: str = "3"
    trail_query_token: str = "cf7c08dec4b09b730bdfe5d5906dcf4e"


@dataclass
class ManifestEntryConfig:
    platform: str
    target_path: str
    description: str = ""
    expected_name: str = ""


@dataclass
class BranchConfig:
    name: str
    checkout_branch: str
    update_diff_id: int
    sim_plan: str


@dataclass
class VoyagerConfig:
    manifest_path: str = "onboard/model_files/MANIFEST.txt"
    commit_prefix: str = "V"
    return_branch: str = "master-Release_CN-a6d66b30c89"
    manifest_entries: List[ManifestEntryConfig] = field(default_factory=list)
    branches: List[BranchConfig] = field(default_factory=list)


@dataclass
class PickerConfig:
    policy: str = "precision_first"
    top_n: int = 3
    loss_tolerance_pct: float = 0.05


@dataclass
class ReleaseConfig:
    runs_dir: Path = DEFAULT_RUNS_DIR
    onnx_file_name: str = "vectorized_scenario_remote_assist_model.onnx"
    luban: LubanConfig = field(default_factory=LubanConfig)
    ifx: IfxConfig = field(default_factory=IfxConfig)
    voyager: VoyagerConfig = field(default_factory=VoyagerConfig)
    picker: PickerConfig = field(default_factory=PickerConfig)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["runs_dir"] = str(self.runs_dir)
        return data


def _default_voyager_config() -> VoyagerConfig:
    return VoyagerConfig(
        manifest_entries=[
            ManifestEntryConfig(
                platform="onnx",
                expected_name="vectorized_scenario_remote_assist_model.onnx",
                target_path="./planner_models/vectorized_scenario_remote_assist_model.onnx",
                description="Vectorized scenario assist stuck model.",
            ),
            ManifestEntryConfig(
                platform="fp32_x86",
                expected_name="vectorized_scenario_remote_assist_model_bs0_fp32_x86.ifxmodel",
                target_path="./planner_models/vectorized_scenario_remote_assist_model_x86.ifxmodel",
            ),
            ManifestEntryConfig(
                platform="fp16_6000",
                expected_name="vectorized_scenario_remote_assist_model_bs0_fp16_6000_trt109.ifxmodel",
                target_path="./planner_models/vectorized_scenario_remote_assist_model_fp16_6000.ifxmodel",
            ),
            ManifestEntryConfig(
                platform="fp16_3060",
                expected_name="vectorized_scenario_remote_assist_model_bs0_fp16_3060_trt109.ifxmodel",
                target_path="./planner_models/vectorized_scenario_remote_assist_model_fp16_3060.ifxmodel",
            ),
            ManifestEntryConfig(
                platform="fp16_gen4",
                expected_name="vectorized_scenario_remote_assist_model_bs0_fp16_gen4_trt109.ifxmodel",
                target_path="./planner_models/vectorized_scenario_remote_assist_model_fp16_gen4.ifxmodel",
            ),
            ManifestEntryConfig(
                platform="fp16_thor",
                expected_name="vectorized_scenario_remote_assist_model_bs0_fp16_thor_trt1013.ifxmodel",
                target_path="./planner_models/vectorized_scenario_remote_assist_model_fp16_thor.ifxmodel",
            ),
        ],
        branches=[
            BranchConfig(
                name="master",
                checkout_branch="jasperchen/2026Q1_test_scenario_dnn_dev",
                update_diff_id=5716859,
                sim_plan="topic_ra_auto_trigger",
            ),
            BranchConfig(
                name="gen4_release_20260403",
                checkout_branch="jasperchen/gen4_release_20260403/scenario_dnn_dev",
                update_diff_id=6076711,
                sim_plan="lxh_ra_stuck_release_20260403-openloop",
            ),
            BranchConfig(
                name="gen4_release_20260410",
                checkout_branch="jasperchen/gen4_release_20260410/scenario_dnn_dev",
                update_diff_id=6106759,
                sim_plan="lxh_ra_stuck_release_20260410-openloop",
            ),
            BranchConfig(
                name="gen4_release_20260417",
                checkout_branch="jasperchen/gen4_release_20260417/scenario_dnn_dev",
                update_diff_id=6106761,
                sim_plan="lxh_ra_stuck_release_20260417-openloop",
            ),
            BranchConfig(
                name="gen4_release_20260327",
                checkout_branch="jasperchen/gen4_release_20260327/scenario_dnn_dev",
                update_diff_id=6076959,
                sim_plan="lxh_ra_stuck_release_20260327-openloop",
            ),
        ],
    )


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _config_from_dict(data: Dict[str, Any]) -> ReleaseConfig:
    voyager_cfg = data.get("voyager", {})
    manifest_entries = [
        ManifestEntryConfig(**entry)
        for entry in voyager_cfg.get("manifest_entries", [])
    ]
    branch_entries = [BranchConfig(**entry) for entry in voyager_cfg.get("branches", [])]
    voyager = _default_voyager_config()
    if manifest_entries:
        voyager.manifest_entries = manifest_entries
    if branch_entries:
        voyager.branches = branch_entries
    for key, value in voyager_cfg.items():
        if key not in {"manifest_entries", "branches"}:
            setattr(voyager, key, value)

    luban = LubanConfig(**data.get("luban", {}))
    ifx = IfxConfig(**data.get("ifx", {}))
    picker = PickerConfig(**data.get("picker", {}))
    runs_dir = Path(str(data.get("runs_dir", DEFAULT_RUNS_DIR))).expanduser()
    return ReleaseConfig(
        runs_dir=runs_dir,
        onnx_file_name=data.get(
            "onnx_file_name", "vectorized_scenario_remote_assist_model.onnx"
        ),
        luban=luban,
        ifx=ifx,
        voyager=voyager,
        picker=picker,
    )


def default_config() -> ReleaseConfig:
    config = ReleaseConfig()
    config.voyager = _default_voyager_config()
    return config


def load_config(config_path: Optional[str] = None) -> ReleaseConfig:
    config = default_config()
    if not config_path:
        return config
    path = Path(config_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = _merge_dict(config.to_dict(), loaded)
    return _config_from_dict(merged)
