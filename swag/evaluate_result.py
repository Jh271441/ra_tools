from enum import Enum
from collections import Counter

import numpy as np


class AssistModelProcessReason(Enum):
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
    FP_YIELD_ON_RIGHT_TURN = 14  # deprecated
    FP_QUEUING = 15
    FN_RA_CZ = 16
    FP_YIELD_ON_TURN = 17
    FN_NEAR_HARD_BOUNDARY = 18
    FN_SELECTION = 19
    FP_OCCLUSION = 20
    FN_BREAKDOWN_CAR = 21
    RESERVED = 22
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


data = np.load(
    "/home/luban/ofs/user/jasperchen/2026Q1_swag_trigger_scenario_clustering_from_rt_event/results/all_trip_segments_trigger_reasons.npz",
    allow_pickle=True)

# print(data.files)
# # ['segments', 'segment_count']
segment_count = int(data["segment_count"])
print(f"Total segments: {segment_count}")
# 98
segments = data["segments"]
# print(type(segments))
# # <class 'numpy.ndarray'>
segments = segments.tolist()

for seg in segments[:10]:
    print(seg)

reason_segment_counter = Counter()

# Trigger Reason Distribution (by segment)
for seg in segments:
    for r in seg["trigger_reasons"]:
        try:
            reason_name = AssistModelProcessReason(r).name
        except ValueError:
            reason_name = f"UNKNOWN({r})"
        reason_segment_counter[reason_name] += 1

print("=== Trigger Reason Distribution ===")
for reason, cnt in reason_segment_counter.most_common():
    print(f"{reason:35}: {cnt}")


# Empty trigger_reasons segments
empty_reason_segments = [
    seg for seg in segments if not seg["trigger_reasons"]
]

print(f"\n=== Empty trigger_reasons segments: {len(empty_reason_segments)} ===")
for seg in empty_reason_segments:
    print(
        f"trip_id={seg['trip_id']}, "
        f"start={seg['start_time']}, "
        f"end={seg['end_time']}, "
        f"trigger_count={seg['trigger_count']}"
    )

# Summary
total_segments = len(segments)
empty_cnt = len(empty_reason_segments)

print("\n=== Summary ===")
print(f"Total segments          : {total_segments}")
print(f"Segments with no trigger: {empty_cnt}")
print(f"Ratio                   : {empty_cnt / total_segments:.2%}")
