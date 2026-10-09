#!/usr/bin/env python3
"""S6 legacy cutover inventory/classification/policy rehearsal.

Dry-run is the default. ``--apply`` writes append-only classifications only;
``--policy`` uses an epoch-checked explicit policy transition.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.db_parts.legacy_cutover import S6_POLICY_VERSION  # noqa: E402
from app.runtime import baseline_registry, database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inventory", "classify", "policy", "shadow"), default="inventory")
    parser.add_argument("--datasets", default="0206,0508,0522,0626,0821")
    parser.add_argument("--policy-version", default=S6_POLICY_VERSION)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--policy", choices=("legacy", "shadow", "canonical"), default="shadow")
    parser.add_argument("--expected-epoch", type=int)
    parser.add_argument("--actor", default="s6-migration")
    args = parser.parse_args()
    ids = list(dict.fromkeys(item.strip() for item in args.datasets.split(",") if item.strip()))
    unknown = [item for item in ids if baseline_registry.by_id(item) is None]
    if unknown:
        parser.error("unknown datasets: " + ", ".join(unknown))
    scopes = [baseline_registry.by_id(item).scope for item in ids]
    result: dict[str, object] = {
        "mode": args.mode,
        "dataset_ids": ids,
        "baseline_scopes": scopes,
        "policy_version": args.policy_version,
        "inventory": database.legacy_scope_inventory(scopes),
    }
    if args.mode == "classify":
        result["classification"] = database.classify_legacy_annotations(
            scopes=scopes, policy_version=args.policy_version,
            actor=args.actor, apply=args.apply,
        )
    elif args.mode == "policy":
        if not args.apply or len(scopes) != 1 or args.expected_epoch is None:
            parser.error("policy requires --apply, one dataset and --expected-epoch")
        inventory = result["inventory"]
        result["policy"] = database.set_legacy_read_policy(
            baseline_scope=scopes[0], policy=args.policy,
            policy_version=args.policy_version,
            inventory_sha256=inventory["inventory_sha256"],
            updated_by=args.actor, expected_epoch=args.expected_epoch,
        )
    elif args.mode == "shadow":
        result["shadow"] = database.legacy_shadow_compare(scopes=scopes)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
