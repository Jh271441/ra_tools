#!/usr/bin/env python3
"""Plan or apply the label-only legacy Review import."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.legacy_label_copy import apply_legacy_label_copy, plan_legacy_label_copy
from app.runtime import baseline_registry, database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "apply"), nargs="?", default="plan")
    parser.add_argument("--datasets", default="0206,0508,0522,0626,0821")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default="migration")
    args = parser.parse_args()
    dataset_ids = list(dict.fromkeys(value.strip() for value in args.datasets.split(",") if value.strip()))
    unknown = [value for value in dataset_ids if baseline_registry.by_id(value) is None]
    if unknown:
        parser.error("unknown datasets: " + ", ".join(unknown))
    scopes = [baseline_registry.by_id(value).scope for value in dataset_ids]
    database.init()
    if args.mode == "apply":
        if not args.apply:
            parser.error("apply mode requires --apply")
        result = apply_legacy_label_copy(database, scopes=scopes, imported_by=args.actor)
    else:
        result = plan_legacy_label_copy(database, scopes=scopes)
        result.pop("plans", None)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
