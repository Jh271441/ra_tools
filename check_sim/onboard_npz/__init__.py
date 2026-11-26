"""Simulation-free Voyager Onboard Stuck DNN NPZ inference & 10Hz road-test replication."""

from .bag_exporter import download_road_scenario_bag, export_road_bag_to_npz, iter_rosbag_messages
from .batch_export_1030 import build_1030_export_tasks, stream_export_1030_dataset
from .detector_replay import (
    ParityReport,
    ReplayResult,
    compute_onboard_parity,
    evaluate_cropped_npz,
    infer_npz_file,
    is_enhanced_road_npz,
    replay_enhanced_road_npz,
)
from .diff_report_1030 import compute_1030_metrics, compute_paired_diff, run_1030_evaluation_and_diff
from .historical_shuyi_eval import (
    build_population_export_tasks,
    compute_shuyi_reconcile_metrics,
    evaluate_single_release_shuyi,
    run_multi_release_shuyi_suite,
    stream_export_population_dataset,
)
from .model_runner import FrameScoreBatch, OnboardModelRunner, TensorSpec, ensure_ifx_bridge_library
from .schema import (
    ENHANCED_NPZ_SCHEMA,
    TIER_LAYER1_CROPPED,
    TIER_LAYER2_ROAD_10HZ,
    AssistModelProcessReason,
    ConnectRequestType,
    NonVoluntaryUnstuckReason,
    OnboardDetectorConfig,
    RequestUpdateType,
    RuleDecision,
    TaskCode,
    UnstuckStatus,
)

__all__ = [
    "ENHANCED_NPZ_SCHEMA",
    "TIER_LAYER1_CROPPED",
    "TIER_LAYER2_ROAD_10HZ",
    "AssistModelProcessReason",
    "ConnectRequestType",
    "FrameScoreBatch",
    "NonVoluntaryUnstuckReason",
    "OnboardDetectorConfig",
    "OnboardModelRunner",
    "ParityReport",
    "ReplayResult",
    "RequestUpdateType",
    "RuleDecision",
    "TaskCode",
    "TensorSpec",
    "UnstuckStatus",
    "build_1030_export_tasks",
    "build_population_export_tasks",
    "compute_1030_metrics",
    "compute_onboard_parity",
    "compute_paired_diff",
    "compute_shuyi_reconcile_metrics",
    "download_road_scenario_bag",
    "ensure_ifx_bridge_library",
    "evaluate_cropped_npz",
    "evaluate_single_release_shuyi",
    "export_road_bag_to_npz",
    "infer_npz_file",
    "is_enhanced_road_npz",
    "iter_rosbag_messages",
    "replay_enhanced_road_npz",
    "run_1030_evaluation_and_diff",
    "run_multi_release_shuyi_suite",
    "stream_export_1030_dataset",
    "stream_export_population_dataset",
]
