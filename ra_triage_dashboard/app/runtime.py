from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import AssetIndex, CameraIndex, VideoIndex
from .auth import validate_identity_settings
from .autotriage_source import AutoTriageSource
from .baseline_registry import (
    BaselineRegistry,
    legacy_registry_from_settings,
    load_baseline_registry,
)
from .batch_prediction_runner import BatchPredictionRunner
from .db import Database
from .media_registry import build_media_registry
from .model_catalog import ModelCatalog
from .observability import BoundedObservationSet
from .prompt_catalog import PromptCatalog
from .settings import Settings
from .web_paths import render_index_html, with_base_path


logger = logging.getLogger("ra_triage_dashboard")
_identity_diagnostic_observations = BoundedObservationSet[
    tuple[str, tuple[tuple[str, str], ...]]
](max_entries=1024)
settings = Settings.from_env()
validate_identity_settings(settings)
database = Database(
    settings.database_url,
    postgres_migrations_dir=settings.postgres_migrations_dir,
    pool_size=10,
)
asset_index = AssetIndex(
    ra_root=settings.ra_auto_triage_root,
    manifest_path=settings.ares_manifest,
    base_path=settings.base_path,
)
camera_index = CameraIndex(settings.camera_root, base_path=settings.base_path)
video_index = VideoIndex(settings.ares_video_root, base_path=settings.base_path)

def _load_active_baseline_registry() -> BaselineRegistry:
    path = settings.baselines_file
    if path is not None and Path(path).is_file():
        return load_baseline_registry(
            Path(path),
            ra_auto_triage_root=settings.ra_auto_triage_root,
        )
    return legacy_registry_from_settings(
        baseline_id="0508",
        label="0508",
        scope=settings.baseline_scope,
        dataset=settings.baseline_dataset,
        xlsx=settings.baseline_label_xlsx,
        layout_id=settings.baseline_scope,
    )


baseline_registry = _load_active_baseline_registry()
media_registry = build_media_registry(
    baseline_registry,
    base_path=settings.base_path,
    product_asset_index=asset_index,
    product_camera_index=camera_index,
    product_video_index=video_index,
    data_dir=settings.data_dir,
    ra_root=settings.ra_auto_triage_root,
)
model_catalog = ModelCatalog(settings)
prompt_catalog = PromptCatalog(settings.ra_auto_triage_root)
autotriage_source = AutoTriageSource(settings.autotriage_api_base_url)
batch_prediction_runner = BatchPredictionRunner(settings, database)
trail_sync_lock = threading.Lock()
gt_sync_lock = threading.Lock()
review_image_semaphore = asyncio.Semaphore(2)
thumbnail_image_semaphore = asyncio.Semaphore(4)
trail_detail_semaphore = asyncio.Semaphore(2)
APP_STARTED_AT = datetime.now(timezone.utc)
APP_STARTED_MONOTONIC = time.monotonic()
INDEX_HTML = render_index_html(
    (settings.static_dir / "index.html").read_text(encoding="utf-8"),
    settings.base_path,
)

def _public_path(path: str) -> str:
    return with_base_path(settings.base_path, path)


MISSING_EVIDENCE_CATALOG: tuple[dict[str, str], ...] = (
    {"key": "routing_direction", "label": "routing 方向缺失", "hint": "未识别自车目标转向 / 车道任务"},
    {"key": "hazard_signal", "label": "双闪缺失", "hint": "未识别前方车辆双闪、临停或故障信号"},
)

