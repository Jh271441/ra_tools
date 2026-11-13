"""Read-only notification provenance and validated discussion entry metadata.

Label-mention audit comments predate explicit source metadata. Validate the exact
revision, body, actor and transaction timestamp before using its combined-submit
receipt. Never infer provenance from task membership or a revision number alone.
Explicit composer origins live in private atomic data-dir records; canonical
Issue comment scope and database constraints remain unchanged.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime
import json
import hashlib
import os
from pathlib import Path
import tempfile

from .db_parts.labeling_mentions import label_mention_revision_id, matches_label_mention_revision


def save_comment_review_context(directory: Path, record: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".navigation-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(record, stream, ensure_ascii=False, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, directory / f"{int(record['comment_id'])}.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def _explicit_review_discussion(conn: Any, row: Any, directory: Path | None) -> dict[str, Any] | None:
    # Entry metadata never changes comment ownership or weakens the Case-scope
    # constraints. A file left by a rolled-back transaction cannot match a row.
    if directory is None or row["discussion_channel"] != "case" or not row["author_verified"]:
        return None
    try:
        with (directory / f"{int(row['id'])}.json").open(encoding="utf-8") as stream:
            record = json.loads(stream.read(4096))
        if not isinstance(record, dict):
            return None
        if record.get("version") != 1 or int(record["comment_id"]) != int(row["id"]):
            return None
        if any(str(record[key]) != str(row[key]) for key in ("issue_id","author","client_request_id")):
            return None
        if datetime.fromisoformat(record["created_at"]) != datetime.fromisoformat(str(row["created_at"])):
            return None
        original_body = str(row["body"])
        if int(row["version"] or 1) > 1:
            original = conn.execute("""SELECT body_before FROM comment_changes
                WHERE comment_kind='review' AND comment_id=? AND version_before=1 ORDER BY id LIMIT 1""",
                (row["id"],)).fetchone()
            if original is None: return None
            original_body = str(original["body_before"])
        if record.get("body_sha256") != hashlib.sha256(original_body.encode()).hexdigest():
            return None
        run_id, campaign_id = str(record["model_run_id"]), str(record.get("campaign_id") or "")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    available = bool(conn.execute("SELECT 1 FROM model_predictions WHERE issue_id=? AND model_run_id=?",
                                 (row["issue_id"], run_id)).fetchone())
    task = conn.execute("""SELECT w.campaign_name, w.lifecycle, w.legacy_read_only, w.evaluation_run_id
        FROM issue_work_splits w JOIN campaign_issue_members m ON m.campaign_id=w.id
        WHERE w.id=? AND m.issue_id=? AND w.purpose='model_review'""",
        (campaign_id, row["issue_id"])).fetchone() if campaign_id else None
    if campaign_id:
        available = available and bool(task and task["lifecycle"] == "active" and not task["legacy_read_only"]
                                       and task["evaluation_run_id"] == run_id)
    return {"kind":"review_discussion", "model_run_id":run_id, "campaign_id":campaign_id,
            "task_name":str(task["campaign_name"] or "") if task else "", "review_link_available":available}


def resolve_comment_source(database: Any, comment_id: int, *, navigation_dir: Path | None = None) -> dict[str, Any]:
    with database.connect() as conn:
        root = conn.execute("SELECT * FROM review_comments WHERE id=?", (comment_id,)).fetchone()
        if root is None:
            return {}
        channel = str(root["discussion_channel"] or "legacy")
        fallback = {"kind": {"case": "issue_discussion", "campaign": "task_discussion",
                             "model_review": "model_review"}.get(channel, "issue_discussion")}
        if channel != "case":
            return fallback
        explicit = _explicit_review_discussion(conn, root, navigation_dir)
        if explicit:
            return explicit
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
        explicit = _explicit_review_discussion(conn, root, navigation_dir)
        if explicit:
            return explicit
        revision_id = label_mention_revision_id(root)
        if revision_id is None:
            return fallback
        revision = conn.execute("""
            SELECT r.*, c.issue_id, c.baseline_scope FROM label_revisions r
            JOIN label_cases c ON c.id=r.label_case_id
            WHERE r.id=? AND c.issue_id=? AND c.baseline_scope=?
              AND r.author=? AND r.author_source=? AND r.author_verified=?
              AND r.created_at=?
        """, (revision_id, root["issue_id"], root["baseline_scope"], root["author"],
              root["author_source"], True, root["created_at"])).fetchone()
        if not matches_label_mention_revision(root, revision):
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
              "review_discussion": "判错复核讨论 / Review discussion",
              "issue_label": "问题标注 / Issue labeling",
              "issue_discussion": "本问题讨论 / Issue discussion",
              "task_discussion": "任务讨论 / Task discussion",
              "model_review": "模型复核 / Model review"}
    label = labels.get(source.get("kind"), "本问题讨论 / Issue discussion")
    if source.get("kind") in {"combined_review", "review_discussion"}:
        if source.get("task_name"):
            label += " · " + str(source["task_name"])[:160]
        if not source.get("review_link_available"):
            label += " · 原入口不可用，查看问题讨论 / Original entry unavailable; open Issue discussion"
    return label
