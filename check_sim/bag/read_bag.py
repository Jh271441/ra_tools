#!/usr/bin/env python3
"""
从 .bag 文件中读取 proto 字段（无需 ROS/voyager 运行时）。

依赖（只需 pip）：
  pip install rosbags

proto 定义来自 voyager Docker 编译产物（bazel-build/bin/protobuf_python/protos_python_pb/），
两种方式二选一：

  方式 A（推荐）：直接引用 Docker 编译好的 pb2（路径需能访问）
    VOYAGER_PROTO_PB=/home/didi/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb

  方式 B（无 voyager 时的兜底）：用本目录的 planning_stub_pb2.py（手写 stub）
    pip install grpcio-tools
    python3 -m grpc_tools.protoc \
      -I check_sim/bag --python_out=check_sim/bag check_sim/bag/planning_stub.proto

用法：
  python3 check_sim/bag/read_bag.py /tmp/my_road.bag
  python3 check_sim/bag/read_bag.py /tmp/my_road.bag --topic /planning/assist_request --show-all
  python3 check_sim/bag/read_bag.py /tmp/my_road.bag --only-opened
"""

import sys
import os
import argparse

# ── proto 路径：优先用 voyager bazel 编译产物，回退到 stub ──
_VOYAGER_PROTO_PB = os.path.expanduser(
    "~/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb"
)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

if os.path.isdir(_VOYAGER_PROTO_PB):
    sys.path.insert(0, _VOYAGER_PROTO_PB)
    _PROTO_SOURCE = "voyager bazel-build"
else:
    sys.path.insert(0, _SCRIPT_DIR)
    _PROTO_SOURCE = "local stub"


def _get_planning_debug_class():
    """加载 PlanningDebug，优先用完整 pb2，回退到 stub。"""
    if _PROTO_SOURCE == "voyager bazel-build":
        from planner_protos import planning_debug_pb2
        return planning_debug_pb2.PlanningDebug
    else:
        # stub 不存在时自动编译
        pb2_file = os.path.join(_SCRIPT_DIR, "planning_stub_pb2.py")
        if not os.path.exists(pb2_file):
            proto_src = os.path.join(_SCRIPT_DIR, "planning_stub.proto")
            if not os.path.exists(proto_src):
                raise FileNotFoundError(
                    f"找不到 {proto_src}，且 voyager bazel-build 路径也不存在。\n"
                    f"请确保 planning_stub.proto 在 check_sim/ 下，或能访问 {_VOYAGER_PROTO_PB}"
                )
            import subprocess
            print("[setup] 编译 planning_stub.proto ...", flush=True)
            r = subprocess.run(
                [sys.executable, "-m", "grpc_tools.protoc",
                 f"-I{_SCRIPT_DIR}", f"--python_out={_SCRIPT_DIR}", proto_src],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                raise RuntimeError(f"protoc 失败:\n{r.stderr}")
        from planning_stub_pb2 import PlanningDebug
        return PlanningDebug


from rosbags.rosbag1 import Reader

# ── 各 topic 的打印逻辑 ──

def _print_planning_debug(ts_ms: int, rawdata: bytes, *, only_opened: bool = False):
    PlanningDebug = _get_planning_debug_class()
    pd = PlanningDebug()
    pd.ParseFromString(rawdata[4:])  # 跳过 4 字节 ROS 长度前缀
    sess = pd.behavior_reasoner_debug.assist_debug.assist_request_session
    if only_opened and not sess.is_opened:
        return
    print(f"  [{ts_ms}ms] is_opened={sess.is_opened}")


def _print_raw(ts_ms: int, rawdata: bytes, **_):
    print(f"  [{ts_ms}ms] {len(rawdata)} bytes (raw)")


# ── 主逻辑 ──

KNOWN_TOPICS = {
    "/planning/planning_debug":                _print_planning_debug,
    "/planning/assist_request":                _print_raw,
    "/planning/stuck_detection_recall_signal": _print_raw,
}


def read_bag(bag_path: str, topics: list, show_all: bool, only_opened: bool):
    with Reader(bag_path) as reader:
        available = {c.topic: c.msgcount for c in reader.connections}
        print(f"bag: {bag_path}  (proto source: {_PROTO_SOURCE})")
        print(f"topics: { {t: n for t, n in available.items()} }")
        print()

        if topics:
            conns = [c for c in reader.connections if c.topic in topics]
        elif show_all:
            conns = list(reader.connections)
        else:
            conns = [c for c in reader.connections if c.topic == "/planning/planning_debug"]

        for conn, ts, rawdata in reader.messages(connections=conns):
            ts_ms = ts // 1_000_000
            handler = KNOWN_TOPICS.get(conn.topic, _print_raw)
            handler(ts_ms, rawdata, only_opened=only_opened)


def main():
    parser = argparse.ArgumentParser(description="Read proto fields from .bag (no ROS needed)")
    parser.add_argument("bag", help=".bag 文件路径")
    parser.add_argument("--topic", nargs="*", help="只显示指定 topic")
    parser.add_argument("--show-all", action="store_true", help="显示所有 topic 的所有消息")
    parser.add_argument("--only-opened", action="store_true", help="只打印 is_opened=True 的行")
    args = parser.parse_args()

    read_bag(args.bag, args.topic or [], args.show_all, args.only_opened)


if __name__ == "__main__":
    main()
