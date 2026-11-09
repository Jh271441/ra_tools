"""Read-only text stages from durable work and validated index receipts.

Completion has no heartbeat expiry. Only a fresh native observation establishes
current execution; an idle/restarted controller cannot erase saved milestones.
"""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import time

from .planning_text_artifact import identity

MAX_ROWS = 20000
FRESH_SECONDS = 180
TERMINAL = {"collected", "partial_source"}
QUEUE_STATES = {
    "pending", "running", "resource_wait", "retry", "owner_wait", "orion_running",
    "complete", "source_empty", "source_failed", "execution_failed", "review", "reused",
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _key(member):
    identity(member)
    return member["issue_id"], member["trip_id"], member["anchor_ms"]


def _matches_version(member, target):
    scope = target.get("scope", "")
    if not scope.startswith("manual_sidecar_version_"):
        return True
    family = scope.removeprefix("manual_sidecar_version_")
    # Both forms exist in saved authority rows. Do not infer trips or anchors.
    return member.get("version") in {family, family[-4:]}


def _source_finished(saved):
    if saved[0] in TERMINAL:
        return True
    # A failed saved receipt might be a recoverable resource/import failure.
    # Only explicit terminal source-decode evidence closes that source phase.
    evidence = saved[2] if len(saved) > 2 else {}
    return saved[0] == "failed" and evidence.get("terminal_source_error") is True


class TextPipeline:
    def __init__(self, data_dir, saved, *, now=None):
        self.now = time.time() if now is None else now
        self.saved = saved
        self.queue = None
        self.runtime = None
        if data_dir is None:
            return
        root = Path(data_dir).resolve()
        directory = Path(data_dir) / "planning_constraints"
        try:
            path = directory / "text-queue.sqlite3"
            path.resolve().relative_to(root)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024**3:
                raise ValueError("invalid_text_queue")
            with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=.1)) as db:
                db.execute("PRAGMA query_only=ON")
                deadline = time.monotonic() + .25
                db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                rows = db.execute("SELECT capture_key,substr(member_json,1,65537),state,"
                                  "substr(detail_json,1,65537),updated_at FROM work LIMIT 20001")
                queue, total_bytes = {}, 0
                for index, (key, raw, state, detail_raw, updated) in enumerate(rows):
                    total_bytes += len(raw.encode()) + len(detail_raw.encode())
                    if index >= MAX_ROWS or total_bytes > 8 * 1024**2:
                        raise ValueError("oversized_text_queue")
                    if len(raw) > 65536 or len(detail_raw) > 65536 or state not in QUEUE_STATES or not _number(updated):
                        raise ValueError("invalid_text_queue_row")
                    member, detail = json.loads(raw), json.loads(detail_raw)
                    if key != identity(member) or not isinstance(detail, dict):
                        raise ValueError("invalid_text_queue_identity")
                    queue[_key(member)] = dict(member=member, state=state, detail=detail, updated_at=updated)
            self.queue = queue
        except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
            pass
        try:
            path = directory / "orion-runtime.json"
            path.resolve().relative_to(root)
            if path.is_symlink():
                raise ValueError("invalid_text_runtime")
            with path.open("rb") as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("oversized_text_runtime")
            value = json.loads(raw)
            if (value.get("schema_version") != 1 or value.get("execution_target") != "orion"
                    or not _number(value.get("at")) or value["at"] > self.now + 5
                    or type(value.get("max_concurrency")) is not int or not 1 <= value["max_concurrency"] <= 500
                    or not isinstance(value.get("jobs"), list) or len(value["jobs"]) > 8
                    or not isinstance(value.get("members"), list) or len(value["members"]) > MAX_ROWS):
                raise ValueError("invalid_text_runtime")
            members = {}
            for row in value["members"]:
                key = _key(row)
                if row.get("capture_key") != identity(row) or key in members or row.get("state") not in QUEUE_STATES:
                    raise ValueError("invalid_text_runtime_member")
                members[key] = row
            self.runtime = dict(value, by_identity=members)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass

    def project(self, targets, counts):
        if counts.get("status") != "ready":
            return dict(status="unavailable", stages={}, runtime=dict(status="unavailable"))
        registered, finished, exporting, validating, publishing = set(), set(), set(), set(), set()
        recovery, recovered, recovering, blocked, source_done = set(), set(), set(), set(), set()
        native = dict(running=0, queued=0, awaiting_result=0, unknown=0)
        runtime = self.runtime
        fresh = bool(runtime and 0 <= self.now - runtime["at"] <= FRESH_SECONDS
                     and not runtime.get("observation_error"))
        latest = None
        for iid, target in targets.items():
            key = iid, target.get("trip_id"), target.get("capture_timestamp_ms") or target.get("ra_start_timestamp")
            saved = self.saved.get(key)
            if saved:
                registered.add(key)
                if _source_finished(saved):
                    finished.add(key)
                    if saved[0] in {"partial_source", "failed"}:
                        source_done.add(key)
            row = (self.queue or {}).get(key)
            if row and not _matches_version(row["member"], target):
                row = None
            if row:
                registered.add(key)
                latest = max(latest or 0, row["updated_at"])
                state, detail = row["state"], row["detail"]
                required = state in {"retry", "resource_wait"} or detail.get("operator_recovery") is True
                if required:
                    recovery.add(key)
                    if key in finished:
                        recovered.add(key)
                if state in {"review", "execution_failed"} and key not in finished:
                    blocked.add(key)
                # A completed native task alone never completes export or validation.
                # Explicit server phase records may refine a future live observation.
                if fresh and state == "orion_running" and key not in finished:
                    if detail.get("stage") == "validation":
                        validating.add(key)
                    elif detail.get("stage") == "index":
                        publishing.add(key)
            if saved and saved[0] == "failed" and key not in finished and (not row or row["state"] in {"complete", "source_failed", "review", "execution_failed"}):
                blocked.add(key)
            observed = runtime["by_identity"].get(key) if runtime else None
            if not observed or not _matches_version(observed, target) or key in finished:
                continue
            if row and row["state"] != "orion_running":
                continue  # A newer durable review/completion supersedes old live activity.
            if observed["state"] != "orion_running":
                continue
            stamp, status = observed.get("native_at"), observed.get("native_status")
            known = (fresh and _number(stamp) and 0 <= self.now - stamp <= FRESH_SECONDS
                     and type(status) is int and status in (1, 2, 3, 4))
            if not known:
                native["unknown"] += 1
                continue
            registered.add(key)
            if status == 2:
                if key not in validating and key not in publishing:
                    exporting.add(key)
                native["running"] += 1
                if key in recovery:
                    recovering.add(key)
            elif status == 1:
                native["queued"] += 1
            else:
                native["awaiting_result"] += 1

        def stage(total, done, running=0, held=0, *, optional=False):
            state = ("not_required" if optional and total == 0 else "complete" if total > 0 and done == total
                     else "running" if running else "blocked" if held else "pending")
            return dict(state=state, total=total, completed=done, running=running, blocked=held,
                        pending=max(0, total - done - running - held), optional=optional,
                        completion_basis="validated_saved_capture")

        total = len(targets)
        stages = {
            "text-input": stage(total, len(registered)),
            "text-export": stage(total, len(finished), len(exporting), len(blocked)),
            "text-verify": stage(total, len(finished), len(validating), len(blocked)),
            "text-index": stage(total, len(finished), len(publishing), len(blocked)),
            "text-recover": stage(len(recovery), len(recovered), len(recovering), optional=True),
            "text-source": stage(len(source_done | blocked), len(source_done), held=len(blocked), optional=True),
        }
        stages["text-input"]["completion_basis"] = "durable_registration_or_saved_capture"
        stages["text-recover"]["completion_basis"] = "explicit_recovery_and_saved_capture"
        return dict(status="ready", observed_at=self.now, stages=stages,
                    durable_queue="ready" if self.queue is not None else "unavailable", updated_at=latest,
                    resume="reconcile_saved_work", blocks_media=False,
                    quality=dict(collected=counts["collected"], partial_source=counts["partial_source"],
                                 failed=counts["failed"], with_frames=counts["with_frames"]),
                    runtime=dict(status="ready" if fresh and not native["unknown"] else "stale" if runtime else "unavailable",
                                 observed_at=runtime["at"] if runtime else None,
                                 max_concurrency=runtime["max_concurrency"] if runtime else None, **native))
