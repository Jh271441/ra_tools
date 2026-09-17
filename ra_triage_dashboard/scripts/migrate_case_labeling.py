#!/usr/bin/env python3
"""Plan or apply the idempotent legacy Review-to-labeling backfill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.labeling_migration import (
    DEFAULT_LABEL_DATASETS,
    DEFAULT_POLICY_VERSION,
    legacy_labeling_inventory,
    migrate_legacy_labeling,
)
from app.runtime import baseline_registry, database
from app.support.catalogs import _review_tag_catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", default=",".join(DEFAULT_LABEL_DATASETS))
    parser.add_argument("--policy-version", default=DEFAULT_POLICY_VERSION)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dataset_ids = [value.strip() for value in args.datasets.split(",") if value.strip()]
    unknown = [value for value in dataset_ids if baseline_registry.by_id(value) is None]
    if unknown:
        parser.error("unknown datasets: " + ", ".join(unknown))
    scopes = [baseline_registry.by_id(value).scope for value in dataset_ids]
    inventory = legacy_labeling_inventory(database, scopes=scopes)
    output: dict[str, object] = {
        "mode": "apply" if args.apply else "plan",
        "dataset_ids": dataset_ids,
        "baseline_scopes": scopes,
        "inventory": inventory,
    }
    if args.apply:
        database.init()
        output["migration"] = migrate_legacy_labeling(
            database,
            scopes=scopes,
            tag_catalog=_review_tag_catalog(),
            policy_version=args.policy_version,
        )
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
