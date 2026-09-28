#!/usr/bin/env python3
"""Install the RA portal on a target Linux host with Nginx and system Supervisor."""

import argparse
import getpass
import os
import re
import shutil
import subprocess
from pathlib import Path


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def install(root, port, manual_port, sim_port):
    root = Path(root).resolve()
    owner = getpass.getuser()
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(root)) or root == Path("/"):
        raise ValueError(
            "Use an absolute deployment directory without special characters"
        )
    for value in (port, manual_port, sim_port):
        if not 1 <= value <= 65535:
            raise ValueError("Invalid port")
    if len({port, manual_port, sim_port}) != 3:
        raise ValueError("Portal and upstream ports must differ")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", owner):
        raise ValueError("Unsupported service user")
    root.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)
    for asset in ("index.html", "favicon.svg"):
        source = Path(__file__).with_name(asset).resolve()
        if source != root / asset:
            shutil.copyfile(source, root / asset)
    config = f"""user {owner};
worker_processes 1;
pid {root}/nginx.pid;
error_log {root}/logs/error.log;
events {{ worker_connections 1024; }}
http {{
 include /etc/nginx/mime.types;
 access_log off;
 client_body_temp_path {root}/client_temp;
 proxy_temp_path {root}/proxy_temp;
 fastcgi_temp_path {root}/fastcgi_temp;
 uwsgi_temp_path {root}/uwsgi_temp;
 scgi_temp_path {root}/scgi_temp;
 proxy_http_version 1.1;
 proxy_set_header Host $http_host;
 proxy_set_header X-Real-IP $remote_addr;
 proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
 proxy_set_header X-Forwarded-Host $http_host;
 proxy_set_header X-Forwarded-Proto $scheme;
 # This direct-IP entry does not authenticate users or inject identity.
 proxy_set_header X-SSO-User "";
 proxy_set_header X-RA-Triage-Ingress "";
 proxy_read_timeout 300s;
 client_max_body_size 100m;
 server {{
  listen {port};
  server_name _;
  absolute_redirect off;
  location = / {{ root {root}; try_files /index.html =404; add_header Cache-Control "no-cache"; }}
  location = /favicon.svg {{ root {root}; try_files /favicon.svg =404; add_header Cache-Control "no-cache"; }}
  location = /favicon.ico {{ return 302 /favicon.svg; }}
  location = /healthz {{ default_type application/json; return 200 '{{"status":"ok"}}'; }}
  location = /manual {{ return 302 /manual/; }}
  location /manual/ {{ proxy_pass http://127.0.0.1:{manual_port}; }}
  location = /sim {{ return 302 /sim/overview; }}
  location /sim/ {{ proxy_pass http://127.0.0.1:{sim_port}; }}
  location / {{ return 404; }}
 }}
}}
"""
    candidate = root / "nginx.candidate.conf"
    candidate.write_text(config)
    run("sudo", "-n", "nginx", "-t", "-c", candidate)
    current = root / "nginx.conf"
    if current.exists():
        shutil.copyfile(current, root / "nginx.previous.conf")
    os.replace(candidate, current)
    program = f"ra_portal_{port}"
    ini = f"""[program:{program}]
command=/usr/sbin/nginx -c {root}/nginx.conf -g "daemon off;"
user=root
autostart=true
autorestart=true
startsecs=3
stopsignal=QUIT
stopwaitsecs=30
redirect_stderr=true
stdout_logfile={root}/logs/supervisor.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
"""
    local = root / "supervisor.conf"
    local.write_text(ini)
    target = Path("/etc/supervisor/conf.d") / (program + ".conf")
    exists = target.exists()
    run("sudo", "-n", "install", "-m", "644", local, target)
    run("sudo", "-n", "supervisorctl", "reread")
    run("sudo", "-n", "supervisorctl", "update", program)
    if exists:
        run("sudo", "-n", "supervisorctl", "signal", "HUP", program)
    run("sudo", "-n", "supervisorctl", "status", program)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--port", type=int, default=80)
    p.add_argument("--manual-port", type=int, default=8785)
    p.add_argument("--sim-port", type=int, default=8787)
    a = p.parse_args()
    install(a.root, a.port, a.manual_port, a.sim_port)
