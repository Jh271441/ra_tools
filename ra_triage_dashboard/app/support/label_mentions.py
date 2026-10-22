"""Validate explicit Case-label mentions before any revision or file write."""
import asyncio
from ..review_mentions import extract_review_mentions, notification_recipients
from .common import _detail


async def prepare_label_mentions(database, settings, rationale, author, verified):
    try:
        mentions = extract_review_mentions(rationale)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    if not mentions:
        return []
    enabled = await asyncio.to_thread(database.enabled_mention_recipients, mentions)
    unknown = [name for name in mentions if name not in enabled]
    if unknown:
        raise _detail(400, "以下用户不在可 @ / DChat 通知人员目录中：" + "、".join("@" + name for name in unknown))
    return notification_recipients(enabled, author=author) if settings.dchat_notifications_enabled and verified else []
