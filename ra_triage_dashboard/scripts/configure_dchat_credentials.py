#!/usr/bin/env python3
"""Interactively create the project-local DChat credential file."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = PROJECT_ROOT / "dchat_credentials.json"


def write_credentials(
    target: Path,
    *,
    client_id: str,
    client_secret: str,
    bot_id: str,
) -> None:
    client_id = str(client_id or "").strip()
    client_secret = str(client_secret or "").strip()
    bot_id = str(bot_id or "").strip()
    if not client_id:
        raise ValueError("Client ID 不能为空。")
    if not client_secret:
        raise ValueError("Client Secret 不能为空。")
    if not bot_id.isdigit():
        raise ValueError("Bot ID 必须是纯数字。")

    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "bot_id": bot_id,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    print(f"将生成：{DEFAULT_TARGET}")
    if DEFAULT_TARGET.exists():
        answer = input("文件已存在，确认覆盖？[y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("已取消，原文件未修改。")
            return 1

    client_id = input("正式应用 Client ID: ").strip()
    client_secret = getpass.getpass("正式应用 Client Secret（输入不显示）: ")
    bot_id = input("正式 Bot ID（纯数字）: ").strip()
    try:
        write_credentials(
            DEFAULT_TARGET,
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id,
        )
    except ValueError as exc:
        print(f"配置失败：{exc}")
        return 2

    print(f"配置完成：{DEFAULT_TARGET}")
    print("文件权限：0600；该路径已被 Git 忽略。")
    print("启动时设置：DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
