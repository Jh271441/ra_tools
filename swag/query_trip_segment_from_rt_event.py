import json
import random
import time
from concurrent.futures import ThreadPoolExecutor

from datetime import datetime

import pandas as pd
from tqdm import tqdm

from ra_api.scenario_api import TripSegment


TIME_BEFORE_EVENT_MS = 5 * 1000  # 5 seconds
TIME_AFTER_EVENT_MS = 5 * 1000  # 5 seconds


def query_swag_scenario_from_ra_event(ra_event_item):
    """
    Create waypoint scenario
    Return: trip_segment
    """
    time.sleep(random.uniform(0.1, 0.5))
    event_time = ra_event_item["rt_event_timestamp"]
    trip_id = ra_event_item["trip_id"]

    start_timestamp = event_time - TIME_BEFORE_EVENT_MS
    end_timestamp = event_time + TIME_AFTER_EVENT_MS
    # date_time = datetime.utcfromtimestamp(event_time / 1000)

    # module = ["PREDICTION", "PLANNING", "ROUTING", "MODEL_POSE", "CONTROL"]
    trip_segment = TripSegment(trip_id, start_timestamp, end_timestamp)
    return trip_segment


rt_event_path = "/home/didi/workspace/ra_tools/swag/swag_trigger_release1226.xlsx"
rt_events = pd.read_excel(rt_event_path)


with ThreadPoolExecutor(max_workers=100) as executor:
    trip_segments = list(
        executor.map(
            lambda row: query_swag_scenario_from_ra_event(
                row
            ),
            [row for _, row in rt_events.iterrows()],
        )
    )

# trip_segments = []
# for index, row in tqdm(rt_events.iterrows()):
#     trip_segment = query_swag_scenario_from_ra_event(row)
print([trip_segment.to_dict() for trip_segment in trip_segments])