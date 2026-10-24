#!/usr/bin/env python3
"""Scoped visual-history release and explicitly authorized admin restore activation.

Run with the cloud Dashboard interpreter and --sha equal to pushed origin/master.
Uses versioned deploy_cloud gates; no schema change or data replay is permitted.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

OLD = "961376d3f7ae19068c2c26286891f80290729405"
OLD_ROOT = Path("/volume/home/workspace/ra_triage_dashboard_deploy/releases/20261024T195327Z-961376d3f7ae/candidate")
REPO = Path("/volume/home/workspace/ra_tools")
PORT = 18789


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
        d.require(not d.migration_changes(OLD, sha), "Schema/dependency changes are not allowed")
        canonical = d.git("status", "--porcelain")
        canonical_sha = d.git("rev-parse", "HEAD")
        pid, app, env = live()
        d.require(app == OLD_ROOT / "ra_triage_dashboard", "Unexpected live directory")
        d.require(d.git("rev-parse", "HEAD", cwd=OLD_ROOT) == OLD and not d.git("status", "--porcelain", cwd=OLD_ROOT), "Original release changed")
        before = d.smoke(8785, OLD, "postgresql")
        d.require(d.get_json(8785, "api/status")["database"]["migration_count"] == 57, "Unexpected original schema")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", PORT))
        release_id, folder = d.create_release_folder(sha)
        candidate, rollback, data = folder / "candidate", folder / "rollback", folder / "gray-data"
        result = dict(status="preparing", target=sha, previous=OLD, candidate=str(candidate), rollback=str(rollback),
                      gray_port=PORT, canonical_sha_preserved=canonical_sha, record=str(folder),
                      migration_mode="none", migration_count=57, rollback_enabled=True)
        d.save(folder / "result.json", result)
        shutil.copyfile(__file__, folder / "isolated-deploy.py")
        d.save(folder / "production-before.json", dict(app=str(app), env=env, sha=OLD, pid=pid, policy=d.policy(before), migration_count=57))
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
            d.require(d.get_json(8785, "api/status")["database"]["migration_count"] == 57, "Schema changed during validation")
            next_env = d.rebase_env(d.rebase_env(env, REPO, candidate), OLD_ROOT, candidate)
            next_env["DASHBOARD_TRAIL_ROLLBACK_ENABLED"] = "true"
            for key in ("DASHBOARD_DATA_DIR", "DASHBOARD_DATABASE_URL_FILE", "DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE", "DASHBOARD_DCHAT_CREDENTIALS_FILE"):
                d.require(next_env.get(key) == env.get(key), "Persistent configuration changed: " + key)
            result["status"] = "promoting"
            d.save(folder / "result.json", result)
            print("Gray passed; switching UI and enabling admin-only restore", flush=True)
            stopped = True
            d.stop_production(pid)
            d.start_production(folder, candidate / "ra_triage_dashboard", next_env, sha, "production")
            replacement = d.git_pane_pid()
            after = d.smoke(8785, sha, "postgresql")
            d.require(d.policy(after) == d.policy(before), "Existing runtime policy changed")
            d.require(d.get_json(8785, "api/status")["database"]["migration_count"] == 57, "Schema verification failed")
            for key in ("gt_sync", "review_notifications"):
                d.require(after.get(key, {}).get("enabled") == before.get(key, {}).get("enabled"), "Service flag changed: " + key)
            audit = d.get_json(8785, "api/trail-history")
            d.require(audit["can_restore"] is False, "Unverified caller gained restore permission")
            d.require(live()[2].get("DASHBOARD_TRAIL_ROLLBACK_ENABLED") == "true", "Restore gate not enabled")
            # No credentials and no existing operation: assert server rejection without business writes.
            import urllib.request, urllib.error
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for action in ("verify", "restore-preview", "restore-commit"):
                request = urllib.request.Request("http://127.0.0.1:8785/api/trail-history/unauthorized-release-check/" + action,
                    data=b"{}", headers={"Content-Type": "application/json", "X-RA-Triage-Request": "browser-v1"}, method="POST")
                try:
                    opener.open(request, timeout=10)
                except urllib.error.HTTPError as error:
                    d.require(error.code == 403, "Unexpected unauthorized restore response")
                else:
                    raise d.DeployError("Unverified restore request was not rejected")
            result["unauthorized_routes_rejected"] = 3
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
