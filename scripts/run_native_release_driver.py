#!/usr/bin/env python3
"""Run the release driver with a pinned, server-local SDK and durable receipts."""
from __future__ import annotations

import json
import os
import pwd
from pathlib import Path
import sys


def command_environment(config, inherited):
    repo = Path(config["repo_root"])
    paths = [repo, *map(Path, config["python_paths"])]
    python = Path(config["python"])
    driver = repo / "scripts/ra_release_orion_driver.py"
    if not python.is_file() or not driver.is_file() or any(not p.is_dir() for p in paths):
        raise ValueError("Native release driver runtime is incomplete")
    env = dict(inherited)
    # Supervisor may retain root's login variables after dropping its uid.
    # SDK runtime caches must belong to the effective service account.
    account = pwd.getpwuid(os.geteuid())
    env.update(HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name)
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "PYTHONHOME", "PYTHONUSERBASE", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        env.pop(key, None)
    env.update(PYTHONPATH=os.pathsep.join(map(str, paths)),
               RELEASE_DRIVER_REPO_ROOT=str(repo),
               RELEASE_DRIVER_STATE_DIR=config["state_dir"],
               PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    # Reuse the server's existing Orion login without creating another credential file.
    # Explicit path avoids dependence on Supervisor's HOME, which may differ from SSH.
    if not env.get("ORION_TOKEN") and config.get("auth_config"):
        auth_path = Path(config["auth_config"])
        if not auth_path.is_absolute():
            raise ValueError("Orion auth config path must be absolute")
        auth = json.loads(auth_path.read_text())
        if auth.get("version") != 1 or not auth.get("auth", {}).get("CN"):
            raise ValueError("Server Orion login is unavailable")
        env["ORION_TOKEN"] = auth["auth"]["CN"]
    return [str(python), str(driver)], env


def main():
    os.umask(0o077)
    command, env = command_environment(json.loads(Path(sys.argv[1]).read_text()), os.environ)
    os.execve(command[0], command, env)


if __name__ == "__main__":
    main()
