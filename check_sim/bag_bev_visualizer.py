#!/usr/bin/env python3
"""
Bag BEV Visualizer —— 从 .bag 中读取 planning_debug / tracked_objects / remote_assist_model_debug，
生成以自车为中心、朝向正上方的鸟瞰图（BEV）。

功能：
  1. 自车 bounding box（粉色，带朝向箭头）
  2. 周围障碍物 bounding box（蓝色半透明）—— 来自 /perception/tracked_objects
  3. unstuck_nominal_path 的 points（绿色连线+圆点）——来自 /planning/remote_assist_model_debug，
     仅在收到该消息时绘制

运行环境：
  conda activate assist_stuck
  export PYTHONPATH=~/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb

用法：
  python3 check_sim/bag_bev_visualizer.py /path/to/road.bag
  python3 check_sim/bag_bev_visualizer.py /path/to/sim.bag --output-dir ./my_frames --range 50
  python3 check_sim/bag_bev_visualizer.py /path/to/sim.bag --every-n 5
  python3 check_sim/bag_bev_visualizer.py /path/to/sim.bag --max-frames 100
"""

import sys
import os
import argparse
import math

# ── proto path ──
_VOYAGER_PROTO_PB = os.path.expanduser(
    "~/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb"
)
if os.path.isdir(_VOYAGER_PROTO_PB) and _VOYAGER_PROTO_PB not in sys.path:
    sys.path.insert(0, _VOYAGER_PROTO_PB)


def _load_visualization_runtime():
    global np, plt, Reader

    import matplotlib
    import numpy as np_module
    from rosbags.rosbag1 import Reader as BagReader

    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot

    np = np_module
    plt = pyplot
    Reader = BagReader


# ──────────────────────────────────────────────────────────────────────
#  Proto class loaders
# ──────────────────────────────────────────────────────────────────────

def _load_planning_debug_class():
    from planner_protos import planning_debug_pb2
    return planning_debug_pb2.PlanningDebug


def _load_model_debug_class():
    from planner_protos import remote_assist_model_debug_pb2
    return remote_assist_model_debug_pb2.RemoteAssistModelDebug


def _load_tracked_objects_class():
    from voy_protos import tracked_objects_pb2
    return tracked_objects_pb2.TrackedObjectList


# ──────────────────────────────────────────────────────────────────────
#  Geometry: world → ego-centric (ego heading = up = +Y)
# ──────────────────────────────────────────────────────────────────────

def world_to_ego(wx, wy, ego_x, ego_y, ego_yaw):
    """将世界坐标转换到以 ego 为原点、ego heading 朝上 (+Y) 的坐标系。"""
    dx = wx - ego_x
    dy = wy - ego_y
    # 旋转使 ego heading 对齐 +Y 轴
    angle = -(ego_yaw - math.pi / 2)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    ex = cos_a * dx - sin_a * dy
    ey = sin_a * dx + cos_a * dy
    return ex, ey


def rotate_heading_to_ego(heading, ego_yaw):
    """将世界坐标系的 heading 转到 ego-centric 坐标系。"""
    return heading - ego_yaw + math.pi / 2


def make_box_corners(cx, cy, length, width, heading):
    """生成旋转矩形的4个角点 (左后→右后→右前→左前)。"""
    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    hl, hw = length / 2, width / 2
    corners = []
    for dl, dw in [(-hl, -hw), (-hl, hw), (hl, hw), (hl, -hw)]:
        x = cx + dl * cos_h - dw * sin_h
        y = cy + dl * sin_h + dw * cos_h
        corners.append((x, y))
    return corners


# ──────────────────────────────────────────────────────────────────────
#  Color palette (dark theme, inspired by InteractiveDataSim)
# ──────────────────────────────────────────────────────────────────────

