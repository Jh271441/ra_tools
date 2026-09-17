#!/usr/bin/env python3
"""Plan, backfill, reconcile or activate the Case-labeling migration."""

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
    activate_legacy_labeling,
    labeling_inventory_fingerprint,
    labeling_inventory_fingerprints,
    legacy_labeling_inventory,
    migrate_legacy_labeling,
    reconcile_legacy_labeling,
)
from app.runtime import baseline_registry, database
from app.support.catalogs import _review_tag_catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("plan", "backfill", "reconcile", "activate"),
        default="plan",
    )
    parser.add_argument("--datasets", default=",".join(DEFAULT_LABEL_DATASETS))
    parser.add_argument("--policy-version", default=DEFAULT_POLICY_VERSION)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default="migration")
    parser.add_argument("--expected-epoch", type=int)
    args = parser.parse_args()
    dataset_ids = list(dict.fromkeys(
        value.strip() for value in args.datasets.split(",") if value.strip()
    ))
    if not dataset_ids:
        parser.error("at least one dataset is required")
    unknown = [value for value in dataset_ids if baseline_registry.by_id(value) is None]
    if unknown:
        parser.error("unknown datasets: " + ", ".join(unknown))
    scopes = [baseline_registry.by_id(value).scope for value in dataset_ids]
    inventory = legacy_labeling_inventory(database, scopes=scopes)
    output: dict[str, object] = {
        "mode": args.mode,
        "dataset_ids": dataset_ids,
        "baseline_scopes": scopes,
        "inventory": inventory,
        "source_inventory_sha256": labeling_inventory_fingerprint(
            database, scopes=scopes
        ),
        "source_inventory_sha256_by_scope": labeling_inventory_fingerprints(
            database, scopes=scopes
        ),
    }
    if args.mode == "backfill":
        if not args.apply:
            parser.error("backfill requires --apply")
        database.init()
        output["migration"] = migrate_legacy_labeling(
            database,
            scopes=scopes,
            tag_catalog=_review_tag_catalog(),
            policy_version=args.policy_version,
            migrated_by=args.actor,
        )
    elif args.mode == "reconcile":
        output["reconciliation"] = reconcile_legacy_labeling(
            database,
            scopes=scopes,
            policy_version=args.policy_version,
            tag_catalog=_review_tag_catalog(),
        )
    elif args.mode == "activate":
        if not args.apply:
            parser.error("activate requires --apply")
        if len(scopes) != 1:
            parser.error("activate exactly one dataset at a time")
        if args.expected_epoch is None:
            parser.error("activate requires --expected-epoch")
        output["activation"] = activate_legacy_labeling(
            database,
            scopes=scopes,
            policy_version=args.policy_version,
            tag_catalog=_review_tag_catalog(),
            expected_epoch=args.expected_epoch,
            updated_by=args.actor,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if output["activation"]["passed"] else 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    if args.mode == "reconcile" and not output["reconciliation"]["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
