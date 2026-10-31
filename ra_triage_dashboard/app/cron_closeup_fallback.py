"""Bounded projection of the existing offline closeup recovery receipts.

This reader never starts a renderer. Terminal evidence survives old heartbeats;
PIDs and nonterminal state strings alone never establish a live execution.
"""
import hashlib
import json
import time

from .closeup_video import RECIPE_ID

LAYOUT_SHA = "613e4a6c1a0c000475e1eba24f1718acb5fb4bfd04dadfd3abd4035da8aa2575"
SOURCE_FAILURES = {
    "source_planning_message_malformed",
    "source_pose_gateway_missing_first_3_frozen_frames",
}


class CloseupFallback:
    def __init__(self, task_root):
        self.root = task_root.resolve()
        self.records = []
        self.status = "not_observed"
        deadline = time.monotonic() + .25
        budget = 0

        def read(path):
            nonlocal budget
            path.resolve().relative_to(self.root)
            if time.monotonic() > deadline:
                raise ValueError("fallback_read_timeout")
            with path.open("rb") as stream:
                raw = stream.read(131073)
            budget += len(raw)
            if len(raw) > 131072 or budget > 2_000_000:
                raise ValueError("oversized_fallback_evidence")
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("invalid_fallback_evidence")
            return row, raw

        try:
            folder = self.root / "local-fallback"
            if not folder.exists():
                return
            for n, run in enumerate(folder.iterdir()):
                if n >= 64:
                    raise ValueError("too_many_fallback_runs")
                if not run.is_dir() or not (run / "fallback-registration.json").is_file():
                    continue
                registration, _ = read(run / "fallback-registration.json")
                sources, raw = read(run / "source-rows.json")
                if (registration.get("recipe") != RECIPE_ID
                        or registration.get("layout_sha256") != LAYOUT_SHA
                        or registration.get("source_rows_sha256") != hashlib.sha256(raw).hexdigest()):
                    raise ValueError("fallback_identity_mismatch")
                rows = sources.get("rows")
                if not isinstance(rows, list) or len(rows) > 2000:
                    raise ValueError("invalid_fallback_sources")
                state, _ = read(run / "state.json")
                cases, remaining = state.get("cases", {}), state.get("remaining", [])
                if not isinstance(cases, dict) or not isinstance(remaining, list):
                    raise ValueError("invalid_fallback_cases")
                blocked_rows = {r.get("issue_id"): r for r in remaining if isinstance(r, dict)
                                and isinstance(r.get("issue_id"), str)}
                at = state.get("updated_at") or state.get("finished_at")
                at = at if type(at) in (int, float) and 0 < at <= time.time() + 5 else None
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("invalid_fallback_source")
                    iid = row.get("issue_id")
                    case = cases.get(iid, {})
                    if not isinstance(case, dict):
                        raise ValueError("invalid_fallback_case")
                    attempted = (type(case.get("started_at")) in (int, float)
                                 or case.get("state") == "published_verified")
                    r = blocked_rows.get(iid, {})
                    blocked = (r.get("trip_id") == row.get("trip_id")
                               and r.get("anchor_ms") == row.get("capture_timestamp_ms")
                               and r.get("disposition") in SOURCE_FAILURES)
                    self.records.append((row, attempted, blocked, at))
                self.status = "ready"
        except (OSError, ValueError, TypeError):
            self.records = []
            self.status = "unavailable"

    def project(self, targets, verified, local_verified, receipts_available):
        registered, attempted, blocked, times = set(), set(local_verified), set(), []
        for row, did_start, source_blocked, at in self.records:
            iid = row.get("issue_id")
            expected = targets.get(iid, {})
            anchor = expected.get("capture_timestamp_ms") or expected.get("ra_start_timestamp")
            if (not expected or not expected.get("trip_id") or type(anchor) is not int
                    or row.get("trip_id") != expected["trip_id"]
                    or row.get("capture_timestamp_ms") != anchor
                    or not isinstance(row.get("scopes"), list)
                    or expected.get("scope") not in row["scopes"]):
                continue
            registered.add(iid)
            if did_start:
                attempted.add(iid)
            if source_blocked and iid not in verified:
                blocked.add(iid)
            if at:
                times.append(at)
        known = self.status == "ready"
        return dict(status=self.status, registered=len(registered) if known else None,
                    attempted_cases=len(attempted) if known or local_verified else None,
                    verified=len(local_verified) if receipts_available else None,
                    source_blocked=len(blocked) if known else None,
                    source_blocked_ids=sorted(blocked)[:100],
                    evidence_at=max(times) if times else None,
                    execution_mode="on_demand_offline")
