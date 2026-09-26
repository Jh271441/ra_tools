#!/usr/bin/env python3
"""Install a deployment as a child of an existing system Supervisor (sudo required)."""

import argparse
import getpass
import hashlib
import shutil
import tempfile
from pathlib import Path

from manage import load, run


def install(config):
    c = load(config)
    root = Path(c["root"])
    name = "ra_sim_" + hashlib.sha256(str(root).encode()).hexdigest()[:10]
    ini = f"""[program:{name}]
command={shutil.which("supervisord")} -n -c {root}/supervisor.ini
user={getpass.getuser()}
directory={root}
autostart=true
autorestart=true
startsecs=5
startretries=10
stopsignal=TERM
stopwaitsecs=180
stopasgroup=false
killasgroup=true
umask=0077
redirect_stderr=true
stdout_logfile={root}/logs/parent-supervisor.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
"""
    dest = Path("/etc/supervisor/conf.d") / (name + ".conf")
    if dest.exists() and dest.read_text() == ini:
        run(["sudo", "-n", "supervisorctl", "start", name])
        return
    if (root / "supervisor.sock").exists():
        run(["supervisorctl", "-c", root / "supervisor.ini", "shutdown"])
        import time

        for _ in range(180):
            if not (root / "supervisor.sock").exists():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Existing Supervisor did not shut down")
    with tempfile.NamedTemporaryFile(mode="w") as f:
        f.write(ini)
        f.flush()
        run(["sudo", "-n", "install", "-m", "644", f.name, dest])
    run(["sudo", "-n", "supervisorctl", "reread"])
    run(["sudo", "-n", "supervisorctl", "update", name])
    print(name)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    install(p.parse_args().config)
