from __future__ import annotations

import re
from typing import Iterable


MAX_REVIEW_MENTIONS = 10
MENTION_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MENTION_RE = re.compile(
    r"(?<![A-Za-z0-9._@-])@(?:\{(?P<braced>[A-Za-z0-9._-]{1,64})\}|(?P<plain>[A-Za-z0-9._-]{1,64}))"
)
_RESERVED_MENTIONS = frozenset({"all", "everyone", "group", "here"})


def normalize_mention_username(value: object) -> str:
    username = str(value or "").strip().lower()
    if not MENTION_USERNAME_RE.fullmatch(username):
        return ""
    if username in _RESERVED_MENTIONS:
        return ""
    return username


def extract_review_mentions(note: object, *, limit: int = MAX_REVIEW_MENTIONS) -> list[str]:
    text = str(note or "")
    mentions: list[str] = []
    seen: set[str] = set()
    for match in _MENTION_RE.finditer(text):
        username = normalize_mention_username(
            match.group("braced") or match.group("plain")
        )
        if not username or username in seen:
            continue
        seen.add(username)
        mentions.append(username)
        if len(mentions) > limit:
            raise ValueError(f"每条 Review 最多 @ {limit} 人。")
    return mentions


def notification_recipients(
    mentions: Iterable[object], *, author: object = ""
) -> list[str]:
    # Mentioning oneself is intentional: reviewers often use DChat as a
    # follow-up reminder. Keep ``author`` in the compatible call signature,
    # but do not silently remove it from an explicit, directory-approved list.
    del author
    recipients: list[str] = []
    seen: set[str] = set()
    for value in mentions:
        username = normalize_mention_username(value)
        if not username or username in seen:
            continue
        seen.add(username)
        recipients.append(username)
    return recipients
