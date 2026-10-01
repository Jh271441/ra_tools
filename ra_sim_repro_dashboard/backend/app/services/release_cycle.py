"""Business releases switch on Monday using the latest completed Thursday cycle."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
BASE_FILTERS = [
    {"attr_id": "trip_category", "val": [0], "operator": "in"},
    {
        "attr_id": "abnormal_behavior",
        "val": [292, 297, 299, 393, 391],
        "operator": "in",
    },
    {"attr_id": "ra_type", "val": [2], "operator": "in"},
    {"attr_id": "trip_odd", "val": ["ODD2"], "operator": "in"},
    {"attr_id": "is_deleted", "val": [0], "operator": "in"},
    {"attr_id": "platform", "val": [7, 8], "operator": "in"},
]


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def load_cycle_config() -> dict:
    from app.config import CONFIG_DIR

    path = Path(
        os.getenv("RELEASE_CYCLES_CONFIG", str(CONFIG_DIR / "release-cycles.default"))
    )
    if not path.exists():
        return {"periods": []}
    value = json.loads(path.read_text())
    command = os.getenv("RELEASE_DRIVER_COMMAND_JSON")
    if command:
        value.setdefault("simulation", {})["driver_command"] = json.loads(command)
    return value


def reference_thursday(day: date | None = None) -> date:
    day = day or datetime.now(TZ).date()
    return day - timedelta(days=day.weekday() + 4)


def validate_period(period: dict, require_verified: bool = False) -> dict:
    if not period.get("evidence") or (
        not period.get("verified") and period.get("basis") != "inferred"
    ):
        raise ValueError("周期缺少运行记录或历史数据推断依据")
    if require_verified and not period.get("verified"):
        raise ValueError("周期边界仍为推断值，尚未完成数据核实")
    if not period.get("release") or period.get("status") != "completed":
        raise ValueError("周期尚未结束")
    start = datetime.fromisoformat(period["case_start"])
    end = datetime.fromisoformat(period["case_end_exclusive"])
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("周期必须使用带时区的左闭右开时间范围")
    cycle_end = date.fromisoformat(period["cycle_end"])
    if cycle_end.weekday() != 3:
        raise ValueError("周期结束日必须为周四")
    if not start.astimezone(TZ).date() <= cycle_end <= end.astimezone(TZ).date():
        raise ValueError("结束日与 case 时间范围不一致")
    return period


def resolve_current(config: dict, day: date | None = None) -> dict:
    """A running two-week cycle does not displace the last completed release."""
    anchor = reference_thursday(day).isoformat()
    base = {
        "reference_thursday": anchor,
        "current_period": None,
        "current_version": None,
        "period_verified": False,
        "retained_previous": False,
        "switch_weekday": "Monday",
    }
    eligible = [
        p
        for p in config.get("periods", [])
        if p.get("cycle_end")
        and p["cycle_end"] <= anchor
        and p.get("status") == "completed"
    ]
    if not eligible:
        return {
            **base,
            "status": "pending_period",
            "reason": f"{anchor} 尚无已结束的 release 周期记录",
        }
    latest_end = max(p["cycle_end"] for p in eligible)
    candidates = [p for p in eligible if p["cycle_end"] == latest_end]
    if len(candidates) != 1:
        return {
            **base,
            "status": "pending_period",
            "reason": f"{latest_end} 存在多个候选 release，请核对实际结束周期",
        }
    try:
        period = validate_period(candidates[0])
        contract = config.get("contract", {})
        if (
            not contract.get("verified")
            or not contract.get("reference")
            or not contract.get("time_field")
        ):
            raise ValueError("数易查询视图与时间字段尚未核实")
        start = datetime.fromisoformat(period["case_start"])
        end = datetime.fromisoformat(period["case_end_exclusive"])
        for other in config.get("periods", []):
            if (
                other is period
                or other.get("release") != period["release"]
                or other.get("status") != "completed"
            ):
                continue
            a = datetime.fromisoformat(other["case_start"])
            b = datetime.fromisoformat(other["case_end_exclusive"])
            if max(a, start) < min(b, end):
                raise ValueError("同一 release 存在重叠周期配置")
    except (ValueError, KeyError, TypeError) as exc:
        return {**base, "status": "pending_verification", "reason": str(exc)}
    inferred = not period.get("verified", False)
    return {
        **base,
        "status": "ready",
        "reason": "周期依据历史数据推断，完整人口与仿真结果另行验收"
        if inferred
        else "",
        "current_period": period,
        "current_version": period["release"],
        "period_verified": not inferred,
        "retained_previous": latest_end < anchor,
    }


def query_contract(
    config: dict, period: dict, include_manual: bool = False
) -> list[dict]:
    validate_period(period)
    contract = config["contract"]
    if (
        not contract.get("verified")
        or not contract.get("reference")
        or not contract.get("time_field")
    ):
        raise ValueError("查询口径未核实")
    filters = json.loads(json.dumps(BASE_FILTERS))
    if include_manual:
        next(f for f in filters if f["attr_id"] == "ra_type")["val"] = [2, 3]
    start = datetime.fromisoformat(period["case_start"])
    end = datetime.fromisoformat(period["case_end_exclusive"])
    return [
        {"attr_id": "version", "val": [period["release"]], "operator": "like"},
        *filters,
        {
            "attr_id": contract["time_field"],
            "operator": "range",
            "val": {
                "min": int(start.timestamp() * 1000),
                "max": int(end.timestamp() * 1000) - 1,
            },
        },
    ]


def real_labels(raw: dict) -> list[str]:
    """Only platform labels; source_labels are query provenance, not actual tags."""
    value = raw.get("labels", raw.get("scenario_labels", []))
    if isinstance(value, str):
        try:
            value = (
                json.loads(value)
                if value.lstrip().startswith("[")
                else value.split(",")
            )
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return sorted(
        {str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip()}
    )
