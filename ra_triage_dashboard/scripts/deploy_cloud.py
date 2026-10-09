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
SENSITIVE_PATHS = (
    "ra_triage_dashboard/migrations",
    "ra_triage_dashboard/requirements.txt",
    "ra_triage_dashboard/requirements-runtime.txt",
    "ra_triage_dashboard/scripts/bootstrap_cloud_postgres.sh",
    "ra_triage_dashboard/scripts/migrate_cloud_postgres_data.sh",
)
POSTGRES_MIGRATION_PREFIX = "ra_triage_dashboard/migrations/postgres/"
RECORD_SCHEMA_VERSION = 2
RELEASE_ID_PATTERN = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}(?:-[0-9]{2})?")
MIGRATION_APPLY_CODE = """
from app.db import Database
from app.settings import Settings

settings = Settings.from_env()
database = Database(
    settings.database_url,
    postgres_migrations_dir=settings.postgres_migrations_dir,
    pool_size=2,
)
database.init()
with database.connect() as connection:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM dashboard_schema_migrations"
    ).fetchone()
print(int(row["count"]))
database.close()
"""

class DeployError(RuntimeError):
    pass

def require(condition, message):
    if not condition:
        raise DeployError(message)

def run(*args, cwd=REPO, **kw):
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True, **kw)

