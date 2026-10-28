"""Read one bounded planning window. Input is server-owned JSON on stdin."""
import contextlib
import json
import os
from pathlib import Path
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.planning_constraint_extract import extract_frame


def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    request = json.load(sys.stdin)
    from labeler.utility import common_utils
    import voy_vbag
    path = Path(request["work_dir"]) / "planning.bag"
    start, end = request["start_ms"], request["end_ms"]
    if not 0 < end - start <= 10000:
        raise ValueError("invalid extraction window")
    with contextlib.redirect_stdout(sys.stderr):
        common_utils.new_download_by_tripid(request["trip_id"], start, end, str(path), ["/planning/planning_debug"])
        bag = voy_vbag.Bag(str(path))
        frames = []
        try:
            for _, msg, published in common_utils.sequential_bags_reader_with_publish_time(
                    bag, topics=["/planning/planning_debug"], start_time=start, end_time=end):
                frames.append(extract_frame(msg, published))
                if len(frames) > 1000:
                    raise ValueError("too many frames")
        finally:
            bag.close()
    print(json.dumps({"status": "ready", "frames": sorted(frames, key=lambda f: f["timestamp_ms"])}))


if __name__ == "__main__":
    main()
