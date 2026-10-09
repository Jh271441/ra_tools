#!/usr/bin/env python3
"""Reconcile and guarded-activate one label-only legacy import scope."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.legacy_label_copy import (
    activate_legacy_label_copy_scope,
    reconcile_legacy_label_copy_activation,
)
from app.runtime import baseline_registry, database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("reconcile", "activate"), nargs="?", default="reconcile")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default="legacy-label-copy-activation")
    args = parser.parse_args()
    baseline = baseline_registry.by_id(args.dataset.strip())
    if baseline is None:
        parser.error("unknown dataset")
    database.init()
    if args.mode == "activate":
        if not args.apply:
            parser.error("activate requires --apply")
        result = activate_legacy_label_copy_scope(
            database, baseline_scope=baseline.scope, actor=args.actor
        )
    else:
        result = reconcile_legacy_label_copy_activation(
            database, baseline_scope=baseline.scope
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
