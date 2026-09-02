from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_launch_full_orion import (
    INDEPENDENT_REPLAY_FLAG,
    STATE_RECOVERY_LEVEL4_FLAG,
    _enable_controlled_ra_replay,
)


def test_enable_controlled_ra_replay_is_idempotent_and_replaces_level():
  class Task:
    arguments = {
        "--sim-exec-args": (
            "--sim_aligned_mode --sim_state_recovery_level=3 "
            f"{INDEPENDENT_REPLAY_FLAG}")
    }

  task = Task()
  _enable_controlled_ra_replay(task)
  _enable_controlled_ra_replay(task)

  tokens = task.arguments["--sim-exec-args"].split()
  assert tokens.count(STATE_RECOVERY_LEVEL4_FLAG) == 1
  assert tokens.count(INDEPENDENT_REPLAY_FLAG) == 1
  assert "--sim_state_recovery_level=3" not in tokens