def git(*args, cwd=REPO):
    return run("git", *args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()

def validate_additive_migration_sql(path, content):
    statements = [
        statement.strip()
        for statement in re.sub(r"--[^\n]*", "", content).split(";")
        if statement.strip()
    ]
    require(statements and statements[0].upper() == "BEGIN", f"Migration must start with BEGIN: {path}")
    require(statements[-1].upper() == "COMMIT", f"Migration must end with COMMIT: {path}")
    for statement in statements[1:-1]:
        normalized = " ".join(statement.split()).upper()
        allowed = (
            normalized.startswith("ALTER TABLE ")
            and " ADD COLUMN IF NOT EXISTS " in f" {normalized} "
        ) or normalized.startswith("CREATE TABLE IF NOT EXISTS ") \
            or normalized.startswith("CREATE INDEX IF NOT EXISTS ") \
            or normalized.startswith("CREATE VIEW REVIEW_RECORDS AS ") \
            or normalized.startswith("CREATE VIEW REVIEW_RECORD_ATTACHMENTS AS ")
        require(allowed, f"Migration is not strictly additive: {path}")


def validate_schema_migration_sql(path, content):
    """Allow only the reviewed intent-label constraint expansion migration."""

    statements = [
        statement.strip()
        for statement in re.sub(r"--[^\n]*", "", content).split(";")
        if statement.strip()
    ]
    require(statements and statements[0].upper() == "BEGIN", f"Migration must start with BEGIN: {path}")
    require(statements[-1].upper() == "COMMIT", f"Migration must end with COMMIT: {path}")
    allowed_constraints = {
        "INTENT_LABEL_REVISIONS_LANE_CHANGE_DEFAULT_CHECK",
        "INTENT_FRAME_OVERRIDES_LANE_CHANGE_INTENT_CHECK",
    }
    for statement in statements[1:-1]:
        normalized = " ".join(statement.split()).upper()
        is_drop = " DROP CONSTRAINT IF EXISTS " in f" {normalized} "
        is_add = " ADD CONSTRAINT " in f" {normalized} " and " CHECK (" in f" {normalized} "
        require(is_drop or is_add, f"Migration is not an approved schema change: {path}")
        require(
            any(name in normalized for name in allowed_constraints),
            f"Migration targets an unapproved constraint: {path}",
        )

def migration_changes(old, sha, *, allow_additive=False, allow_schema=False):
    sensitive = git("diff", "--name-only", old, sha, "--", *SENSITIVE_PATHS).splitlines()
    if not sensitive:
        return []
    require(
        allow_additive or allow_schema,
        "Migration/runtime dependency changes require a separately planned deployment",
    )
    require(
        all(path.startswith(POSTGRES_MIGRATION_PREFIX) and path.endswith(".sql") for path in sensitive),
        "Additive migration mode only permits PostgreSQL migration files",
    )
    statuses = git("diff", "--name-status", old, sha, "--", *sensitive).splitlines()
    require(
        len(statuses) == len(sensitive)
        and all(line.startswith("A\t") for line in statuses),
        "Additive migration mode only permits newly added migration files",
    )
    for path in sensitive:
        content = git("show", f"{sha}:{path}")
        if allow_additive:
            try:
                validate_additive_migration_sql(path, content)
                continue
            except DeployError:
                pass
        require(allow_schema, f"Migration is not additive: {path}")
        validate_schema_migration_sql(path, content)
    return sensitive


def migration_mode(*, allow_additive=False, allow_schema=False):
    require(
        not (allow_additive and allow_schema),
        "Choose only one migration authorization mode",
    )
    if allow_schema:
        return "schema"
    if allow_additive:
        return "additive"
    return "none"

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

def apply_additive_migrations(candidate, env, migrations, record_dir, expected_count):
    migration_env = rebase_env(env, REPO, candidate)
    backup_script = candidate / "ra_triage_dashboard/scripts/backup_cloud_postgres.sh"
    verify_script = candidate / "ra_triage_dashboard/scripts/verify_cloud_postgres_backup.sh"
    backup_result = run(
        "bash", backup_script,
        cwd=candidate,
        env=migration_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
    )
    backup_lines = backup_result.stdout.decode().strip().splitlines()
    require(backup_lines, "PostgreSQL backup did not return a path")
    backup = Path(backup_lines[-1]).resolve()
    backup_root = (Path(env["DASHBOARD_DATA_DIR"]) / "postgres_backups").resolve()
    require(backup.parent == backup_root and backup.is_file(), "Backup path is outside the configured backup directory")
    with (record_dir / "backup-verify.log").open("w") as log:
        run(
            "bash", verify_script, backup,
            cwd=candidate,
            env=migration_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
    with (record_dir / "migration.log").open("w") as log:
        migrated = run(
            PYTHON, "-c", MIGRATION_APPLY_CODE,
            cwd=candidate / "ra_triage_dashboard",
            env=migration_env,
            stdout=subprocess.PIPE,
            stderr=log,
            timeout=120,
        )
    output = migrated.stdout.decode().strip().splitlines()
    require(output and output[-1].isdigit(), "Migration count verification failed")
    migration_count = int(output[-1])
    require(
        migration_count == expected_count + len(migrations),
        "Unexpected PostgreSQL migration count after apply",
    )
    return str(backup), migration_count

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
    # Process exit precedes tmux removing its wrapper/session; allow that bounded lag.
    session_deadline = time.monotonic() + 5
    while subprocess.run(["tmux", "has-session", "-t", "=" + SESSION], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        if time.monotonic() >= session_deadline:
            raise DeployError("Dashboard tmux session did not exit")
        time.sleep(0.1)

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
        try:
            obj = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if obj.get("status") == "success":
            records.append((path.parent, obj))
    keep = {p for p, _ in sorted(records, reverse=True)[:2]} | {current}
    removed = []
    for folder, obj in records:
        if folder in keep:
            continue
        for key in ("candidate", "rollback"):
            value = obj.get(key)
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            if path != folder / key or not path.exists() or in_use(path):
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
        has_owned_worktree_record = all(
            isinstance(obj.get(key), str)
            and Path(obj[key]) == folder / key
            for key in ("candidate", "rollback")
        )
        if has_owned_worktree_record and all(not Path(obj[k]).exists() for k in ("candidate", "rollback")) and data.is_dir() and not data.is_symlink() and not in_use(data):
            shutil.rmtree(data)
        # Small result records and logs remain for diagnosis.
    return removed


def preflight(
    sha,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
):
    require(sys.platform == "linux" and REPO.is_dir() and PYTHON.is_file(), "Run on the configured cloud_server")
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "Supply a full 40-character pushed commit SHA")
    mode = migration_mode(
        allow_additive=allow_additive_migrations,
        allow_schema=allow_schema_migrations,
    )
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
    migrations = migration_changes(
        old,
        sha,
        allow_additive=allow_additive_migrations,
        allow_schema=allow_schema_migrations,
    )
    migration_count_before = None
    if migrations:
        status = get_json(8785, "api/status")
        migration_count_before = status.get("database", {}).get("migration_count")
        require(
            isinstance(migration_count_before, int),
            "Production migration count is unavailable",
        )
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 8786))
        except OSError:
            raise DeployError("8786 is occupied; preserve the existing gray session") from None
    return {
        "pid": pid,
        "env": env,
        "before": before,
        "old": old,
        "migrations": migrations,
        "migration_count_before": migration_count_before,
        "migration_mode": mode,
    }


