"""Ares speed_table_raw.dominantConstraint, default selected candidate.

Port of Vitruvian 8c071689 speed-table-raw.ts and ares-utils/modules/planning.
No model inference, semantic translation, or object-ID based reconstruction.
"""
from __future__ import annotations


def enum_name(message, field):
    value = getattr(message, field, None)
    descriptor = getattr(message, "DESCRIPTOR", None)
    field_type = getattr(descriptor, "fields_by_name", {}).get(field)
    enum = getattr(field_type, "enum_type", None)
    entry = getattr(enum, "values_by_number", {}).get(value)
    return entry.name if entry else value


def present(message, field):
    if message is None:
        return False
    try:
        return message.HasField(field)
    except (AttributeError, ValueError):
        return hasattr(message, field)


def extract_frame(message, publish_ms):
    result = {"timestamp_ms": int(publish_ms), "planning_timestamp_ms": int(message.timestamp),
              "status": "unresolved", "constraint_id": None, "raw": ""}
    behavior = getattr(message, "behavior_reasoner_debug", None)
    maneuvers = getattr(behavior, "decoupled_maneuvers", [])
    maneuver = next((m for m in maneuvers if enum_name(m, "type") == "DECOUPLED_LANE_FOLLOW"), None)
    if maneuver is None:
        maneuver = next((m for m in maneuvers if enum_name(m, "type") == "DECOUPLED_FORWARD"), None)
    if maneuver is None:
        return result
    metas = list(maneuver.trajectory_selection_debug.trajectory_meta_debugs)
    selected = [m for m in metas if m.is_selected]
    # Do not masquerade an arbitrary fallback candidate as the selected path.
    if len(selected) != 1:
        return result
    meta = selected[0]
    label = str(meta.label)
    candidates = [c for lane in maneuver.single_lane_sequence_plan_debug
                  for c in lane.single_intention_plan_debug
                  if label and str(c.candidate_identifier)[:len(label)-1] == label[:-1]]
    if len(candidates) != 1:
        return result
    speed = candidates[0].speed_generator_debug
    solver_ix = int(meta.speed_ix) if present(meta, "speed_ix") else 0
    if not 0 <= solver_ix < len(speed.speed_solver_debugs):
        return result
    solver = speed.speed_solver_debugs[solver_ix]
    if not present(solver, "search_debug"):
        return result
    search = solver.search_debug
    if not present(search, "dominant_constraint_ix"):
        return result
    constraints = speed.primitive_constraints if len(speed.primitive_constraints) else search.constraints
    ix = int(search.dominant_constraint_ix)
    gap = "Gap align." if enum_name(search, "search_result") == "SUCCESS_WITH_GAP_ALIGN" else "Non gap align."
    obj = int(search.dominant_constraint_obj_id) if present(search, "dominant_constraint_obj_id") else None
    brake = int(search.earliest_brake_time_ix) if present(search, "earliest_brake_time_ix") else None
    constraint_id = None
    phrase = "No dominant constraint."
    status = "no_constraint"
    if 0 <= ix < len(constraints):
        value = str(constraints[ix].unique_constraint_id)
        if not value:
            return result
        constraint_id = value
        status = "ready"
        phrase = f"Dominant constraint: {value}, Object id: {obj if obj is not None else 'undefined'}."
    result.update(status=status, constraint_id=constraint_id, object_id=obj,
                  candidate=label, speed_ix=solver_ix, dominant_constraint_ix=ix,
                  raw=f"{gap} {phrase} Earliest search brake time ix: {brake if brake is not None else 'undefined'}")
    return result
