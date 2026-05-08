from typing import List, Dict, Any, Optional


def get_first_event_time(events: List[Dict[str, Any]], event_name: str, value_name: Optional[str] = None) -> Optional[
    int]:
    if not events or not event_name:
        return None
    for event in events:
        if event.get("event") == event_name and (value_name is None or event.get("value") == value_name):
            timestamp = event.get("timestamp")
            if timestamp is not None:
                return timestamp
    return None