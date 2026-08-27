from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .dchat import (
    DChatClient,
    DChatLoopbackClient,
    DChatSendError,
    build_review_notification_text,
    build_review_url,
)


logger = logging.getLogger("ra_triage_dashboard")


class ReviewNotificationDispatcher:
    def __init__(self, settings: Any, database: Any) -> None:
        self.settings = settings
        self.database = database
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        await asyncio.to_thread(self.database.recover_review_notifications)
        while True:
            handled = await asyncio.to_thread(self._dispatch_one)
            if handled:
                # DChat documents a common BotUser limit of 5 QPS.
                await asyncio.sleep(0.21)
                continue
            self._wake.clear()
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.settings.dchat_poll_seconds
                )
            except asyncio.TimeoutError:
                pass

    def _dispatch_one(self) -> bool:
        now = datetime.now(timezone.utc)
        item = self.database.claim_review_notification(
            now=now.isoformat(timespec="seconds")
        )
        if item is None:
            return False
        notification_id = int(item["id"])
        try:
            client = (
                DChatLoopbackClient()
                if self.settings.dchat_delivery_mode == "loopback"
                else DChatClient(
                    base_url=self.settings.dchat_base_url,
                    credentials_file=self.settings.dchat_credentials_file,
                    timeout_seconds=self.settings.dchat_timeout_seconds,
                )
            )
            review_url = build_review_url(
                self.settings.kylin_sso_return_url,
                issue_id=str(item["issue_id"]),
                model_run_id=str(item.get("model_run_id") or ""),
            )
            text = build_review_notification_text(
                issue_id=str(item["issue_id"]),
                author=str(item.get("author") or ""),
                note=str(item.get("note") or ""),
                review_url=review_url,
            )
            result = client.send_to_username(str(item["recipient"]), text)
        except DChatSendError as exc:
            attempts = int(item.get("attempt_count") or 1)
            terminal = not exc.transient or attempts >= self.settings.dchat_max_attempts
            delay_seconds = min(300, 2 ** min(attempts, 8))
            self.database.defer_review_notification(
                notification_id,
                next_attempt_at=(now + timedelta(seconds=delay_seconds)).isoformat(
                    timespec="seconds"
                ),
                error=str(exc),
                terminal=terminal,
            )
            logger.warning(
                "DChat Review notification id=%s %s",
                notification_id,
                "failed" if terminal else "deferred",
            )
            return True
        except Exception:
            logger.exception(
                "unexpected DChat Review notification failure id=%s",
                notification_id,
            )
            attempts = int(item.get("attempt_count") or 1)
            self.database.defer_review_notification(
                notification_id,
                next_attempt_at=(now + timedelta(seconds=30)).isoformat(
                    timespec="seconds"
                ),
                error="发送器内部错误。",
                terminal=attempts >= self.settings.dchat_max_attempts,
            )
            return True
        self.database.complete_review_notification(
            notification_id,
            trace_id=result.trace_id,
            message_unique_id=result.message_unique_id,
        )
        return True
