"""Pure release cycle rules, query contract, and execution artifact quality checks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.hashing import digest

TZ = ZoneInfo("Asia/Shanghai")
RELEASE = re.compile(r"^gen4-release-\d{8}$")
TRIGGER = "dpe_assist_channel_triggered__group1"

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


def checks(row: dict[str, Any]) -> list[str]:
    errors = []
    if row.get("task_status") != 3 or not str(row.get("task_outcome", "")).startswith("Done"):
        errors.append("task_failed")
    if row.get("simulator_cache_hit") is not False:
        errors.append("cache_unverified")
    for key in ("inference_log_count", "dpe_output_count", "output_bag_count"):
        if not isinstance(row.get(key), (int, float)) or row[key] <= 0:
            errors.append(key)
    for key in ("failed_evaluation_count", "unexpected_warning_count"):
        if row.get(key) != 0:
            errors.append(key)
    value = row.get(TRIGGER)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < -1
    ):
        errors.append("dpe_missing")
    return errors


def reference_thursday(day: date | None = None) -> date:
    day = day or datetime.now(TZ).date()
    return day - timedelta(days=day.weekday() + 4)


def validate_period(period: dict[str, Any], require_verified: bool = False) -> dict[str, Any]:
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
    if period.get("completion_rule") == "issue_last_time_24h":
        checked = datetime.fromisoformat(period["observed_at"])
        last = datetime.fromisoformat(period["last_issue_at"])
        if (
            any(t.tzinfo is None for t in (checked, last))
            or (checked - last).total_seconds() < 86400
        ):
            raise ValueError("最近Issue距今未满24小时")
        if not start <= last < end <= checked:
            raise ValueError("最近Issue时间与收集范围不一致")
    elif period.get("completion_rule") == "issue_inactivity_24h":
        quiet = datetime.fromisoformat(period["quiet_since"])
        checked = datetime.fromisoformat(period["observed_at"])
        last = datetime.fromisoformat(period["last_issue_at"])
        if (
            any(t.tzinfo is None for t in (quiet, checked, last))
            or (checked - max(quiet, last)).total_seconds() < 86400
        ):
            raise ValueError("连续24小时无新增Issue的观察证据不足")
        if not start <= last < end <= checked:
            raise ValueError("静默观察证据与人口边界不一致")
    elif cycle_end.weekday() != 3:
        raise ValueError("周期结束日必须为周四")
    if not start.astimezone(TZ).date() <= cycle_end <= end.astimezone(TZ).date():
        raise ValueError("结束日与 case 时间范围不一致")
    return period


def resolve_current(config: dict[str, Any], day: date | None = None) -> dict[str, Any]:
    today = day or datetime.now(TZ).date()
    anchor = reference_thursday(today).isoformat()
    base = {
        "reference_thursday": anchor,
        "current_period": None,
        "current_version": None,
        "period_verified": False,
        "retained_previous": False,
        "switch_weekday": "Monday",
    }

    def observable(p):
        if p.get("completion_rule") != "issue_last_time_24h" or p.get("verified") is not True:
            return False
        try:
            checked = datetime.fromisoformat(p["observed_at"])
            cutoff = (
                datetime.combine(today + timedelta(days=1), datetime.min.time(), TZ)
                if day
                else datetime.now(TZ)
            )
            return (
                checked.tzinfo is not None
                and checked <= cutoff
                and date.fromisoformat(p["cycle_end"]) <= today
            )
        except (KeyError, ValueError, TypeError):
            return False

    eligible = [
        p
        for p in config.get("periods", [])
        if p.get("cycle_end")
        and (
            (p.get("completion_rule") != "issue_last_time_24h" and p["cycle_end"] <= anchor)
            or observable(p)
        )
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
        "reason": "周期依据历史数据推断，完整人口与仿真结果另行验收" if inferred else "",
        "switch_weekday": "on_collection_complete"
        if period.get("completion_rule") == "issue_last_time_24h"
        else "Monday",
        "current_period": period,
        "current_version": period["release"],
        "period_verified": not inferred,
        "retained_previous": latest_end < anchor,
    }


def query_contract(
    config: dict[str, Any], period: dict[str, Any], include_manual: bool = False
) -> list[dict[str, Any]]:
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


def period_key(config: dict[str, Any], period: dict[str, Any]) -> str:
    return digest(
        {
            "period": period,
            "contract": config["contract"],
            "query": query_contract(config, period, True),
        }
    )
