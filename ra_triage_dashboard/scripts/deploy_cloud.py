#!/usr/bin/env python3
"""Deploy an exact pushed Dashboard commit on cloud_server; see docs/deployment.md."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

REPO = Path("/volume/home/workspace/ra_tools")
STATE = Path("/volume/home/workspace/ra_triage_dashboard_deploy")
PYTHON = Path("/volume/home/workspace/ra_triage_dashboard_venv/bin/python3")
SESSION = "ra_triage_dashboard"
PREFIXES = ("DASHBOARD_", "ARES_", "CAMERA_", "RA_AUTO_TRIAGE_")
BASE_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "NO_PROXY", "no_proxy"}
OFF = ("DASHBOARD_SYNC_TRAIL_ON_START", "DASHBOARD_BATCH_PREDICTION_ENABLED",
       "DASHBOARD_AUTOTRIAGE_PUSH_ENABLED", "DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED",
       "DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED", "DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED")

class DeployError(RuntimeError):
    pass

def require(condition, message):
    if not condition:
        raise DeployError(message)

def run(*args, cwd=REPO, **kw):
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True, **kw)

def git(*args, cwd=REPO):
    return run("git", *args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

def save(path, obj):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(obj, stream, indent=2, ensure_ascii=False)
    os.replace(temp, path)

def get_json(port, route):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/{route}", timeout=10) as response:
        return json.load(response)

def read_live():
    matches = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if b"uvicorn" in args and b"8785" in args:
                env = dict(x.split("=", 1) for x in (proc / "environ").read_bytes().decode().split("\0") if "=" in x)
                matches.append((int(proc.name), env, (proc / "cwd").resolve()))
        except (OSError, ValueError):
            continue
    require(len(matches) == 1, "Expected exactly one owned Dashboard uvicorn on 8785")
    pid, env, cwd = matches[0]
    pane = git_pane_pid()
    require(pid == pane, "Dashboard must be the sole foreground process in its tmux pane")
    require(cwd == REPO / "ra_triage_dashboard", "Live process uses another checkout; reconcile before deploying")
    return pid, capture_env(env)

def git_pane_pid():
    value = run("tmux", "list-panes", "-t", "=" + SESSION, "-F", "#{pane_pid}", stdout=subprocess.PIPE).stdout.decode().splitlines()
    require(len(value) == 1, "Expected one Dashboard tmux pane")
    return int(value[0])

def capture_env(env):
    result = {k: v for k, v in env.items() if k.startswith(PREFIXES) or k in BASE_KEYS}
    for key, value in result.items():
        if value and (key == "DASHBOARD_DATABASE_URL" or
                      (re.search(r"(?:SECRET|PASSWORD|TOKEN|API_KEY)$", key) and not key.endswith("_FILE"))):
            raise DeployError("Inline credential configuration is unsupported; use credential files")
    require(result.get("DASHBOARD_DATABASE_URL_FILE"), "Production must use a database URL file")
    return result

def rebase_env(env, old, new):
    old, new = str(old), str(new)
    return {k: new + v[len(old):] if v.startswith(old + "/") else v for k, v in env.items()}

def gray_env(env, candidate, data, sha):
    result = rebase_env(env, REPO, candidate)
    result.update({key: "false" for key in OFF})
    result.update(DASHBOARD_DATA_DIR=str(data), DASHBOARD_DATABASE_URL="sqlite:///" + str(data / "triage.sqlite3"),
                  DASHBOARD_DATABASE_URL_FILE="", DASHBOARD_POSTGRES_PERSISTENT_DATA="false",
                  DASHBOARD_BUILD_COMMIT=sha, DASHBOARD_PORT="8786", DASHBOARD_HOST="127.0.0.1",
                  DASHBOARD_BATCH_BAG_CACHE_DIR=str(data / "batch_bags"),
                  DASHBOARD_BOOTSTRAP_MODEL_JSON="", DASHBOARD_DCHAT_CREDENTIALS_FILE="",
                  DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE="", DASHBOARD_DEPLOYMENT_MODE="production",
                  DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS="false")
    return result

def check_health(health, sha, storage):
    require(health.get("ok") is True, "Health is not OK")
    require(health.get("build_commit") == sha, "Running SHA differs from target")
    backend = {"sqlite-mvp": "sqlite"}.get(health.get("storage"), health.get("storage"))
    require(backend == storage, "Unexpected database backend")
    if storage == "sqlite":
        for key in ("trail_attribute_write_enabled", "trail_attribute_review_write_enabled",
                    "batch_prediction_enabled", "autotriage_push_enabled"):
            require(health.get(key) is False, "Gray writer is not disabled: " + key)

def wait_health(port, sha, storage, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            health = get_json(port, "health")
            check_health(health, sha, storage)
            return health
        except (OSError, ValueError, DeployError):
            time.sleep(1)
    raise DeployError(f"Health gate failed on port {port}; inspect release log")

def policy(health):
    keys = ("base_path", "deployment_mode", "trail_attribute_write_enabled",
            "trail_attribute_review_write_enabled", "batch_prediction_enabled", "autotriage_push_enabled")
    return {k: health.get(k) for k in keys}

def smoke(port, sha, storage):
    health = wait_health(port, sha, storage)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for route in ("", "api/import-contract", "api/change-revision"):
        with opener.open(f"http://127.0.0.1:{port}/{route}", timeout=15) as response:
            require(response.status == 200, "Smoke route failed")
    if storage == "postgresql":
        status = get_json(port, "api/status")
        require(status.get("database", {}).get("ok") is True, "Database health failed")
        require(status["database"].get("persistent_data") is True, "Database is not persistent")
        require(status.get("overall", {}).get("status") == "healthy", "Production status is degraded")
    return health

def stop_child(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)

@contextlib.contextmanager
def deployment_lock(state):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeployError("Another deployment holds the lock") from None
        yield

def serve(config):
    path = Path(config)
    require(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0, "Unsafe runtime config permissions")
    data = json.loads(path.read_text())
    app = Path(data["app"])
    os.chdir(app)
    os.execve("/bin/bash", ["bash", str(app / "scripts/run_cloud_server.sh")], data["env"])

def start_production(record_dir, app, env, sha, name):
    env = dict(env, DASHBOARD_BUILD_COMMIT=sha)
    config = record_dir / (name + "-env.json")
    save(config, {"app": str(app), "env": env})
    launcher = record_dir / "launcher.py"
    if not launcher.exists():
        shutil.copyfile(__file__, launcher)
    command = shlex.join([str(PYTHON), str(launcher), "--serve", str(config)])
    command += " >> " + shlex.quote(str(record_dir / (name + ".log"))) + " 2>&1"
    run("tmux", "new-session", "-d", "-s", SESSION, command)

def process_alive(pid):
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
        # Container init may leave exited uvicorn children unreaped indefinitely.
        return status.rsplit(") ", 1)[1].split()[0] not in {"Z", "X"}
    except FileNotFoundError:
        return False


def stop_production(pid):
    require(git_pane_pid() == pid, "Production process changed during validation")
    os.kill(pid, signal.SIGTERM)
    end = time.monotonic() + 30
    while process_alive(pid) and time.monotonic() < end:
        time.sleep(0.2)
    require(not process_alive(pid), "Production did not stop gracefully")
    # tmux normally removes the empty session automatically.
    if subprocess.run(["tmux", "has-session", "-t", "=" + SESSION], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise DeployError("Dashboard tmux session did not exit")

def in_use(path):
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            values = [os.readlink(proc / "cwd"), (proc / "cmdline").read_bytes().decode(errors="replace")]
            for fd in (proc / "fd").iterdir():
                try:
                    values.append(os.readlink(fd))
                except OSError:
                    pass
            if any(str(path) in value for value in values):
                return True
        except OSError:
            pass
    return False

def cleanup(state, current):
    """Only own successful releases; failed/unknown releases require manual inspection."""
    records = []
    for path in (state / "releases").glob("*/result.json"):
        obj = json.loads(path.read_text())
        if obj.get("status") == "success":
            records.append((path.parent, obj))
    keep = {p for p, _ in sorted(records, reverse=True)[:2]} | {current}
    removed = []
    for folder, obj in records:
        if folder in keep:
            continue
        for key in ("candidate", "rollback"):
            path = Path(obj[key])
            if path.parent != folder or not path.exists() or in_use(path):
                continue
            if git("status", "--porcelain", cwd=path):
                continue
            ignored = git("ls-files", "--others", "--ignored", "--exclude-standard", cwd=path).splitlines()
            if any(not ({"__pycache__", ".pytest_cache"} & set(Path(x).parts)) for x in ignored):
                continue
            run("git", "worktree", "remove", str(path))
            removed.append(str(path))
        # Only our old successful, no-longer-running isolated data can expire.
        data = folder / "gray-data"
        if all(not Path(obj[k]).exists() for k in ("candidate", "rollback")) and data.is_dir() and not data.is_symlink() and not in_use(data):
            shutil.rmtree(data)
        # Small result records and logs remain for diagnosis.
    return removed

def deploy(sha, check_only=False):
    require(sys.platform == "linux" and REPO.is_dir() and PYTHON.is_file(), "Run on the configured cloud_server")
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "Supply a full 40-character pushed commit SHA")
    with deployment_lock(STATE):
        run("git", "fetch", "origin", "master")
        require(git("branch", "--show-current") == "master", "Production checkout must be on master")
        require(not git("status", "--porcelain"), "Production checkout has local changes")
        require(git("rev-parse", "origin/master") == sha, "Target is not current origin/master")
        run("git", "merge-base", "--is-ancestor", "HEAD", sha)
        pid, env = read_live()
        before = get_json(8785, "health")
        old = before.get("build_commit", "")
        require(re.fullmatch(r"[0-9a-f]{40}", old), "Live build SHA is unavailable")
        check_health(before, old, "postgresql")
        sensitive = git("diff", "--name-only", old, sha, "--", "ra_triage_dashboard/migrations", "ra_triage_dashboard/requirements.txt", "ra_triage_dashboard/requirements-runtime.txt", "ra_triage_dashboard/scripts/bootstrap_cloud_postgres.sh", "ra_triage_dashboard/scripts/migrate_cloud_postgres_data.sh")
        require(not sensitive, "Migration/runtime dependency changes require a separately planned deployment")
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", 8786))
            except OSError:
                raise DeployError("8786 is occupied; preserve the existing gray session") from None
        if check_only:
            print(json.dumps({"preflight": "ok", "target": sha, "live": old}))
            return
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + sha[:12]
        folder = STATE / "releases" / stamp
        folder.mkdir(parents=True, mode=0o700)
        candidate, rollback, data = folder / "candidate", folder / "rollback", folder / "gray-data"
        result = {"status": "running", "target": sha, "previous": old, "candidate": str(candidate), "rollback": str(rollback)}
        save(folder / "result.json", result)
        gray = None
        switched = False
        replacement_pid = None
        try:
            run("git", "worktree", "add", "--detach", candidate, sha)
            run("git", "worktree", "add", "--detach", rollback, old)
            data.mkdir(mode=0o700)
            media = Path(env["DASHBOARD_DATA_DIR"]) / "media_layouts"
            if media.is_dir():
                (data / "media_layouts").symlink_to(media, target_is_directory=True)
            test_env = gray_env(env, candidate, data, sha)
            print("Running complete cloud test suite", flush=True)
            with (folder / "tests.log").open("w") as log:
                run(PYTHON, "-m", "pytest", "ra_triage_dashboard/tests", "-q", cwd=candidate, env=dict(test_env, DASHBOARD_BASE_PATH=""), stdout=log, stderr=subprocess.STDOUT, timeout=600)
            with (folder / "gray.log").open("w") as log:
                gray = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", str(candidate / "ra_triage_dashboard"), "--host", "127.0.0.1", "--port", "8786"], cwd=candidate, env=test_env, stdout=log, stderr=subprocess.STDOUT)
            smoke(8786, sha, "sqlite")
            stop_child(gray)
            require(git("rev-parse", "origin/master") == sha and not git("status", "--porcelain"), "Checkout changed during gray")
            now_pid, now_env = read_live()
            require(now_pid == pid and now_env == env, "Runtime changed during gray")
            print("Gray passed; promoting exact SHA", flush=True)
            save(folder / "production-before.json", {"app": str(REPO / "ra_triage_dashboard"), "env": env, "sha": old})
            run("git", "merge", "--ff-only", sha)
            switched = True
            stop_production(pid)
            start_production(folder, REPO / "ra_triage_dashboard", env, sha, "production")
            replacement_pid = git_pane_pid()
            after = smoke(8785, sha, "postgresql")
            require(policy(after) == policy(before), "Runtime access/writer policy changed")
            result.update(status="success", policy=policy(after))
            save(folder / "result.json", result)
            try:
                result["cleaned_worktrees"] = cleanup(STATE, folder)
            except Exception as exc:
                result["cleanup_warning"] = type(exc).__name__
            save(folder / "result.json", result)
            print(json.dumps({"status": "success", "target": sha, "record": str(folder / "result.json")}))
        except BaseException as exc:
            stop_child(gray)
            result.update(status="failed", error_type=type(exc).__name__)
            if switched and not process_alive(pid):
                try:
                    if replacement_pid is not None:
                        stop_production(replacement_pid)
                except (DeployError, subprocess.CalledProcessError):
                    pass
                try:
                    start_production(folder, rollback / "ra_triage_dashboard", rebase_env(env, REPO, rollback), old, "rollback")
                    smoke(8785, old, "postgresql")
                    result["rollback_status"] = "healthy"
                except Exception as rollback_error:
                    result["rollback_status"] = type(rollback_error).__name__
            save(folder / "result.json", result)
            print("Deployment failed; record: " + str(folder / "result.json"), file=sys.stderr)
            raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha")
    parser.add_argument("--check", action="store_true", help="preflight only, without service/worktree changes")
    parser.add_argument("--serve", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve)
    else:
        require(args.sha, "--sha is required")
        deploy(args.sha, args.check)

if __name__ == "__main__":
    try:
        main()
    except (DeployError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Do not expose subprocess environment or credential-bearing output.
        print(str(exc) if isinstance(exc, DeployError) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
