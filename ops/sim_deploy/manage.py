#!/usr/bin/env python3
"""Independent, relocatable native deployment (Linux, nginx/redis/Postgres/supervisor).
Run as the service owner. Configuration and runtime secrets are JSON, never shell code.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from check_http import verify_http


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def write(path, text):
    path.write_text(text)
    path.chmod(0o600)


def validate_config(c):
    c = dict(c)
    for key in ("root", "source", "pg_bin"):
        if not Path(c[key]).is_absolute() or ".." in Path(c[key]).parts:
            raise ValueError(
                f"Expected an absolute target path without parent traversal: {key}"
            )
        c[key] = str(Path(c[key]))
        if not re.fullmatch(r"/[A-Za-z0-9_/.-]+", c[key]):
            raise ValueError(f"Unsupported path characters: {key}")
    for key in ("port", "api_port"):
        c[key] = int(c[key])
        if not 1024 <= c[key] <= 65535:
            raise ValueError(f"Invalid port: {key}")
    if c["port"] == c["api_port"]:
        raise ValueError("HTTP and backend ports must differ")
    if c["root"] == "/":
        raise ValueError("Unsafe deployment root")
    return c


def load(path):
    return validate_config(json.loads(Path(path).read_text()))


def prepare(c):
    root, src, pg = (Path(c[k]) for k in ("root", "source", "pg_bin"))
    for tool in ("nginx", "redis-server", "supervisord", "supervisorctl"):
        if not shutil.which(tool):
            raise RuntimeError(f"Missing runtime: {tool}")
    for tool in ("postgres", "initdb", "pg_ctl", "psql", "pg_dump"):
        if not (pg / tool).is_file():
            raise RuntimeError(f"Missing {pg / tool}")
    if not (src / "ra_sim_repro_dashboard/frontend/dist/index.html").is_file():
        raise RuntimeError(
            "Build frontend with npm ci && npm run build -- --base=/sim/ first"
        )
    if not (root / "venv/bin/python").exists():
        raise RuntimeError(
            "Create root/venv and install backend/requirements.txt first"
        )
    for name in ("", "logs", "pgsocket", "redis", "backups", "weekly"):
        p = root / name
        p.mkdir(parents=True, exist_ok=True)
        p.chmod(0o700)
    if not (root / "postgres/PG_VERSION").exists():
        run(
            [
                pg / "initdb",
                "-D",
                root / "postgres",
                "--encoding=UTF8",
                "--locale=C.UTF-8",
                "--auth-local=trust",
                "--auth-host=reject",
            ]
        )
        with (root / "postgres/postgresql.conf").open("a") as f:
            f.write(
                f"\nlisten_addresses = ''\nunix_socket_directories = '{root}/pgsocket'\n"
            )
    env = json.loads((root / "secrets.json").read_text())
    env.update(
        SIM_SOURCE_ROOT=str(src),
        DATABASE_URL=f"postgresql+psycopg2:///ra_sim?host={root}/pgsocket",
        REDIS_URL=f"unix://{root}/redis/redis.sock",
        ENABLE_RQ="1",
        VERSIONS_CONFIG=str(src / "ra_sim_repro_dashboard/config/versions.yaml"),
        DISABLE_MOCK_DATA="1",
        MOCK_DATA_DIR=str(root / "disabled_mock"),
        REPORT_DIR=str(src / "reports"),
        PYTHONPATH=str(src / "ra_sim_repro_dashboard/backend") + ":" + str(src),
        TZ="Asia/Shanghai",
    )
    write(root / "runtime.json", json.dumps(env))
    runner = """import json, os, sys\nfrom pathlib import Path\np=Path(__file__).resolve().parent\nos.environ.update(json.loads((p/'runtime.json').read_text()))\nos.execvpe(sys.argv[1], sys.argv[1:], os.environ)\n"""
    write(root / "run.py", runner)
    write(
        root / "redis.conf",
        f"port 0\nunixsocket {root}/redis/redis.sock\nunixsocketperm 700\ndir {root}/redis\nappendonly yes\ndaemonize no\n",
    )
    write(
        root / "nginx.conf",
        f"""worker_processes 1;
