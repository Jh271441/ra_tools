#!/usr/bin/env python3
"""Project a label-free role observer to evidence-only fields.

The observer's normal-role and summary fields can act as an implicit prior.
This adapter keeps only directly auditable role/corridor/cross-frame facts and
uncertainty notes.  It deliberately drops GT, raw responses, metadata and all
observer conclusions outside that allowlist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


KEEP = (
    "maneuver_observations",
    "actor_role_observations",
    "cross_frame_relations",
    "observation_conflicts",
    "visibility_limitations",
    "semantic_limitations",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--include-abnormal-anchor",
        action="store_true",
        help="retain the observer's visual abnormal-role observation",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.output}")
    payload = json.loads(args.source.read_text(encoding="utf-8"))
    source_rows = payload.get("results")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("source must be a non-empty observer artifact with results")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for row in source_rows:
        if "issue_id" not in row:
            raise ValueError("observer row is missing issue_id")
        observer = row.get("trigger_expert") or {}
        projected = {
            key: observer[key]
            for key in KEEP
            if key in observer and observer[key] not in (None, "", [], {})
        }
        if args.include_abnormal_anchor and observer.get("abnormal_role_anchors"):
            projected["abnormal_role_anchors"] = observer["abnormal_role_anchors"]
        results.append(
            {
                "issue_id": str(row.get("issue_id")),
                "trigger_expert": projected,
            }
        )
    args.output.write_text(
        json.dumps(
            {
                "architecture": "label_free_role_observer_evidence_projection",
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
