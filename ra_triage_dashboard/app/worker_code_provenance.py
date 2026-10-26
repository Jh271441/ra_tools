"""Verify pinned RA exports before the worker imports external code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


REQUIRED_MODULES = {"vlm/__init__.py", "utils/config.py", "core/batch_engine.py"}
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def verified_export_commit(ra_root: Path, manifest_pin: str) -> str:
    root = ra_root.resolve()
    manifest = root / "migration-code-receipt.json"
    if not SHA256_RE.fullmatch(manifest_pin):
        raise ValueError("RA 代码清单 SHA-256 配置非法。")
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("RA 代码清单缺失或格式非法。")
    with manifest.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("RA 代码清单缺失或格式非法。")
    if hashlib.sha256(raw).hexdigest() != manifest_pin:
        raise ValueError("RA 代码清单与部署固定 SHA-256 不一致。")
    try:
        receipt = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("RA 代码清单缺失或格式非法。") from exc
    if not isinstance(receipt, dict):
        raise ValueError("RA 代码清单缺失或格式非法。")
    source_sha = receipt.get("source_sha", "")
    files = receipt.get("files_sha256")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("RA 代码来源版本非法。")
    if not isinstance(files, dict) or not REQUIRED_MODULES.issubset(files):
        raise ValueError("RA 代码清单缺少必要模块。")
    for name, expected in files.items():
        relative = Path(name)
        path = root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or not path.is_file()
            or not isinstance(expected, str)
            or not SHA256_RE.fullmatch(expected)
        ):
            raise ValueError("RA 代码清单包含非法文件。")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"RA 代码文件与部署清单不一致: {name}")
    actual_python = {
        str(path.relative_to(root)) for path in root.rglob("*.py") if path.is_file()
    }
    if actual_python != {name for name in files if name.endswith(".py")}:
        raise ValueError("RA 代码目录存在清单外或缺失的 Python 模块。")
    return source_sha
