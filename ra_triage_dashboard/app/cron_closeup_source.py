"""Bounded, read-only closeup receipts for the same daily media cohort."""
import json
from pathlib import Path
import time
import os
import sqlite3
from contextlib import closing

from .closeup_video import CloseupVideoIndex, RECIPE_ID, ISSUE_RE
from .cron_closeup_fallback import CloseupFallback
from .cron_closeup_retries import CloseupRetries


def task_root(ra_root):
    return Path(ra_root).resolve().parent / "ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029"


class CloseupCohort:
    """One queue snapshot per request; no video hashing, scheduler or source I/O.

    Jobs are only identity/queue evidence. Verified delivery always needs the
    same root-confined publication receipt used by the video player.
    """
    def __init__(self, ra_root, media_root=None):
        self.root = task_root(ra_root)
        if media_root is None:
            from .settings import Settings
            settings = Settings.from_env()
            media_root = Path(os.getenv("DASHBOARD_MEDIA_LAYOUT_ROOT") or settings.data_dir / "media_layouts")
        self.index = CloseupVideoIndex(Path(media_root) / "bev_closeup")
        self.fallback = CloseupFallback(self.root)
        self.retries = CloseupRetries(self.root)
        self.jobs = {}
        self.available = False
        deadline = time.monotonic() + .75
        try:
            queue = (self.root / "queue.sqlite3").resolve()
            queue.relative_to(self.root.resolve())
            with closing(sqlite3.connect(queue.as_uri() + "?mode=ro", uri=True, timeout=.1)) as db:
                db.execute("PRAGMA query_only=ON")
                db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                size = 0
                rows = db.execute("SELECT issue_id,substr(row_json,1,32769),state FROM jobs LIMIT 20001")
                for n, (iid, raw, state) in enumerate(rows):
                    size += len(raw)
                    if n >= 20000 or size > 8_000_000 or time.monotonic() > deadline:
                        raise ValueError("oversized_closeup_queue")
                    if len(raw) > 32768:
                        raise ValueError("oversized_closeup_member")
                    row = json.loads(raw)
                    if not isinstance(row, dict) or row.get("issue_id") != iid or iid in self.jobs:
                        raise ValueError("invalid_closeup_member")
                    self.jobs[iid] = (row, state)
            self.available = True
        except (sqlite3.Error, OSError, ValueError, TypeError):
            self.jobs = {}

    def project(self, targets, paired):
        """targets carry authoritative identity and scope, never just an ID."""
        verified, pending, attention, unknown, local_verified = set(), set(), set(), set(), set()
        for iid, expected in targets.items():
            if not isinstance(iid, str) or not ISSUE_RE.fullmatch(iid):
                raise ValueError("invalid_cohort_issue")
            job, state = self.jobs.get(iid, ({}, None))
            trip = expected.get("trip_id")
            anchor = expected.get("capture_timestamp_ms") or expected.get("ra_start_timestamp")
            scope = expected.get("scope")
            # A missing authoritative identity cannot borrow one from a job.
            if not isinstance(trip, str) or not trip or type(anchor) is not int or anchor <= 0 or not scope:
                unknown.add(iid)
                continue
            receipt = self.index.receipt(iid, scope)
            if receipt and receipt.get("trip_id") == trip and receipt["anchor_ms"] == anchor:
                verified.add(iid)
                if receipt.get("producer") == "ares_animation_local":
                    local_verified.add(iid)
            elif job.get("trip_id") == trip and job.get("capture_timestamp_ms") == anchor:
                if state in {"queued", "retry_wait"}:
                    pending.add(iid)
                elif state == "verified":
                    # A previously published job without an in-scope receipt
                    # needs scope/receipt reconciliation, not another render.
                    unknown.add(iid)
                else:
                    # Legacy `running` includes native failed jobs. It is not
                    # proof of a currently running renderer.
                    attention.add(iid)
            else:
                unknown.add(iid)
        receipts_available = self.index.root.is_dir()
        return dict(selected=len(targets), verified=len(verified) if receipts_available else None,
                    queued=len(pending) if self.available else None,
                    attention=len(attention) if self.available else None, unknown=len(unknown),
                    attention_ids=sorted(attention)[:100],
                    status="ready" if self.available else "unavailable",
                    receipt_status="ready" if receipts_available else "unavailable",
                    recipe_id=RECIPE_ID,
                    retry=self.retries.project(targets),
                    fallback=self.fallback.project(targets, verified, local_verified, receipts_available),
                    triple_verified=len(verified & set(paired)) if receipts_available else None)


def closeup_status(ra_root):
    root = task_root(ra_root)
    path = root / "progress.json"
    if not path.is_file():
        return None
    if path.stat().st_size > 100000:
        raise ValueError("oversized_closeup_status")
    row = json.loads(path.read_text())
    if not isinstance(row, dict):
        raise ValueError("invalid_closeup_status")
    counts = lambda values: {k: n for k, n in (values.items() if isinstance(values, dict) else []) if isinstance(k, str) and type(n) is int and n >= 0}
    states = {"queued", "collecting", "waiting", "idle", "blocked_auth", "pilot_failed_requires_review", "pilot_visual_review_required", "resource_wait", "stopped", "interrupted_claim_requires_review", "orion_results_require_review", "orion_running", "orion_idle", "scheduled", "download_resource_wait", "orion_observation_unavailable"}
    at = row.get("checked_at")
    versions = row.get("versions") if isinstance(row.get("versions"), dict) else {}
    members = row.get("source_members") if isinstance(row.get("source_members"), dict) else {}
    return dict(state=row.get("state") if row.get("state") in states else "unknown",
                next_action_at=row.get('next_action_at') if type(row.get('next_action_at')) in (int, float) else None,
                updated_at=at, stale=type(at) not in (int, float) or not 0 <= time.time() - at < 180,
                states=counts(row.get("states", {})), total=counts(row).get("total"), verified=counts(row).get("verified"),
                versions={k: counts(v) for k, v in versions.items() if isinstance(k, str) and k.isdigit()},
                source_members={k: counts(v) for k, v in members.items() if isinstance(k, str) and k.isdigit()})
