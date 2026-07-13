"""Canonical Scenario DNN TensorDict feature shapes.

Single source of truth for the fixed input shapes consumed by the numbered
check_sim scripts (03/05 extract, 07 sweeps). Kept here so the table is defined
once instead of copy-pasted per entrypoint. Pure constant, no heavy deps.
"""

EXPECTED_SHAPES = {
    "old_dnn_features": (1, 9800),
    "ego_geometric": (1, 1, 10, 5, 2),
    "ego_heading": (1, 1, 10, 1),
    "ego_continuous": (1, 1, 10, 3),
    "ego_discrete": (1, 1, 10, 1),
    "ego_trajectory": (1, 1, 10, 100, 4),
    "ego_valid_geometric": (1, 1, 10),
    "ego_valid_history": (1, 1),
    "ego_valid_trajectory": (1, 1, 10),
    "agent_geometric": (1, 50, 30, 5, 2),
    "agent_heading": (1, 50, 30, 1),
    "agent_continuous": (1, 50, 30, 6),
    "agent_discrete": (1, 50, 30, 12),
    "agent_trajectory": (1, 50, 30, 50, 4),
    "agent_valid_geometric": (1, 50, 30),
    "agent_valid_history": (1, 50),
    "agent_valid_trajectory": (1, 50, 30),
    "zone_geometric": (1, 10, 1, 32, 2),
    "zone_discrete": (1, 10, 1, 7),
    "zone_valid_geometric": (1, 10, 1),
    "zone_valid_history": (1, 10),
    "obj_geometric": (1, 20, 1, 10, 2),
    "obj_discrete": (1, 20, 1, 1),
    "obj_valid_geometric": (1, 20, 1),
    "obj_valid_history": (1, 20),
    "tl_continuous": (1, 10, 30, 4),
    "tl_discrete": (1, 10, 30, 5),
    "tl_valid_history": (1, 10),
    "nearby_lane_geometric": (1, 90, 1, 62, 2),
    "nearby_lane_continuous": (1, 90, 1, 2),
    "nearby_lane_discrete": (1, 90, 1, 7),
    "nearby_lane_valid_geometric": (1, 90, 1),
    "nearby_lane_valid_history": (1, 90),
}


FEATURE_GROUPS = {
    "old_dnn_features": ["old_dnn_features"],
    "ego": [name for name in EXPECTED_SHAPES if name.startswith("ego_")],
    "agent": [name for name in EXPECTED_SHAPES if name.startswith("agent_")],
    "zone": [name for name in EXPECTED_SHAPES if name.startswith("zone_")],
    "obj": [name for name in EXPECTED_SHAPES if name.startswith("obj_")],
    "tl": [name for name in EXPECTED_SHAPES if name.startswith("tl_")],
    "nearby_lane": [
        name for name in EXPECTED_SHAPES if name.startswith("nearby_lane_")
    ],
}

SUBFEATURES = list(EXPECTED_SHAPES)