BG_COLOR      = "#1a1a2e"
GRID_COLOR    = "#2a2a4a"
EGO_COLOR     = "#ff69b4"      # 粉色
EGO_EDGE      = "#ff1493"
OBJ_COLOR     = "#5dade2"      # 蓝色
OBJ_EDGE      = "#3498db"
PATH_COLOR    = "#2ecc71"      # 绿色
PATH_DOT      = "#27ae60"
TEXT_COLOR    = "#e0e0e0"
ARROW_COLOR   = "#ffffff"


# ──────────────────────────────────────────────────────────────────────
#  Drawing
# ──────────────────────────────────────────────────────────────────────

def draw_bev(
    ego_x, ego_y, ego_yaw,
    ego_length, ego_width,
    objects,          # list of (cx, cy, length, width, heading, obj_type_str)
    path_points,      # list of (x, y) in world coords, or None
    frame_idx,
    timestamp_ms,
    output_path,
    view_range=60,
):
    """绘制一帧 BEV 图。"""
    fig, ax = plt.subplots(1, 1, figsize=(10, 10), dpi=120)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    half = view_range / 2

    # ── Grid ──
    grid_step = 10
    for g in np.arange(-half, half + grid_step, grid_step):
        ax.axhline(y=g, color=GRID_COLOR, linewidth=0.5, alpha=0.6)
        ax.axvline(x=g, color=GRID_COLOR, linewidth=0.5, alpha=0.6)

    # ── Obstacles (tracked objects) ──
    for (ox, oy, ol, ow, oh, otype) in objects:
        ex, ey = world_to_ego(ox, oy, ego_x, ego_y, ego_yaw)
        if abs(ex) > half + 5 or abs(ey) > half + 5:
            continue
        eh = rotate_heading_to_ego(oh, ego_yaw)
        corners = make_box_corners(ex, ey, ol, ow, eh)
        poly = plt.Polygon(corners, closed=True,
                           facecolor=OBJ_COLOR, edgecolor=OBJ_EDGE,
                           alpha=0.5, linewidth=1.2)
        ax.add_patch(poly)
        # 朝向箭头
        arrow_len = max(ol, ow) * 0.4
        ax.annotate("", xy=(ex + arrow_len * math.cos(eh),
                            ey + arrow_len * math.sin(eh)),
                    xytext=(ex, ey),
                    arrowprops=dict(arrowstyle="->", color=ARROW_COLOR,
                                   lw=1.0, mutation_scale=8))

    # ── Unstuck nominal path points ──
    if path_points and len(path_points) > 0:
        pts_ego = [world_to_ego(px, py, ego_x, ego_y, ego_yaw)
                   for (px, py) in path_points]
        xs = [p[0] for p in pts_ego]
        ys = [p[1] for p in pts_ego]
        ax.plot(xs, ys, color=PATH_COLOR, linewidth=2.5, alpha=0.85,
                zorder=5, label="unstuck path")
        ax.scatter(xs, ys, color=PATH_DOT, s=30, zorder=6,
                   edgecolors=PATH_COLOR, linewidths=0.8)

    # ── Ego vehicle (always at origin, heading up) ──
    ego_heading_ego = math.pi / 2
    ego_corners = make_box_corners(0, 0, ego_length, ego_width, ego_heading_ego)
    ego_poly = plt.Polygon(ego_corners, closed=True,
                           facecolor=EGO_COLOR, edgecolor=EGO_EDGE,
                           alpha=0.8, linewidth=2, zorder=10)
    ax.add_patch(ego_poly)
    ax.annotate("", xy=(0, ego_length * 0.5), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color="#ffffff",
                                lw=2.0, mutation_scale=15),
                zorder=11)

    # ── Axes ──
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_aspect("equal")
    ax.tick_params(colors=TEXT_COLOR, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    # ── Title ──
    title = f"Frame {frame_idx}  |  ts={timestamp_ms}ms"
    n_obj = len([1 for (ox, oy, ol, ow, oh, ot) in objects
                 if abs(world_to_ego(ox, oy, ego_x, ego_y, ego_yaw)[0]) <= half + 5
                 and abs(world_to_ego(ox, oy, ego_x, ego_y, ego_yaw)[1]) <= half + 5])
    title += f"  |  objs={n_obj}"
    if path_points:
        title += f"  |  path pts={len(path_points)}"
    ax.set_title(title, color=TEXT_COLOR, fontsize=11, pad=10)
    ax.set_xlabel("← left          right →", color=TEXT_COLOR, fontsize=8)
    ax.set_ylabel("← behind          ahead →", color=TEXT_COLOR, fontsize=8)

    if path_points:
        ax.legend(loc="upper right", fontsize=8, facecolor=BG_COLOR,
                  edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)

    plt.tight_layout()
    fig.savefig(output_path, facecolor=fig.get_facecolor())
    plt.close(fig)


# ──────────────────────────────────────────────────────────────────────
#  Bag parsing
# ──────────────────────────────────────────────────────────────────────

DEFAULT_EGO_LENGTH = 4.9
DEFAULT_EGO_WIDTH  = 1.9


def parse_planning_debug(rawdata, PlanningDebug):
    """解析 /planning/planning_debug → (ego_pose, []) 。"""
    pd = PlanningDebug()
    pd.ParseFromString(rawdata[4:])  # 跳过 4 字节 ROS 长度前缀
    pose = pd.pose
    return (pose.x, pose.y, pose.yaw)


def parse_model_debug(rawdata, RemoteAssistModelDebug):
    """解析 /planning/remote_assist_model_debug → [(x,y), ...] unstuck path points。"""
    md = RemoteAssistModelDebug()
    md.ParseFromString(rawdata[4:])
    points = []
    try:
        for p in md.waypoint_auto_generation_model_debug.unstuck_nominal_path.points:
            points.append((p.x, p.y))
    except Exception:
        pass
    return points


def parse_tracked_objects(rawdata, TrackedObjectList):
    """解析 /perception/tracked_objects → objects list。"""
    tol = TrackedObjectList()
    tol.ParseFromString(rawdata[4:])
    objects = []
    for obj in tol.tracked_objects:
        if obj.length > 0.1 and obj.width > 0.1:
            objects.append((
                obj.center_x, obj.center_y,
                obj.length, obj.width,
                obj.heading,
                str(obj.object_type),
            ))
        elif len(obj.contour) >= 3:
            xs = [p.x for p in obj.contour]
            ys = [p.y for p in obj.contour]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            dx, dy = max(xs) - min(xs), max(ys) - min(ys)
            objects.append((cx, cy, max(dx, 0.5), max(dy, 0.5),
                            obj.heading, str(obj.object_type)))
    return objects


# ──────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="从 .bag 生成 BEV 可视化帧（自车朝上，显示 obstacles 和 unstuck path）"
    )
    parser.add_argument("bag", help=".bag 文件路径")
    parser.add_argument("--output-dir", default="./bev_frames",
                        help="输出目录 (默认 ./bev_frames)")
    parser.add_argument("--range", type=float, default=60,
                        help="BEV 视野范围 (米，默认 60)")
    parser.add_argument("--every-n", type=int, default=1,
                        help="每 N 帧画一张 (默认 1)")
    parser.add_argument("--max-frames", type=int, default=0,
                        help="最多画多少帧 (0=不限)")
    parser.add_argument("--ego-length", type=float, default=DEFAULT_EGO_LENGTH)
    parser.add_argument("--ego-width", type=float, default=DEFAULT_EGO_WIDTH)
    args = parser.parse_args()

    _load_visualization_runtime()
    os.makedirs(args.output_dir, exist_ok=True)

    PlanningDebug = _load_planning_debug_class()
    RemoteAssistModelDebug = _load_model_debug_class()
    TrackedObjectList = _load_tracked_objects_class()

    PLANNING_TOPIC = "/planning/planning_debug"
    MODEL_TOPIC    = "/planning/remote_assist_model_debug"
    TRACKED_TOPIC_CANDIDATES = [
        "/perception/tracked_objects",
        "/perception/tracked_object_list",
    ]

    print(f"bag: {args.bag}")
    print(f"output: {args.output_dir}")
    print(f"view range: {args.range}m, every-n: {args.every_n}")
    print()

    with Reader(args.bag) as reader:
        available = {c.topic: c.msgcount for c in reader.connections}

        # 自动检测 tracked objects topic 名
        TRACKED_TOPIC = None
        for candidate in TRACKED_TOPIC_CANDIDATES:
            if candidate in available:
                TRACKED_TOPIC = candidate
                break

        all_interesting = {PLANNING_TOPIC, MODEL_TOPIC} | set(TRACKED_TOPIC_CANDIDATES)
        print("topics in bag:")
        for t, n in sorted(available.items()):
            marker = " ◄" if t in all_interesting else ""
            print(f"  {t}: {n} msgs{marker}")
        print()

        if PLANNING_TOPIC not in available:
            print(f"✗ 缺少 {PLANNING_TOPIC}，无法获取 ego pose，退出。")
            sys.exit(1)
        if TRACKED_TOPIC:
            print(f"✓ 使用 {TRACKED_TOPIC} 读取障碍物 bounding box")
        else:
            print(f"⚠ 未找到 tracked objects topic，将无法显示障碍物 bounding box")
        if MODEL_TOPIC not in available:
            print(f"⚠ 缺少 {MODEL_TOPIC}，将无法显示 unstuck path points")

        topic_set = {PLANNING_TOPIC}
        if MODEL_TOPIC in available:
            topic_set.add(MODEL_TOPIC)
        if TRACKED_TOPIC:
            topic_set.add(TRACKED_TOPIC)

        conns = [c for c in reader.connections if c.topic in topic_set]

        latest_path_points = None
        latest_tracked_objects = []
        frame_idx = 0
        drawn_count = 0

        print("开始处理帧...", flush=True)

        for conn, ts, rawdata in reader.messages(connections=conns):
            ts_ms = ts // 1_000_000

            if conn.topic == MODEL_TOPIC:
                pts = parse_model_debug(rawdata, RemoteAssistModelDebug)
                if pts:
                    latest_path_points = pts
                    print(f"  [model_debug] ts={ts_ms}ms  收到 {len(pts)} 个 path points")
                continue

            if conn.topic == TRACKED_TOPIC:
                latest_tracked_objects = parse_tracked_objects(rawdata, TrackedObjectList)
                continue

            if conn.topic == PLANNING_TOPIC:
                frame_idx += 1
                if frame_idx % args.every_n != 0:
                    continue

                ego_pose = parse_planning_debug(rawdata, PlanningDebug)
                ego_x, ego_y, ego_yaw = ego_pose

                # 跳过 pose 未初始化的帧 (warmup 阶段 x=y=yaw=0)
                if ego_x == 0.0 and ego_y == 0.0 and ego_yaw == 0.0:
                    continue

                out_path = os.path.join(args.output_dir, f"bev_{drawn_count:06d}.png")

                draw_bev(
                    ego_x, ego_y, ego_yaw,
                    args.ego_length, args.ego_width,
                    latest_tracked_objects,
                    latest_path_points,
                    frame_idx, ts_ms,
                    out_path,
                    view_range=args.range,
                )

                drawn_count += 1
                if drawn_count % 10 == 0:
                    print(f"  已生成 {drawn_count} 帧 (frame_idx={frame_idx}, ts={ts_ms}ms)",
                          flush=True)

                if 0 < args.max_frames <= drawn_count:
                    print(f"  达到 max-frames={args.max_frames}，停止")
                    break

    print(f"\n✓ 完成！共生成 {drawn_count} 帧 BEV 图像到 {args.output_dir}/")
    print(f"  可用 ffmpeg 合成视频：")
    print(f"  ffmpeg -framerate 10 -i {args.output_dir}/bev_%06d.png "
          f"-c:v libx264 -pix_fmt yuv420p bev_replay.mp4")


if __name__ == "__main__":
    main()
