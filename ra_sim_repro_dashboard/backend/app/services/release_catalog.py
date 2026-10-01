"""Discover completed cycles from observed release transitions, never name arithmetic."""

from __future__ import annotations
from datetime import datetime, timedelta
import re
from app.services.release_cycle import TZ, BASE_FILTERS
from app.services.release_source import complete_query, trail_credentials
import os


def fetch_recent_releases(config):
    now = datetime.now(TZ)
    begin = now - timedelta(days=60)
    attrs = [
        *BASE_FILTERS,
        {"attr_id": "version", "operator": "like", "val": ["gen4-release-"]},
        {
            "attr_id": config["contract"]["time_field"],
            "operator": "range",
            "val": {
                "min": int(begin.timestamp() * 1000),
                "max": int(now.timestamp() * 1000),
            },
        },
    ]
    attrs = [{**f, "val": [2, 3]} if f["attr_id"] == "ra_type" else f for f in attrs]
    app_id, token = trail_credentials()
    base = os.getenv("TRAIL_ISSUE_BASE_URL", "http://10.88.128.83").rstrip("/")
    return complete_query(
        base + "/paladin/issue/pool/query/",
        {
            "view_id": config["contract"].get("view_id", 2410),
            "user_location": "cn",
            "query_attrs": attrs,
        },
        app_id,
        token,
        "issue_id",
    )


def infer_completed_cycles(rows, time_field="issue_time"):
    groups = {}
    for row in rows:
        match = re.search(r"gen4-release-\d{8}", str(row.get("version", "")))
        if not match:
            continue
        release = match[0]
        stamp = datetime.fromtimestamp(float(row[time_field]) / 1000, TZ)
        group = groups.setdefault(
            release,
            {
                "first": stamp,
                "last": stamp,
                "count": 0,
                "latest_road_version": row["version"],
                "road_versions": set(),
            },
        )
        group["first"] = min(group["first"], stamp)
        if stamp >= group["last"]:
            group["last"] = stamp
            group["latest_road_version"] = row["version"]
        group["count"] += 1
        group["road_versions"].add(str(row["version"]))
    ordered = sorted(groups, key=lambda key: groups[key]["first"])
    periods = []
    warnings = []
    for release, next_release in zip(ordered, ordered[1:]):
        current = groups[release]
        following = groups[next_release]
        end = following["first"].date()
        if end.weekday() != 3 or current["last"].date() > end:
            warnings.append(
                {
                    "release": release,
                    "reason": "观察到非周四切换或周期之外的旧版本尾部，保留已确认周期",
                }
            )
            continue
        if current["first"].date().weekday() != 3:
            warnings.append(
                {"release": release, "reason": "查询窗口截断或主周期起点不明"}
            )
            continue
        start = datetime.combine(current["first"].date(), datetime.min.time(), TZ)
        stop = datetime.combine(end + timedelta(days=1), datetime.min.time(), TZ)
        periods.append(
            {
                "release": release,
                "status": "completed",
                "basis": "observed",
                "verified": True,
                "cycle_end": end.isoformat(),
                "case_start": start.isoformat(),
                "case_end_exclusive": stop.isoformat(),
                "target_road_version": current["latest_road_version"],
                "road_versions": sorted(current["road_versions"]),
                "evidence": f"Trail完整分页观察：{release} {current['first'].isoformat()}–{current['last'].isoformat()}；后继{next_release}始于{following['first'].isoformat()}",
            }
        )
    return periods, warnings
