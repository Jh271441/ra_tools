#!/usr/bin/env python3
"""Deploy an exact pushed Dashboard commit on cloud_server; see docs/deployment.md."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
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
import urllib.error
import urllib.request

REPO = Path("/volume/home/workspace/ra_tools")
STATE = Path("/volume/home/workspace/ra_triage_dashboard_deploy")
PYTHON = Path("/volume/home/workspace/ra_triage_dashboard_venv/bin/python3")
SESSION = "ra_triage_dashboard"
NGINX_SESSION = "ra_triage_dashboard_nginx"
NGINX_BIN = Path("/usr/sbin/nginx")
PUBLIC_PORT = 8785
BLUEGREEN_SLOTS = {"blue": 18791, "green": 18792}
DEFAULT_GRAY_PORT = 19786
PREFIXES = ("DASHBOARD_", "ARES_", "CAMERA_", "RA_AUTO_TRIAGE_")
BASE_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "NO_PROXY", "no_proxy"}
OFF = ("DASHBOARD_SYNC_TRAIL_ON_START", "DASHBOARD_BATCH_PREDICTION_ENABLED",
       "DASHBOARD_AUTOTRIAGE_PUSH_ENABLED", "DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED",
       "DASHBOARD_TRAIL_RD_WRITE_ENABLED", "DASHBOARD_HUMAN_LABEL_WRITE_ENABLED",
       "DASHBOARD_TRAIL_TE_WRITE_ENABLED",
       "DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED", "DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED")
SENSITIVE_PATHS = (
    "ra_triage_dashboard/migrations",
    "ra_triage_dashboard/requirements.txt",
    "ra_triage_dashboard/requirements-runtime.txt",
    "ra_triage_dashboard/scripts/bootstrap_cloud_postgres.sh",
    "ra_triage_dashboard/scripts/migrate_cloud_postgres_data.sh",
)
POSTGRES_MIGRATION_PREFIX = "ra_triage_dashboard/migrations/postgres/"
# Unique indexes and transactional event triggers require exact reviewed files;
# generic additive SQL continues to reject arbitrary constraints and functions.
REVIEWED_ADDITIVE_MIGRATIONS = {
    "ra_triage_dashboard/migrations/postgres/060_comment_submission_ids.sql":
        "fae1928d683098cbef62be2f733f129b526543164aa4f490efc9beb945956b6d",
    "ra_triage_dashboard/migrations/postgres/061_human_label_publication.sql":
        "646f328dd24db468f33e2221d5e7de993a4945d40de01e1260c2fef70e4460bd",
    "ra_triage_dashboard/migrations/postgres/065_labeling_idempotency_keys.sql":
        "9451a3fd80e008ab72a537ef1c5098bddc0d443501c2337aa29c80983554d86d",
}
RECORD_SCHEMA_VERSION = 2
RELEASE_ID_PATTERN = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}(?:-[0-9]{2})?")
MIGRATION_LIST_CODE = """
import json
import psycopg
from app.settings import Settings

settings = Settings.from_env()
with psycopg.connect(settings.database_url) as connection:
    rows = connection.execute(
        "SELECT version FROM dashboard_schema_migrations ORDER BY version"
    ).fetchall()
versions = [str(row[0]) for row in rows]
print(json.dumps({"count": len(versions), "versions": versions}))
"""

RUNNING_BATCH_CHECK_CODE = """
import json
import psycopg
from app.settings import Settings

settings = Settings.from_env()
with psycopg.connect(settings.database_url) as connection:
    row = connection.execute(
        "SELECT COUNT(*) FROM batch_prediction_jobs "
        "WHERE status IN ('queued', 'running') OR publish_status = 'running'"
    ).fetchone()
print(json.dumps({"running": int(row[0] if row else 0)}))
"""

MIGRATION_APPLY_CODE = """
import json
from app.db import Database
from app.settings import Settings

settings = Settings.from_env()
database = Database(
    settings.database_url,
    postgres_migrations_dir=settings.postgres_migrations_dir,
    pool_size=2,
)
try:
    versions = database.apply_postgres_migrations()
finally:
    database.close()
print(json.dumps({"count": len(versions), "versions": versions}))
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
    reviewed_digest = REVIEWED_ADDITIVE_MIGRATIONS.get(path)
    if reviewed_digest and hashlib.sha256(content.strip().encode()).hexdigest() == reviewed_digest:
        return
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

