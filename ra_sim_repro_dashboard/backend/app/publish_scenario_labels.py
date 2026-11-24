"""Offline: preview, append and verify a single reconciled AutoTriage label set.

Example: python -m app.publish_scenario_labels --release ... --output /private/run
Default is read-only preview. --apply PLAN_ID is required for platform writes.
"""

import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import time
import requests
from app.clients.scenario_publisher import ScenarioPlatformClient
from app.database import SessionLocal
from app.domain.hashing import digest
from app.services import evaluation_pipeline as pipeline, scenario_label_sets as tags


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".next")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.chmod(0o600)
    temp.replace(path)


class Platform:
    def __init__(self):
        self.api = ScenarioPlatformClient()
        self.session = self.api.session

    def post(self, url, payload, read_only=False):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = {
            "Content-Type": "application/json",
            "app_id": os.getenv("SCENARIO_APP_ID", "voyager-autotest"),
            "sign": self.api._sign_for_json_string(body),
        }
        attempts = 3 if read_only else 1
        for attempt in range(attempts):
            try:
                response = self.session.post(
                    url, data=body.encode("utf-8"), headers=headers, timeout=60
                )
                response.raise_for_status()
                value = response.json()
                if value.get("errno") != 0:
                    raise ValueError(f"scenario_platform_errno_{value.get('errno')}")
                return value
            except requests.RequestException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                transient = status is None or status >= 500 or status == 429
                if not read_only or not transient or attempt + 1 >= attempts:
                    raise
                time.sleep(attempt + 1)

    def query(self, ids=None, label=None):
        result = []
        page = 1
        while True:
            payload = {"page": page, "size": 500}
            if ids is not None:
                payload["id"] = ",".join(ids)
            if label:
                payload["labels"] = label
            value = self.post(self.api.query_url, payload, read_only=True)["data"]
            rows = value.get("res", value.get("data", []))
            count = int(value.get("total", value.get("count", -1)))
            if count < 0 or not isinstance(rows, list):
                raise ValueError("incomplete_scenario_query")
            result.extend(rows)
            if len(result) >= count:
                if len(result) != count or len({str(r["id"]) for r in result}) != count:
                    raise ValueError("incomplete_scenario_query")
                return result
            if len(rows) != 500:
                raise ValueError("incomplete_scenario_query")
            page += 1

    def append(self, row, expected):
        values = sorted(tags.labels(row) | set(expected["add_labels"]))
        return self.post(
            self.api.update_url,
            {
                "id": int(expected["scenario_id"]),
                "labels": ",".join(values),
                "updater": "jasperchen",
                "user_location": "cn",
                "keep_review_status": True,
            },
        )


