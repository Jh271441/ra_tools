#!/usr/bin/env python3
"""One scoped release: preserve the occupied gray/canonical trees and migrate audit57.

Run with the cloud Dashboard interpreter and --sha equal to pushed origin/master.
Uses versioned deploy_cloud gates; the migration exception is bound to exact bytes.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import time

OLD = "20e86effd5d24df9142c50ca102a5080a3dc194d"
OLD_ROOT = Path("/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T194629Z-20e86effd5d2/candidate")
REPO = Path("/volume/home/workspace/ra_tools")
MIGRATION = "ra_triage_dashboard/migrations/postgres/057_trail_history.sql"
DIGEST = "54008df2790bc6910495524f0ae622da3e448248c9fe910b5a4195281a677e3a"
PORT = 18789


def migrate(d, candidate, env, folder):
    """Stopped-writer backup, exact restore/fingerprint rehearsal, then apply."""
    from psycopg.conninfo import conninfo_to_dict
    import psycopg
    from psycopg import sql

    url = Path(env["DASHBOARD_DATABASE_URL_FILE"]).read_text().strip()
    ci = conninfo_to_dict(url)
    owner = pwd.getpwuid(os.getuid()).pw_name
    d.require(not ci.get("password") and ci.get("host", "").strip("/") in {"", "var/run/postgresql"}
              and ci.get("port", "5432") == "5432" and ci.get("user", owner) == owner,
              "Only the existing local peer-authenticated database is supported")
    root = d.STATE / "migrations" / folder.name
    (root / "config").mkdir(parents=True, mode=0o700)
    d.save(root / "config/service_env.json", {key: env[key] for key in ("DASHBOARD_DATABASE_URL_FILE", "DASHBOARD_DATA_DIR")})
    with (folder / "backup.log").open("w") as log:
        output = d.run(d.PYTHON, candidate / "ra_triage_dashboard/scripts/backup_instance.py",
                       "--instance", root, "--verify", cwd=candidate, env=dict(env, USER=owner),
                       stdout=subprocess.PIPE, stderr=log, timeout=600).stdout.decode()
    backup = json.loads(output.strip().splitlines()[-1])
    d.require(backup["restore_verified"] and backup["database"] == ci["dbname"], "Wrong or unverified backup")
    dump = Path(backup["dump"])
    receipt = json.loads(dump.with_suffix(".receipt.json").read_text())
    # Keep this cutover backup outside rolling daily/release cleanup.
    for suffix in (".dump", ".dump.sha256", ".assets.tar.gz", ".receipt.json"):
        source = dump.with_suffix(suffix)
        if source.exists():
            shutil.copy2(source, root / source.name)
    saved = root / dump.name
    d.require(hashlib.sha256(saved.read_bytes()).hexdigest() == receipt["sha256"], "Permanent backup checksum differs")
    spec = importlib.util.spec_from_file_location("backup_fingerprints", candidate / "ra_triage_dashboard/scripts/backup_instance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with psycopg.connect(url) as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        before = module.fingerprints(conn)
    d.require(before == receipt["table_fingerprints"], "Live data changed after stopped-writer backup")
    restore = "trail_history_rehearsal_" + str(os.getpid())
    d.run("sudo", "-u", "postgres", "createdb", "--template=template0", "--owner", owner, restore)
    try:
        d.run("pg_restore", "--dbname", restore, "--no-owner", "--no-privileges", "--exit-on-error", saved, timeout=600)
        with psycopg.connect(dbname=restore) as conn:
            d.require(module.fingerprints(conn) == before, "Rehearsal restore differs")
        rehearsal_file = root / "rehearsal-url.txt"
        rehearsal_file.write_text("postgresql:///" + restore)
        rehearsal_file.chmod(0o600)
        rehearsal_env = dict(env, DASHBOARD_DATABASE_URL_FILE=str(rehearsal_file), DASHBOARD_DATABASE_URL="")
        with (folder / "migration-rehearsal.log").open("w") as log:
            d.run(d.PYTHON, "-c", d.MIGRATION_APPLY_CODE, cwd=candidate / "ra_triage_dashboard",
                  env=rehearsal_env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        with psycopg.connect(dbname=restore) as conn:
            after = module.fingerprints(conn)
            count = conn.execute("SELECT count(*) FROM dashboard_schema_migrations").fetchone()[0]
            triggers = conn.execute("SELECT count(*) FROM pg_trigger WHERE tgname IN ('trail_audit_immutable','trail_audit_revision') AND tgenabled='O'").fetchone()[0]
        protected = set(before) - {"dashboard_change_revision", "dashboard_schema_migrations"}
        d.require(count == 57 and triggers == 6, "Rehearsal schema/trigger verification failed")
        d.require(all(before[name] == after[name] for name in protected), "Rehearsal changed pre-existing business data")
        d.save(root / "rehearsal.json", {"migration_sha256": DIGEST, "schema": count,
               "protected_tables": len(protected), "protected_fingerprints_match": True,
               "enabled_audit_triggers": triggers, "backup_sha256": receipt["sha256"]})
    finally:
        d.run("sudo", "-u", "postgres", "dropdb", "--if-exists", restore)
    with (folder / "migration.log").open("w") as log:
        d.run(d.PYTHON, "-c", d.MIGRATION_APPLY_CODE, cwd=candidate / "ra_triage_dashboard",
              env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    with psycopg.connect(url) as conn:
        actual = module.fingerprints(conn)
        count = conn.execute("SELECT count(*) FROM dashboard_schema_migrations").fetchone()[0]
    d.require(count == 57 and all(before[name] == actual[name] for name in protected),
              "Production schema or protected fingerprints differ")
    d.save(root / "applied.json", {"schema": count, "protected_tables": len(protected),
           "protected_fingerprints_match": True, "migration_sha256": DIGEST})
    return str(root), count


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    sha = parser.parse_args().sha
    source = subprocess.check_output(["git", "show", sha + ":ra_triage_dashboard/scripts/deploy_cloud.py"], cwd=REPO)
    helper = Path("/tmp/trail-history-deploy-helpers-" + str(os.getpid()) + ".py")
    helper.write_bytes(source)
    spec = importlib.util.spec_from_file_location("deploy_helpers", helper)
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)

    def live():
        pid = d.git_pane_pid()
        proc = Path("/proc") / str(pid)
        d.require(proc.stat().st_uid == os.getuid(), "Wrong process owner")
        args = (proc / "cmdline").read_bytes().split(b"\0")
        d.require(b"uvicorn" in args and b"8785" in args, "Wrong foreground process")
        values = dict(v.split("=", 1) for v in (proc / "environ").read_bytes().decode().split("\0") if "=" in v)
        return pid, (proc / "cwd").resolve(), d.capture_env(values)

    with d.deployment_lock(d.STATE):
        d.run("git", "fetch", "origin", "master")
        d.require(d.git("rev-parse", "origin/master") == sha, "Target differs from origin/master")
        d.run("git", "merge-base", "--is-ancestor", OLD, sha)
        sensitive = d.git("diff", "--name-status", OLD, sha, "--", *d.SENSITIVE_PATHS)
        d.require(sensitive == "A\t" + MIGRATION, "Unexpected schema/dependency changes")
        migration = subprocess.check_output(["git", "show", sha + ":" + MIGRATION], cwd=REPO)
        d.require(hashlib.sha256(migration).hexdigest() == DIGEST, "Reviewed migration bytes changed")
        canonical = d.git("status", "--porcelain")
        canonical_sha = d.git("rev-parse", "HEAD")
        pid, app, env = live()
        d.require(app == OLD_ROOT / "ra_triage_dashboard", "Unexpected live directory")
        d.require(d.git("rev-parse", "HEAD", cwd=OLD_ROOT) == OLD and not d.git("status", "--porcelain", cwd=OLD_ROOT), "Original release changed")
        before = d.smoke(8785, OLD, "postgresql")
        d.require(d.get_json(8785, "api/status")["database"]["migration_count"] == 56, "Unexpected original schema")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", PORT))
        release_id, folder = d.create_release_folder(sha)
        candidate, rollback, data = folder / "candidate", folder / "rollback", folder / "gray-data"
        result = dict(status="preparing", target=sha, previous=OLD, candidate=str(candidate), rollback=str(rollback),
                      gray_port=PORT, canonical_sha_preserved=canonical_sha, record=str(folder),
                      migration_sha256=DIGEST, migration_mode="reviewed-audit57", rollback_enabled=False)
        d.save(folder / "result.json", result)
        shutil.copyfile(__file__, folder / "isolated-deploy.py")
        d.save(folder / "production-before.json", dict(app=str(app), env=env, sha=OLD, pid=pid, policy=d.policy(before), migration_count=56))
        gray = None
        stopped = False
        replacement = None
        try:
            d.run("git", "worktree", "add", "--detach", candidate, sha)
            d.run("git", "worktree", "add", "--detach", rollback, OLD)
            data.mkdir(mode=0o700)
            media = Path(env["DASHBOARD_DATA_DIR"]) / "media_layouts"
            if media.is_dir():
                (data / "media_layouts").symlink_to(media, target_is_directory=True)
            gray_env = d.gray_env(d.rebase_env(env, OLD_ROOT, REPO), candidate, data, sha)
            gray_env.update(DASHBOARD_PORT=str(PORT), DASHBOARD_GT_SYNC_ENABLED="false", DASHBOARD_SMOKE_LOOPBACK_ADMIN_ENABLED="false", DASHBOARD_TRAIL_ROLLBACK_ENABLED="false")
            print("Release " + release_id + "; running complete cloud test suite", flush=True)
            with (folder / "tests.log").open("w") as log:
                d.run(d.PYTHON, "-m", "pytest", "ra_triage_dashboard/tests", "-q", cwd=candidate,
                      env=dict(gray_env, DASHBOARD_BASE_PATH="", DASHBOARD_MEDIA_LAYOUT_ROOT=""),
                      stdout=log, stderr=subprocess.STDOUT, timeout=600)
            print((folder / "tests.log").read_text().splitlines()[-1], flush=True)
            with (folder / "gray.log").open("w") as log:
                gray = subprocess.Popen([str(d.PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", str(candidate / "ra_triage_dashboard"), "--host", "127.0.0.1", "--port", str(PORT)], cwd=candidate, env=gray_env, stdout=log, stderr=subprocess.STDOUT)
            gray_health = d.smoke(PORT, sha, "sqlite")
            d.require(gray_health.get("gt_sync", {}).get("enabled") is False, "Gray GT sync is enabled")
            audit = d.get_json(PORT, "api/trail-history")
            d.require(audit["total"] == 0 and audit["can_restore"] is False, "Gray audit is not isolated/read-only")
            d.stop_child(gray)
            d.validate_prepared_worktree(candidate, sha)
            d.validate_prepared_worktree(rollback, OLD)
            d.run("git", "fetch", "origin", "master")
            d.require(live() == (pid, app, env), "Production process/config changed")
            d.require(d.git("rev-parse", "origin/master") == sha, "Origin target changed")
            d.require(d.git("status", "--porcelain") == canonical and d.git("rev-parse", "HEAD") == canonical_sha, "Canonical checkout changed")
            d.require(d.get_json(8785, "api/status")["database"]["migration_count"] == 56, "Schema changed during validation")
            next_env = d.rebase_env(d.rebase_env(env, REPO, candidate), OLD_ROOT, candidate)
            next_env["DASHBOARD_TRAIL_ROLLBACK_ENABLED"] = "false"
            for key in ("DASHBOARD_DATA_DIR", "DASHBOARD_DATABASE_URL_FILE", "DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE", "DASHBOARD_DCHAT_CREDENTIALS_FILE"):
                d.require(next_env.get(key) == env.get(key), "Persistent configuration changed: " + key)
            result["status"] = "promoting"
            d.save(folder / "result.json", result)
            print("Gray passed; stopping Dashboard for backup, restore rehearsal and audit57 migration", flush=True)
            stopped = True
            d.stop_production(pid)
            backup_root, count = migrate(d, candidate, next_env, folder)
            result.update(backup_root=backup_root, migration_count=count)
            d.save(folder / "result.json", result)
            d.start_production(folder, candidate / "ra_triage_dashboard", next_env, sha, "production")
            replacement = d.git_pane_pid()
            after = d.smoke(8785, sha, "postgresql")
            d.require(d.policy(after) == d.policy(before), "Existing runtime policy changed")
            d.require(d.get_json(8785, "api/status")["database"]["migration_count"] == 57, "Schema verification failed")
            for key in ("gt_sync", "review_notifications"):
                d.require(after.get(key, {}).get("enabled") == before.get(key, {}).get("enabled"), "Service flag changed: " + key)
            audit = d.get_json(8785, "api/trail-history")
            d.require(audit["can_restore"] is False, "Restore gate unexpectedly enabled")
            d.require(d.git("status", "--porcelain") == canonical and d.git("rev-parse", "HEAD") == canonical_sha, "Canonical checkout changed")
            result.update(status="success", policy=d.policy(after), promoted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), pid=replacement, audit_records=audit["total"])
            d.save(folder / "result.json", result)
            try:
                result["cleaned_worktrees"] = d.cleanup(d.STATE, folder)
            except Exception as exc:
                result["cleanup_warning"] = type(exc).__name__
            d.save(folder / "result.json", result)
            print(json.dumps(result), flush=True)
        except BaseException as exc:
            d.stop_child(gray)
            result.update(status="failed", error_type=type(exc).__name__)
            if stopped and not d.process_alive(pid):
                try:
                    if replacement is not None and d.process_alive(replacement):
                        d.stop_production(replacement)
                    d.start_production(folder, app, env, OLD, "rollback")
                    d.smoke(8785, OLD, "postgresql")
                    result["rollback_status"] = "healthy"
                except BaseException as recovery:
                    result["rollback_status"] = type(recovery).__name__
            d.save(folder / "result.json", result)
            print(json.dumps(dict(status=result["status"], error_type=result["error_type"], record=str(folder), rollback=result.get("rollback_status"))), flush=True)
            raise


if __name__ == "__main__":
    main()