def check_release(
    sha,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
):
    with deployment_lock(STATE):
        state = preflight(
            sha,
            allow_additive_migrations,
            allow_schema_migrations,
        )
        print(json.dumps({
            "preflight": "ok",
            "target": sha,
            "live": state["old"],
            "migrations": state["migrations"],
            "additive_migrations": state["migrations"],
            "migration_mode": state["migration_mode"],
        }))


def create_release_folder(sha):
    base = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + sha[:12]
    releases = STATE / "releases"
    releases.mkdir(mode=0o700, parents=True, exist_ok=True)
    for index in range(100):
        release_id = base if index == 0 else f"{base}-{index:02d}"
        folder = releases / release_id
        try:
            folder.mkdir(mode=0o700)
            return release_id, folder
        except FileExistsError:
            continue
    raise DeployError("Unable to allocate a unique release record")


def prepare_release(
    sha,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
):
    with deployment_lock(STATE):
        state = preflight(
            sha,
            allow_additive_migrations,
            allow_schema_migrations,
        )
        pid = state["pid"]
        env = state["env"]
        before = state["before"]
        old = state["old"]
        migrations = state["migrations"]
        migration_count_before = state["migration_count_before"]
        stamp, folder = create_release_folder(sha)
        candidate, rollback, data = folder / "candidate", folder / "rollback", folder / "gray-data"
        result = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "status": "preparing",
            "target": sha,
            "previous": old,
            "candidate": str(candidate),
            "rollback": str(rollback),
            "additive_migrations": migrations,
            "migration_mode": state["migration_mode"],
        }
        save(folder / "result.json", result)
        gray = None
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
            save(folder / "production-before.json", {
                "app": str(REPO / "ra_triage_dashboard"),
                "env": env,
                "sha": old,
                "pid": pid,
                "policy": policy(before),
                "migration_count": migration_count_before,
            })
            result.update(
                status="prepared",
                prepared_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                policy=policy(before),
                migration_count_before=migration_count_before,
            )
            save(folder / "result.json", result)
            print(json.dumps({
                "status": "prepared",
                "target": sha,
                "release_id": stamp,
                "record": str(folder / "result.json"),
            }))
            return stamp
        except BaseException as exc:
            stop_child(gray)
            result.update(status="failed", error_type=type(exc).__name__)
            save(folder / "result.json", result)
            print("Preparation failed; record: " + str(folder / "result.json"), file=sys.stderr)
            raise


def load_prepared_release(release_id):
    require(
        isinstance(release_id, str) and RELEASE_ID_PATTERN.fullmatch(release_id),
        "Invalid prepared release id",
    )
    folder = STATE / "releases" / release_id
    require(folder.is_dir() and not folder.is_symlink(), "Prepared release does not exist")
    result_path = folder / "result.json"
    recovery_path = folder / "production-before.json"
    for path in (result_path, recovery_path):
        require(path.is_file() and not path.is_symlink(), "Prepared release record is unavailable")
        status = path.stat()
        require(
            status.st_uid == os.getuid() and status.st_mode & 0o077 == 0,
            "Prepared release record permissions are unsafe",
        )
    try:
        result = json.loads(result_path.read_text())
        recovery = json.loads(recovery_path.read_text())
    except (OSError, ValueError) as exc:
        raise DeployError("Prepared release record is unreadable") from exc
    require(result.get("schema_version") == RECORD_SCHEMA_VERSION, "Prepared release record version is unsupported")
    require(result.get("status") == "prepared", "Release is not ready for promotion")
    for key in ("candidate", "rollback"):
        require(Path(result.get(key, "")) == folder / key, "Prepared release path is not owned by its record")
    return folder, result, recovery


def validate_prepared_worktree(path, sha):
    require(path.is_dir() and not path.is_symlink(), "Prepared worktree is unavailable")
    require(git("rev-parse", "HEAD", cwd=path) == sha, "Prepared worktree SHA changed")
    require(not git("status", "--porcelain", cwd=path), "Prepared worktree has local changes")


