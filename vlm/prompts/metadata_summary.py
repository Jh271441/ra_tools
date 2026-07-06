from typing import Any, Dict, List, Optional

_SPEED_EPS = 0.3  # m/s

def _has_yield(y: Any) -> bool:
    s = str(y or "").strip()
    return bool(s) and s not in ("无", "None", "nan")

def aggregate_features(windows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """将时间窗口行聚合为标量特征。"""
    if not windows:
        return {"n_windows": 0}

    def _spd(rows: List[Dict[str, Any]]) -> List[float]:
        return [float(w.get("speed", 0.0)) for w in rows]

    pre = [w for w in windows if w.get("t_offset_ms", 0) < 0]
    post = [w for w in windows if w.get("t_offset_ms", 0) > 0]
    pre5 = [w for w in pre if w.get("t_offset_ms", 0) >= -5000]
    post10 = [w for w in post if w.get("t_offset_ms", 0) <= 10000]

    speeds_all = _spd(windows)
    step_ms = 1000
    zero_cnt = sum(1 for s in speeds_all if abs(s) <= _SPEED_EPS)

    w0 = min(windows, key=lambda w: abs(w.get("t_offset_ms", 0)))
    yield_pre = any(_has_yield(w.get("yielding")) for w in pre)
    yield_post = any(_has_yield(w.get("yielding")) for w in post)

    return {
        "n_windows": len(windows),
        "speed_pre_avg": round(sum(_spd(pre5)) / len(pre5), 3) if pre5 else None,
        "speed_pre_max": round(max(_spd(pre5)), 3) if pre5 else None,
        "speed_post_max": round(max(_spd(post10)), 3) if post10 else None,
        "speed_at_t0": round(float(w0.get("speed", 0.0)), 3),
        "speed_zero_duration_s": round(zero_cnt * step_ms / 1000.0, 1),
        "yield_at_t0": _has_yield(w0.get("yielding")),
        "yield_obj_id_t0": str(w0.get("yielding_object_id", "")),
        "yield_status_change": bool(yield_pre and not yield_post),
        "yield_pre": yield_pre,
        "yield_post": yield_post,
    }

def format_metadata_summary(windows: List[Dict[str, Any]], ra_options: Any = None) -> str:
    """将物理时序特征格式化为中文文本摘要，作为 {{metadata_summary}} 注入 prompt。"""
    features = aggregate_features(windows)

    lines = [
        "**车辆物理时序与协助信号分析**:",
    ]

    # 1. 速度特征
    spd_pre_avg = features.get("speed_pre_avg")
    spd_post_max = features.get("speed_post_max")
    spd_at_t0 = features.get("speed_at_t0")
    spd_zero_dur = features.get("speed_zero_duration_s")

    spd_parts = []
    if spd_pre_avg is not None:
        spd_parts.append(f"触发前5s均速 {spd_pre_avg:.2f}m/s")
    if spd_at_t0 is not None:
        spd_parts.append(f"触发时刻速度 {spd_at_t0:.2f}m/s")
    if spd_zero_dur is not None:
        spd_parts.append(f"近静止持续时间 {spd_zero_dur:.1f}s")
    if spd_post_max is not None:
        spd_parts.append(f"触发后10s最大车速 {spd_post_max:.2f}m/s")

    if spd_parts:
        lines.append(f"- 车速演化: {'; '.join(spd_parts)}")

    # 2. 让行与约束
    yield_t0 = features.get("yield_at_t0")
    yield_pre = features.get("yield_pre")
    yield_post = features.get("yield_post")
    yield_change = features.get("yield_status_change")
    obj_id = features.get("yield_obj_id_t0")

    yield_parts = []
    if yield_t0:
        yield_parts.append(f"触发时刻正在让行(对象ID {obj_id or '未知'})")
    else:
        yield_parts.append("触发时刻未检测到让行对象")

    if yield_change:
        yield_parts.append("触发后让行状态自行解除(Yielding→Free)")
    else:
        status_str = "触发前后持续检测到让行" if (yield_pre and yield_post) else \
                     "触发前有让行，后无检测" if yield_pre else \
                     "触发前无让行，后检测到让行" if yield_post else \
                     "全程无让行记录"
        yield_parts.append(status_str)

    lines.append(f"- 让行特征: {'; '.join(yield_parts)}")

    # 3. 远端操作记录
    if ra_options is not None:
        from vlm.prompts.trail_metadata_prejudge import _normalize_ra_options, _STRONG_RECOVERY_OPS
        ops = _normalize_ra_options(ra_options)
        if ops:
            has_strong = bool(set(ops) & _STRONG_RECOVERY_OPS)
            ops_str = "、".join(ops)
            lines.append(f"- 远端协助记录: 包含操作 {ops_str} ({'有' if has_strong else '无'}强脱困指令)")
        else:
            lines.append("- 远端协助记录: 无具体协助指令")
    else:
        lines.append("- 远端协助记录: 无协助指令")

    return "\n".join(lines)
