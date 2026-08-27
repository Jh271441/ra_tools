from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import stat
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from .review_mentions import MENTION_USERNAME_RE


_ALLOWED_DCHAT_ENDPOINTS = {
    "oapi-dichat.intra.xiaojukeji.com": "",
    "api-kylin.intra.xiaojukeji.com": "/snitch_openapi_online_lb",
}
_MAX_CREDENTIAL_BYTES = 16 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_DCHAT_TEXT_LENGTH = 3000


class DChatSendError(RuntimeError):
    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class DChatCredentials:
    client_id: str
    client_secret: str
    bot_id: str


@dataclass(frozen=True)
class DChatSendResult:
    trace_id: str
    message_unique_id: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise DChatSendError("DChat OpenAPI 返回了未允许的重定向。", transient=False)


def validate_dchat_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    allowed_path = _ALLOWED_DCHAT_ENDPOINTS.get(str(parsed.hostname or "").lower())
    if (
        parsed.scheme != "https"
        or allowed_path is None
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != allowed_path
    ):
        raise RuntimeError("DChat OpenAPI 地址必须是已批准的 HTTPS 国内或备用域名。")
    return raw


def _read_credentials(path: Path) -> DChatCredentials:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DChatSendError("DChat 凭据文件必须是普通文件。", transient=False)
        if metadata.st_uid != os.getuid():
            raise DChatSendError("DChat 凭据文件必须属于当前服务用户。", transient=False)
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise DChatSendError("DChat 凭据文件权限必须为 0600。", transient=False)
        content = os.read(descriptor, _MAX_CREDENTIAL_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(content) > _MAX_CREDENTIAL_BYTES:
        raise DChatSendError("DChat 凭据文件内容过长。", transient=False)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DChatSendError("DChat 凭据文件不是合法 JSON。", transient=False) from exc
    if not isinstance(payload, dict):
        raise DChatSendError("DChat 凭据文件必须是 JSON 对象。", transient=False)
    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    bot_id = str(payload.get("bot_id") or "").strip()
    if not client_id or not client_secret or not bot_id.isdigit():
        raise DChatSendError(
            "DChat 凭据文件必须包含 client_id、client_secret 和数字 bot_id。",
            transient=False,
        )
    if any(len(value) > 512 for value in (client_id, client_secret, bot_id)):
        raise DChatSendError("DChat 凭据字段过长。", transient=False)
    return DChatCredentials(client_id, client_secret, bot_id)


def dchat_credentials_status(path: Path) -> dict[str, Any]:
    try:
        _read_credentials(path)
    except FileNotFoundError:
        return {"ready": False, "message": "DChat BotUser 凭据文件不存在。"}
    except (OSError, DChatSendError) as exc:
        message = (
            str(exc)
            if isinstance(exc, DChatSendError)
            else "DChat BotUser 凭据文件无法读取。"
        )
        return {"ready": False, "message": message[:240]}
    return {"ready": True, "message": "DChat BotUser 凭据可用。"}


def _markdown_plaintext(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    for character in (
        "\\", "`", "*", "_", "{", "}", "[", "]", "(", ")",
        "#", "+", "-", ".", "!", ">",
    ):
        text = text.replace(character, f"\\{character}")
    return text


def build_review_notification_text(
    *,
    issue_id: str,
    author: str,
    note: str,
    review_url: str,
) -> str:
    excerpt = str(note or "").strip()
    if len(excerpt) > 1200:
        excerpt = excerpt[:1199] + "…"
    lines = [
        "**【RA Triage】你在判错复核中被 @提及**",
        "",
        f"{_markdown_plaintext(author or '一位复核人')} 在 `{_markdown_plaintext(issue_id)}` 的 Review 中提到了你：",
    ]
    if excerpt:
        lines.extend(["", f"> {_markdown_plaintext(excerpt).replace(chr(10), chr(10) + '> ')}"])
    lines.extend(["", f"[查看 Review 详情]({review_url})"])
    return "\n".join(lines)[:_MAX_DCHAT_TEXT_LENGTH]


def build_comment_notification_text(
    *,
    issue_id: str,
    author: str,
    body: str,
    review_url: str,
    is_reply: bool = False,
) -> str:
    excerpt = str(body or "").strip()
    if len(excerpt) > 1200:
        excerpt = excerpt[:1199] + "…"
    action = "回复了你的评论" if is_reply else "在评论中提到了你"
    lines = [
        "**【RA Triage】评论通知**",
        "",
        f"{_markdown_plaintext(author or '一位同事')} 在 `{_markdown_plaintext(issue_id)}` 中{action}：",
    ]
    if excerpt:
        lines.extend(["", f"> {_markdown_plaintext(excerpt).replace(chr(10), chr(10) + '> ')}"])
    lines.extend(["", f"[查看评论]({review_url})"])
    return "\n".join(lines)[:_MAX_DCHAT_TEXT_LENGTH]


def build_review_url(return_url: str, *, issue_id: str, model_run_id: str = "") -> str:
    parsed = urlparse(return_url)
    query = {"issue": issue_id}
    if model_run_id:
        query["run"] = model_run_id
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


class DChatClient:
    def __init__(
        self, *, base_url: str, credentials_file: Path, timeout_seconds: float
    ) -> None:
        self.base_url = validate_dchat_base_url(base_url)
        self.credentials_file = credentials_file
        self.timeout_seconds = max(0.2, min(float(timeout_seconds), 10.0))

    def send_to_username(self, username: str, text: str) -> DChatSendResult:
        recipient = str(username or "").strip().lower()
        if not MENTION_USERNAME_RE.fullmatch(recipient):
            raise DChatSendError("DChat 收件人 LDAP 格式不合法。", transient=False)
        try:
            credentials = _read_credentials(self.credentials_file)
        except DChatSendError:
            raise
        except OSError as exc:
            raise DChatSendError(
                "DChat BotUser 凭据文件无法读取。", transient=False
            ) from exc
        payload = json.dumps(
            {
                "receive_id": recipient,
                "receive_id_type": "2",
                "text": str(text or "")[:_MAX_DCHAT_TEXT_LENGTH],
                "markdown": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        token = base64.b64encode(
            f"{credentials.client_id}:{credentials.client_secret}".encode("utf-8")
        ).decode("ascii")
        request = urllib.request.Request(
            f"{self.base_url}/v3/message.create",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json;charset=utf-8",
                "X-Bot-Type": "bot_user",
                "X-Bot-Id": credentials.bot_id,
            },
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirect(),
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                content = response.read(_MAX_RESPONSE_BYTES + 1)
        except DChatSendError:
            raise
        except urllib.error.HTTPError as exc:
            transient = exc.code == 429 or 500 <= exc.code < 600
            raise DChatSendError(
                f"DChat OpenAPI HTTP {exc.code}。", transient=transient
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DChatSendError("DChat OpenAPI 暂时不可达。", transient=True) from exc
        if len(content) > _MAX_RESPONSE_BYTES:
            raise DChatSendError("DChat OpenAPI 响应过大。", transient=True)
        try:
            response_payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DChatSendError("DChat OpenAPI 返回了非法 JSON。", transient=True) from exc
        code = response_payload.get("code") if isinstance(response_payload, dict) else None
        if code != 0:
            transient = code == 1006
            raise DChatSendError(
                f"DChat OpenAPI 返回错误码 {code!s}。", transient=transient
            )
        result = response_payload.get("result") or {}
        return DChatSendResult(
            trace_id=str(result.get("trace_id") or "")[:128],
            message_unique_id=str(result.get("message_unique_id") or "")[:256],
        )


class DChatLoopbackClient:
    """Development-only sink that exercises dispatch without network I/O."""

    @staticmethod
    def send_to_username(username: str, text: str) -> DChatSendResult:
        digest = hashlib.sha256(
            f"{str(username).lower()}\0{text}".encode("utf-8")
        ).hexdigest()[:32]
        return DChatSendResult(
            trace_id=f"loopback-{digest[:16]}",
            message_unique_id=f"loopback-{digest}",
        )
