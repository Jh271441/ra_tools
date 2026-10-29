"""Small read-only status of the independent closeup sidecar."""
import json
from pathlib import Path
import time


def closeup_status(ra_root):
    root = Path(ra_root).resolve().parent / "ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029"
    path = root / "progress.json"
    if not path.is_file():
        return None
    if path.stat().st_size > 100000:
        raise ValueError("oversized_closeup_status")
    row = json.loads(path.read_text())
    if not isinstance(row, dict):
        raise ValueError("invalid_closeup_status")
    counts = lambda values: {k: n for k, n in (values.items() if isinstance(values, dict) else []) if isinstance(k, str) and type(n) is int and n >= 0}
    states = {"queued", "collecting", "waiting", "idle", "blocked_auth", "pilot_failed_requires_review", "pilot_visual_review_required", "resource_wait", "stopped", "interrupted_claim_requires_review"}
    at = row.get("checked_at")
    versions = row.get("versions") if isinstance(row.get("versions"), dict) else {}
    members = row.get("source_members") if isinstance(row.get("source_members"), dict) else {}
    return dict(state=row.get("state") if row.get("state") in states else "unknown",
                updated_at=at, stale=type(at) not in (int, float) or not 0 <= time.time() - at < 180,
                states=counts(row.get("states", {})), total=counts(row).get("total"), verified=counts(row).get("verified"),
                versions={k: counts(v) for k, v in versions.items() if isinstance(k, str) and k.isdigit()},
                source_members={k: counts(v) for k, v in members.items() if isinstance(k, str) and k.isdigit()})
