#!/usr/bin/env python3
"""
在 cloud_server (172.16.145.60:12017) 上下载路测 bag 片段。

直接运行，无需额外配置：
  python3 download_road_bag_cloud.py \
      --trip 10385_20260525_070411 \
      --start 1779665020000 \
      --end   1779665070000 \
      --output /tmp/my_road.bag

可选：--topics /topic1 /topic2 ...
"""

import sys
import os
import types
import argparse

# 确保 LD_LIBRARY_PATH 包含 EzSim 共享库（重启一次自身）
EZSIM_LIB = "/volume/home/.voyager/ezsim/binary/1665523/tmp/lib"
if "_EZSIM_LIB_SET" not in os.environ:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = EZSIM_LIB + ":" + env.get("LD_LIBRARY_PATH", "")
    env["_EZSIM_LIB_SET"] = "1"
    os.execve(sys.executable, [sys.executable] + sys.argv, env)

# rosbag 在 /opt/voy-sdk 下，需要加进 sys.path
sys.path.insert(0, "/opt/voy-sdk/lib/python3/dist-packages")

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

# voy_scan_udp 的 C 扩展不可用，注入 stub
_scan_stub = types.ModuleType("voy_scan_udp")
_scan_stub.TOPIC_MAP = {}

class _FakeScanUdpConverter:
    def __init__(self, *a, **kw): pass
    def convert(self, *a, **kw): return None

_scan_stub.ScanUdpConverter = _FakeScanUdpConverter
sys.modules["voy_scan_udp"] = _scan_stub

from voy_tempest import bag as tempest_bag

DEFAULT_TOPICS = [
    "/planning/planning_debug",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]


def download(trip_id: str, start_ms: int, end_ms: int, output: str, topics=None):
    topics = topics or DEFAULT_TOPICS
    print(f"[INFO] trip={trip_id}  {start_ms}~{end_ms}  ({(end_ms - start_ms) / 1000:.0f}s)")
    print(f"[INFO] topics={topics}")
    print(f"[INFO] output={output}")
    reader = tempest_bag.BagReader(
        trip_id=trip_id,
        start_time=start_ms,
        end_time=end_ms,
        topics=topics,
        user_location=tempest_bag.UserLocation.CN,
    )
    reader.save_to_bag(output)
    print(f"[DONE] saved to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download road bag from Tempest (cloud_server edition)")
    parser.add_argument("--trip",   required=True, help="trip_id, e.g. 10385_20260525_070411")
    parser.add_argument("--start",  required=True, type=int, help="start time ms")
    parser.add_argument("--end",    required=True, type=int, help="end time ms")
    parser.add_argument("--output", required=True, help="output .bag file path")
    parser.add_argument("--topics", nargs="*",
                        help="topics (default: planning_debug + assist_request + stuck_detection)")
    args = parser.parse_args()
    download(args.trip, args.start, args.end, args.output, args.topics or None)
