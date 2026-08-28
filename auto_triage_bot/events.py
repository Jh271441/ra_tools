from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit


USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
ISSUE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{6,128})(?![A-Za-z0-9_-])")


@dataclass(frozen=True)
class IncomingEvent:
    event_id: str
    sender: str
    text: str
    chat_id: str = ""
    event_type: str = "message"


def challenge_value(payload: dict[str, Any]) -> str:
    value = payload.get("challenge")
    if isinstance(value, str) and 1 <= len(value) <= 512:
        return value
    return ""


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("content", "text", "body"):
            found = _text(value.get(key))
            if found:
                return found
    return ""


def parse_event(payload: dict[str, Any], *, max_chars: int = 3000) -> IncomingEvent:
    data = _dict(payload.get("data"))
    event = _dict(payload.get("event")) or data
    message = _dict(event.get("message")) or _dict(payload.get("message"))
    sender_obj = _dict(event.get("sender")) or _dict(payload.get("sender"))
    sender = next(
        (
            str(value).strip().lower()
            for value in (
                sender_obj.get("username"),
                sender_obj.get("ldap"),
                event.get("sender_username"),
                payload.get("sender_username"),
                payload.get("username"),
                event.get("senderStaffId"),
            )
            if value
        ),
        "",
    )
    text = next(
        (
            value
            for value in (
                _text(message.get("text")),
                _text(message.get("content")),
                _text(event.get("text")),
                _text(payload.get("text")),
            )
            if value
        ),
        "",
    )
    raw_event_id = next(
        (
            str(value).strip()
            for value in (
                event.get("event_id"),
                event.get("eventId"),
                message.get("message_id"),
                message.get("msg_id"),
                event.get("msgId"),
                payload.get("event_id"),
                payload.get("msgId"),
            )
            if value
        ),
        "",
    )
    if not USERNAME_RE.fullmatch(sender):
        raise ValueError("DChat 事件缺少合法的发送人 LDAP。")
    if not text or len(text) > max_chars or any(char == "\0" for char in text):
        raise ValueError("DChat 事件消息为空或过长。")
    event_id = raw_event_id[:256] if raw_event_id else hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    chat_id = str(
        event.get("chat_id")
        or event.get("conversation_id")
        or payload.get("chat_id")
        or ""
    ).strip()[:256]
    return IncomingEvent(event_id=event_id, sender=sender, text=text, chat_id=chat_id)


def extract_issue_id(text: str) -> str:
    for token in re.findall(r"https?://[^\s<>()]+", text):
        parsed = urlsplit(token.rstrip(".,;，。；"))
        query = parse_qs(parsed.query)
        for key in ("issue", "issue_id", "id"):
            for value in query.get(key, []):
                if _looks_like_issue(value):
                    return value
        for part in reversed([part for part in parsed.path.split("/") if part]):
            if _looks_like_issue(part):
                return part
    for match in ISSUE_TOKEN_RE.finditer(text):
        value = match.group(1)
        if _looks_like_issue(value):
            return value
    return ""


def extract_run_id(text: str) -> str:
    for token in re.findall(r"https?://[^\s<>()]+", text):
        values = parse_qs(urlsplit(token.rstrip(".,;，。；")).query).get("run", [])
        if values and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", values[0]):
            return values[0]
    match = re.search(r"(?:run|模型\s*run)\s*[:：=]\s*([A-Za-z0-9_-]{1,128})", text, re.I)
    return match.group(1) if match else ""


def _looks_like_issue(value: str) -> bool:
    value = str(value or "").strip()
    return bool(
        re.fullmatch(r"[A-Za-z0-9_-]{6,128}", value)
        and any(char.isdigit() for char in value)
        and value.lower() not in {"127001", "localhost"}
    )
