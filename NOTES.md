# RA 工具链踩坑笔记

环境配置、bag 下载、仿真运行过程中遇到的非显而易见的问题记录。

---

## 1. EzSim 仿真

### 1.1 cloud_server EzSim 地址

```
https://172.16.145.60:10900
```

`~/.voyager/ezsim/agent.port` 记的是本地 EzSim agent 端口（如 10800），如果本机没跑 EzSim 会报 Connection refused。
触发仿真时加 `--server https://172.16.145.60:10900` 指向 cloud_server。

### 1.2 `Voyager` build 有 undefined symbol 问题

cloud_server 上注册的 `Voyager` build（`/volume/home/workspace/voyager/bazel-build/bin/devel`）存在编译不完整的问题：

```
libplanner_node.so: undefined symbol: _ZN7planner3fLB60FLAGS_planning_enable_selection_longitudinal_speed_diff_costE
```

**解决**：改用 `DefaultBuild`（voyager2）或用 `--binary <id>` 指定 CI binary：

```bash
# 用 DefaultBuild
python3 scripts/ezsim_run.py 32138520 --server https://172.16.145.60:10900 --build DefaultBuild --wait

# 用 CI binary
python3 scripts/ezsim_run.py 32138520 --server https://172.16.145.60:10900 --binary 1665523 --wait
```

### 1.3 不同 build 的仿真结果可能差异很大

以 scenario 32138520（cn32318631）为例：

| build | RA 触发 | 触发时间 |
|-------|---------|---------|
| 路测真实 | 是 | 1779665038741ms |
| DefaultBuild (voyager2) | 是 | 1779665026252ms（早 12s） |
| binary 1665523（路测版本） | **否** | — |

binary 1665523 复现不了是因为 FN forcing rule（`AssistStuckForcingRecallStrategy`）的计数器在仿真中从 0 开始，35s 内无法累积到阈值。

---

## 2. bag 下载

### 2.1 `voy_scan_udp` C 扩展加载失败

`voy_tempest` 导入时会尝试加载 `voy_scan_udp`（C 扩展），在某些环境下会报 `undefined symbol`。
**解决**：在 import 前注入 stub：

```python
import types, sys
_stub = types.ModuleType("voy_scan_udp")
_stub.TOPIC_MAP = {}
class _FakeScanUdpConverter:
    def __init__(self, *a, **kw): pass
    def convert(self, *a, **kw): return None
_stub.ScanUdpConverter = _FakeScanUdpConverter
sys.modules["voy_scan_udp"] = _stub
```

### 2.2 ICU 版本不兼容（本机运行 voy_vbag 时）

本机（Ubuntu 22.04，ICU 70）+ EzSim 18.04 编译的 ROS 库（ICU 60）混用时报：

```
libicui18n.so.60: cannot open shared object file
```

**解决**：在 cloud_server 上下载（Ubuntu 22.04 + EzSim 也是 22.04，版本一致），用 `scripts/download_road_bag_cloud.py`。

### 2.3 cloud_server 上 vbag_modules.so 需要 LD_LIBRARY_PATH

`vbag_modules.so` 没有设置 RPATH，依赖的 `libvbag_proto.so` 等需要手动加入 `LD_LIBRARY_PATH`：

```bash
export LD_LIBRARY_PATH=/volume/home/.voyager/ezsim/binary/1665523/tmp/lib:$LD_LIBRARY_PATH
```

`scripts/download_road_bag_cloud.py` 已经通过 `os.execve` 自动重启处理，无需手动设置。

---

## 3. bag 读取与 proto 解析

### 3.1 rosbag Python 库无法反序列化 proto_msg 类型

`proto_msg/PlanningDebug` 的 md5 是 `"proto_md5"`，标准 rosbag 库拿到的 msg 没有任何字段属性：

```python
msg.behaviorReasonerDebug  # AttributeError！
```

**正确做法**：用 `raw=True` 读原始字节，再用 pb2 反序列化：

```python
for topic, msg, t in bag.read_messages(raw=True):
    dtype, data, md5, pos, pytype = msg
    proto_bytes = data[4:]  # 跳过前 4 字节 ROS 长度前缀
    pd = PlanningDebug()
    pd.ParseFromString(proto_bytes)
```

或使用 `rosbags` 库（纯 Python，推荐）：

```python
from rosbags.rosbag1 import Reader
with Reader(bag_path) as reader:
    for conn, ts, rawdata in reader.messages(connections=conns):
        pd.ParseFromString(rawdata[4:])
```

### 3.2 `rosbags.Reader.messages()` 传空 connections 会遍历全部消息

`connections=[]` 时不是"不读"，而是退化为读所有消息。需要判断后再调用：

```python
if conns:
    for conn, ts, rawdata in reader.messages(connections=conns):
        ...
```

### 3.3 proto pb2 两种来源

**优先**：`~/workspace/voyager/bazel-build/bin/protobuf_python/protos_python_pb/`
— Docker 编译产物，包含全部字段，宿主机可直接访问（共享 `~/.cache/bazel`）。

**兜底**：`scripts/planning_stub.proto` 手写 stub，只含 `is_opened` 字段路径（field numbers 21→14→5→1）。
字段 field number 改变时需手动更新 stub。

`scripts/read_bag.py` 启动时自动检测，找不到 bazel 产物时降级到 stub。

---

## 4. proto 字段路径备忘

`planning_debug.behaviorReasonerDebug.assistDebug.assistRequestSession.isOpened`
对应 proto field numbers：`PlanningDebug(21)` → `BehaviorReasonersDebug(14)` → `AssistDebug(5)` → `AssistRequestSession(1)`

proto 文件位置：
- `onboard/planner/planner_protos/planning_debug.proto`（field 21）
- `onboard/planner/planner_protos/debug/behavior_reasoners/behavior_reasoners_debug.proto`（field 14）
- `onboard/planner/planner_protos/debug/behavior_reasoners/assist/assist_debug.proto`（field 5）
- `onboard/planner/planner_protos/common/behavior_reasoner/assist_request_session.proto`（field 1）
