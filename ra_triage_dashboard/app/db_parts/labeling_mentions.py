"""Case-label mention audit comments and outbox share the revision transaction."""
from ..review_mentions import extract_review_mentions
from .shared import _json


def label_mention_body(revision):
    return (f"Issue 标签 #{revision['id']} · 标注依据 / Label rationale\n" + revision["rationale"])[:3500]


def append_label_mention_event(database, conn, *, revision, issue_id, baseline_scope, recipients):
    mentions = extract_review_mentions(revision.get("rationale", ""))
    queued = list(dict.fromkeys(name for name in recipients if name in mentions))
    if not queued or not revision.get("author_verified"):
        return {"mentions": mentions, "queued": [], "status": "disabled" if mentions else "none"}
    # Called only for a newly inserted revision. Acknowledgments and combined
    # idempotency replays never create a second audit comment or delivery.
    body = label_mention_body(revision)
    now = revision["created_at"]
    sql = """INSERT INTO review_comments
        (issue_id, model_run_id, body, author, author_source, author_verified,
         mentions_json, reply_to_id, created_at, discussion_channel,
         campaign_id, baseline_scope, evaluation_run_id)
        VALUES (?, '', ?, ?, ?, ?, ?, NULL, ?, 'case', '', ?, '')"""
    if database.backend == "postgresql":
        sql += " RETURNING id"
    cursor = conn.execute(sql, (issue_id, body, revision["author"], revision["author_source"],
                               True, _json(mentions), now, baseline_scope))
    comment_id = int(cursor.fetchone()["id"]) if database.backend == "postgresql" else int(cursor.lastrowid)
    for recipient in queued:
        conn.execute("""INSERT INTO comment_notifications
            (comment_id, issue_id, recipient, status, attempt_count, next_attempt_at, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
            ON CONFLICT(comment_id, recipient) DO NOTHING""", (comment_id, issue_id, recipient, now, now, now))
    return {"mentions": mentions, "queued": queued, "status": "queued", "comment_id": comment_id}
