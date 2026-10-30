"""Read-only status for version incremental processing and its independent media queue."""
import json, time
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

STATE = Path(
    "/volume/home/workspace/ra_auto_triage_deploy/state/version_incremental_v3"
)


def document(path):
    if not path.is_file():
        return {}
    if path.stat().st_size > 2_000_000:
        raise ValueError("Oversized version status")
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError("Invalid version status")
    return result


def version_queue_states(state):
    """Read one bounded queue snapshot; never create a ledger or use import lag as queue state."""
    deadline = time.monotonic() + 0.75
    try:
        with closing(sqlite3.connect((state / "ledger.sqlite3").resolve().as_uri() + "?mode=ro",
                                     uri=True, timeout=0.1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = conn.execute("SELECT family,state,COUNT(*) FROM items GROUP BY family,state LIMIT 5001").fetchall()
            if len(rows) > 5000:
                return None
        result = defaultdict(dict)
        for family, status, count in rows:
            if re.fullmatch(r"\d{8}", str(family)):
                result[str(family)][status] = count
        return dict(result)
    except (sqlite3.Error, OSError):
        return None


def media_counts(targets, reused, published, failed, queued):
    verified = (reused | published) & targets
    return {"selected": len(targets), "verified": len(verified),
            "reused": len(reused & targets), "failure_count": len((failed - verified) & targets),
            "queued": len((queued - verified) & targets)}


def version_status(root):
    state = (
        Path(root).resolve().parent
        / "ra_auto_triage_deploy/state/version_incremental_v3"
    )
    control = document(state / "control.json")
    if control.get("enabled") is not True:
        return None
    heartbeat = document(state / "heartbeat.json")
    states = {
        k: v
        for k, v in heartbeat.get("states", {}).items()
        if isinstance(k, str) and type(v) is int and v >= 0
    }
    from .runtime import database

    datasets = database.list_version_datasets()
    targets_by_family = defaultdict(set)
    with database.connect() as conn:
        for row in conn.execute(
            "SELECT d.release_family,i.issue_id FROM version_dataset_items i "
            "JOIN version_datasets d ON d.id=i.dataset_id WHERE i.is_target=1"
        ).fetchall():
            targets_by_family[str(row["release_family"])].add(row["issue_id"])
    targets = set().union(*targets_by_family.values())
    reused = set()
    published = set()
    failed = set()
    queued = set()
    for path in list((state / "outbox").glob("*.receipt.json"))[-1000:]:
        receipt = document(path)
        reused.update(receipt.get("media", {}).get("reused_ids", []))
        queued.update(receipt.get("media", {}).get("queued_ids", []))
    for folder in list(
        (Path(root) / "reports/manual_sidecar_20261019/versions").glob("*/*")
    )[-1000:]:
        for path in (folder / "media-publication").glob("cn*.json"):
            receipt = document(path)
            if receipt.get("state") == "verified":
                published.add(receipt.get("issue_id"))
        for row in document(folder / "final-failures.json").get("failures", []):
            failed.add(row.get("issue_id"))
    queue_states = version_queue_states(state)
    families = sorted({str(v) for v in heartbeat.get("families", [])}
                      | {str(d["release_family"]) for d in datasets}
                      | set(queue_states or {}), reverse=True)
    families = [f for f in families if re.fullmatch(r"\d{8}", f)]
    from .cron_incremental_history import incremental_history
    return {
        "enabled": True,
        "states": states,
        "families": families,
        "versions": [{"family": family,
                      "states": (queue_states or {}).get(family),
                      "states_status": "ready" if queue_states is not None and family in queue_states else "unavailable",
                      "media": media_counts(targets_by_family[family], reused, published, failed, queued)}
                     for family in families],
        "updated_at": heartbeat.get("checked_at"),
        "stale": time.time() - heartbeat.get("checked_at", 0) > 1200,
        "sampling_policy": "version_probability_v3",
        "discovery_schedule": {"hours": [h for h in heartbeat.get("discovery_schedule", {}).get("hours", []) if type(h) is int and 0 <= h <= 23],
                               "timezone": "Asia/Shanghai", "next_at": heartbeat.get("discovery_schedule", {}).get("next_at")},
        "increments": incremental_history(state, control, datasets, database),
        "datasets": datasets,
        "media": media_counts(targets, reused, published, failed, queued),
    }
