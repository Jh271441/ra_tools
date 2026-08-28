from __future__ import annotations

import hashlib
import hmac
import os
import stat
import time
from pathlib import Path


MAX_SECRET_BYTES = 16 * 1024


class SecretError(RuntimeError):
    pass


def read_secret_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SecretError("Bot 密钥文件不可读取。") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size <= 0
            or info.st_size > MAX_SECRET_BYTES
        ):
            raise SecretError("Bot 密钥必须是当前服务用户持有的 0600 普通文件。")
        value = os.read(descriptor, MAX_SECRET_BYTES + 1).strip()
    finally:
        os.close(descriptor)
    if not value or len(value) > MAX_SECRET_BYTES or b"\0" in value:
        raise SecretError("Bot 密钥内容非法。")
    return value


def verify_webhook(
    *,
    body: bytes,
    secret: bytes,
    mode: str,
    signature: str,
    timestamp: str = "",
    now: float | None = None,
) -> bool:
    if mode == "token":
        return hmac.compare_digest(signature.strip(), secret.decode("utf-8"))
    if mode != "hmac":
        return False
    signed = body
    if timestamp:
        try:
            event_time = int(timestamp)
        except ValueError:
            return False
        current = int(now if now is not None else time.time())
        if abs(current - event_time) > 300:
            return False
        signed = timestamp.encode("ascii") + b"." + body
    expected = hmac.new(secret, signed, hashlib.sha256).hexdigest()
    supplied = signature.strip().lower()
    if supplied.startswith("sha256="):
        supplied = supplied[7:]
    return hmac.compare_digest(supplied, expected)
