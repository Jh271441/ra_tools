"""Read Scenario source identities without pandas numeric-string coercion."""

from __future__ import annotations
import json
from pathlib import Path
import pandas as pd


def read_source(path: Path) -> pd.DataFrame:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError("Issue source must be an array")
    for row in rows:
        if not isinstance(row.get("trip_id"), str) or not row["trip_id"].strip():
            raise ValueError("trip_id must retain its original string identity")
    return pd.DataFrame(rows)


def read_plan(path: Path, original: pd.DataFrame) -> pd.DataFrame:
    plan = pd.read_csv(
        path, low_memory=False, dtype={"trip_id": str, "issue_id": str}
    ).fillna("")
    by_issue = original.set_index("issue_id")["trip_id"].to_dict()
    if plan["issue_id"].duplicated().any():
        raise ValueError("Duplicate Issue in creation plan")
    for row in plan.itertuples():
        if row.trip_id != by_issue.get(row.issue_id):
            raise ValueError("Creation plan changed a source trip identity")
    if plan["validation_error"].astype(bool).any():
        raise ValueError("Scenario conversion has unresolved errors")
    return plan
