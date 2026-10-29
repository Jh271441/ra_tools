"""Single coordinator, durable jobs, bounded retries; no model/GT/Trail writes."""
import argparse
from collections import Counter, defaultdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

from contract import LAYOUT, RECIPE_ID, publish, save, verify_case
from inventory import freeze, build_snapshot, resolve_missing

STOP = False


def stopped(*_):
    global STOP
    STOP = True


def connect(root):
    db = sqlite3.connect(Path(root) / "queue.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS members(issue_id TEXT PRIMARY KEY, version TEXT NOT NULL,
        source_state TEXT NOT NULL, source_status TEXT NOT NULL, row_json TEXT NOT NULL, frozen INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS jobs(job_key TEXT PRIMARY KEY, issue_id TEXT NOT NULL,
        row_json TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 10, pilot INTEGER NOT NULL DEFAULT 0,
        next_at REAL NOT NULL DEFAULT 0, started_at REAL, finished_at REAL, error TEXT, batch TEXT,
        UNIQUE(issue_id, job_key));
      CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
    """)
    return db


def event(db, kind, **payload):
    db.execute("INSERT INTO events(at,kind,payload) VALUES(?,?,?)", (time.time(), kind, json.dumps(payload)))
    db.commit()


def key(row):
    return hashlib.sha256(json.dumps([row["issue_id"], row["trip_id"], row["capture_timestamp_ms"], RECIPE_ID], separators=(",", ":")).encode()).hexdigest()


def enqueue(db, snapshot, frozen):
    new = 0
    for row in snapshot["members"]:
        old = db.execute("SELECT * FROM members WHERE issue_id=?", (row["issue_id"],)).fetchone()
        if old and old["version"] != row["version"]:
            raise ValueError("version_identity_conflict")
        db.execute("INSERT INTO members VALUES(?,?,?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET source_state=excluded.source_state,source_status=excluded.source_status,row_json=excluded.row_json", (row["issue_id"], row["version"], row["state"], row["source_status"], json.dumps(row), int(frozen)))
        if row["state"] != "published" or row["source_status"] != "ready":
            continue
        existing = db.execute("SELECT row_json FROM jobs WHERE issue_id=?", (row["issue_id"],)).fetchall()
        if any(key(json.loads(r[0])) != key(row) for r in existing):
            event(db, "anchor_conflict", issue_id=row["issue_id"])
            continue
        cursor = db.execute("INSERT OR IGNORE INTO jobs(job_key,issue_id,row_json,priority) VALUES(?,?,?,?)", (key(row), row["issue_id"], json.dumps(row), 10 if frozen else 0))
        new += cursor.rowcount
    db.commit()
    event(db, "enrolled", frozen=frozen, new=new, snapshot_sha=snapshot["membership_sha256"])


def pilot(db):
    if db.execute("SELECT count(*) FROM jobs WHERE pilot=1").fetchone()[0]:
        return
    for version in ("0821", "1009", "1016"):
        rows = db.execute("SELECT job_key,row_json FROM jobs ORDER BY issue_id").fetchall()
        candidates = [r for r in rows if json.loads(r["row_json"])["version"] == version]
        preferred = {"cn35635511", "cn37101871", "cn37103123", "cn36854187"}
        candidates.sort(key=lambda r: (json.loads(r["row_json"])["issue_id"] not in preferred, json.loads(r["row_json"])["anchor_source"] != "existing_media", json.loads(r["row_json"])["issue_id"]))
        for n, r in enumerate(candidates[:10]):
            db.execute("UPDATE jobs SET pilot=1,priority=? WHERE job_key=?", (-100 + n * 3 + ("0821", "1009", "1016").index(version), r["job_key"]))
    db.commit()


def resource_state():
    limit_file = Path("/sys/fs/cgroup/memory.max")
    current_file = Path("/sys/fs/cgroup/memory.current")
    if not limit_file.exists() or not current_file.exists():
        return {"status": "memory_limit_unavailable"}
    raw = limit_file.read_text().strip()
    if raw == "max":
        return {"status": "memory_limit_unavailable"}
    limit, current = int(raw), int(current_file.read_text())
    return dict(status="ready" if current < limit * .85 and limit - current >= 6 * 1024**3 else "memory_wait", memory_limit_bytes=limit, memory_current_bytes=current)


def status(root, db, state, current=None, **extra):
    counts = dict(db.execute("SELECT state,count(*) FROM jobs GROUP BY state").fetchall())
    versions = defaultdict(Counter)
    for r in db.execute("SELECT m.version,j.state,count(*) AS n FROM jobs j JOIN members m USING(issue_id) GROUP BY m.version,j.state"):
        versions[r["version"]][r["state"]] = r["n"]
    source = defaultdict(Counter)
    for r in db.execute("SELECT version,source_state,source_status,count(*) AS n FROM members GROUP BY version,source_state,source_status"):
        source[r["version"]][r["source_state"] + ":" + r["source_status"]] = r["n"]
    payload = dict(state=state, checked_at=time.time(), pid=os.getpid(), cwd=str(Path.cwd()), recipe_id=RECIPE_ID,
                   workers=1, total=sum(counts.values()), verified=counts.get("verified", 0), states=counts,
                   versions=dict(versions), source_members=dict(source), current=current,
                   main_pipeline_affected=False, **extra)
    save(Path(root) / "progress.json", payload)
    return payload


def run_batch(args, db, jobs):
    root = Path(args.root)
    batch = root / "batches" / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8])
    batch.mkdir(parents=True)
    rows = [json.loads(j["row_json"]) for j in jobs]
    # Renderer owns one Chromium root for this entire bounded batch.
    source_rows = [{k: r[k] for k in ("issue_id", "trip_id", "capture_timestamp_ms", "version")} for r in rows]
    save(batch / "source-rows.json", source_rows)
    now = time.time()
    for j in jobs:
        db.execute("UPDATE jobs SET state='running',attempts=attempts+1,started_at=?,batch=? WHERE job_key=?", (now, str(batch), j["job_key"]))
    db.commit()
    env = dict(os.environ)
    env.update(RA_BEV_CAPTURE_ROOT=str(Path(args.runtime).resolve()), NO_PROXY="*", no_proxy="*")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    command = [args.capture_python, "-u", str(Path(__file__).with_name("renderer.py")),
               "--view-distance", "30", "--ego-forward-m", "4", "--source-rows", str(batch / "source-rows.json"),
               "--layout", "debug_review", "--profile", "video_only", "--video-start-offset-sec", "-20",
               "--video-duration-sec", "40", "--video-prewarm-sec", "0", "--video-size", "1920x1080",
               "--viewport", "1920x1080", "--video-frame-step-ms", "100", "--video-capture-mode", "frame_seek",
               "--out", str(batch / "capture"), "--storage-state", args.storage_state,
               "--timeout-ms", "120000", "--wait-after-load-ms", "3000"]
    sys.path.insert(0, str(Path(args.runtime).resolve()))
    from ares_capture.process_tree import descendants, identity, finish_shutdown
    tracked = {}
    with (batch / "capture.log").open("a") as log:
        proc = subprocess.Popen(command, cwd=args.runtime, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        owned_root = identity(proc.pid)
        process_record = dict(pid=proc.pid, argv=command, started_at=now, cwd=args.runtime,
                              start_ticks=owned_root.start_ticks if owned_root else None)
        save(batch / "process.json", process_record)
        deadline = time.monotonic() + 1800 * len(rows)
        while proc.poll() is None:
            tracked.update({(p.pid, p.start_ticks): p for p in descendants(proc.pid)})
            save(batch / "process.json", dict(process_record, children=[dict(pid=p.pid, start_ticks=p.start_ticks) for p in tracked.values()]))
            status(root, db, "collecting", [r["issue_id"] for r in rows], capture_pid=proc.pid, batch=str(batch), resources=resource_state())
            if STOP or (root / "STOP").exists() or time.monotonic() > deadline:
                finish_shutdown([*tracked.values(), *([owned_root] if owned_root else [])])
                proc.wait(timeout=30)
                break
            time.sleep(10)
        finish_shutdown(list(tracked.values()))
    auth_block = False
    for job, row in zip(jobs, rows):
        folder = batch / "capture" / LAYOUT / f'{row["issue_id"]}_{row["capture_timestamp_ms"]}'
        try:
            evidence = batch / "verification" / row["issue_id"]
            path, result = verify_case(folder, row, evidence)
            receipt = publish(path, folder / "meta.json", evidence, result, args.publish_root)
            db.execute("UPDATE jobs SET state='verified',finished_at=?,error=NULL WHERE job_key=?", (time.time(), job["job_key"]))
            event(db, "verified", issue_id=row["issue_id"], sha256=receipt["sha256"], batch=str(batch))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            # Full raw diagnostics stay in this private task; public status only
            # carries stable categories and Issue IDs.
            error = type(exc).__name__ + ":" + str(exc)[:400]
            failed_meta = folder / "meta.json"
            auth_block = auth_block or (failed_meta.exists() and any(s in failed_meta.read_text().lower() for s in ("sso", "storage state", "login redirect", "authentication")))
            attempts = db.execute("SELECT attempts FROM jobs WHERE job_key=?", (job["job_key"],)).fetchone()[0]
            state = "failed" if attempts >= 3 else "retry_wait"
            db.execute("UPDATE jobs SET state=?,next_at=?,error=?,finished_at=? WHERE job_key=?", (state, time.time() + min(3600, 300 * 2**(attempts - 1)), error, time.time(), job["job_key"]))
            save(batch / "verification" / row["issue_id"] / "failure.json", dict(issue_id=row["issue_id"], state=state, error=error, attempts=attempts, source=row))
            event(db, "capture_failure", issue_id=row["issue_id"], state=state, error=error)
    db.commit()
    return auth_block


def reuse_previews(args, db):
    if not args.preview_root:
        return
    preview = Path(args.preview_root)
    report = json.loads((preview / "verification.json").read_text())
    if report.get("status") != "verified" or report.get("visual_review", {}).get("status") != "passed":
        raise ValueError("preview_not_approved")
    for entry in report["cases"]:
        job = db.execute("SELECT * FROM jobs WHERE issue_id=?", (entry["issue_id"],)).fetchone()
        if not job or job["state"] == "verified":
            continue
        row = json.loads(job["row_json"])
        folder = preview / LAYOUT / f'{row["issue_id"]}_{row["capture_timestamp_ms"]}'
        evidence = Path(args.root) / "reused-previews" / row["issue_id"]
        path, result = verify_case(folder, row, evidence)
        if result["sha256"] != entry["sha256"]:
            raise ValueError("preview_sha_mismatch")
        result["visual_review"] = "passed"
        publish(path, folder / "meta.json", evidence, result, args.publish_root)
        db.execute("UPDATE jobs SET state='verified',finished_at=? WHERE job_key=?", (time.time(), job["job_key"]))
        db.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("freeze", "resolve", "run", "status"))
    p.add_argument("--root", required=True)
    p.add_argument("--layouts-root", required=True)
    p.add_argument("--publish-root", required=True)
    p.add_argument("--runtime", required=True)
    p.add_argument("--capture-python", default="/volume/home/workspace/ra_auto_triage/.venv-ares-capture/bin/python")
    p.add_argument("--storage-state", default="/tmp/ares_storage_state.json")
    p.add_argument("--preview-root")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    signal.signal(signal.SIGTERM, stopped)
    signal.signal(signal.SIGINT, stopped)
    with (root / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = connect(root)
        if args.mode == "status":
            print(json.dumps(status(root, db, "observed"), ensure_ascii=False))
            return
        snapshot = freeze(root, args.layouts_root)
        if not db.execute("SELECT count(*) FROM members").fetchone()[0]:
            enqueue(db, snapshot, True)
        if args.mode == "resolve":
            rows = [json.loads(r[0]) for r in db.execute("SELECT row_json FROM members WHERE source_status='missing_anchor' AND source_state='published'")]
            resolved = dict(created_at=time.time(), membership_sha256=snapshot["membership_sha256"], members=resolve_missing(rows))
            save(root / "source-resolutions" / f"{int(time.time())}.json", resolved)
            enqueue(db, resolved, True)
            if db.execute("SELECT count(*) FROM jobs WHERE attempts>0 OR state='verified'").fetchone()[0] == 0:
                db.execute("UPDATE jobs SET pilot=0,priority=10")
                db.commit()
            pilot(db)
            print(json.dumps(status(root, db, "queued"), ensure_ascii=False))
            return
        pilot(db)
        if args.mode == "freeze":
            print(json.dumps(status(root, db, "queued"), ensure_ascii=False))
            return
        # A stale running claim is never silently re-rendered: inspect its
        # actual process identity and completed files before manual recovery.
        if db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0]:
            status(root, db, "interrupted_claim_requires_review")
            return
        reuse_previews(args, db)
        last_discovery = time.time()
        blocked_auth_mtime = None
        while not STOP and not (root / "STOP").exists():
            if blocked_auth_mtime is not None:
                current = Path(args.storage_state).stat().st_mtime_ns
                if current == blocked_auth_mtime:
                    status(root, db, "blocked_auth")
                    time.sleep(30)
                    continue
                blocked_auth_mtime = None
            pilot_left = db.execute("SELECT count(*) FROM jobs WHERE pilot=1 AND state!='verified'").fetchone()[0]
            if pilot_left and db.execute("SELECT count(*) FROM jobs WHERE pilot=1 AND state='failed'").fetchone()[0]:
                status(root, db, "pilot_failed_requires_review")
                time.sleep(30)
                continue
            if not pilot_left and not (root / "pilot-passed.json").exists():
                if not (root / "pilot-visual-review.json").is_file():
                    status(root, db, "pilot_visual_review_required")
                    time.sleep(30)
                    continue
                visual = json.loads((root / "pilot-visual-review.json").read_text())
                if visual.get("status") != "passed" or not {"0821", "1009", "1016"}.issubset(set(visual.get("versions", []))):
                    raise ValueError("pilot_visual_review_incomplete")
                save(root / "pilot-passed.json", dict(passed_at=time.time(), recipe_id=RECIPE_ID, count=db.execute("SELECT count(*) FROM jobs WHERE pilot=1 AND state='verified'").fetchone()[0], visual_review=visual))
            resources = resource_state()
            import shutil
            if resources["status"] != "ready" or shutil.disk_usage(root).free < 10 * 1024**3:
                status(root, db, "resource_wait", resources=resources)
                time.sleep(30)
                continue
            query = "SELECT * FROM jobs WHERE state IN ('queued','retry_wait') AND next_at<=?" + (" AND pilot=1" if pilot_left else "") + " ORDER BY priority,issue_id LIMIT 3"
            jobs = db.execute(query, (time.time(),)).fetchall()
            if not jobs:
                status(root, db, "waiting" if pilot_left else "idle")
                if args.once:
                    break
                time.sleep(30)
            else:
                if run_batch(args, db, jobs):
                    blocked_auth_mtime = Path(args.storage_state).stat().st_mtime_ns
                if args.once:
                    break
            if time.time() - last_discovery > 3600:
                try:
                    delta = build_snapshot(args.layouts_root, incremental=True)
                    save(root / "discoveries" / f"{int(time.time())}.json", delta)
                    enqueue(db, delta, False)
                except Exception as exc:
                    event(db, "discovery_failed", code=type(exc).__name__)
                last_discovery = time.time()
        status(root, db, "stopped")


if __name__ == "__main__":
    main()
