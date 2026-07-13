#!/usr/bin/env python3
"""Compatibility entrypoint for check_sim.repro.legacy.download_road_bag."""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parent.parent / "check_sim/repro/legacy/download_road_bag.py"),
    run_name="__main__",
)
