"""Stable identities for retrying one Issue comment without duplicate deliveries."""
from __future__ import annotations

import hashlib
import json
import re


class CommentSubmissionConflictError(ValueError):
    pass


def validate_comment_request_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value):
        raise ValueError("评论请求标识无效。 / Invalid comment request ID.")
    return value


def comment_request_fingerprint(body, reply_to_id, attachments):
    # Upload IDs change when the same file is normalized again after a lost
    # response. Compare ordered content hashes and canonical placeholders.
    text = body
    for index, attachment in enumerate(attachments):
        text = text.replace(f"attachment:{attachment['id']}", f"attachment:upload-{index}")
    payload = {"body": text, "reply_to_id": reply_to_id,
               "images": [item["sha256"] for item in attachments]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
