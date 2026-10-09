#!/usr/bin/env python3
"""Dry-run or SHA-pinned legacy Campaign mapping on an isolated S4 smoke DB."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from app.db import Database  # noqa: E402
from inventory_s4_campaigns import SAFE_DATABASE_RE, collect_inventory, read_url_file  # noqa: E402

SAFE_HOSTS = {"", "127.0.0.1", "::1", "localhost"}
POLICY_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true", help="apply only explicit mappings; unresolved splits remain read-only")
    parser.add_argument("--expected-inventory-sha256", default="")
    parser.add_argument("--policy-version", default="s4-campaign-v1")
    parser.add_argument("--actor", default="")
    return parser.parse_args()


def _validate_target(database: Database) -> dict[str, str]:
    with database.connect() as connection:
        if database.backend != "postgresql":
            raise RuntimeError("S4 Campaign migration requires PostgreSQL.")
        connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(
            "SELECT current_database() AS name, COALESCE(inet_server_addr()::text, '') AS host"
        ).fetchone()
        name, host = str(row["name"] or ""), str(row["host"] or "")
        if not SAFE_DATABASE_RE.fullmatch(name) or host not in SAFE_HOSTS:
            raise RuntimeError("S4 Campaign migration refuses a non-smoke or non-local database.")
        return {"database": name, "host": host or "local_socket"}


def _write_private_json(path: Path, value: dict[str, Any]) -> Path:
    output = path.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_metadata = os.stat(output.parent, follow_symlinks=False)
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
        or stat.S_IMODE(parent_metadata.st_mode) & 0o077
    ):
        raise RuntimeError("S4 migration output directory must be owned by the current user and private (0700 or stricter).")
    try:
        os.chmod(output.parent, 0o700)
    except OSError:
        pass
    temporary = output.with_suffix(output.suffix + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    os.chmod(output, 0o600)
    return output


def main() -> int:
    args = parse_args()
    url = read_url_file(Path(args.database_url_file))
    database = Database(
        url,
        postgres_migrations_dir=APP_ROOT / "migrations" / "postgres",
        pool_size=4,
    )
    result: dict[str, Any]
    try:
        target = _validate_target(database)
        report = collect_inventory(database)
        result = {
            **report,
            "mode": "apply_requested" if args.apply else "read_only_dry_run",
            "apply": None,
        }
        if args.apply:
            expected = str(args.expected_inventory_sha256 or "").strip().lower()
            actor = str(args.actor or "").strip()
            policy = str(args.policy_version or "").strip()
            if not SHA256_RE.fullmatch(expected):
                raise RuntimeError("--apply requires a 64-character --expected-inventory-sha256.")
            if expected != str(report.get("source_inventory_sha256") or ""):
                raise RuntimeError("S4 source inventory changed; regenerate the dry-run and inspect it before apply.")
            if not ACTOR_RE.fullmatch(actor):
                raise RuntimeError("--apply requires a valid --actor.")
            if not POLICY_RE.fullmatch(policy):
                raise RuntimeError("--policy-version has an invalid format.")
            # init() applies the new DDL migration only after the target and
            # current legacy inventory have both passed the smoke/SHA guards.
            database.init()
            result["apply"] = database.apply_legacy_campaign_inventory(
                inventory=report,
                expected_inventory_sha256=expected,
                policy_version=policy,
                actor=actor,
            )
            result["mode"] = "applied_explicit_mappings"
        output = _write_private_json(Path(args.output), result)
        summary = {
            "status": "passed",
            "mode": result["mode"],
            "database": target["database"],
            "source_inventory_sha256": report["source_inventory_sha256"],
            "split_count": report["split_count"],
            "proposed_purpose_counts": report["proposed_purpose_counts"],
            "read_only_count": report["read_only_ambiguous_or_conflicting_split_count"],
            "apply_counts": {
                key: result["apply"].get(key, 0)
                for key in ("mapped", "read_only", "already_applied")
            } if result["apply"] else None,
            "output": str(output),
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
