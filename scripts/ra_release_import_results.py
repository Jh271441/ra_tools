#!/usr/bin/env python3
"""Validate and import local, audited exports of repeated release executions."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ra_sim_repro_dashboard/backend"))
from app.services.result_integration import integrate, import_executions
from scripts.ra_release_orion_driver import validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--exports", type=Path, nargs="+", required=True)
    parser.add_argument("--primary-job", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write verified imports to the configured dashboard database",
    )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    exports = [json.loads(path.read_text()) for path in args.exports]
    result = integrate(plan, exports, args.primary_job)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if args.apply:
        from app.database import SessionLocal
        from app.models import ReleaseIssueSnapshot
        from app.services.release_workflow import population_identity
        from sqlalchemy import select

        with SessionLocal() as db:
            snapshot = db.scalars(
                select(ReleaseIssueSnapshot)
                .where(ReleaseIssueSnapshot.release == plan["release"])
                .order_by(ReleaseIssueSnapshot.id.desc())
                .limit(1)
            ).first()
            if (
                not snapshot
                or population_identity(snapshot.payload) != plan["population_hash"]
            ):
                raise ValueError(
                    "Current source snapshot differs from the audited evaluation plan"
                )
            result = import_executions(db, plan, exports, args.primary_job)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "release",
                    "primary_job_id",
                    "job_ids",
                    "scenario_count",
                    "valid_scenario_count",
                    "missing_scenario_count",
                    "coverage",
                    "quality_gate_passed",
                    "comparison",
                    "subset_summary",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
