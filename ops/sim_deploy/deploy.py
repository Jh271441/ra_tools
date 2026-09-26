#!/usr/bin/env python3
"""Deploy an exported source bundle onto an arbitrary SSH target.
Requires a service-owner-writable root, Python >=3.10, uv, nginx, Redis,
Postgres tools, Supervisor and sudo for registering startup with Supervisor.
No SSH alias or host address is built in. Secrets are passed only as private files.
"""

import argparse
import datetime
import json
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

from manage import validate_config


def run(args):
    subprocess.run(args, check=True)


def deploy(
    config,
    bundle,
    secrets,
    dump=None,
    weekly=None,
    schedule_state=None,
    weekly_data=None,
):
    c = json.loads(Path(config).read_text())
    host = c.pop("ssh")
    if not host or host.startswith("-") or any(x.isspace() for x in host):
        raise ValueError("Invalid SSH destination")
    c = validate_config(dict(c, source=c["root"] + "/source"))
    root = c["root"]
    tag = (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    stage = f"{root}/incoming/{tag}"
    c["source"] = f"{root}/releases/{tag}"
    q = shlex.quote

    def remote(command):
        run(["ssh", "-o", "BatchMode=yes", host, command])

    remote(
        "test ! -e "
        + q(root + "/target.json")
        + ' || { echo "Deployment already exists"; exit 2; }; umask 077; mkdir -p '
        + q(stage)
    )
    with tempfile.TemporaryDirectory() as tmp:
        conf = Path(tmp) / "target.json"
        conf.write_text(json.dumps(c))
        files = [
            (Path(bundle), "source.tar.gz"),
            (Path(secrets), "secrets.json"),
            (conf, "target.json"),
            (Path(__file__).with_name("manage.py"), "manage.py"),
            (Path(__file__).with_name("check_http.py"), "check_http.py"),
            (Path(__file__).with_name("install_startup.py"), "install_startup.py"),
            (Path(__file__).with_name("weekly.py"), "weekly.py"),
            (Path(__file__).with_name("scheduler.py"), "scheduler.py"),
        ]
        if weekly_data:
            files.append((Path(weekly_data), "weekly-data.tar.gz"))
        if weekly:
            files.append((Path(weekly), "weekly.json"))
        if schedule_state:
            files.append((Path(schedule_state), "weekly-schedule-state.json"))
        if dump:
            files.append((Path(dump), "database.sql"))
        for src, name in files:
            run(["scp", "-q", str(src), host + ":" + q(stage + "/" + name)])
    # Fresh deployments only: a repeated invocation is non-destructive and stops
    # before changing the live configuration. Upgrades use a new root and migrate.
    remote(f"""set -eu
umask 077
test ! -e {q(root + "/target.json")} || {{ echo 'Deployment exists: use a new root for staged migration.'; exit 2; }}
command -v uv nginx redis-server supervisord supervisorctl >/dev/null
test -x {q(c["pg_bin"] + "/initdb")}
mkdir -p {q(c["source"])}
tar -xzf {q(stage + "/source.tar.gz")} -C {q(c["source"])}
cp {q(stage + "/target.json")} {q(stage + "/secrets.json")} {q(stage + "/manage.py")} {q(stage + "/check_http.py")} {q(stage + "/install_startup.py")} {q(stage + "/weekly.py")} {q(stage + "/scheduler.py")} {q(root + "/")}
if test -f {q(stage + "/weekly-data.tar.gz")}; then mkdir -p {q(root + "/weekly")}; tar -xzf {q(stage + "/weekly-data.tar.gz")} -C {q(root + "/weekly")}; fi
if test -f {q(stage + "/weekly.json")}; then cp {q(stage + "/weekly.json")} {q(root + "/weekly.json")}; fi
if test -f {q(stage + "/weekly-schedule-state.json")}; then cp {q(stage + "/weekly-schedule-state.json")} {q(root + "/weekly-schedule-state.json")}; fi
uv venv {q(root + "/venv")} --python python3
uv pip install --python {q(root + "/venv/bin/python")} -r {q(c["source"] + "/ra_sim_repro_dashboard/backend/requirements.txt")}
uv pip install --python {q(root + "/venv/bin/python")} pandas==2.3.3 requests==2.34.2
python3 {q(root + "/manage.py")} --config {q(root + "/target.json")} prepare
python3 {q(root + "/manage.py")} --config {q(root + "/target.json")} start
""")
    if dump:
        remote(
            f"python3 {q(root + '/manage.py')} --config {q(root + '/target.json')} restore --dump {q(stage + '/database.sql')}"
        )
    else:
        remote(
            f"sleep 3; {q(c['pg_bin'] + '/createdb')} -h {q(root + '/pgsocket')} ra_sim"
        )
    remote(
        f"sleep 5; python3 {q(root + '/manage.py')} --config {q(root + '/target.json')} check"
    )
    remote(
        f"python3 {q(root + '/install_startup.py')} --config {q(root + '/target.json')}"
    )
    remote(
        f"sleep 5; python3 {q(root + '/manage.py')} --config {q(root + '/target.json')} check"
    )
    print("Deployment verified and persistent startup installed.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True)
    p.add_argument("--bundle", required=True)
    p.add_argument("--secrets", required=True)
    p.add_argument("--dump")
    p.add_argument("--weekly")
    p.add_argument("--schedule-state")
    p.add_argument("--weekly-data")
    a = p.parse_args()
    deploy(
        a.target, a.bundle, a.secrets, a.dump, a.weekly, a.schedule_state, a.weekly_data
    )