pid {root}/nginx.pid;
error_log {root}/logs/nginx-error.log;
events {{ worker_connections 1024; }}
http {{
 include /etc/nginx/mime.types;
 access_log off;
 client_body_temp_path {root}/nginx-client;
 proxy_temp_path {root}/nginx-proxy;
 fastcgi_temp_path {root}/nginx-fastcgi;
 uwsgi_temp_path {root}/nginx-uwsgi;
 scgi_temp_path {root}/nginx-scgi;
 server {{
  listen {c["port"]};
  server_name _;
  absolute_redirect off;
  # Gateways may strip the external /sim prefix before forwarding.
  # Keep explicit aliases only; do not turn arbitrary missing paths into the SPA.
  rewrite ^/(overview|issues|status|assets|weekly|favicon[.]svg)(/.*)?$ /sim/$1$2 last;
  location /api/ {{ proxy_pass http://127.0.0.1:{c["api_port"]}/api/; proxy_read_timeout 120s; }}
  location = / {{ return 302 /sim/overview; }}
  location = /sim {{ return 302 /sim/overview; }}
  location /sim/api/ {{ proxy_pass http://127.0.0.1:{c["api_port"]}/api/; proxy_read_timeout 120s; }}
  location = /sim/weekly {{ return 302 /sim/weekly/; }}
  location /sim/weekly/ {{ alias {root}/weekly/; index index.html; }}
  location /sim/ {{ alias {src}/ra_sim_repro_dashboard/frontend/dist/; index index.html; try_files $uri $uri/ /sim/index.html; }}
 }}
}}
""",
    )
    py = root / "venv/bin/python"
    prefix = f"{py} {root}/run.py"
    programs = {
        "postgres": (10, f"{pg}/postgres -D {root}/postgres"),
        "redis": (20, f"{shutil.which('redis-server')} {root}/redis.conf"),
        "api": (
            30,
            f"{prefix} {py} -m uvicorn app.main:app --host 127.0.0.1 --port {c['api_port']}",
        ),
        "worker": (
            40,
            f"{prefix} {root}/venv/bin/rq worker -u unix://{root}/redis/redis.sock ra_dashboard_refresh",
        ),
        "web": (50, f'{shutil.which("nginx")} -c {root}/nginx.conf -g "daemon off;"'),
    }
    if (root / "weekly.json").exists():
        programs["weekly"] = (60, f"{py} {root}/scheduler.py {root}")
    ini = f"""[unix_http_server]
file={root}/supervisor.sock
chmod=0700
[supervisord]
logfile={root}/logs/supervisord.log
pidfile={root}/supervisord.pid
childlogdir={root}/logs
logfile_maxbytes=10MB
logfile_backups=3
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix://{root}/supervisor.sock
"""
    for name, (priority, command) in programs.items():
        ini += f"""\n[program:{name}]
command={command}
directory={src}
priority={priority}
autostart=true
autorestart=true
startsecs=3
startretries=10
stopasgroup=true
killasgroup=true
stopwaitsecs=60
redirect_stderr=true
stdout_logfile={root}/logs/{name}.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
umask=0077
"""
    write(root / "supervisor.ini", ini)
    run(["nginx", "-t", "-c", root / "nginx.conf"])
    print("Prepared independent deployment; no source services changed.")


def ctl(c, *args):
    return run(["supervisorctl", "-c", Path(c["root"]) / "supervisor.ini", *args])


def sql(c, statement):
    return run(
        [
            Path(c["pg_bin"]) / "psql",
            "-h",
            Path(c["root"]) / "pgsocket",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            statement,
        ]
    )


def backup(c):
    root = Path(c["root"])
    dest = (
        root
        / "backups"
        / (
            "database-"
            + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + ".sql"
        )
    )
    temp = dest.with_suffix(".tmp")
    with temp.open("wb") as f:
        run(
            [
                Path(c["pg_bin"]) / "pg_dump",
                "-h",
                root / "pgsocket",
                "-d",
                "ra_sim",
                "--no-owner",
                "--no-privileges",
            ],
            stdout=f,
        )
    temp.chmod(0o600)
    temp.rename(dest)
    print(dest)
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument(
        "action",
        choices=["prepare", "start", "stop", "status", "check", "backup", "restore"],
    )
    p.add_argument("--dump")
    p.add_argument("--replace", action="store_true")
    a = p.parse_args()
    c = load(a.config)
    root = Path(c["root"])
    os.umask(0o077)
    if a.action == "prepare":
        prepare(c)
    elif a.action == "start":
        if (root / "supervisor.sock").exists():
            ctl(c, "start", "all")
        else:
            run(["supervisord", "-c", root / "supervisor.ini"])
    elif a.action == "stop":
        ctl(c, "stop", "all")
    elif a.action == "status":
        ctl(c, "status")
    elif a.action == "backup":
        backup(c)
    elif a.action == "restore":
        if not a.dump:
            p.error("--dump is required")
        # New pg_dump clients emit restrict guards that older psql cannot parse.
        # Accept only a matched pair in an explicitly supplied, trusted dump.
        dump_text = Path(a.dump).read_text()
        guards = re.findall(
            r"^\\(unrestrict|restrict) ([A-Za-z0-9]+)$", dump_text, re.M
        )
        if guards:
            if (
                len(guards) != 2
                or guards[0][0] != "restrict"
                or guards[1] != ("unrestrict", guards[0][1])
            ):
                raise ValueError("Invalid dump restriction guards")
            dump_text = re.sub(
                r"^\\(?:unrestrict|restrict) [A-Za-z0-9]+\n", "", dump_text, flags=re.M
            )
        # Never destroy an existing database without an explicit replacement and backup.
        ctl(c, "stop", "api", "worker")
        if a.replace:
            backup(c)
            sql(c, "DROP DATABASE ra_sim;")
        sql(c, "CREATE DATABASE ra_sim;")
        with tempfile.TemporaryFile() as f:
            f.write(dump_text.encode())
            f.seek(0)
            run(
                [
                    Path(c["pg_bin"]) / "psql",
                    "-h",
                    root / "pgsocket",
                    "-d",
                    "ra_sim",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "--single-transaction",
                ],
                stdin=f,
                stdout=subprocess.DEVNULL,
            )
        ctl(c, "start", "api", "worker")
    elif a.action == "check":
        ctl(c, "status")
        verify_http(f"http://127.0.0.1:{c['port']}")


if __name__ == "__main__":
    main()
