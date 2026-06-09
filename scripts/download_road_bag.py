#!/usr/bin/env python3
"""
从 Tempest 下载路测 bag 片段（不依赖 voy-bag 外部工具）。

首次使用前安装依赖（只需一次）：
  cd /home/didi/workspace/ra_tools
  .venv/bin/pip install voy-tempest \
      -i http://10.88.128.83/pypi/voyager/stable/+simple/ --trusted-host 10.88.128.83
  .venv/bin/pip install "numpy<2" boto3 \
      /home/didi/workspace/voyager/offboard/sparklingwater/third_party_pkg_py310/genpy-0.6.14-py3-none-any.whl \
      /home/didi/workspace/voyager/offboard/sparklingwater/third_party_pkg_py310/genmsg-0.5.16-py3-none-any.whl

直接运行（脚本会自动编译 ICU shim 并 LD_PRELOAD 自身）：
  .venv/bin/python3 scripts/download_road_bag.py \\
      --trip 10385_20260525_070411 \\
      --start 1779665020000 \\
      --end   1779665070000 \\
      --output /tmp/my_road.bag
"""

import sys
import os
import subprocess
import argparse

# ─────────────────────────────────────────────────────────────────────
# 背景：EzSim 的 ROS 原生库编译于 Ubuntu 18.04（ICU 60），
#       本机 Ubuntu 22.04 装的是 ICU 70，namespace 不同导致符号找不到。
#       在子进程里 LD_PRELOAD 一个 shim 库来桥接，不影响父进程。
# ─────────────────────────────────────────────────────────────────────

SHIM_SRC  = os.path.join(os.path.dirname(__file__), "icu60shim.cpp")
SHIM_SO   = "/tmp/libicu60shim.so"
EZSIM_LIB = "/media/didi/data/ezsim/binary/1347303/tmp/lib"


def _build_shim_if_needed():
    """编译 ICU shim（如果尚未编译）。"""
    if os.path.exists(SHIM_SO):
        return
    print("[setup] Compiling ICU 60→70 shim ...", flush=True)
    result = subprocess.run(
        ["g++", "-shared", "-fPIC", "-o", SHIM_SO, SHIM_SRC, "-licuuc", "-licui18n"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[error] shim compile failed:\n{result.stderr}")
        sys.exit(1)
    print(f"[setup] shim built: {SHIM_SO}", flush=True)


def _relaunch_with_preload():
    """用 LD_PRELOAD 重新启动自身（只跑一次）。"""
    if os.environ.get("_ICU_SHIM_ACTIVE"):
        return  # 已经在 preload 环境里了

    _build_shim_if_needed()

    env = os.environ.copy()
    env["LD_PRELOAD"] = SHIM_SO
    env["LD_LIBRARY_PATH"] = f"/tmp:{EZSIM_LIB}:" + env.get("LD_LIBRARY_PATH", "")
    env["_ICU_SHIM_ACTIVE"] = "1"

    os.execve(sys.executable, [sys.executable] + sys.argv, env)


# 重启自身（带 preload），如果已经在 preload 环境里则直接跳过
_relaunch_with_preload()

# ─────── 以下代码只在 LD_PRELOAD 生效后执行 ───────

import types

EZSIM_SITE = f"{EZSIM_LIB}/../lib/voy-sdk/python3/dist-packages"
EZSIM_PY   = f"{EZSIM_LIB}/../lib/python3/dist-packages"
VENV_SITE  = "/home/didi/workspace/ra_tools/.venv/lib/python3.10/site-packages"

sys.path = [EZSIM_SITE, EZSIM_PY, EZSIM_LIB + "/../lib"] + sys.path
sys.path.append(VENV_SITE)

os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

# voy_scan_udp 的 C 扩展在本机无法加载，注入 stub
_scan_stub = types.ModuleType("voy_scan_udp")
_scan_stub.TOPIC_MAP = {}

class _FakeScanUdpConverter:
    def __init__(self, *a, **kw): pass
    def convert(self, *a, **kw): return None

_scan_stub.ScanUdpConverter = _FakeScanUdpConverter
sys.modules["voy_scan_udp"] = _scan_stub

from voy_tempest import bag as tempest_bag  # noqa: E402

DEFAULT_TOPICS = [
    "/planning/planning_debug",
    "/planning/assist_request",
    "/planning/stuck_detection_recall_signal",
]


def download(trip_id: str, start_ms: int, end_ms: int, output: str, topics=None):
    topics = topics or DEFAULT_TOPICS
    print(f"[INFO] trip={trip_id}  {start_ms} ~ {end_ms}  "
          f"({(end_ms - start_ms) / 1000:.0f}s)")
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
    parser = argparse.ArgumentParser(description="Download road bag segment from Tempest")
    parser.add_argument("--trip",   required=True, help="trip_id, e.g. 10385_20260525_070411")
    parser.add_argument("--start",  required=True, type=int, help="start time ms")
    parser.add_argument("--end",    required=True, type=int, help="end time ms")
    parser.add_argument("--output", required=True, help="output .bag file path")
    parser.add_argument("--topics", nargs="*",
                        help="topics to download (default: planning_debug + assist_request + stuck_detection_recall_signal)")
    args = parser.parse_args()
    download(args.trip, args.start, args.end, args.output, args.topics or None)