REVIEW_TAG_CATALOG: tuple[dict[str, Any], ...] = (
    # Issue description: keep scene context separate from interaction
    # decisions.  The false/true-trigger buckets are retained because they are
    # part of the existing Review vocabulary and historical annotations.
    {"key": "construction_change", "label": "施工/变更区域", "section": "scene", "group": "environment"},
    {"key": "gate", "label": "道闸", "section": "scene", "group": "environment"},
    {"key": "park_entrance", "label": "园区出入口", "section": "scene", "group": "environment"},
    {"key": "environment_u_turn", "label": "掉头", "section": "scene", "group": "environment"},
    {"key": "environment_other", "label": "其他", "section": "scene", "group": "environment"},
    {"key": "intent_straight", "label": "直行", "section": "scene", "group": "self_intent"},
    {"key": "intent_left_turn", "label": "左转", "section": "scene", "group": "self_intent"},
    {"key": "intent_right_turn", "label": "右转", "section": "scene", "group": "self_intent"},
    {"key": "intent_u_turn", "label": "掉头", "section": "scene", "group": "self_intent"},
    {"key": "traffic_light", "label": "等灯", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "queue", "label": "排队", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "yielding", "label": "让行", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "u_turn", "label": "掉头", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "park_in", "label": "泊入", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "park_out", "label": "泊出", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "scene_false_other", "label": "其他", "section": "interaction_decision", "group": "false_trigger"},
    {"key": "obstacle_not_avoided", "label": "未避障", "section": "interaction_decision", "group": "true_trigger"},
    {"key": "close_distance", "label": "距离近", "section": "interaction_decision", "group": "true_trigger"},
    {"key": "perception_fp", "label": "感知FP", "section": "interaction_decision", "group": "true_trigger"},
    {"key": "scene_true_other", "label": "其他", "section": "interaction_decision", "group": "true_trigger"},
    # Issue resolution: how could the vehicle leave the scene?
    {"key": "egress_swag", "label": "SWAG", "section": "egress", "group": "ra"},
    {"key": "egress_detour", "label": "左右绕行", "section": "egress", "group": "ra"},
    {"key": "egress_waypoint", "label": "Waypoint", "section": "egress", "group": "ra"},
    {"key": "egress_reverse", "label": "倒车", "section": "egress", "group": "ra"},
    {"key": "egress_traffic_light", "label": "红绿灯通行", "section": "egress", "group": "ra"},
    {"key": "egress_ra_other", "label": "其他", "section": "egress", "group": "ra"},
    {"key": "lead_vehicle_departed", "label": "前车驶离", "section": "egress", "group": "no_assist"},
    {"key": "system_decision_change", "label": "主系统决策变化", "section": "egress", "group": "no_assist"},
    {"key": "perception_fp_change", "label": "感知FP变化", "section": "egress", "group": "no_assist"},
    {"key": "egress_no_assist_other", "label": "其他", "section": "egress", "group": "no_assist"},
    # Legacy values remain readable in Review history but are no longer offered
    # as new Issue tags.  Keeping them in the contract avoids losing old data.
    {"key": "manual_trigger", "label": "人工触发", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "perception_fp_cleared", "label": "感知FP消失", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "occlusion", "label": "大车遮挡", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "right_turn", "label": "右转", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "left_turn", "label": "左转", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "temporary_stop", "label": "前车双闪", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "vulnerable_road_user", "label": "摩自/行人", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "gt_boundary", "label": "GT 待复核", "section": "legacy", "group": "legacy", "visible": False},
    {"key": "scene_other", "label": "其他（旧交互决策）", "section": "legacy", "group": "legacy", "visible": False},
)
REVIEW_TAG_KEYS = frozenset(item["key"] for item in REVIEW_TAG_CATALOG)
# Managed groups that reviewers may extend from the Review form ＋ control.
# Map group_key → section so create/update stay aligned with the Issue-tag axes.
REVIEW_TAG_MANAGED_GROUPS: dict[str, str] = {
    "environment": "scene",
    "self_intent": "scene",
    "false_trigger": "interaction_decision",
    "true_trigger": "interaction_decision",
    "ra": "egress",
    "no_assist": "egress",
}
REVIEW_TAG_SCENE_GROUPS = frozenset(
    group for group, section in REVIEW_TAG_MANAGED_GROUPS.items() if section == "scene"
)
REVIEW_TAG_ALIASES = {
    "红绿灯": "traffic_light",
    "等灯": "traffic_light",
    "排队": "queue",
    "让行": "yielding",
    "掉头": "u_turn",
    "施工/变更区域": "construction_change",
    "施工区域": "construction_change",
    "变更区域": "construction_change",
    "道闸": "gate",
    "园区出入口": "park_entrance",
    "场景其他": "environment_other",
    "直行": "intent_straight",
    "自车直行": "intent_straight",
    "自车左转": "intent_left_turn",
    "自车右转": "intent_right_turn",
    "自车掉头": "intent_u_turn",
    "泊入": "park_in",
    "泊出": "park_out",
    "人工触发": "manual_trigger",
    "感知FP消失": "perception_fp_cleared",
    "感知FP": "perception_fp",
    "前车驶离": "lead_vehicle_departed",
    "主系统决策变化": "system_decision_change",
    "未避障": "obstacle_not_avoided",
    "距离近": "close_distance",
    "红绿灯通行": "egress_traffic_light",
    "左右绕行": "egress_detour",
    "Waypoint": "egress_waypoint",
    "倒车": "egress_reverse",
    "感知FP变化": "perception_fp_change",
    "双闪临停": "temporary_stop",
    "前方大车遮挡": "occlusion",
    "大车遮挡": "occlusion",
    "右转": "intent_right_turn",
    "左转": "intent_left_turn",
    "左转待转": "intent_left_turn",
    # Preserve common historical values while the new UI emits the compact catalog above.
    "信号灯": "traffic_light",
    "双闪": "temporary_stop",
    "临停": "temporary_stop",
    "故障车": "temporary_stop",
    "遮挡": "occlusion",
    "摩自": "vulnerable_road_user",
    "行人": "vulnerable_road_user",
    "SWAG": "egress_swag",
    "RA": "egress_swag",
    "GT": "gt_boundary",
    "GT待复核": "gt_boundary",
}

