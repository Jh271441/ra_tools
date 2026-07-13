#!/usr/bin/env python3
"""Query Voyager RA issues and export them to CSV/XLSX."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ra_api.issue_api import TrailInterface


DEFAULT_QUERY_ATTRS: list[dict[str, Any]] = [
    {
        "attr_id": "version",
        "operator": "like",
        "val": [
            "gen4-release20260522",
            "gen4-release-20260522",
        ],
    },
    {
        "attr_id": "trip_category",
        "operator": "in",
        "val": [
            0,
        ],
    },
    {
        "attr_id": "region",
        "operator": "not_in",
        "val": [
            "suzhou_close_test",
        ],
    },
    {
        "attr_id": "ra_trigger",
        "operator": "in",
        "val": [
            "StuckModel",
            "CorePlanner",
            "UNDEFINED_REASON",
            "FP_TRAFFIC_JAM",
            "FP_RED_LIGHT",
            "FP_STOP_FENCE",
            "FP_STARTUP",
            "FP_MAXSPD",
            "FP_CROSSWALK",
            "FN_REJECT_INQUEUE",
            "FN_JUNCTION",
            "FN_SOLID_LANEMARK",
            "FN_LOW_PRED",
            "FP_PULL_OVER",
            "FP_YIELD_DYNAMIC_OBJECT",
            "FP_EOL_WITH_RED_TL",
            "FP_YIELD_ON_RIGHT_TURN",
            "FP_QUEUING",
            "FN_RA_CZ",
            "FP_YIELD_ON_TURN",
            "FN_NEAR_HARD_BOUNDARY",
            "FN_SELECTION",
            "FP_OCCLUSION",
            "FN_BREAKDOWN_CAR",
            "FN_TEMP_PARKED",
            "REQUEST_FROM_ROUTING",
            "FN_PERCEPTION_FP",
            "FN_EOL",
            "FP_REMOTE_SPEED_LIMIT",
            "FN_CZ",
            "REQUEST_FROM_CREEP",
            "FN_NO_BLOCK",
            "FN_LANE_CHANGE_STUCK",
            "ManualTrigger",
            "CloudTrigger",
            "-",
            "FN_FORCING_RECALL",
            "FN_VEHICLE_HAZARD_SIGNAL",
            "DNNModel",
            "GBMModel",
            "AbnormalTrafficLight",
            "TidalFlowLane",
            "DNN_2025Q1",
            "DNN_2025Q2",
            "SCEN_DNN_2025Q3",
            "kEndOfLaneSequence",
            "FN_FINAL_FORCING_RECALL",
            "ASSIST_STUCK_MODEL",
            "SPECIAL_STUCK_SCENE",
        ],
    },
    {
        "attr_id": "ra_type",
        "operator": "in",
        "val": [
            3,
            2,
        ],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-id", type=int, default=2410, help="Voyager issue pool view id.")
    parser.add_argument("--size", type=int, default=500, help="Page size for issue query.")
    parser.add_argument(
        "--query-json",
        type=Path,
        help="Optional JSON file containing query_attrs. Defaults to the 20260522 RA query.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("exports") / f"ra_issues_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="CSV output path.",
    )
    parser.add_argument("--xlsx", type=Path, help="Optional XLSX output path.")
    return parser.parse_args()


def load_query_attrs(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return DEFAULT_QUERY_ATTRS
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("query JSON must be a list of query_attrs")
    return data


def normalize_for_export(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    for column in normalized.columns:
        if normalized[column].map(lambda value: isinstance(value, (dict, list))).any():
            normalized[column] = normalized[column].map(
                lambda value: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            )
    return normalized


def bypass_proxy_for_intranet() -> None:
    hosts = ["voyager.intra.xiaojukeji.com", ".intra.xiaojukeji.com"]
    for key in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(key, "")
        parts = [part.strip() for part in existing.split(",") if part.strip()]
        for host in hosts:
            if host not in parts:
                parts.append(host)
        os.environ[key] = ",".join(parts)


def main() -> int:
    args = parse_args()
    bypass_proxy_for_intranet()
    query_attrs = load_query_attrs(args.query_json)

    print(f"querying issues: view_id={args.view_id}, page_size={args.size}")
    df = TrailInterface().query_issue_poll(view_id=args.view_id, query_attrs=query_attrs, size=args.size)
    df = normalize_for_export(df)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"csv saved: {args.out} rows={len(df)} cols={len(df.columns)}")

    if args.xlsx:
        args.xlsx.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(args.xlsx, index=False)
        print(f"xlsx saved: {args.xlsx}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
