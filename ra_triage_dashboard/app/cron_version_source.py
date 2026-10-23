"""Read-only status for version incremental processing and its independent media queue."""
import json, time
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
    with database.connect() as conn:
        targets = {
            r["issue_id"]
            for r in conn.execute(
                "SELECT issue_id FROM version_dataset_items WHERE is_target=1"
            ).fetchall()
        }
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
    verified = (reused | published) & targets
    return {
        "enabled": True,
        "states": states,
        "families": [str(v) for v in heartbeat.get("families", []) if str(v).isdigit()],
        "updated_at": heartbeat.get("checked_at"),
        "stale": time.time() - heartbeat.get("checked_at", 0) > 1200,
        "sampling_policy": "version_probability_v3",
        "datasets": datasets,
        "media": {
            "selected": len(targets),
            "verified": len(verified),
            "reused": len(reused & targets),
            "failure_count": len((failed - verified) & targets),
            "queued": len((queued - verified) & targets),
        },
    }