def promote_release(
    release_id,
    sha=None,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
):
    with deployment_lock(STATE):
        folder, result, recovery = load_prepared_release(release_id)
        target = result.get("target", "")
        if sha is not None:
            require(sha == target, "Prepared release target differs from requested SHA")
        requested_mode = migration_mode(
            allow_additive=allow_additive_migrations,
            allow_schema=allow_schema_migrations,
        )
        require(result.get("migration_mode", "none") == requested_mode, "Promotion requires the same migration authorization mode used during prepare")
        state = preflight(
            target,
            allow_additive_migrations,
            allow_schema_migrations,
        )
        pid = state["pid"]
        env = state["env"]
        before = state["before"]
        old = state["old"]
        migrations = state["migrations"]
        migration_count_before = state["migration_count_before"]
        require(old == result.get("previous") == recovery.get("sha"), "Production SHA changed after prepare")
        require(pid == recovery.get("pid") and env == recovery.get("env"), "Production process or environment changed after prepare")
        require(policy(before) == recovery.get("policy") == result.get("policy"), "Production access/writer policy changed after prepare")
        require(migrations == result.get("additive_migrations"), "Migration set changed after prepare")
        require(migration_count_before == recovery.get("migration_count") == result.get("migration_count_before"), "Production migration count changed after prepare")
        candidate = folder / "candidate"
        rollback = folder / "rollback"
        validate_prepared_worktree(candidate, target)
        validate_prepared_worktree(rollback, old)
        replacement_pid = None
        production_stop_attempted = False
        result["status"] = "promoting"
        save(folder / "result.json", result)
        try:
            print("Prepared gray passed; promoting exact SHA", flush=True)
            production_stop_attempted = True
            stop_production(pid)
            if migrations:
                backup, migration_count = apply_additive_migrations(
                    candidate,
                    env,
                    migrations,
                    folder,
                    migration_count_before,
                )
                result.update(
                    backup=backup,
                    migration_count_after=migration_count,
                )
                save(folder / "result.json", result)
            run("git", "merge", "--ff-only", target)
            start_production(folder, REPO / "ra_triage_dashboard", env, target, "production")
            replacement_pid = git_pane_pid()
            after = smoke(8785, target, "postgresql")
            require(policy(after) == policy(before), "Runtime access/writer policy changed")
            result.update(
                status="success",
                policy=policy(after),
                promoted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            save(folder / "result.json", result)
            try:
                result["cleaned_worktrees"] = cleanup(STATE, folder)
            except Exception as exc:
                result["cleanup_warning"] = type(exc).__name__
            save(folder / "result.json", result)
            print(json.dumps({"status": "success", "target": target, "release_id": release_id, "record": str(folder / "result.json")}))
        except BaseException as exc:
            result.update(status="failed", error_type=type(exc).__name__)
            if production_stop_attempted and not process_alive(pid):
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


def deploy(
    sha,
    check_only=False,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
):
    if check_only:
        return check_release(
            sha,
            allow_additive_migrations,
            allow_schema_migrations,
        )
    release_id = prepare_release(
        sha,
        allow_additive_migrations,
        allow_schema_migrations,
    )
    return promote_release(
        release_id,
        sha,
        allow_additive_migrations,
        allow_schema_migrations,
    )

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="preflight only, without service/worktree changes")
    action.add_argument("--prepare", action="store_true", help="run tests and isolated gray, then stop before production changes")
    action.add_argument("--promote", metavar="RELEASE_ID", help="promote a previously prepared release")
    action.add_argument("--serve", help=argparse.SUPPRESS)
    migration = parser.add_mutually_exclusive_group()
    migration.add_argument(
        "--allow-additive-migrations",
        action="store_true",
        help="permit new strictly additive PostgreSQL migrations with backup verification",
    )
    migration.add_argument(
        "--allow-schema-migrations",
        action="store_true",
        help="permit the reviewed intent lane-change constraint migration with backup verification",
    )
    args = parser.parse_args()
    if args.serve:
        serve(args.serve)
    elif args.promote:
        promote_release(
            args.promote,
            args.sha,
            args.allow_additive_migrations,
            args.allow_schema_migrations,
        )
    else:
        require(args.sha, "--sha is required")
        if args.prepare:
            prepare_release(
                args.sha,
                args.allow_additive_migrations,
                args.allow_schema_migrations,
            )
        else:
            deploy(
                args.sha,
                args.check,
                args.allow_additive_migrations,
                args.allow_schema_migrations,
            )

if __name__ == "__main__":
    try:
        main()
    except (DeployError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Do not expose subprocess environment or credential-bearing output.
        print(str(exc) if isinstance(exc, DeployError) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
