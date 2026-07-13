#!/usr/bin/env python3
"""Compatibility entrypoint for check_sim.scenario_repro."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from check_sim.repro.scenario_repro import main


if __name__ == "__main__":
    main()