runtime_state: dict[str, Any] = {
    "baseline": {"status": "not_loaded", "message": "等待加载 0508 baseline。", "count": 0},
    "baselines": [],
    "baseline_conflicts": [],
    "trail_sync": {
        "status": "not_started",
        "message": "尚未检查 Trail 模型字段。",
        "run_id": "",
        "can_create": False,
        "default_changed": False,
    },
    # Process-local in-flight state keyed by baseline scope. Persisted sync
    # state remains authoritative and survives restarts in gt_sync_state.
    "gt_sync": {},
}


EXAMPLE_CASES: tuple[dict[str, str], ...] = (
    {
        "issue_id": "cn32171803",
        "title": "左转待转，等灯场景",
        "scenario": "红绿灯周期性等待",
        "summary": "多个路口红灯持续亮起，有停止线；前方摩自停在停止线后方，自车同步等待。",
        "review_note": "当前模型说明为“正确判断为等灯”；用于核验等灯识别与标注流程。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32171803?view_id=2410",
    },
    {
        "issue_id": "cn31954847",
        "title": "排队等灯，前方大车遮挡",
        "scenario": "红绿灯周期性等待",
        "summary": "红灯、停止线/斑马线明确；白色厢式货车停在停止线后，红灯转绿后车流通行。",
        "review_note": "当前模型说明为“正确判断排队等灯”；可用于检验大车遮挡下的等灯识别。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn31954847?view_id=2410",
    },
    {
        "issue_id": "cn32000543",
        "title": "自车右转，前方双闪临停车",
        "scenario": "绕行/异常停车",
        "summary": "模型判为排队，未覆盖 RA 协助下绕行通行；案例关注双闪特征。",
        "review_note": "问题假设：双闪缺失导致“排队”FP。请重点标注异常车辆与可绕行性。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32000543?view_id=2410",
    },
    {
        "issue_id": "cn32044177",
        "title": "自车右转，摩自直行且有绕行空间",
        "scenario": "routing 方向 / 绕行空间",
        "summary": "模型判为等灯，但未判断 routing 方向和可绕行空间。",
        "review_note": "问题假设：routing 方向缺失导致“等灯”FP。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32044177?view_id=2410",
    },
    {
        "issue_id": "cn32000563",
        "title": "自车右转，在直行车道排队",
        "scenario": "routing 方向 / 右侧通行空间",
        "summary": "模型判为排队，未识别右侧可右转通行空间；SWAG 右变道后又左加塞回原车道，需复核。",
        "review_note": "问题假设：routing 方向缺失导致“排队”FP；需再 review SWAG 操作链。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32000563?view_id=2410",
    },
    {
        "issue_id": "cn31983487",
        "title": "自车右转，前车直行等灯且无绕行空间",
        "scenario": "routing 方向 / 无绕行空间",
        "summary": "模型判为等灯，但没有判断 routing 方向。",
        "review_note": "问题假设：routing 方向缺失导致“等灯”FP。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn31983487?view_id=2410",
    },
)
