"""Annotations HTTP helpers."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..db import AnnotationConflictError
from ..review_mentions import extract_review_mentions, notification_recipients
from ..runtime import database, settings
from ..review_workflow import derive_review_status, resolve_expected_output
from .catalogs import (
    _normalise_missing_evidence,
    _normalise_review_excluded,
    _normalise_review_tags,
    _review_tag_catalog,
)
from .common import _as_text, _detail
from .identity import _action_actor


def _create_annotation_record(
    *,
    issue_id: str,
    request: Request,
    body: dict[str, Any],
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    is_excluded = _normalise_review_excluded(body.get("is_excluded", False))
    tags = body.get("tags") or []
    missing_evidence = body.get("missing_evidence") or []
    if not isinstance(tags, list):
        raise _detail(400, "tags 必须是数组。")
    if not isinstance(missing_evidence, list):
        raise _detail(400, "missing_evidence 必须是数组。")
    tags = _normalise_review_tags(tags)
    missing_evidence = _normalise_missing_evidence(missing_evidence)
    expected_output = _as_text(body.get("expected_output"))
    legacy_label = _as_text(body.get("label"))
    if expected_output and legacy_label and expected_output != legacy_label:
        raise _detail(400, "expected_output 与兼容字段 label 不一致。")
    try:
        expected_output = resolve_expected_output(
            expected_output or legacy_label,
            tags,
            _review_tag_catalog(),
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    case = database.get_case(issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    review_status = derive_review_status(
        expected_output,
        case.get("gt_label"),
    )
    model_run_id = _as_text(body.get("model_run_id"))
    has_expected_previous = "expected_previous_annotation_id" in body
    expected_previous_annotation_id: int | None = None
    if has_expected_previous:
        raw_expected = body.get("expected_previous_annotation_id")
        if raw_expected in (None, "", 0, "0"):
            expected_previous_annotation_id = None
        else:
            try:
                expected_previous_annotation_id = int(raw_expected)
            except (TypeError, ValueError) as exc:
                raise _detail(400, "expected_previous_annotation_id 不合法。") from exc
            if expected_previous_annotation_id <= 0:
                raise _detail(400, "expected_previous_annotation_id 不合法。")
    author, author_source, author_verified = _action_actor(request, body.get("author"))
    note = _as_text(body.get("note"))
    try:
        mentions = extract_review_mentions(note)
    except ValueError as exc:
        raise _detail(400, str(exc)) from exc
    enabled_mentions = database.enabled_mention_recipients(mentions)
    unsupported_mentions = [
        username for username in mentions if username not in enabled_mentions
    ]
    if unsupported_mentions:
        raise _detail(
            400,
            "以下用户不在可 @ / DChat 通知人员目录中："
            + "、".join(f"@{item}" for item in unsupported_mentions),
        )
    recipients = notification_recipients(enabled_mentions, author=author)
    queued_recipients = (
        recipients
        if settings.dchat_notifications_enabled and author_verified
        else []
    )
    annotation_kwargs: dict[str, Any] = {
        "issue_id": issue_id,
        "model_run_id": model_run_id,
        # ``annotations.label`` is the existing compatible storage column for
        # the newly named expected output.  Keep it populated so older readers,
        # filters and history remain valid without a schema rewrite.
        "label": expected_output,
        "review_status": review_status,
        "is_excluded": is_excluded,
        "tags": tags,
        "missing_evidence": missing_evidence,
        "note": note,
        "author": author,
        "author_source": author_source,
        "author_verified": author_verified,
        "attachments": attachments,
        "mentions": mentions,
        "notification_recipients": queued_recipients,
    }
    if has_expected_previous:
        annotation_kwargs["expected_previous_annotation_id"] = expected_previous_annotation_id
    try:
        annotation = database.create_annotation(
            **annotation_kwargs,
        )
        annotation["notification"] = {
            "mentions": mentions,
            "queued": queued_recipients,
            "status": (
                "no_mentions" if not recipients
                else "queued" if queued_recipients
                else "disabled" if not settings.dchat_notifications_enabled
                else "unverified_identity"
            ),
        }
        return annotation
    except AnnotationConflictError as exc:
        raise _detail(409, str(exc))
    except ValueError as exc:
        raise _detail(400, str(exc))
