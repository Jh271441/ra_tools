"""Bounded, read-only increments from discovery events and immutable import receipts."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo


def window_start(at):
    base = datetime.fromtimestamp(at, ZoneInfo("Asia/Shanghai")).replace(minute=0, second=0, microsecond=0)
    slots = [base.replace(hour=h) for h in (7, 19)]
    slots.append(base.replace(hour=19) - timedelta(days=1))
    return max(d.timestamp() for d in slots if d.timestamp() <= at)


def incremental_history(state, control, datasets, database):
    try:
        return _history(Path(state), control, datasets, database)
    except Exception as exc:
        # History is supplementary: pool/source errors must not hide totals.
        return {"status": "unavailable", "items": [], "error_type": type(exc).__name__}


def _history(state, control, datasets, database):
    if control.get("discovery_schedule", {}).get("hours") != [7, 19]:
        return {"status": "unsupported", "items": []}
    deadline = time.monotonic() + 0.75
    with sqlite3.connect((state / "ledger.sqlite3").resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        conn.execute("BEGIN")
        history_start = control.get("discovery_history_started_at", control.get("updated_at", 0))
        scans = conn.execute("SELECT at FROM scans WHERE at>=? ORDER BY at DESC LIMIT 64", (history_start,)).fetchall()
        rounds = {}
        for scan in scans:
            rounds.setdefault(window_start(scan["at"]), {"scan_state": "success", "scan_finished_at": scan["at"]})
        path = state / "discovery-schedule.json"
        schedule = json.loads(path.read_text()) if path.is_file() else {}
        attempt = schedule.get("last_attempt_slot")
        if attempt and schedule.get("state") in ("running", "failed", "interrupted"):
            rounds.setdefault(attempt, {"scan_state": schedule["state"], "scan_finished_at": None})
        slots = sorted(rounds, reverse=True)[:14]
        if not slots:
            return {"status": "empty", "items": []}
        earliest = min(slots)
        events = conn.execute("SELECT at,family,issue_id,action,detail_json FROM events WHERE at>=? "
                              "AND action IN ('discovered','source_transition','published') ORDER BY id LIMIT 50001", (earliest,)).fetchall()
        if len(events) > 50000:
            raise ValueError("Event history exceeds bounded window")
    counts = defaultdict(lambda: {key: set() for key in ("new", "filled", "published")})
    for event in events:
        slot = window_start(event["at"])
        if slot not in slots:
            continue
        bucket = counts[(slot, event["family"])]
        if event["action"] == "discovered":
            bucket["new"].add(event["issue_id"])
        elif event["action"] == "published":
            bucket["published"].add(event["issue_id"])
        else:
            change = json.loads(event["detail_json"])
            if change.get("from") == "waiting_metadata" and change.get("to") == "ready":
                bucket["filled"].add(event["issue_id"])
    imports = defaultdict(lambda: {"added": 0, "removed": 0})
    families = {str(d["release_family"]): d["id"] for d in datasets}
    dids = list(families.values())
    if dids:
        with database.connect() as conn:
            batches = conn.execute("SELECT dataset_id,batch_key,receipt_json,created_at FROM dataset_ingestion_batches "
                                   "WHERE created_at>=? AND dataset_id IN (" + ",".join("?" for _ in dids) + ") "
                                   "ORDER BY created_at LIMIT 5001", (datetime.fromtimestamp(earliest, timezone.utc).isoformat(), *dids)).fetchall()
        if len(batches) > 5000:
            raise ValueError("Import history exceeds bounded window")
        reverse = {did: family for family, did in families.items()}
        seen = set()
        for batch in batches:
            key = (batch["dataset_id"], batch["batch_key"])
            if key in seen:
                continue
            seen.add(key)
            slot = window_start(datetime.fromisoformat(str(batch["created_at"]).replace("Z", "+00:00")).timestamp())
            if slot not in slots:
                continue
            receipt = json.loads(batch["receipt_json"])
            bucket = imports[(slot, reverse[batch["dataset_id"]])]
            for source, target in (("target_added", "added"), ("target_retired", "removed")):
                value = receipt[source]
                if type(value) is not int or value < 0:
                    raise ValueError("Invalid increment receipt")
                bucket[target] += value
    rows = []
    for slot in slots:
        for family in sorted(families, reverse=True):
            bucket = counts[(slot, family)]
            scanned = rounds[slot]["scan_state"] == "success"
            rows.append({"start_at": slot, "end_at": slot + 43200, "family": family, **rounds[slot],
                         "new": len(bucket["new"]) if scanned else None, "filled": len(bucket["filled"]) if scanned else None,
                         "published": len(bucket["published"]), "target_added": imports[(slot, family)]["added"],
                         "target_removed": imports[(slot, family)]["removed"]})
    return {"status": "ready", "items": rows, "timezone": "Asia/Shanghai", "basis": "event_and_import_completion_windows", "max_rounds": 14}
