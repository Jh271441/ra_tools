"""Single source of truth for deterministic content hashing and population identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def population_identity(payload: dict[str, Any]) -> str:
    period = payload["period"]
    issues = [
        {
            **{
                k: row.get(k)
                for k in ("issue_id", "ra_type", "ra_merge_result", "issue_time", "version")
            },
            **(
                {"evaluation_exclusion": row["evaluation_exclusion"]}
                if row.get("evaluation_exclusion")
                else {}
            ),
        }
        for row in payload["issues"]
    ]
    scenarios = [
        {
            k: row.get(k)
            for k in (
                "scenario_id",
                "issue_id",
                "scenario_revision",
                "start_timestamp",
                "end_timestamp",
            )
        }
        for row in payload["scenarios"]
    ]
    return digest(
        {
            "period": {
                k: period.get(k)
                for k in ("release", "case_start", "case_end_exclusive", "binary_id")
            },
            "issues": sorted(issues, key=lambda row: str(row["issue_id"])),
            "scenarios": sorted(scenarios, key=lambda row: str(row["scenario_id"])),
        }
    )
