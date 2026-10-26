#!/usr/bin/env python3
"""Supervised daily target backups; fail visibly instead of hiding backup errors."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import time

ROOT = Path("/local-data/services/manual")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--after-load-report", type=Path)
    args = p.parse_args()
    status = ROOT / "state/backup-scheduler-status.json"

    def save(**values):
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp = status.with_suffix(".tmp")
        temp.write_text(json.dumps(values, indent=2))
        temp.replace(status)

    with (ROOT / "state/.backup-scheduler.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = json.loads(status.read_text()) if status.exists() else {}
        if args.after_load_report:
            save(state="waiting_for_load_test", interval_seconds=86400)
            deadline = time.monotonic() + 3600
            while not args.after_load_report.is_file():
                if time.monotonic() >= deadline:
                    save(
                        state="failed",
                        error="Load test report did not appear within one hour",
                    )
                    raise RuntimeError("Timed out waiting for load test completion")
                time.sleep(15)
        if previous.get("last_success"):
            last = datetime.fromisoformat(previous["last_success"])
            remaining = max(
                0,
                min(86400, 86400 - (datetime.now(timezone.utc) - last).total_seconds()),
            )
            save(
                state="idle",
                last_success=previous["last_success"],
                interval_seconds=86400,
            )
            time.sleep(remaining)
        while True:
            try:
                save(state="waiting_for_database", interval_seconds=86400)
                deadline = time.monotonic() + 120
                while True:
                    probe = subprocess.run(
                        [
                            "/usr/lib/postgresql/14/bin/pg_isready",
                            "-h",
                            str(ROOT / "run/postgresql"),
                            "-p",
                            "55432",
                        ],
                        stdout=subprocess.DEVNULL,
                        timeout=5,
                    )
                    if probe.returncode == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Database not ready within two minutes")
                    time.sleep(2)
                save(state="running_backup", interval_seconds=86400)
                subprocess.run(
                    [
                        str(ROOT / "venv/bin/python3"),
                        str(ROOT / "config/migration_backup.py"),
                        "--config",
                        str(ROOT / "config/shadow-env.json"),
                        "--expected-database",
                        "manual_shadow_20261018",
                    ],
                    check=True,
                    timeout=1800,
                )
                save(
                    state="idle",
                    last_success=datetime.now(timezone.utc).isoformat(),
                    interval_seconds=86400,
                )
            except Exception as exc:
                save(state="failed", error=str(exc), interval_seconds=86400)
                raise
            time.sleep(86400)


if __name__ == "__main__":
    main()