def save_text(path, text, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(temp, path)


def slot_session(slot):
    require(slot in BLUEGREEN_SLOTS, f"Unknown blue-green slot: {slot}")
    return f"{SESSION}_{slot}"


def other_slot(slot):
    require(slot in BLUEGREEN_SLOTS, f"Unknown blue-green slot: {slot}")
    return "green" if slot == "blue" else "blue"


def nginx_binary():
    if NGINX_BIN.is_file() and os.access(NGINX_BIN, os.X_OK):
        return str(NGINX_BIN)
    found = shutil.which("nginx")
    require(bool(found), "nginx binary is unavailable on this host")
    return found


def nginx_dir(state=None):
    return Path(state or STATE) / "nginx"


def render_upstream_conf(port):
    require(isinstance(port, int) and 1024 <= port <= 65535, "Invalid upstream port")
    return (
        "upstream ra_triage_active {\n"
        f"    server 127.0.0.1:{port} max_fails=0;\n"
        "    keepalive 32;\n"
        "}\n"
    )


def render_maintenance_writes_conf(enabled=False, retry_after=15):
    mode = enabled
    if mode is True:
        mode = "all"
    elif mode is False or mode in ("", "off", None):
        return "# Maintenance write guard disabled\n"
    require(mode in {"all", "batch"}, f"Unsupported maintenance write guard mode: {mode}")
    retry = max(1, int(retry_after))
    if mode == "batch":
        uri_pattern = "^/(?:manual/)?api/prediction-batches(?:/|$|\\?)"
        payload = (
            '{"detail":"系统正在切换 Batch 执行槽位，暂不支持提交或推送 Batch 任务，请稍后重试。'
            ' / System is switching Batch worker slots; Batch submissions and pushes are briefly paused.'
            f' Please retry shortly.","maintenance":true,"scope":"batch","retry_after":{retry}}}'
        )
    else:
        uri_pattern = "^/(?:manual/)?api/"
        payload = (
            '{"detail":"系统正在维护升级，暂不支持写入，您的草稿已保留，请稍后重试。'
            ' / System is under maintenance; writes are paused and your draft is preserved.'
            f' Please retry shortly.","maintenance":true,"retry_after":{retry}}}'
        )
    return (
        f"# Maintenance write guard enabled ({mode})\n"
        "set $ra_maint_block 0;\n"
        f'if ($request_uri ~* "{uri_pattern}") {{ set $ra_maint_block 1; }}\n'
        'if ($request_method ~* "^(GET|HEAD|OPTIONS)$") { set $ra_maint_block 0; }\n'
        "if ($ra_maint_block = 1) { return 503; }\n"
        "error_page 503 = @ra_maint_503;\n"
        "location @ra_maint_503 {\n"
        "    default_type application/json;\n"
        f"    add_header Retry-After {retry} always;\n"
        '    add_header Cache-Control "no-store" always;\n'
        f"    return 503 '{payload}';\n"
        "}\n"
    )


def render_nginx_conf(nginx_root, public_port=PUBLIC_PORT):
    root = Path(nginx_root)
    mime_include = "    include /etc/nginx/mime.types;\n" if Path("/etc/nginx/mime.types").is_file() else ""
    return (
        "worker_processes 1;\n"
        "worker_shutdown_timeout 180s;\n"
        f"pid {root / 'nginx.pid'};\n"
        f"error_log {root / 'nginx-error.log'} warn;\n"
        "events { worker_connections 2048; }\n"
        "http {\n"
        f"{mime_include}"
        "    default_type application/octet-stream;\n"
        "    log_format ra_triage_bluegreen "
        "'$remote_addr - [$time_local] \"$request_method $uri $server_protocol\" "
        "$status $body_bytes_sent $request_time upstream=$upstream_addr:$upstream_status';\n"
        f"    access_log {root / 'nginx-access.log'} ra_triage_bluegreen;\n"
        "    sendfile on;\n"
        "    tcp_nopush on;\n"
        "    keepalive_timeout 65;\n"
        "    client_max_body_size 128m;\n"
        f"    client_body_temp_path {root / 'client_temp'};\n"
        f"    proxy_temp_path {root / 'proxy_temp'};\n"
        f"    fastcgi_temp_path {root / 'fastcgi_temp'};\n"
        f"    uwsgi_temp_path {root / 'uwsgi_temp'};\n"
        f"    scgi_temp_path {root / 'scgi_temp'};\n"
        f"    include {root / 'active_upstream.conf'};\n"
        "    server {\n"
        f"        listen 0.0.0.0:{public_port};\n"
        "        server_name _;\n"
        "        absolute_redirect off;\n"
        "        proxy_http_version 1.1;\n"
        '        proxy_set_header Connection "";\n'
        "        proxy_set_header Host $http_host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_pass_request_headers on;\n"
        "        proxy_next_upstream off;\n"
        "        proxy_connect_timeout 5s;\n"
        "        proxy_read_timeout 180s;\n"
        "        proxy_send_timeout 180s;\n"
        f"        include {root / 'maintenance_writes.conf'};\n"
        "        location ~ ^/(?:manual/)?api/(?:cases/[^/]+/video|intent-datasets/[^/]+/assets) {\n"
        "            proxy_buffering off;\n"
        "            proxy_pass http://ra_triage_active;\n"
        "        }\n"
        "        location / {\n"
        "            proxy_pass http://ra_triage_active;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def ensure_nginx_layout(state, active_port, *, public_port=PUBLIC_PORT, maintenance_writes=None):
    root = nginx_dir(state)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for sub in ("client_temp", "proxy_temp", "fastcgi_temp", "uwsgi_temp", "scgi_temp"):
        (root / sub).mkdir(exist_ok=True, mode=0o700)
    save_text(root / "active_upstream.conf", render_upstream_conf(active_port))
    maint_path = root / "maintenance_writes.conf"
    if maintenance_writes is not None or not maint_path.exists():
        save_text(maint_path, render_maintenance_writes_conf(bool(maintenance_writes)))
    conf_path = root / "nginx.conf"
    save_text(conf_path, render_nginx_conf(root, public_port=public_port))
    return conf_path


def validate_nginx_config(state):
    conf_path = nginx_dir(state) / "nginx.conf"
    require(conf_path.is_file(), "Nginx configuration is missing")
    result = subprocess.run(
        [nginx_binary(), "-t", "-c", str(conf_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        raise DeployError("Nginx configuration test failed: " + (detail[-1] if detail else "unknown error"))


def reload_nginx(state):
    conf_path = nginx_dir(state) / "nginx.conf"
    validate_nginx_config(state)
    result = subprocess.run(
        [nginx_binary(), "-s", "reload", "-c", str(conf_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        raise DeployError("Nginx reload failed: " + (detail[-1] if detail else "unknown error"))


def switch_nginx_upstream(state, target_port, *, reload_running=True):
    upstream_path = nginx_dir(state) / "active_upstream.conf"
    previous = upstream_path.read_text(encoding="utf-8") if upstream_path.is_file() else None
    save_text(upstream_path, render_upstream_conf(target_port))
    try:
        if reload_running:
            reload_nginx(state)
        else:
            validate_nginx_config(state)
    except BaseException:
        if previous is not None:
            save_text(upstream_path, previous)
        raise


def set_nginx_maintenance_writes(state, enabled, *, retry_after=15, reload_running=True):
    maint_path = nginx_dir(state) / "maintenance_writes.conf"
    previous = maint_path.read_text(encoding="utf-8") if maint_path.is_file() else None
    save_text(maint_path, render_maintenance_writes_conf(enabled, retry_after=retry_after))
    try:
        if reload_running:
            reload_nginx(state)
        else:
            validate_nginx_config(state)
    except BaseException:
        if previous is not None:
            save_text(maint_path, previous)
        raise


def nginx_master_pid(state=None):
    pid_path = nginx_dir(state) / "nginx.pid"
    if not pid_path.is_file() or pid_path.is_symlink():
        return None
    raw = pid_path.read_text(encoding="utf-8").strip()
    if not raw.isdigit():
        return None
    pid = int(raw)
    return pid if process_alive(pid) else None


def nginx_worker_pids(state=None):
    master = nginx_master_pid(state)
    if master is None:
        return []
    workers = []
    uid = os.getuid()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != uid:
                continue
            status = (proc / "stat").read_text()
            fields = status.rsplit(") ", 1)[1].split()
            if fields[0] in {"Z", "X"}:
                continue
            if int(fields[1]) == master:
                workers.append(int(proc.name))
        except (OSError, ValueError, IndexError):
            continue
    return sorted(workers)


def wait_nginx_workers_drained(worker_pids, *, timeout=180):
    """Wait until pre-reload Nginx worker processes finish in-flight requests and exit."""
    remaining = {int(p) for p in (worker_pids or ()) if process_alive(int(p))}
    if not remaining:
        return
    deadline = time.monotonic() + max(1.0, float(timeout))
    notice_at = time.monotonic() + 15
    while remaining:
        remaining = {p for p in remaining if process_alive(p)}
        if not remaining:
            return
        now = time.monotonic()
        if now >= deadline:
            raise DeployError(
                f"Pre-reload Nginx worker(s) {sorted(remaining)} did not drain within {timeout}s"
            )
        if now >= notice_at:
            print(
                f"Waiting for pre-reload Nginx worker(s) {sorted(remaining)} to finish in-flight requests",
                flush=True,
            )
            notice_at = now + 15
        time.sleep(0.2)


def stop_nginx(state=None, *, timeout=15):
    pid = nginx_master_pid(state)
    if pid is not None:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        end = time.monotonic() + timeout
        while process_alive(pid) and time.monotonic() < end:
            time.sleep(0.1)
    if subprocess.run(
        ["tmux", "has-session", "-t", "=" + NGINX_SESSION],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0:
        with contextlib.suppress(Exception):
            run("tmux", "kill-session", "-t", "=" + NGINX_SESSION)


def start_nginx(state):
    conf_path = nginx_dir(state) / "nginx.conf"
    validate_nginx_config(state)
    command = shlex.join([nginx_binary(), "-c", str(conf_path), "-g", "daemon off;"])
    command += " >> " + shlex.quote(str(nginx_dir(state) / "nginx-console.log")) + " 2>&1"
    run("tmux", "new-session", "-d", "-s", NGINX_SESSION, command)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if nginx_master_pid(state) is not None:
            return
        time.sleep(0.1)
    raise DeployError("Nginx failed to start and write its PID file")


def read_active_slot(state=None):
    path = Path(state or STATE) / "active_slot.json"
    if not path.exists():
        return None
    require(path.is_file() and not path.is_symlink(), "Active slot state is invalid")
    stat = path.stat()
    require(stat.st_uid == os.getuid() and stat.st_mode & 0o077 == 0, "Unsafe active slot state permissions")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeployError("Active slot state is unreadable") from exc
    slot = data.get("slot")
    require(slot in BLUEGREEN_SLOTS, "Unknown active blue-green slot")
    require(data.get("port") == BLUEGREEN_SLOTS[slot], "Active slot port mismatch")
    require(data.get("session") == slot_session(slot), "Active slot session mismatch")
    return data


def read_live_on_port(port, *, session=SESSION):
    matches = []
    port_arg = str(port).encode()
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if b"uvicorn" in args and port_arg in args:
                env = dict(x.split("=", 1) for x in (proc / "environ").read_bytes().decode().split("\0") if "=" in x)
                matches.append((int(proc.name), env, (proc / "cwd").resolve()))
        except (OSError, ValueError):
            continue
    require(len(matches) == 1, f"Expected exactly one owned Dashboard uvicorn on {port}")
    pid, env, cwd = matches[0]
    pane = git_pane_pid(session)
    require(pid == pane, "Dashboard must be the sole foreground process in its tmux pane")
    captured = capture_env(env)
    if cwd != REPO / "ra_triage_dashboard":
        validate_live_candidate(cwd, captured.get("DASHBOARD_BUILD_COMMIT", ""))
        captured = rebase_env(captured, cwd.parent, REPO)
    return pid, captured


def read_live():
    active = read_active_slot(STATE)
    if active is None:
        return read_live_on_port(PUBLIC_PORT, session=SESSION)
    require(nginx_master_pid(STATE) is not None, "Blue-green Nginx frontend is not running")
    return read_live_on_port(active["port"], session=active["session"])


def validate_live_candidate(app, sha):
    """Accept only owned, receipted isolated/blue-green releases or verified recovery runtimes."""
    folder = app.parent.parent
    require(folder.parent == STATE / "releases" and RELEASE_ID_PATTERN.fullmatch(folder.name),
            "Live process uses an unrecognized checkout")
    require(app in (folder / "candidate" / "ra_triage_dashboard", folder / "rollback" / "ra_triage_dashboard")
            and not folder.is_symlink() and not app.parent.is_symlink(), "Live process is not an owned release")
    path = folder / "result.json"
    require(path.is_file() and not path.is_symlink(), "Live candidate receipt is missing")
    stat = path.stat()
    require(stat.st_uid == os.getuid() and stat.st_mode & 0o077 == 0, "Unsafe live candidate receipt")
    record = json.loads(path.read_text())
    candidate = (
        app.parent.name == "candidate"
        and (
            record.get("status") == "success"
            or (
                record.get("status") == "failed"
                and record.get("rollback_status") == "kept_new_slot"
                and record.get("deploy_mode") == "bluegreen"
            )
        )
        and (bool(record.get("isolated_ref")) or record.get("deploy_mode") == "bluegreen")
        and record.get("target") == sha
        and record.get("candidate") == str(app.parent)
    )
    rollback = (app.parent.name == "rollback" and record.get("status") == "failed"
                and record.get("rollback_status") == "healthy" and record.get("previous") == sha
                and record.get("rollback") == str(app.parent))
    require(candidate or rollback,
            "Live candidate receipt does not match runtime")
    validate_prepared_worktree(app.parent, sha)


def release_ref(isolated_ref="", expected_live_sha=""):
    require(bool(isolated_ref) == bool(expected_live_sha), "Isolated ref and expected live SHA are required together")
    if isolated_ref:
        require(re.fullmatch(r"codex/[a-z0-9][a-z0-9-]{0,63}", isolated_ref), "Invalid isolated release branch")
        require(re.fullmatch(r"[0-9a-f]{40}", expected_live_sha), "Expected live SHA must be full length")
    return "origin/" + (isolated_ref or "master")

def git_pane_pid(session=SESSION):
    value = run("tmux", "list-panes", "-t", "=" + session, "-F", "#{pane_pid}", stdout=subprocess.PIPE).stdout.decode().splitlines()
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
    # Secrets are untracked runtime state, never files in the candidate code tree.
    persistent_files = {"DASHBOARD_DCHAT_CREDENTIALS_FILE", "DASHBOARD_DATABASE_URL_FILE",
                        "DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE"}
    return {k: new + v[len(old):] if k not in persistent_files and v.startswith(old + "/") else v
            for k, v in env.items()}

def configured_gray_port():
    value = os.environ.get("RA_DASHBOARD_DEPLOY_GRAY_PORT", str(DEFAULT_GRAY_PORT))
    require(value.isascii() and value.isdecimal() and len(value) <= 5,
            "RA_DASHBOARD_DEPLOY_GRAY_PORT must be an integer port")
    port = int(value)
    reserved = {PUBLIC_PORT, *BLUEGREEN_SLOTS.values()}
    require(1024 <= port <= 65535 and port not in reserved,
            "Choose an unprivileged gray port other than production/blue-green ports")
    return port

def gray_env(env, candidate, data, sha, port=8786):
    result = rebase_env(env, REPO, candidate)
    result.update({key: "false" for key in OFF})
    result.update(DASHBOARD_DATA_DIR=str(data), DASHBOARD_DATABASE_URL="sqlite:///" + str(data / "triage.sqlite3"),
                  DASHBOARD_DATABASE_URL_FILE="", DASHBOARD_POSTGRES_PERSISTENT_DATA="false",
                  DASHBOARD_BUILD_COMMIT=sha, DASHBOARD_PORT=str(port), DASHBOARD_HOST="127.0.0.1",
                  DASHBOARD_BATCH_BAG_CACHE_DIR=str(data / "batch_bags"),
                  DASHBOARD_BOOTSTRAP_MODEL_JSON="", DASHBOARD_DCHAT_CREDENTIALS_FILE="",
                  DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE="", DASHBOARD_DEPLOYMENT_MODE="production",
                  DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS="false")
    return result

def supports_deferred_batch_recovery(app_dir):
    """Return True only when app_dir defers Batch interruption recovery behind a renewed lease."""
    main_py = Path(app_dir) / "app/main.py"
    try:
        text = main_py.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "recover_interrupted_jobs=not defer_batch_recovery" in text
        and "_batch_prediction_leader" in text
    )


def read_running_batch_jobs(env, *, app_dir=None):
    """Return count of currently running Batch prediction or publish jobs in PostgreSQL."""
    checked = run(
        PYTHON, "-c", RUNNING_BATCH_CHECK_CODE,
        cwd=app_dir or (REPO / "ra_triage_dashboard"),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    lines = checked.stdout.decode().strip().splitlines()
    require(lines, "Running Batch job check returned no output")
    try:
        payload = json.loads(lines[-1])
    except ValueError as exc:
        raise DeployError("Running Batch job check output is unreadable") from exc
    count = payload.get("running")
    require(isinstance(count, int) and count >= 0, "Running Batch job count is malformed")
    return count


def read_applied_postgres_migrations(env, *, app_dir=None):
    """Query exact applied migration filenames from PostgreSQL without running init/recovery."""
    listed = run(
        PYTHON, "-c", MIGRATION_LIST_CODE,
        cwd=app_dir or (REPO / "ra_triage_dashboard"),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    lines = listed.stdout.decode().strip().splitlines()
    require(lines, "PostgreSQL applied migration list is unavailable")
    try:
        payload = json.loads(lines[-1])
    except ValueError as exc:
        raise DeployError("PostgreSQL applied migration list is unreadable") from exc
    versions = payload.get("versions")
    require(isinstance(versions, list) and all(isinstance(v, str) for v in versions),
            "PostgreSQL applied migration list is malformed")
    return sorted(set(versions))


def apply_additive_migrations(candidate, env, migrations, record_dir, expected_count, *, applied_before=None):
    target_versions = [Path(path).name for path in migrations]
    if applied_before is not None:
        applied_set = set(applied_before)
        pending = [path for path in migrations if Path(path).name not in applied_set]
        if not pending:
            require(
                all(version in applied_set for version in target_versions),
                "Target PostgreSQL migrations are not recorded in dashboard_schema_migrations",
            )
            print("All target PostgreSQL migrations are already applied; skipping re-apply", flush=True)
            return "", expected_count
    else:
        pending = list(migrations)
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
    require(output, "Migration count verification failed")
    last_line = output[-1]
    versions_after = None
    if last_line.isdigit():
        migration_count = int(last_line)
    else:
        try:
            payload = json.loads(last_line)
        except ValueError as exc:
            raise DeployError("Migration count verification failed") from exc
        require(isinstance(payload, dict) and isinstance(payload.get("count"), int),
                "Migration count verification failed")
        migration_count = int(payload["count"])
        raw_versions = payload.get("versions")
        if isinstance(raw_versions, list):
            versions_after = {str(v) for v in raw_versions}
    require(
        migration_count == expected_count + len(pending),
        "Unexpected PostgreSQL migration count after apply",
    )
    if versions_after is not None:
        require(
            all(version in versions_after for version in target_versions),
            "Expected PostgreSQL migration versions were not recorded after apply",
        )
    return str(backup), migration_count

def check_health(health, sha, storage):
    require(health.get("ok") is True, "Health is not OK")
    require(health.get("build_commit") == sha, "Running SHA differs from target")
    backend = {"sqlite-mvp": "sqlite"}.get(health.get("storage"), health.get("storage"))
    require(backend == storage, "Unexpected database backend")
    if storage == "sqlite":
        require(health.get("human_label_write_enabled", False) is False, "Gray human writer is not disabled")
        require(health.get("trail_te_write_enabled", False) is False, "Gray TE writer is not disabled")
        for key in ("trail_attribute_write_enabled", "trail_attribute_review_write_enabled",
                    "trail_rd_write_enabled",
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
    return {**{k: health.get(k) for k in keys},
            "trail_te_write_enabled": health.get("trail_te_write_enabled", False),
            "trail_rd_write_enabled": health.get("trail_rd_write_enabled", False),
            "human_label_write_enabled": health.get("human_label_write_enabled", False)}


def requested_policy(health, enable_trail_rd_write=False):
    expected = policy(health)
    if enable_trail_rd_write:
        require(isinstance(health.get("trail_rd_write_enabled"), bool), "Live RD writer policy is unavailable")
        expected["trail_rd_write_enabled"] = True
    return expected

def smoke(port, sha, storage, *, require_notifications=True):
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
        notifications = status.get("review_notifications", {})
        if require_notifications and notifications.get("enabled") and notifications.get("delivery_mode") == "openapi":
            require(notifications.get("credentials", {}).get("ready") is True,
                    "DChat notification credentials are unavailable; preserve their persistent file reference")
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

def start_production(record_dir, app, env, sha, name, *, session=SESSION, port=None, host=None, enable_lease_gating=False):
    env = dict(env, DASHBOARD_BUILD_COMMIT=sha)
    if port is not None:
        env["DASHBOARD_PORT"] = str(port)
    if host is not None:
        env["DASHBOARD_HOST"] = str(host)
    if enable_lease_gating:
        env["DASHBOARD_WORKER_LEASE_GATING"] = "true"
        env.setdefault("DASHBOARD_UVICORN_GRACEFUL_TIMEOUT", "30")
    config = record_dir / (name + "-env.json")
    save(config, {"app": str(app), "env": env})
    launcher = record_dir / "launcher.py"
    if not launcher.exists():
        shutil.copyfile(__file__, launcher)
    command = shlex.join([str(PYTHON), str(launcher), "--serve", str(config)])
    command += " >> " + shlex.quote(str(record_dir / (name + ".log"))) + " 2>&1"
    run("tmux", "new-session", "-d", "-s", session, command)

def process_alive(pid):
    try:
        status = Path(f"/proc/{pid}/stat").read_text()
        # Container init may leave exited uvicorn children unreaped indefinitely.
        return status.rsplit(") ", 1)[1].split()[0] not in {"Z", "X"}
    except FileNotFoundError:
        return False


def wait_production_stopped(pid, *, session=SESSION):
    # SIGTERM cannot be undone: never abandon a draining server just because
    # it exceeds a deadline. Keep the deployment lock until ownership resolves.
    notice_at = time.monotonic() + 30
    while process_alive(pid):
        if time.monotonic() >= notice_at:
            print(f"Dashboard process {pid} is still draining; retaining deployment ownership", flush=True)
            notice_at = time.monotonic() + 15
        time.sleep(0.2)
    # Process exit precedes tmux removing its wrapper/session. A new owner is
    # never ours to stop; an old wrapper must disappear before reusing its session.
    while subprocess.run(["tmux", "has-session", "-t", "=" + session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        try:
            owner = git_pane_pid(session)
        except subprocess.CalledProcessError:
            # has-session and list-panes are not atomic: normal teardown can
            # remove the session between them. Fail closed if it still exists.
            if subprocess.run(["tmux", "has-session", "-t", "=" + session],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
                break
            raise
        require(owner == pid, "Dashboard session acquired another process during shutdown")
        time.sleep(0.1)


def stop_production(pid, *, on_signal=None, session=SESSION):
    require(git_pane_pid(session) == pid, "Production process changed during validation")
    os.kill(pid, signal.SIGTERM)
    if on_signal is not None:
        on_signal()
    wait_production_stopped(pid, session=session)

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
    active = read_active_slot(state)
    if active and active.get("release_id"):
        keep.add(Path(state) / "releases" / str(active["release_id"]))
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
    isolated_ref="", expected_live_sha="",
):
    require(sys.platform == "linux" and REPO.is_dir() and PYTHON.is_file(), "Run on the configured cloud_server")
    require(re.fullmatch(r"[0-9a-f]{40}", sha), "Supply a full 40-character pushed commit SHA")
    mode = migration_mode(
        allow_additive=allow_additive_migrations,
        allow_schema=allow_schema_migrations,
    )
    ref = release_ref(isolated_ref, expected_live_sha)
    require(not isolated_ref or mode == "none", "Isolated releases do not permit migrations")
    run("git", "fetch", "origin", "+refs/heads/" + (isolated_ref or "master") + ":refs/remotes/" + ref)
    require(git("branch", "--show-current") == "master", "Production checkout must be on master")
    require(not git("status", "--porcelain"), "Production checkout has local changes")
    require(git("rev-parse", ref) == sha, "Target differs from the pushed release branch")
    run("git", "merge-base", "--is-ancestor", "HEAD", sha)
    pid, env = read_live()
    before = get_json(8785, "health")
    old = before.get("build_commit", "")
    require(re.fullmatch(r"[0-9a-f]{40}", old), "Live build SHA is unavailable")
    check_health(before, old, "postgresql")
    if isolated_ref:
        require(old == expected_live_sha, "Production changed since isolated release was authorized")
    # Never lose already-published work, including a previous isolated release.
    run("git", "merge-base", "--is-ancestor", old, sha)
    migrations = migration_changes(
        old,
        sha,
        allow_additive=allow_additive_migrations,
        allow_schema=allow_schema_migrations,
    )
    migration_count_before = None
    applied_migrations_before = None
    pending_migrations = []
    if migrations:
        status = get_json(8785, "api/status")
        migration_count_before = status.get("database", {}).get("migration_count")
        require(
            isinstance(migration_count_before, int),
            "Production migration count is unavailable",
        )
        applied_migrations_before = read_applied_postgres_migrations(env)
        require(
            len(applied_migrations_before) == migration_count_before,
            "Production applied migration list does not match reported count",
        )
        applied_set = set(applied_migrations_before)
        pending_migrations = [path for path in migrations if Path(path).name not in applied_set]
    gray_port = configured_gray_port()
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", gray_port))
        except OSError:
            raise DeployError(f"Gray port {gray_port} is occupied; preserve its existing service") from None
    return {
        "gray_port": gray_port,
        "pid": pid,
        "env": env,
        "before": before,
        "old": old,
        "migrations": migrations,
        "pending_migrations": pending_migrations,
        "applied_migrations_before": applied_migrations_before,
        "migration_count_before": migration_count_before,
        "migration_mode": mode,
    }


def check_release(
    sha,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
    isolated_ref="", expected_live_sha="", enable_trail_rd_write=False,
):
    with deployment_lock(STATE):
        state = preflight(
            sha,
            allow_additive_migrations,
            allow_schema_migrations,
            isolated_ref, expected_live_sha,
        )
        active_slot = read_active_slot(STATE)
        print(json.dumps({
            "preflight": "ok",
            "deploy_mode": "bluegreen" if active_slot else "legacy",
            "active_slot": active_slot["slot"] if active_slot else None,
            "gray_port": state["gray_port"],
            "target": sha,
            "live": state["old"],
            "migrations": state["migrations"],
            "pending_migrations": state["pending_migrations"],
            "additive_migrations": state["migrations"],
            "migration_mode": state["migration_mode"],
            "requested_policy": requested_policy(state["before"], enable_trail_rd_write),
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
    isolated_ref="", expected_live_sha="", enable_trail_rd_write=False,
):
    with deployment_lock(STATE):
        state = preflight(
            sha,
            allow_additive_migrations,
            allow_schema_migrations,
            isolated_ref, expected_live_sha,
        )
        pid = state["pid"]
        env = state["env"]
        before = state["before"]
        old = state["old"]
        migrations = state["migrations"]
        pending_migrations = state["pending_migrations"]
        applied_migrations_before = state["applied_migrations_before"]
        migration_count_before = state["migration_count_before"]
        stamp, folder = create_release_folder(sha)
        candidate, rollback, data = folder / "candidate", folder / "rollback", folder / "gray-data"
        result = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "status": "preparing",
            "gray_port": state["gray_port"],
            "target": sha,
            "previous": old,
            "candidate": str(candidate),
            "rollback": str(rollback),
            "additive_migrations": migrations,
            "pending_migrations": pending_migrations,
            "applied_migrations_before": applied_migrations_before,
            "migration_mode": state["migration_mode"],
            "isolated_ref": isolated_ref,
            "expected_live_sha": expected_live_sha,
            "checkout_sha": git("rev-parse", "HEAD"),
            "enable_trail_rd_write": enable_trail_rd_write,
            "requested_policy": requested_policy(before, enable_trail_rd_write),
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
            gray_port = state["gray_port"]
            isolated_env = gray_env(env, candidate, data, sha, port=gray_port)
            test_env = dict(isolated_env, DASHBOARD_BASE_PATH="")
            if test_dependencies := os.environ.get("RA_DASHBOARD_DEPLOY_TEST_PYTHONPATH"):
                test_env["PYTHONPATH"] = test_dependencies
            print("Running complete cloud test suite", flush=True)
            with (folder / "tests.log").open("w") as log:
                run(PYTHON, "-m", "pytest", "ra_triage_dashboard/tests", "-q", cwd=candidate, env=test_env, stdout=log, stderr=subprocess.STDOUT, timeout=600)
            with (folder / "gray.log").open("w") as log:
                gray = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", str(candidate / "ra_triage_dashboard"), "--host", "127.0.0.1", "--port", str(gray_port)], cwd=candidate, env=isolated_env, stdout=log, stderr=subprocess.STDOUT)
            smoke(gray_port, sha, "sqlite")
            stop_child(gray)
            require(git("rev-parse", release_ref(isolated_ref, expected_live_sha)) == sha
                    and git("rev-parse", "HEAD") == result["checkout_sha"]
                    and not git("status", "--porcelain"), "Checkout changed during gray")
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


def verify_port_free(port, label):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise DeployError(f"{label} port {port} is occupied; preserve its existing service") from None


def check_metrics_blocked_via_proxy(port=PUBLIC_PORT):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/metrics", timeout=10) as response:
            raise DeployError(f"Expected /metrics via Nginx on {port} to return 403, got {response.status}")
    except urllib.error.HTTPError as exc:
        require(exc.code == 403, f"Expected /metrics via Nginx on {port} to return 403, got {exc.code}")


def promote_bluegreen_release(
    *,
    folder,
    release_id,
    result,
    target,
    old,
    pid,
    env,
    migrations,
    pending_migrations,
    applied_migrations_before,
    migration_count_before,
    requested_mode,
    expected_policy,
    isolated_ref,
    enable_trail_rd_write,
    active_slot,
):
    old_slot = active_slot["slot"]
    old_port = active_slot["port"]
    old_session = active_slot["session"]
    target_slot = other_slot(old_slot)
    target_port = BLUEGREEN_SLOTS[target_slot]
    target_session = slot_session(target_slot)
    verify_port_free(target_port, f"Blue-green target slot ({target_slot})")
    require(
        subprocess.run(
            ["tmux", "has-session", "-t", "=" + target_session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode != 0,
        f"Target tmux session {target_session} already exists",
    )
    candidate = folder / "candidate"
    replacement_pid = None
    switched = False
    committed = False
    old_slot_stop_attempted = False
    maint_enabled = False
    batch_freeze_enabled = False

    def mark_old_slot_stopping():
        nonlocal old_slot_stop_attempted
        old_slot_stop_attempted = True

    result["status"] = "promoting"
    result["deploy_mode"] = "bluegreen"
    save(folder / "result.json", result)
    try:
        print(
            f"Prepared gray passed; blue-green promoting exact SHA into {target_slot}:{target_port}",
            flush=True,
        )
        if migrations:
            if pending_migrations and requested_mode == "schema":
                set_nginx_maintenance_writes(STATE, True)
                maint_enabled = True
            backup, migration_count = apply_additive_migrations(
                candidate,
                env,
                migrations,
                folder,
                migration_count_before,
                applied_before=applied_migrations_before,
            )
            result.update(
                backup=backup,
                migration_count_after=migration_count,
            )
            save(folder / "result.json", result)
        old_app = Path(active_slot.get("app") or (REPO / "ra_triage_dashboard"))
        if not supports_deferred_batch_recovery(old_app):
            # Transitional upgrade from a pre-lease-renewal slot: block new Batch
            # submissions/pushes at Nginx FIRST, drain pre-freeze workers so no
            # in-flight Batch POST can still reach old_app, then verify zero
            # active/queued Batch jobs and keep Batch frozen until old_slot exits.
            pre_freeze_workers = nginx_worker_pids(STATE)
            if not maint_enabled:
                set_nginx_maintenance_writes(STATE, "batch")
            batch_freeze_enabled = True
            wait_nginx_workers_drained(pre_freeze_workers)
            running_batch = read_running_batch_jobs(env, app_dir=old_app)
            require(
                running_batch == 0,
                "Old active slot lacks continuous Batch lease renewal; wait for active/queued Batch jobs to finish before blue-green promotion",
            )
        production_env = dict(env)
        if enable_trail_rd_write:
            production_env["DASHBOARD_TRAIL_RD_WRITE_ENABLED"] = "true"
        slot_env = rebase_env(production_env, REPO, candidate)
        start_production(
            folder,
            candidate / "ra_triage_dashboard",
            slot_env,
            target,
            f"production-{target_slot}",
            session=target_session,
            port=target_port,
            host="127.0.0.1",
            enable_lease_gating=True,
        )
        replacement_pid = git_pane_pid(target_session)
        slot_health = smoke(target_port, target, "postgresql")
        require(
            policy(slot_health) == expected_policy,
            "Candidate slot access/writer policy differs from explicitly requested policy",
        )
        pre_reload_workers = nginx_worker_pids(STATE)
        switch_nginx_upstream(STATE, target_port)
        switched = True
        if maint_enabled:
            set_nginx_maintenance_writes(STATE, "batch" if batch_freeze_enabled else False)
            maint_enabled = False
        after = smoke(PUBLIC_PORT, target, "postgresql")
        require(
            policy(after) == expected_policy,
            "Public entrance access/writer policy differs from explicitly requested policy",
        )
        # Wait for pre-reload Nginx workers to finish buffering/proxying any
        # slow uploads aimed at old_port before committing and stopping old_slot.
        wait_nginx_workers_drained(pre_reload_workers)
        save(
            STATE / "active_slot.json",
            {
                "slot": target_slot,
                "port": target_port,
                "session": target_session,
                "pid": replacement_pid,
                "sha": target,
                "release_id": release_id,
                "app": str(candidate / "ra_triage_dashboard"),
                "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        # Commit point: public traffic is verified on target_slot, pre-reload
        # Nginx workers have drained, and active_slot.json records target_slot.
        # Post-commit failures must keep the healthy new slot live rather than
        # pointing 8785 back at a draining or stopped old slot.
        committed = True
        stop_production(pid, session=old_session, on_signal=mark_old_slot_stopping)
        if batch_freeze_enabled:
            set_nginx_maintenance_writes(STATE, False)
            batch_freeze_enabled = False
        if not isolated_ref:
            run("git", "merge", "--ff-only", target)
        result.update(
            status="success",
            deploy_mode="bluegreen",
            slot=target_slot,
            port=target_port,
            previous_slot=old_slot,
            previous_port=old_port,
            policy=policy(after),
            promoted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        save(folder / "result.json", result)
        try:
            result["cleaned_worktrees"] = cleanup(STATE, folder)
        except Exception as exc:
            result["cleanup_warning"] = type(exc).__name__
        save(folder / "result.json", result)
        print(json.dumps({
            "status": "success",
            "deploy_mode": "bluegreen",
            "slot": target_slot,
            "port": target_port,
            "target": target,
            "release_id": release_id,
            "record": str(folder / "result.json"),
        }))
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__)
        try:
            if committed or old_slot_stop_attempted:
                result.update(
                    rollback_status="kept_new_slot",
                    slot=target_slot,
                    port=target_port,
                    previous_slot=old_slot,
                    previous_port=old_port,
                )
            elif switched:
                # Verify old slot directly before routing public traffic back, then
                # wait for Nginx workers serving green to finish in-flight uploads
                # before stopping target_slot.
                smoke(old_port, old, "postgresql")
                rollback_pre_workers = nginx_worker_pids(STATE)
                switch_nginx_upstream(STATE, old_port)
                smoke(PUBLIC_PORT, old, "postgresql")
                wait_nginx_workers_drained(rollback_pre_workers)
                if replacement_pid is not None:
                    stop_production(replacement_pid, session=target_session)
                result["rollback_status"] = "healthy"
            else:
                if replacement_pid is not None:
                    stop_production(replacement_pid, session=target_session)
                result["rollback_status"] = "unchanged"
            if maint_enabled or batch_freeze_enabled:
                set_nginx_maintenance_writes(STATE, False)
        except Exception as rollback_error:
            result["rollback_status"] = type(rollback_error).__name__
        save(folder / "result.json", result)
        print("Deployment failed; record: " + str(folder / "result.json"), file=sys.stderr)
        raise


def bootstrap_nginx():
    """One-time cutover from legacy uvicorn on 8785 to Nginx + blue/green loopback slots."""
    require(sys.platform == "linux" and REPO.is_dir() and PYTHON.is_file(), "Run on the configured cloud_server")
    with deployment_lock(STATE):
        require(read_active_slot(STATE) is None, "Blue-green Nginx mode is already bootstrapped")
        legacy_pid, env = read_live_on_port(PUBLIC_PORT, session=SESSION)
        before = get_json(PUBLIC_PORT, "health")
        old_sha = before.get("build_commit", "")
        require(re.fullmatch(r"[0-9a-f]{40}", old_sha), "Live build SHA is unavailable")
        check_health(before, old_sha, "postgresql")
        expected_policy = policy(before)
        live_cwd = (Path(f"/proc/{legacy_pid}/cwd")).resolve()
        blue_port = BLUEGREEN_SLOTS["blue"]
        blue_session = slot_session("blue")
        verify_port_free(blue_port, "Blue-green bootstrap slot (blue)")
        for sess in (blue_session, NGINX_SESSION):
            require(
                subprocess.run(
                    ["tmux", "has-session", "-t", "=" + sess],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode != 0,
                f"Session {sess} already exists",
            )
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        record_dir = STATE / "bootstrap" / f"{stamp}-{old_sha[:12]}"
        record_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        blue_pid = None
        legacy_stop_attempted = False

        def mark_legacy_stopping():
            nonlocal legacy_stop_attempted
            legacy_stop_attempted = True

        try:
            blue_env = rebase_env(env, REPO, live_cwd.parent) if live_cwd != REPO / "ra_triage_dashboard" else dict(env)
            ensure_nginx_layout(STATE, blue_port, public_port=PUBLIC_PORT, maintenance_writes=False)
            validate_nginx_config(STATE)
            # Only warm-start blue while legacy is still alive if legacy ALREADY
            # runs deferred, lease-gated Batch recovery AND holds active leases.
            # Otherwise (e.g. legacy 3368f74c/5093743d or unleased legacy), an
            # overlapping blue startup would run database.init() recovery and
            # kill live Batch jobs; refuse while Batch is running and stop legacy
            # completely before booting blue.
            can_overlap_with_legacy = (
                env.get("DASHBOARD_WORKER_LEASE_GATING") == "true"
                and supports_deferred_batch_recovery(live_cwd)
            )
            if can_overlap_with_legacy:
                start_production(
                    record_dir,
                    live_cwd,
                    blue_env,
                    old_sha,
                    "bootstrap-blue",
                    session=blue_session,
                    port=blue_port,
                    host="127.0.0.1",
                    enable_lease_gating=True,
                )
                blue_pid = git_pane_pid(blue_session)
                blue_health = smoke(blue_port, old_sha, "postgresql")
                require(policy(blue_health) == expected_policy, "Blue slot policy differs from legacy live service")
                stop_production(legacy_pid, session=SESSION, on_signal=mark_legacy_stopping)
            else:
                running_batch = read_running_batch_jobs(env, app_dir=live_cwd)
                require(
                    running_batch == 0,
                    "Cannot bootstrap Nginx while a legacy Batch prediction or publish job is running; wait for it to finish",
                )
                stop_production(legacy_pid, session=SESSION, on_signal=mark_legacy_stopping)
                start_production(
                    record_dir,
                    live_cwd,
                    blue_env,
                    old_sha,
                    "bootstrap-blue",
                    session=blue_session,
                    port=blue_port,
                    host="127.0.0.1",
                    enable_lease_gating=True,
                )
                blue_pid = git_pane_pid(blue_session)
                blue_health = smoke(blue_port, old_sha, "postgresql")
                require(policy(blue_health) == expected_policy, "Blue slot policy differs from legacy live service")
            start_nginx(STATE)
            after = smoke(PUBLIC_PORT, old_sha, "postgresql")
            require(policy(after) == expected_policy, "Proxied policy differs from legacy live service")
            check_metrics_blocked_via_proxy(PUBLIC_PORT)
            slot_state = {
                "slot": "blue",
                "port": blue_port,
                "session": blue_session,
                "pid": blue_pid,
                "sha": old_sha,
                "release_id": "",
                "app": str(live_cwd),
                "bootstrapped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            save(STATE / "active_slot.json", slot_state)
            print(json.dumps({"status": "bootstrapped", **slot_state}))
            return slot_state
        except BaseException:
            if legacy_stop_attempted:
                try:
                    stop_nginx(STATE)
                    if blue_pid is not None:
                        with contextlib.suppress(Exception):
                            stop_production(blue_pid, session=blue_session)
                    wait_production_stopped(legacy_pid, session=SESSION)
                    start_production(record_dir, live_cwd, env, old_sha, "bootstrap-rollback", session=SESSION)
                    smoke(PUBLIC_PORT, old_sha, "postgresql")
                except Exception as rollback_error:
                    print(
                        f"Bootstrap rollback failed ({type(rollback_error).__name__}); inspect {record_dir}",
                        file=sys.stderr,
                    )
            elif blue_pid is not None:
                with contextlib.suppress(Exception):
                    stop_production(blue_pid, session=blue_session)
            raise


def toggle_maintenance_writes(mode):
    require(mode in {"on", "off"}, "Maintenance writes mode must be 'on' or 'off'")
    with deployment_lock(STATE):
        active = read_active_slot(STATE)
        require(active is not None, "Maintenance write guard requires Nginx blue-green mode")
        require(nginx_master_pid(STATE) is not None, "Blue-green Nginx frontend is not running")
        enabled = mode == "on"
        set_nginx_maintenance_writes(STATE, enabled)
        print(json.dumps({"status": "ok", "maintenance_writes": enabled, "slot": active["slot"], "port": active["port"]}))


def promote_release(
    release_id,
    sha=None,
    allow_additive_migrations=False,
    allow_schema_migrations=False,
    isolated_ref="", expected_live_sha="", enable_trail_rd_write=False,
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
        require(result.get("isolated_ref", "") == isolated_ref and result.get("expected_live_sha", "") == expected_live_sha,
                "Promotion requires the same isolated release authorization")
        require(result.get("enable_trail_rd_write", False) == enable_trail_rd_write,
                "Promotion requires the same explicit RD writer authorization used during prepare")
        state = preflight(
            target,
            allow_additive_migrations,
            allow_schema_migrations,
            isolated_ref, expected_live_sha,
        )
        pid = state["pid"]
        env = state["env"]
        before = state["before"]
        old = state["old"]
        migrations = state["migrations"]
        pending_migrations = state["pending_migrations"]
        applied_migrations_before = state["applied_migrations_before"]
        migration_count_before = state["migration_count_before"]
        require(state["gray_port"] == result.get("gray_port", DEFAULT_GRAY_PORT), "Gray port changed after prepare")
        require(old == result.get("previous") == recovery.get("sha"), "Production SHA changed after prepare")
        require(git("rev-parse", "HEAD") == result.get("checkout_sha"), "Checkout changed after prepare")
        require(pid == recovery.get("pid") and env == recovery.get("env"), "Production process or environment changed after prepare")
        require(policy(before) == recovery.get("policy") == result.get("policy"), "Production access/writer policy changed after prepare")
        expected_policy = requested_policy(before, enable_trail_rd_write)
        require(result.get("requested_policy", policy(before)) == expected_policy, "Requested production policy changed after prepare")
        require(migrations == result.get("additive_migrations"), "Migration set changed after prepare")
        require(
            pending_migrations == result.get("pending_migrations", migrations),
            "Pending migration set changed after prepare",
        )
        require(migration_count_before == recovery.get("migration_count") == result.get("migration_count_before"), "Production migration count changed after prepare")
        candidate = folder / "candidate"
        rollback = folder / "rollback"
        validate_prepared_worktree(candidate, target)
        validate_prepared_worktree(rollback, old)
        active_slot = read_active_slot(STATE)
        if active_slot is not None:
            return promote_bluegreen_release(
                folder=folder,
                release_id=release_id,
                result=result,
                target=target,
                old=old,
                pid=pid,
                env=env,
                migrations=migrations,
                pending_migrations=pending_migrations,
                applied_migrations_before=applied_migrations_before,
                migration_count_before=migration_count_before,
                requested_mode=requested_mode,
                expected_policy=expected_policy,
                isolated_ref=isolated_ref,
                enable_trail_rd_write=enable_trail_rd_write,
                active_slot=active_slot,
            )
        replacement_pid = None
        production_stop_attempted = False
        def mark_production_stopping():
            nonlocal production_stop_attempted
            production_stop_attempted = True
        result["status"] = "promoting"
        save(folder / "result.json", result)
        try:
            print("Prepared gray passed; promoting exact SHA", flush=True)
            stop_production(pid, on_signal=mark_production_stopping)
            if migrations:
                backup, migration_count = apply_additive_migrations(
                    candidate,
                    env,
                    migrations,
                    folder,
                    migration_count_before,
                    applied_before=applied_migrations_before,
                )
                result.update(
                    backup=backup,
                    migration_count_after=migration_count,
                )
                save(folder / "result.json", result)
            production_env = dict(env)
            if enable_trail_rd_write:
                production_env["DASHBOARD_TRAIL_RD_WRITE_ENABLED"] = "true"
            if isolated_ref:
                start_production(folder, candidate / "ra_triage_dashboard",
                                 rebase_env(production_env, REPO, candidate), target, "production")
            else:
                run("git", "merge", "--ff-only", target)
                start_production(folder, REPO / "ra_triage_dashboard", production_env, target, "production")
            replacement_pid = git_pane_pid()
            after = smoke(8785, target, "postgresql")
            require(policy(after) == expected_policy, "Runtime access/writer policy differs from explicitly requested policy")
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
            if production_stop_attempted:
                try:
                    if replacement_pid is not None:
                        stop_production(replacement_pid)
                    else:
                        wait_production_stopped(pid)
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
    isolated_ref="", expected_live_sha="", enable_trail_rd_write=False,
):
    if check_only:
        return check_release(
            sha,
            allow_additive_migrations,
            allow_schema_migrations,
            isolated_ref, expected_live_sha, enable_trail_rd_write,
        )
    release_id = prepare_release(
        sha,
        allow_additive_migrations,
        allow_schema_migrations,
        isolated_ref, expected_live_sha, enable_trail_rd_write,
    )
    return promote_release(
        release_id,
        sha,
        allow_additive_migrations,
        allow_schema_migrations,
        isolated_ref, expected_live_sha, enable_trail_rd_write,
    )

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha")
    parser.add_argument("--enable-trail-rd-write", action="store_true", help="explicitly enable confirmed RD publishing; gray remains disabled")
    parser.add_argument("--isolated-ref", default="", help="explicit pushed codex branch; keep main checkout unchanged")
    parser.add_argument("--expected-live-sha", default="", help="required current full SHA for isolated release")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="preflight only, without service/worktree changes")
    action.add_argument("--prepare", action="store_true", help="run tests and isolated gray, then stop before production changes")
    action.add_argument("--promote", metavar="RELEASE_ID", help="promote a previously prepared release")
    action.add_argument("--bootstrap-nginx", action="store_true", help="one-time cutover from legacy 8785 uvicorn to Nginx + blue/green loopback slots")
    action.add_argument("--maintenance-writes", choices=("on", "off"), help="toggle Nginx 503 + Retry-After write guard in blue-green mode")
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
    elif args.bootstrap_nginx:
        bootstrap_nginx()
    elif args.maintenance_writes:
        toggle_maintenance_writes(args.maintenance_writes)
    elif args.promote:
        promote_release(
            args.promote,
            args.sha,
            args.allow_additive_migrations,
            args.allow_schema_migrations,
            args.isolated_ref, args.expected_live_sha, args.enable_trail_rd_write,
        )
    else:
        require(args.sha, "--sha is required")
        if args.prepare:
            prepare_release(
                args.sha,
                args.allow_additive_migrations,
                args.allow_schema_migrations,
                args.isolated_ref, args.expected_live_sha, args.enable_trail_rd_write,
            )
        else:
            deploy(
                args.sha,
                args.check,
                args.allow_additive_migrations,
                args.allow_schema_migrations,
                args.isolated_ref, args.expected_live_sha, args.enable_trail_rd_write,
            )

if __name__ == "__main__":
    try:
        main()
    except (DeployError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Do not expose subprocess environment or credential-bearing output.
        print(str(exc) if isinstance(exc, DeployError) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
