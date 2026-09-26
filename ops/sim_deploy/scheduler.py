#!/usr/bin/env python3
"""Persistent weekly scheduler, Asia/Shanghai Monday 09:00, three bounded attempts.
State survives restarts. Retries are six hours apart; successful weeks are not rerun.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo


def due(now, state):
    monday = now.date() - dt.timedelta(days=now.weekday())
    scheduled = dt.datetime.combine(monday, dt.time(9), ZoneInfo("Asia/Shanghai"))
    if now < scheduled:
        return False
    week = monday.isoformat()
    if state.get("week") != week:
        return True
    if state.get("status") == "complete" or state.get("attempts", 0) >= 3:
        return False
    return now.timestamp() - state.get("attempted_at", 0) >= 6 * 3600


def main(root):
    root = Path(root)
    state_path = root / "weekly-schedule-state.json"
    os.umask(0o077)
    while True:
        now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if due(now, state):
            week = (now.date() - dt.timedelta(days=now.weekday())).isoformat()
            count = state.get("attempts", 0) if state.get("week") == week else 0
            state = {
                "week": week,
                "attempts": count + 1,
                "attempted_at": now.timestamp(),
                "status": "running",
            }
            temp = state_path.with_suffix(".tmp")
            temp.write_text(json.dumps(state))
            temp.replace(state_path)
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(root / "run.py"),
                        sys.executable,
                        str(root / "weekly.py"),
                        "--config",
                        str(root / "weekly.json"),
                        "--output",
                        str(root / "weekly"),
                    ],
                    timeout=3600,
                    check=True,
                )
                state["status"] = json.loads((root / "weekly/status.json").read_text())[
                    "status"
                ]
            except Exception as exc:
                state["status"] = "check_failed"
                print(type(exc).__name__, flush=True)
            temp.write_text(json.dumps(state))
            temp.replace(state_path)
        time.sleep(60)


if __name__ == "__main__":
    main(sys.argv[1])