def publish(
    plan,
    platform,
    directory,
    apply=False,
    canary_only=False,
    allowed_ids=None,
    canary_scenario_id=None,
):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    expected = {s["scenario_id"]: s for s in plan["scenarios"]}
    before = {}
    for start in range(0, len(expected), 100):
        ids = list(expected)[start : start + 100]
        found = platform.query(ids)
        if len(found) != len(ids) or {str(r["id"]) for r in found} != set(ids):
            raise ValueError("scenario_query_coverage_mismatch")
        for row in found:
            sid = str(row["id"])
            tags.verify_identity(row, expected[sid])
            before[sid] = row
    write(directory / "plan.json", plan)
    write(directory / "before.json", before)
    preview = {
        "plan_id": plan["id"],
        "namespace": plan["namespace"],
        "scenario_count": len(expected),
        "mapped_issues": plan["mapped_issues"],
        "pending_issues": plan["pending_issues"],
        "already_tagged": sum(
            set(expected[sid]["add_labels"]) <= tags.labels(row) for sid, row in before.items()
        ),
    }
    write(directory / "preview.json", preview)
    if not apply:
        return preview
    ids = list(expected) if allowed_ids is None else [sid for sid in expected if sid in allowed_ids]
    if canary_scenario_id is not None:
        if canary_scenario_id not in ids:
            raise ValueError("canary_outside_label_plan")
        ids.remove(canary_scenario_id)
        ids.insert(0, canary_scenario_id)
    if canary_only:
        ids = ids[:1]
    journal = directory / "updates.jsonl"
    for n, sid in enumerate(ids):
        rows = platform.query([sid])
        if len(rows) != 1:
            raise ValueError("scenario_query_coverage_mismatch")
        live = rows[0]
        tags.verify_identity(live, expected[sid])
        if tags.physical(live) != tags.physical(before[sid]):
            raise ValueError("scenario_input_changed")
        receipt = {
            "scenario_id": sid,
            "before_labels": sorted(tags.labels(live)),
            "status": "intent",
            "at": tags.now(),
        }
        with journal.open("a") as log:
            log.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            log.flush()
            os.fsync(log.fileno())
        if not set(expected[sid]["add_labels"]) <= tags.labels(live):
            platform.append(live, expected[sid])
        for visibility_attempt in range(5):
            after = platform.query([sid])
            if len(after) != 1:
                raise ValueError("scenario_query_coverage_mismatch")
            try:
                tags.verify_after(live, after[0], expected[sid])
                break
            except ValueError as exc:
                if str(exc) != "scenario_labels_not_preserved" or visibility_attempt == 4:
                    raise
                time.sleep(0.5 * (visibility_attempt + 1))
        receipt.update(
            status="verified",
            after_labels=sorted(tags.labels(after[0])),
            version=after[0]["version"],
        )
        with journal.open("a") as log:
            log.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            log.flush()
            os.fsync(log.fileno())
        if n % 50 == 0:
            print(json.dumps({"verified": n + 1, "total": len(ids)}), flush=True)
    if canary_only:
        write(directory / "canary.json", receipt)
        return {"canary_verified": True, **preview}
    verified_rows = platform.query(label=plan["namespace"])
    verified = {str(row["id"]): row for row in verified_rows}
    if set(verified) != set(expected):
        raise ValueError("scenario_label_query_coverage_mismatch")
    for sid, row in verified.items():
        tags.verify_after(before[sid], row, expected[sid])
    automatic = {sid for sid, s in expected.items() if s["ra_type"] == 2}
    query_auto = platform.query(label=plan["namespace"] + "_AutoTrigger")
    if {str(row["id"]) for row in query_auto} != automatic:
        raise ValueError("scenario_trigger_query_mismatch")
    write(directory / "after.json", verified)
    with SessionLocal() as db:
        summary = tags.save_verified(db, plan, verified)
    write(directory / "complete.json", summary)
    return summary


def resume_allowlist(plan, value):
    core = {k: v for k, v in value.items() if k != "verification_hash"}
    if digest(core) != value.get("verification_hash") or value.get("plan_id") != plan["id"]:
        raise ValueError("invalid_resume_receipt")
    allowed = set(value["allowed_ids"])
    confirmed = set(value["confirmed_ids"])
    attempted = set(value["previously_attempted_ids"])
    if (
        allowed & confirmed
        or allowed & attempted
        or not attempted <= confirmed
        or allowed | confirmed != {s["scenario_id"] for s in plan["scenarios"]}
    ):
        raise ValueError("resume_would_repeat_prior_write")
    return allowed


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument("--release", required=True)
    p.add_argument("--profile-id", default="auto_triage_sql_v2")
    p.add_argument("--date-start", required=True)
    p.add_argument("--date-end", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--apply")
    p.add_argument("--canary-only", action="store_true")
    p.add_argument("--resume-only")
    p.add_argument("--canary-scenario-id")
    args = p.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "publish.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with SessionLocal() as db:
            ctx = {
                "release": args.release,
                "profile_id": args.profile_id,
                "date_start": args.date_start,
                "date_end": args.date_end,
            }
            board = pipeline.board(db, **ctx)
            if board["stale"] or not board["revision"]:
                raise ValueError("evaluation_stale")
            revision = pipeline.current_revision(db, **ctx)
            plan = tags.build_plan(revision)
        if args.apply and args.apply != plan["id"]:
            raise ValueError("label_plan_changed")
        allowed = (
            resume_allowlist(plan, json.loads(Path(args.resume_only).read_text()))
            if args.resume_only
            else None
        )
        result = publish(
            plan,
            Platform(),
            directory,
            apply=bool(args.apply),
            canary_only=args.canary_only,
            allowed_ids=allowed,
            canary_scenario_id=args.canary_scenario_id,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
