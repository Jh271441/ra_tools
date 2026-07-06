"""读取某次 EzSim 仿真的 forcing-recall 计数器轨迹（验证 RA 复现性 ② 的工具）。

数据源：events.log 中的 AssistStuckForcingRecallHit 事件，
每个累积 cycle 都会 post 一次 state 的 DebugString（见 forcing_recall.cpp:362）。
据此回答：
  - 计数器第一帧值是多少（warmup seed 是否把高计数带进来）
  - 是否爬到 trigger_cycle（能否触发）
  - 中途有没有被 Reset（ego 速度过 reset_speed_mps=2.0）

用法:
    python3 read_forcing_trajectory.py <sim_id> [<sim_id> ...]
    python3 read_forcing_trajectory.py --base /custom/sim/dir <sim_id>
"""
import argparse
import re
import sys
from pathlib import Path

DEFAULT_BASE = Path.home() / ".voyager/ezsim/simulation"

HIT_KEY = "rt_event.planner::AssistStuckForcingRecallHit"
FORBID_KEY = "rt_event.planner::AssistStuckRequestForbidByLaneChange"
ROUTE_KEY = "rt_event.planner::RouteUnstuck"
TRIGGER_KEY = "rt_event.planner::AssistStuckForcingRecallTrigger"


def _values_for(content: str, event_key: str):
    """提取某 eventKey 的所有 eventValue（已 unescape）。"""
    pat = (r'"eventKey"\s*:\s*"' + re.escape(event_key) +
           r'".*?"eventValue"\s*:\s*"((?:[^"\\]|\\.)*)"')
    out = []
    for m in re.finditer(pat, content, re.DOTALL):
        raw = m.group(1)
        try:
            out.append(raw.encode().decode("unicode_escape"))
        except Exception:
            out.append(raw)
    return out


def _num(s, key, cast=int):
    m = re.search(re.escape(key) + r'["\s:]+(-?[\d.]+)', s)
    return cast(m.group(1)) if m else None


def analyze(sim_dir: Path):
    log = sim_dir / "events.log"
    if not log.exists():
        print(f"  ✗ 无 events.log: {log}")
        return
    content = log.read_bytes().decode("utf-8", errors="replace")

    hits = _values_for(content, HIT_KEY)
    if not hits:
        print("  forcing-recall: 无 Hit 事件 → 计数器从未累积"
              "（要么 ego 一直 >2.0 m/s 被 Reset，要么一直有 valid stationary reason）")
    else:
        accs = [(_num(h, "accumulated_cycle"), _num(h, "ego_speed", float),
                 _num(h, "trigger_cycle")) for h in hits]
        accs = [a for a in accs if a[0] is not None]
        first_acc = accs[0][0]
        max_acc = max(a[0] for a in accs)
        trig = next((a[2] for a in accs if a[2]), "?")
        # 检测回退（Reset 后重新从低值开始）
        resets = sum(1 for i in range(1, len(accs)) if accs[i][0] < accs[i - 1][0] - 1)
        speeds = [a[1] for a in accs if a[1] is not None]
        print(f"  forcing-recall: Hit数={len(accs)}  首帧accumulated={first_acc}  "
              f"峰值={max_acc}  trigger_cycle={trig}")
        print(f"                  达到阈值={'是' if isinstance(trig,int) and max_acc>=trig else '否'}  "
              f"中途回退次数={resets}  "
              f"ego_speed[min/max]={min(speeds):.2f}/{max(speeds):.2f}" if speeds else "")
        # 判读
        if first_acc is not None and first_acc <= 2:
            print("                  ⚠ 首帧≈0 → warmup seed 未把路测高计数带入（疑似真 bug 或窗口起点选早了）")
        elif first_acc and first_acc > 50:
            print(f"                  ✓ warmup seed 带入了高计数（首帧={first_acc}）")
        if resets:
            print("                  ⚠ 计数器中途被 Reset → ego 速度越过 2.0 m/s（场景发散 ③）")

    trig_evt = _values_for(content, TRIGGER_KEY)
    print(f"  ForcingRecallTrigger 事件: {len(trig_evt)}（>0 表示 forcing recall 真的触发了 request）")
    forbid = _values_for(content, FORBID_KEY)
    if forbid:
        print(f"  ⚠ ForbidByLaneChange: {len(forbid)} 次（FP 压制，类型 A）")
    route = _values_for(content, ROUTE_KEY)
    if route:
        kinds = set(re.findall(r'(receive_fix_point_from_cloud|kRelaxLaneMarking\w*)', " ".join(route)))
        print(f"  RouteUnstuck: {len(route)} 次  kinds={kinds or '?'}（场景发散信号，类型 B）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sim_ids", nargs="+")
    ap.add_argument("--base", default=str(DEFAULT_BASE))
    args = ap.parse_args()
    base = Path(args.base)
    for sid in args.sim_ids:
        print(f"=== sim {sid} ===")
        analyze(base / sid)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
