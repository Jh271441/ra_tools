"""Receipt-backed timing for Cron graphs; never use file mtimes or sum parallel work."""
from __future__ import annotations

import json
from datetime import datetime
import math
from pathlib import Path
import re

MAX_BYTES = 2_000_000
MAX_MEMBERS = 1000
ISSUE = re.compile(r"[A-Za-z0-9_-]{3,128}")
ATTEMPT = re.compile(r"attempt_(\d{18,20})")


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def timestamp(value):
    value = number(value)
    return value if value and value > 0 else None


def read_receipt(root: Path, path: Path, fallback=None):
    if root.resolve() not in path.resolve().parents or path.is_symlink():
        raise ValueError("timing receipt escapes root")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return fallback
    if len(raw) > MAX_BYTES:
        raise ValueError("timing receipt too large")
    return json.loads(raw)


def timing(start=None, end=None, *, seconds=None, running=False, observed_at=None,
           kind="elapsed", basis="", observed=None, total=None):
    start, end, seconds = timestamp(start), timestamp(end), number(seconds)
    as_of = timestamp(observed_at)
    result = dict(started_at=start, finished_at=end, elapsed_seconds=None,
                  mode="unavailable", kind=kind, basis=basis)
    if observed is not None:
        result.update(observed=observed, total=total)
    if start and end and end >= start and (as_of is None or end <= as_of + 5):
        result.update(elapsed_seconds=end - start, mode="finished")
    elif seconds is not None and end is None and not running and (start is None or as_of is None or start + seconds <= as_of + 5):
        # The pipeline exports elapsed_seconds from its immutable registration.
        result.update(elapsed_seconds=seconds, mode="finished")
        if start and (as_of is None or start + seconds <= as_of + 5):
            result["finished_at"] = start + seconds
    elif running and start and as_of and as_of >= start:
        result.update(elapsed_seconds=as_of - start, mode="running", observed_at=as_of)
    return result


def receipt_span(root, cases, members, stage, *, expected, observed_at):
    starts, ends = [], []
    for iid in members:
        folder = cases / iid / stage
        for attempt in sorted(folder.glob("attempt_*"))[:20]:
            match = ATTEMPT.fullmatch(attempt.name)
            if match and not attempt.is_symlink() and root.resolve() in attempt.resolve().parents and (attempt / "intent.json").is_file():
                # workflow._mutate persists time.time_ns() in the attempt name.
                value = int(match[1]) / 1_000_000_000
                if value <= observed_at + 5:
                    starts.append(value)
        receipt = read_receipt(root, folder / "verified.json", {})
        end = timestamp(receipt.get("verified_at")) if isinstance(receipt, dict) else None
        if end and end <= observed_at + 5:
            ends.append(end)
    result = timing(min(starts) if starts else None, max(ends) if ends else None,
                    observed_at=observed_at, kind="span", basis=stage + "_receipts",
                    observed=len(ends), total=expected)
    if len(ends) != expected and result["mode"] == "finished":
        result["mode"] = "observed"
    return result


def add_main_timings(overview: dict, ra_root: Path | None):
    as_of = timestamp(overview.get("collected_at"))
    daily = overview.get("daily", {})
    for index, run in enumerate(daily.get("runs", [])):
        run.pop("timing_error", None)
        active = run.get("health") == "running"
        run["timing"] = timing(run.get("started_at"), seconds=None if active else run.get("elapsed_seconds"),
                               running=active, observed_at=as_of, basis="pipeline_registration")
        run["stage_timings"] = {}
        # Recent stage receipts only; old runs retain their exported total.
        if ra_root is None or as_of is None or index >= 8 or not re.fullmatch(r"daily-\d{4}-\d{2}-\d{2}", run.get("id", "")):
            continue
        root = ra_root.parent / "ra_auto_triage_deploy"
        work = root / "state/pipeline_v1" / run["id"]
        try:
            registration = read_receipt(root, work / "registration.json", {})
            if (registration.get("run_id") != run["id"] or
                    registration.get("scope", {}).get("date_cst") != run.get("target_date_cst") or
                    timestamp(registration.get("started_at")) != timestamp(run.get("started_at"))):
                continue
            stages = run["stage_timings"]
            stages["main-infer"] = timing(run.get("started_at"), running=active and run.get("stage") == "inference", observed_at=as_of,
                kind="span", basis="registration_to_publication")
            launches = []
            for launch in daily.get("launches", []) + daily.get("recoveries", []):
                if launch.get("target_date_cst") != run.get("target_date_cst"):
                    continue
                try:
                    date = datetime.fromisoformat(launch.get("started_at", ""))
                    if date.tzinfo is not None and 0 < date.timestamp() <= registration["started_at"]:
                        launches.append(date.timestamp())
                except (ValueError, TypeError):
                    pass
            stages["main-query"] = timing(max(launches) if launches else None, run.get("started_at"),
                kind="span", basis="launch_to_registration", observed_at=as_of)
            cohort = read_receipt(root, work / "publication_cohort.json", {})
            included = cohort.get("included_ids", [])
            if (cohort.get("run_id") != run["id"] or not isinstance(included, list) or
                    len(included) > MAX_MEMBERS or any(not isinstance(i, str) or not ISSUE.fullmatch(i) for i in included) or len(set(included)) != len(included) or
                    not re.fullmatch(r"[a-f0-9]{64}", str(cohort.get("selection_sha256", ""))) or
                    cohort.get("selection_sha256") != registration.get("selection_sha256")):
                continue
            stages["main-publish"] = receipt_span(root, work / "cases", included, "publication", expected=len(included), observed_at=as_of)
            plan = read_receipt(root, work / "review_plan.json", {})
            sampled = plan.get("sampled_ids", [])
            if isinstance(sampled, list) and len(sampled) <= MAX_MEMBERS and all(isinstance(i, str) and i in included for i in sampled) and len(set(sampled)) == len(sampled):
                stages["main-verify"] = receipt_span(root, work / "cases", sampled, "sample_hook", expected=len(sampled), observed_at=as_of)
            # This is a measured boundary-to-boundary span, including preparation;
            # it is not the sum of per-case model runtimes.
            publish_start = stages["main-publish"]["started_at"]
            stages["main-infer"] = timing(run.get("started_at"), publish_start,
                running=active and run.get("stage") == "inference", observed_at=as_of,
                kind="span", basis="registration_to_publication")
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            # Timing loss must never hide the run or its independent outcome.
            run["timing_error"] = True
