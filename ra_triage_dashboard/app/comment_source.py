"""Read-only notification provenance; discussion ownership never changes.

Label-mention audit comments predate explicit source metadata. Validate the exact
revision, body, actor and transaction timestamp before using its combined-submit
receipt. Never infer provenance from task membership or a revision number alone.
"""
from __future__ import annotations

import re
from typing import Any

from .db_parts.labeling_mentions import label_mention_body


def resolve_comment_source(database: Any, comment_id: int) -> dict[str, Any]:
    with database.connect() as conn:
        root = conn.execute("SELECT * FROM review_comments WHERE id=?", (comment_id,)).fetchone()
        if root is None:
            return {}
        channel = str(root["discussion_channel"] or "legacy")
        fallback = {"kind": {"case": "issue_discussion", "campaign": "task_discussion",
                             "model_review": "model_review"}.get(channel, "issue_discussion")}
        if channel != "case":
            return fallback
        scope_keys = ("issue_id", "baseline_scope", "discussion_channel", "campaign_id", "evaluation_run_id")
        scope = tuple(root[key] for key in scope_keys)
        seen = set()
        # Reply provenance follows the root, not the page used to write a reply.
        for _ in range(64):
            if root["id"] in seen:
                return fallback
            seen.add(root["id"])
            if not root["reply_to_id"]:
                break
            root = conn.execute("SELECT * FROM review_comments WHERE id=?", (root["reply_to_id"],)).fetchone()
            if root is None or tuple(root[key] for key in scope_keys) != scope:
                return fallback
        else:
            return fallback
        match = re.match(r"\AIssue 标签 #([1-9][0-9]{0,17}) · 标注依据 / Label rationale\n", root["body"])
        if not match or not root["author_verified"]:
            return fallback
        revision = conn.execute("""
            SELECT r.*, c.issue_id, c.baseline_scope FROM label_revisions r
            JOIN label_cases c ON c.id=r.label_case_id
            WHERE r.id=? AND c.issue_id=? AND c.baseline_scope=?
              AND r.author=? AND r.author_source=? AND r.author_verified=?
              AND r.created_at=?
        """, (int(match[1]), root["issue_id"], root["baseline_scope"], root["author"],
              root["author_source"], True, root["created_at"])).fetchone()
        if revision is None or label_mention_body(dict(revision)) != root["body"]:
            return fallback
        source = {"kind": "issue_label", "label_revision_id": int(revision["id"]),
                  "root_comment_id": int(root["id"])}
        receipts = conn.execute("""
            SELECT s.campaign_id, s.model_run_id, w.campaign_name, w.lifecycle,
                   w.legacy_read_only, w.evaluation_run_id, w.workflow_mode,
                   r.id AS existing_run
            FROM combined_review_submissions s
            LEFT JOIN issue_work_splits w ON w.id=s.campaign_id
            LEFT JOIN model_runs r ON r.id=s.model_run_id
            WHERE s.label_revision_id=? AND s.label_case_id=? AND s.issue_id=?
              AND s.reviewer=? AND s.created_at=? AND s.case_action='submitted'
            LIMIT 2
        """, (revision["id"], revision["label_case_id"], root["issue_id"],
              root["author"], revision["created_at"])).fetchall()
        # Acknowledgements and later repairs must not reattribute the original.
        if len(receipts) != 1:
            return source
        receipt = dict(receipts[0])
        source.update(kind="combined_review", campaign_id=receipt["campaign_id"],
                      model_run_id=receipt["model_run_id"], task_name=receipt["campaign_name"] or "")
        source["review_link_available"] = bool(receipt["existing_run"]) and (
            not receipt["campaign_id"] or (
                receipt["lifecycle"] == "active" and not receipt["legacy_read_only"]
                and receipt["evaluation_run_id"] == receipt["model_run_id"]
                and receipt["workflow_mode"] == "model_review_and_case_label"
            )
        )
        return source


def comment_source_label(source: dict[str, Any]) -> str:
    labels = {"combined_review": "联合复核 / Combined review",
              "issue_label": "问题标注 / Issue labeling",
              "issue_discussion": "本问题讨论 / Issue discussion",
              "task_discussion": "任务讨论 / Task discussion",
              "model_review": "模型复核 / Model review"}
    label = labels.get(source.get("kind"), "本问题讨论 / Issue discussion")
    if source.get("kind") == "combined_review":
        if source.get("task_name"):
            label += " · " + str(source["task_name"])[:160]
        if not source.get("review_link_available"):
            label += " · 原入口不可用，查看问题讨论 / Original entry unavailable; open Issue discussion"
    return label
