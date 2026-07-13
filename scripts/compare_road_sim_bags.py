#!/usr/bin/env python3
"""Compatibility entrypoint for check_sim.compare_road_sim_bags."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from check_sim.bag.compare_road_sim_bags import main


if __name__ == "__main__":
    main()
