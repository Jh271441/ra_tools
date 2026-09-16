#!/usr/bin/env python3
"""Run the exact origin/master Dashboard deployer on cloud_server."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]
DEPLOYER_PATH = "ra_triage_dashboard/scripts/deploy_cloud.py"
DEFAULT_HOST = "cloud_server"
DEFAULT_REMOTE_REPO = "/volume/home/workspace/ra_tools"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
HOST_PATTERN = re.compile(r"[A-Za-z0-9_.@-]+")
REMOTE_BOOTSTRAP = """\
import os
import subprocess
import sys
import tempfile

repo, *args = sys.argv[1:]
fd, path = tempfile.mkstemp(prefix="ra-dashboard-deploy-", suffix=".py")
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(sys.stdin.buffer.read())
    completed = subprocess.run([sys.executable, path, *args], cwd=repo)
    raise SystemExit(completed.returncode)
finally:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
"""


class ReleaseError(RuntimeError):
    pass


def git_bytes(*args):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode(errors="replace").strip()
        raise ReleaseError(message or "Git command failed") from exc


def resolve_target(requested_sha=None):
    git_bytes("fetch", "origin", "master")
    target = git_bytes("rev-parse", "origin/master").decode().strip()
    if not SHA_PATTERN.fullmatch(target):
        raise ReleaseError("origin/master did not resolve to a full commit SHA")
    if requested_sha is not None:
        if not SHA_PATTERN.fullmatch(requested_sha):
            raise ReleaseError("--sha must be a full 40-character commit SHA")
        if requested_sha != target:
            raise ReleaseError("Requested SHA is not current origin/master")
    return target


def exact_deployer(target):
    versioned = git_bytes("show", f"{target}:{DEPLOYER_PATH}")
    local = REPO / DEPLOYER_PATH
    if not local.is_file() or local.read_bytes() != versioned:
        raise ReleaseError("Local deployer differs from origin/master; push the reviewed deployer first")
    return versioned


def validate_destination(host, remote_repo):
    if not HOST_PATTERN.fullmatch(host) or host.startswith("-"):
        raise ReleaseError("Unsafe SSH host")
    if remote_repo != DEFAULT_REMOTE_REPO:
        raise ReleaseError("Remote repository must be the configured cloud_server checkout")
    path = PurePosixPath(remote_repo)
    if not path.is_absolute() or ".." in path.parts or any("\n" in part or "\r" in part for part in path.parts):
        raise ReleaseError("Remote repository must be a safe absolute path")


def deployer_args(args, target):
    result = ["--sha", target]
    if args.check:
        result.append("--check")
    elif args.prepare:
        result.append("--prepare")
    elif args.promote:
        result.extend(["--promote", args.promote])
    if args.allow_additive_migrations:
        result.append("--allow-additive-migrations")
    if args.allow_schema_migrations:
        result.append("--allow-schema-migrations")
    return result


def run_remote(host, remote_repo, remote_args, deployer):
    command = shlex.join(["python3", "-c", REMOTE_BOOTSTRAP, remote_repo, *remote_args])
    try:
        return subprocess.run(["ssh", host, command], input=deployer).returncode
    except OSError as exc:
        raise ReleaseError(f"Unable to start ssh: {exc}") from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="run cloud preflight only")
    action.add_argument("--prepare", action="store_true", help="run tests and isolated gray without changing production")
    action.add_argument("--promote", metavar="RELEASE_ID", help="promote a prepared release")
    migration = parser.add_mutually_exclusive_group()
    migration.add_argument("--allow-additive-migrations", action="store_true")
    migration.add_argument("--allow-schema-migrations", action="store_true")
    parser.add_argument("--sha", help="full origin/master SHA; defaults to the fetched remote SHA")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"SSH host alias (default: {DEFAULT_HOST})")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        validate_destination(args.host, DEFAULT_REMOTE_REPO)
        target = resolve_target(args.sha)
        deployer = exact_deployer(target)
        print(f"Dashboard target: {target}", flush=True)
        return run_remote(
            args.host,
            DEFAULT_REMOTE_REPO,
            deployer_args(args, target),
            deployer,
        )
    except ReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
