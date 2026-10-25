#!/usr/bin/env python3
"""Publish verified backup generations to the dedicated OFS backup mount."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import uuid

try:
    from .migration_files import file_sha256 as digest
except ImportError:  # Direct script invocation.
    from migration_files import file_sha256 as digest

MOUNT = Path("/mnt/ofs/manual-backups")
GENERATION = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")
FILES = {"database.dump": "dump_sha256", "attachments.tar.gz": "assets_sha256"}


def verified(path):
    if path.is_symlink() or not GENERATION.fullmatch(path.name):
        raise ValueError("Unexpected backup generation")
    if (path / "receipt.json").is_symlink():
        raise ValueError("Receipt symlink rejected")
    receipt = json.loads((path / "receipt.json").read_text())
    if not receipt.get("complete") or not receipt.get("restore_verified"):
        raise ValueError("Backup restore verification required")
    if {p.name for p in path.iterdir()} != {*FILES, "receipt.json"}:
        raise ValueError("Unexpected generation contents; do not prune")
    for name, key in FILES.items():
        p = path / name
        if p.is_symlink() or not p.is_file() or digest(p) != receipt[key]:
            raise ValueError("Backup hash mismatch")
    return receipt


def publish(source, base):
    receipt = verified(source)
    base.mkdir(mode=0o700, exist_ok=True)
    dest = base / source.name
    if dest.exists():
        remote = verified(dest)
        if any(remote[key] != receipt[key] for key in FILES.values()):
            raise ValueError("Existing replica has a different identity")
    else:
        used = sum(p.stat().st_size for p in base.rglob("*") if p.is_file())
        needed = sum((source / name).stat().st_size for name in FILES)
        if used + needed > 20 * 1024**3:
            raise RuntimeError("Replica capacity limit; existing backups preserved")
        temp = base / (".partial-" + uuid.uuid4().hex)
        temp.mkdir(mode=0o700)
        try:
            for name, key in FILES.items():
                with (source / name).open("rb") as inp, (temp / name).open("xb") as out:
                    shutil.copyfileobj(inp, out, length=4 * 1024**2)
                    out.flush()
                    os.fsync(out.fileno())
                if digest(temp / name) != receipt[key]:
                    raise ValueError("Replica readback hash mismatch")
            (temp / "receipt.json").write_text(json.dumps(receipt, indent=2))
            temp.rename(dest)
        except Exception:
            shutil.rmtree(temp)
            raise
        verified(dest)
    receipt["off_host_replica_verified"] = True
    receipt["replica"] = {
        "storage": "OFS remote-assist-stuck-model",
        "generation": source.name,
        "scope": "independent of target local-data; local backup retained for OFS outage",
    }
    for path in (source, dest):
        temp_receipt = path / ".receipt.tmp"
        temp_receipt.write_text(json.dumps(receipt, indent=2))
        temp_receipt.replace(path / "receipt.json")
    return dest


def prune(local, remote, keep=14):
    if keep < 14:
        raise ValueError("At least 14 generations must remain")
    common = sorted(
        p.name
        for p in local.iterdir()
        if GENERATION.fullmatch(p.name) and (remote / p.name).is_dir()
    )
    if len(common) <= keep:
        return []
    # Verify retained copies before removing any older generation. Unknown,
    # incomplete, pinned and nonmatching directories are never removed.
    for name in common:
        left, right = verified(local / name), verified(remote / name)
        if any(left[key] != right[key] for key in FILES.values()):
            raise ValueError("Retention refused: replica identity mismatch")
    removed = []
    for name in common[:-keep]:
        shutil.rmtree(local / name)
        shutil.rmtree(remote / name)
        removed.append(name)
    return removed


def check_mount():
    rows = [line.split() for line in Path("/proc/mounts").read_text().splitlines()]
    if not any(
        row[0] == "orangefs:remote-assist-stuck-model"
        and row[1] == str(MOUNT)
        and "rw" in row[3].split(",")
        for row in rows
    ):
        raise RuntimeError("Dedicated backup mount is unavailable")
    if (
        json.loads((MOUNT / ".manual-backups.json").read_text()).get("purpose")
        != "manual-backups"
    ):
        raise RuntimeError("Backup sentinel mismatch")


def replicate(source):
    os.umask(0o077)
    check_mount()
    remote = MOUNT / "scheduled"
    dest = publish(source, remote)
    removed = prune(source.parent, remote)
    return {
        "replica": str(dest),
        "sha256_verified": True,
        "removed_generations": removed,
        "retention": 14,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("generation", type=Path)
    args = p.parse_args()
    print(json.dumps(replicate(args.generation)))
