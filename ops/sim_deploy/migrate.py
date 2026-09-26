#!/usr/bin/env python3
"""Migrate between native deployments: quiesce, export, deploy, verify, retire.
Only operates on this deployment's child Supervisor. Never stops host services.
"""

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from deploy import deploy


def main(source_config, target_config):
    c = json.loads(Path(source_config).read_text())
    host = c["ssh"]
    root = c["root"]
    if host.startswith("-") or any(x.isspace() for x in host):
        raise ValueError("Invalid SSH host")
    q = shlex.quote

    def remote(command):
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", host, command],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    ctl = f"supervisorctl -c {q(root + '/supervisor.ini')}"
    # Refuse to interrupt a refresh that may be writing a partially updated cohort.
    probe = """import json, urllib.request
r=json.load(urllib.request.urlopen("http://127.0.0.1:"+str(CONFIG["port"])+"/sim/api/system/status",timeout=30))
checks={c["key"]:c for c in r["checks"]}
assert checks["queue"]["extra"]["pending_jobs"]==0, "Refresh queue not empty"
assert checks["last_refresh"]["extra"].get("job_status") not in ("queued","running"), "Refresh still running"
"""
    command = (
        "import json\nCONFIG=json.load(open("
        + repr(root + "/target.json")
        + "))\n"
        + probe
    )
    remote("python3 -c " + q(command))
    names = remote(ctl + " status")
    programs = [
        n
        for n in ("weekly", "api", "worker", "web")
        if any(line.split()[0] == n for line in names.splitlines())
    ]
    frozen = False
    target_attempted = False
    try:
        frozen = True
        remote(ctl + " stop " + " ".join(programs))
        dump = (
            remote(
                f"python3 {q(root + '/manage.py')} --config {q(root + '/target.json')} backup"
            )
            .strip()
            .splitlines()[-1]
        )
        command = """import json, tarfile
from pathlib import Path
c=json.load(open(CONFIG_PATH));src=Path(c['source']);dest=Path(c['root'])/'backups/migration-source.tar.gz'
with tarfile.open(dest,'w:gz') as tar:
 for name in ('ra_sim_repro_dashboard','reports','scripts','ra_api','tests'):
  if (src/name).exists():
   def filt(info):
    parts=Path(info.name).parts
    return None if any(p in ('.git','.venv','node_modules','__pycache__','.env','.env.local') for p in parts) else info
   tar.add(src/name,arcname=name,filter=filt)
print(dest)
""".replace("CONFIG_PATH", repr(root + "/target.json"))
        bundle = remote("python3 -c " + q(command)).strip()
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            for path, name in [
                (dump, "database.sql"),
                (bundle, "source.tar.gz"),
                (root + "/secrets.json", "secrets.json"),
            ]:
                subprocess.run(
                    ["scp", "-q", host + ":" + q(path), str(temp / name)], check=True
                )
            optional = {}
            for name in ("weekly.json", "weekly-schedule-state.json"):
                if (
                    remote(
                        "test -f " + q(root + "/" + name) + " && echo yes || true"
                    ).strip()
                    == "yes"
                ):
                    subprocess.run(
                        [
                            "scp",
                            "-q",
                            host + ":" + q(root + "/" + name),
                            str(temp / name),
                        ],
                        check=True,
                    )
                    optional[name] = temp / name
            # Explicit manifest paths must be portable relative to the source tree.
            if optional.get("weekly.json"):
                cfg = json.loads(optional["weekly.json"].read_text())
                for period in cfg["periods"]:
                    if period.get("manifest", "").startswith("/"):
                        raise ValueError(
                            "Use source-relative manifest paths before migrating weekly configuration"
                        )
            weekly_data = None
            if (
                remote(
                    "test -d " + q(root + "/weekly") + " && echo yes || true"
                ).strip()
                == "yes"
            ):
                remote(
                    "tar -czf "
                    + q(root + "/backups/weekly-data.tar.gz")
                    + " -C "
                    + q(root + "/weekly")
                    + " ."
                )
                weekly_data = temp / "weekly-data.tar.gz"
                subprocess.run(
                    [
                        "scp",
                        "-q",
                        host + ":" + q(root + "/backups/weekly-data.tar.gz"),
                        str(weekly_data),
                    ],
                    check=True,
                )
            target_attempted = True
            deploy(
                target_config,
                temp / "source.tar.gz",
                temp / "secrets.json",
                temp / "database.sql",
                optional.get("weekly.json"),
                optional.get("weekly-schedule-state.json"),
                weekly_data,
            )
        retire = """import configparser
from pathlib import Path
p=Path(CONFIG); c=configparser.ConfigParser(interpolation=None);c.read(p)
for name in NAMES:c['program:'+name]['autostart']='false'
with p.open('w') as f:c.write(f)
""".replace("CONFIG", repr(root + "/supervisor.ini")).replace("NAMES", repr(programs))
        remote("python3 -c " + q(retire))
        remote(ctl + " reread")
        remote(ctl + " update")
        print(
            "Target verified. Source web/API/worker/scheduler remain stopped with autostart disabled for rollback."
        )
    except BaseException:
        if frozen and not target_attempted:
            remote(ctl + " start " + " ".join(programs))
        elif frozen:
            print(
                "Source remains stopped: target deployment was attempted. Verify and stop target writers before resuming source.",
                file=sys.stderr,
            )
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    a = p.parse_args()
    main(a.source, a.target)
