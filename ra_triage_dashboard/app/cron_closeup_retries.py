"""Read-only, same-cohort evidence for the single closeup Orion retry."""
import hashlib
import json
import time

from .closeup_video import RECIPE_ID
from .cron_closeup_fallback import LAYOUT_SHA


class CloseupRetries:
    def __init__(self, task_root):
        self.root = task_root.resolve()
        self.records = []
        self.status = "not_observed"
        self.extra = []
        deadline, budget = time.monotonic() + .25, 0

        def read(path, limit=262144):
            nonlocal budget
            path.resolve().relative_to(self.root)
            if time.monotonic() > deadline:
                raise ValueError("retry_evidence_timeout")
            with path.open("rb") as stream:
                raw = stream.read(limit + 1)
            budget += len(raw)
            if len(raw) > limit or budget > 8_000_000:
                raise ValueError("oversized_retry_evidence")
            return json.loads(raw), raw

        try:
            if not (self.root / "orion/jobs.json").is_file():
                return
            registration, _ = read(self.root / "orion/registration.json")
            if (registration.get("recipe_id") != RECIPE_ID
                    or registration.get("rendered_layout_sha256") != LAYOUT_SHA):
                raise ValueError("retry_layout_mismatch")
            jobs, _ = read(self.root / "orion/jobs.json")
            if not isinstance(jobs, list) or len(jobs) > 64:
                raise ValueError("invalid_retry_jobs")
            for job in jobs:
                if not isinstance(job, dict):
                    raise ValueError("invalid_retry_job")
                attempt = job.get("attempt_number")
                if type(attempt) is not int or attempt < 2:
                    continue
                run = self.root / job["run"]
                sources, raw = read(run / "source-rows.json")
                if hashlib.sha256(raw).hexdigest() != job.get("source_sha256"):
                    raise ValueError("retry_source_mismatch")
                rows = sources.get("rows") if isinstance(sources, dict) else sources
                if not isinstance(rows, list) or len(rows) > 2000 or not all(isinstance(r, dict) for r in rows):
                    raise ValueError("invalid_retry_members")
                if attempt > 2:
                    self.extra.extend(rows)
                    continue
                status, _ = read(run / "status.json")
                counts = status.get("counts", {})
                total = status.get("total")
                if (status.get("job_id") != job.get("job_id") or type(total) is not int
                        or total != len(rows) or not isinstance(counts, dict)
                        or not all(type(n) is int and n >= 0 for n in counts.values())
                        or sum(counts.values()) != total):
                    raise ValueError("invalid_retry_status")
                failed = counts.get("failed", 0) + counts.get("cancelled", 0)
                terminal = counts.get("completed", 0) + failed == total
                failed_ids = set()
                if terminal and failed:
                    native, _ = read(run / "native-failed-tasks.json", limit=2_000_000)
                    if not isinstance(native, list):
                        raise ValueError("invalid_failed_retry_tasks")
                    by_id = {r.get("issue_id"): r for r in rows}
                    for task in native:
                        # These archived lists contain native FAILED (4) tasks.
                        # Other terminal enums need their own confirmed evidence.
                        if not isinstance(task, dict) or task.get("status") != 4:
                            raise ValueError("invalid_failed_retry_task_status")
                        parts = str(task.get("signature", "")).rsplit("-", 2)
                        if len(parts) != 3 or parts[0] not in by_id:
                            raise ValueError("retry_task_identity_mismatch")
                        row = by_id[parts[0]]
                        if task.get("job_id") != job["job_id"] or parts[1] != str(row.get("capture_timestamp_ms")):
                            raise ValueError("retry_task_identity_mismatch")
                        failed_ids.add(parts[0])
                    if counts.get("cancelled", 0):
                        raise ValueError("unsupported_cancelled_retry_evidence")
                    if len(native) != failed or len(failed_ids) != failed:
                        raise ValueError("incomplete_retry_tasks")
                at = status.get("observed_at")
                at = at if type(at) in (int, float) and 0 < at <= time.time() + 5 else None
                for row in rows:
                    outcome = "failed" if row.get("issue_id") in failed_ids else "completed" if terminal else "unknown"
                    self.records.append((row, outcome, at))
            self.status = "ready"
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.records, self.extra, self.status = [], [], "unavailable"

    @staticmethod
    def matches(row, expected):
        anchor = expected.get("capture_timestamp_ms") or expected.get("ra_start_timestamp")
        return (expected.get("trip_id") and type(anchor) is int and anchor > 0
                and row.get("trip_id") == expected["trip_id"]
                and row.get("capture_timestamp_ms") == anchor
                and isinstance(row.get("scopes"), list) and expected.get("scope") in row["scopes"])

    def project(self, targets):
        selected, times = {}, []
        for row, outcome, at in self.records:
            iid = row.get("issue_id")
            if self.matches(row, targets.get(iid, {})):
                # Multiple automatic retries would violate the single-retry contract.
                if iid in selected:
                    return dict(status="unavailable",total=None,processed=None,completed=None,failed=None,evidence_at=None)
                selected[iid] = outcome
                if at:
                    times.append(at)
        known = self.status == "ready"
        completed, failed = list(selected.values()).count("completed"), list(selected.values()).count("failed")
        total = len(selected)
        status = ("partial_failed" if failed else "completed") if total and completed + failed == total else "unknown" if total else "not_observed"
        return dict(status=status if known else self.status, total=total if known else None,
                    processed=completed+failed if known else None, completed=completed if known else None,
                    failed=failed if known else None, evidence_at=max(times) if times else None,
                    legacy_extra_attempt_cases=len({r.get("issue_id") for r in self.extra if self.matches(r,targets.get(r.get("issue_id"),{}))}))
