"""Exact Onboard C++ enums, default parameters, and Enhanced Road NPZ schema constants.

Synced directly with Voyager Onboard C++ sources:
  - ``onboard/planner/config/master/behavior_reasoner_config/remote_assist.conf``
  - ``onboard/planner/planner_protos/debug/behavior_reasoners/ego_stuck/ego_stuck_debug.proto``
  - ``onboard/planner/planner_protos/remote_assist.proto``
  - ``onboard/planner/planner_protos/debug/remote_assist/assist_stuck_debug.proto``
  - ``onboard/common/voy_protos/remote_warning.proto``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, FrozenSet


ENHANCED_NPZ_SCHEMA = "ra-onboard-road-npz/v1"
TIER_LAYER1_CROPPED = "layer1_cropped_npz"
TIER_LAYER2_ROAD_10HZ = "layer2_road_10hz"


class UnstuckStatus(IntEnum):
    UNSTUCK_UNDEFIEND = 0
    CORE_PLANNER_DETECT = 1
    WAITTING_CORE_PLANNER_UNSTUCK = 2
    MODEL_FP = 3
    MODEL_DETECT = 4
    MODEL_REQUEST = 5
    ALREADY_IN_LIGHT_ASSIST = 6
    OPS_REFUSED_SCENE = 7
    NOT_STATIONARY = 8
    RULE_FN_DETECT = 9
    ALREADY_IN_WAYPOINT_ASSIST = 10
    ALREADY_IN_REVERSING = 11
    MANUAL_DRIVING = 12
    NORMAL_EXIT = 13
    NO_DEBUG_MESSAGE = 14
    PULLOUT_IN_REQUEST = 15
    FLAG_DISABLE = 16
    OUTER_RA_REQUEST = 17
    MRC_REACHED = 18
    INTERVENTION_FORBID = 19
    OMNI_PERF_DISABLE = 20
    SPECIAL_STUCK_DETECT = 21
    CANCEL_REQUEST = 22


class NonVoluntaryUnstuckReason(IntEnum):
    Undefined = 0
    UndetectedStuckScene = 1
    UnstuckFail = 2


class RuleDecision(IntEnum):
    kNone = 0
    kAbort = 1
    kStuckDetected = 2
    kRequestImmediately = 3
    kHasActivateFN = 4
    kModelDetected = 5


class AssistModelProcessReason(IntEnum):
    UNDEFINED_REASON = 0
    FP_TRAFFIC_JAM = 1
    FP_RED_LIGHT = 2
    FP_STOP_FENCE = 3
    FP_STARTUP = 4
    FP_MAXSPD = 5
    FP_CROSSWALK = 6
    FN_REJECT_INQUEUE = 7
    FN_JUNCTION = 8
    FN_SOLID_LANEMARK = 9
    FN_LOW_PRED = 10
    FP_PULL_OVER = 11
    FP_YIELD_DYNAMIC_OBJECT = 12
    FP_EOL_WITH_RED_TL = 13
    FP_YIELD_ON_RIGHT_TURN = 14
    FP_QUEUING = 15
    FN_RA_CZ = 16
    FP_YIELD_ON_TURN = 17
    FN_NEAR_HARD_BOUNDARY = 18
    FN_SELECTION = 19
    FP_OCCLUSION = 20
    FN_BREAKDOWN_CAR = 21
    REQUEST_FROM_ROUTING = 23
    FN_PERCEPTION_FP = 24
    FN_EOL = 25
    FP_REMOTE_SPEED_LIMIT = 26
    FN_CZ = 27
    REQUEST_FROM_CREEP = 28
    FN_NO_BLOCK = 29
    FN_LANE_CHANGE_STUCK = 30
    FN_FORCING_RECALL = 31
    FN_VEHICLE_HAZARD_SIGNAL = 32
    REQUEST_FROM_TIDAL_FLOW_LANE = 33
    REQUIREMENT_OF_TRAFFIC_LIGHT = 34
    FN_ABNORMAL_TRAFFIC_LIGHT = 35
    ASSIST_STUCK_MODEL = 36
    SPECIAL_STUCK_SCENE = 37
    FP_OPEN_SPACE_PLANNING = 38
    FP_LANE_CHANGE_FORBID = 39
    FN_FINAL_FORCING_RECALL = 40
    FN_RA_CZ_TRAFFIC_LIGHT = 41


class RequestUpdateType(IntEnum):
    kNone = 0
    kNewState = 1
    kTimeout = 2
    kCancel = 3


class ConnectRequestType(IntEnum):
    kUndefinedType = 0
    kCorePlannerRequest = 1
    kStuckModelRequest = 2
    kCZTrafficLightRequest = 3
    kAbnormalTrafficLight = 4
    kTidalFlowLane = 5
    kEndOfLaneSequence = 6
    kSecondPullover = 7


class TaskCode(IntEnum):
    UNKNOWN = 0
    STUCK_OTHER = 1100
    STUCK_NARROW_SPACE = 1101
    STUCK_TRAFFIC_LIGHT_BROKEN = 1102
    STUCK_TRAFFIC_LIGHT_CHANGED = 1103
    STUCK_ARROW_MARK_CHANGED = 1104
    STUCK_ROAD_LINE_CHANGED = 1105
    STUCK_EGO_CAUSE_TRAFFIC_JAM = 1106
    STUCK_EGO_IN_NO_STOPPING_ZONE = 1107
    STUCK_POTENTIAL_TRAFFIC_JAM = 1108
    STUCK_SPECIAL_STUCK_SCENE = 1109


EARLY_RETURN_STATUSES: FrozenSet[int] = frozenset({
    UnstuckStatus.OPS_REFUSED_SCENE,
    UnstuckStatus.PULLOUT_IN_REQUEST,
    UnstuckStatus.MANUAL_DRIVING,
    UnstuckStatus.MRC_REACHED,
    UnstuckStatus.NOT_STATIONARY,
    UnstuckStatus.NORMAL_EXIT,
    UnstuckStatus.NO_DEBUG_MESSAGE,
    UnstuckStatus.INTERVENTION_FORBID,
})

ALREADY_IN_ASSIST_STATUSES: FrozenSet[int] = frozenset({
    UnstuckStatus.ALREADY_IN_LIGHT_ASSIST,
    UnstuckStatus.ALREADY_IN_WAYPOINT_ASSIST,
    UnstuckStatus.ALREADY_IN_REVERSING,
})

SELECTION_DISCOUNTED_FP_REASONS: FrozenSet[int] = frozenset({
    AssistModelProcessReason.FP_CROSSWALK,
    AssistModelProcessReason.FP_OCCLUSION,
    AssistModelProcessReason.FP_YIELD_ON_TURN,
})

IN_ASSIST_ALLOWED_FN_REASONS: FrozenSet[int] = frozenset({
    AssistModelProcessReason.FN_RA_CZ,
    AssistModelProcessReason.FN_RA_CZ_TRAFFIC_LIGHT,
    AssistModelProcessReason.FN_ABNORMAL_TRAFFIC_LIGHT,
    AssistModelProcessReason.FN_PERCEPTION_FP,
})

DEFAULT_FN_REASON_TASK_CODE: Dict[int, int] = {
    AssistModelProcessReason.ASSIST_STUCK_MODEL: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_RA_CZ: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_RA_CZ_TRAFFIC_LIGHT: TaskCode.STUCK_TRAFFIC_LIGHT_CHANGED,
    AssistModelProcessReason.REQUEST_FROM_ROUTING: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_FORCING_RECALL: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_FINAL_FORCING_RECALL: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.REQUEST_FROM_CREEP: TaskCode.STUCK_NARROW_SPACE,
    AssistModelProcessReason.FN_ABNORMAL_TRAFFIC_LIGHT: TaskCode.STUCK_TRAFFIC_LIGHT_BROKEN,
    AssistModelProcessReason.FN_NEAR_HARD_BOUNDARY: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_SELECTION: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_BREAKDOWN_CAR: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_PERCEPTION_FP: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_EOL: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_CZ: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_NO_BLOCK: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_LANE_CHANGE_STUCK: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.FN_VEHICLE_HAZARD_SIGNAL: TaskCode.STUCK_OTHER,
    AssistModelProcessReason.SPECIAL_STUCK_SCENE: TaskCode.STUCK_EGO_CAUSE_TRAFFIC_JAM,
}


@dataclass(frozen=True)
class OnboardDetectorConfig:
    """Exact production parameters from ``remote_assist.conf`` + ``planning_gflags.cpp``."""

    default_stuck_threshold: float = 0.5
    stuck_likelihood_queue_size: int = 10
    stuck_likelihood_queue_expire_dur_in_ms: int = 12000
    n_times_positive_for_recall: int = 3
    stuck_likelihood_continuous_threshold_ms: int = 1500
    fn_trigger_cycle_count: int = 60
    model_request_hold_cycle_count: int = 300
    delay_posting_request_cycle_cnt: int = 100
    voluntary_undetected_stuck_scene_time_threshold_ms: int = 1000
    voluntary_unstuck_time_threshold_ms: int = 5000
    enable_uncertain_delay: bool = False
    enable_vlm_block: bool = True
    enable_cancel_request: bool = False


def enum_name(enum_cls, code: int) -> str:
    try:
        return enum_cls(int(code)).name
    except ValueError:
        return f"UNKNOWN_{code}"
