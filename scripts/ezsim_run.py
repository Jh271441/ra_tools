#!/usr/bin/env python3
"""Compatibility module for check_sim.ezsim."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from check_sim.ezsim import (
    EzSimClient,
    _DEFAULT_EXTRA_ARGS,
    _DEFAULT_MODULES,
    _get_trail_trip_segment,
    _resolve_build_dir_hash,
    main,
)

__all__ = [
    "EzSimClient",
    "_DEFAULT_EXTRA_ARGS",
    "_DEFAULT_MODULES",
    "_get_trail_trip_segment",
    "_resolve_build_dir_hash",
    "main",
]


if __name__ == "__main__":
    main()
