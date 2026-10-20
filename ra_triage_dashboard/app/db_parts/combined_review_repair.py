"""Explicit, append-only repair of a confirmed missing Campaign association."""
import hashlib
import json
from datetime import datetime
from uuid import uuid4

from .shared import AnnotationConflictError, _json, utc_now


def repair_association(database, *, submission_id, campaign_id, label_revision_id,
                       model_review_revision_id, actor, reason, apply=False,
                       expected_fingerprint=""):
    if not str(actor).strip() or not str(reason).strip():
        raise ValueError("修复必须记录操作人和原因。")
    with database._write_lock, database.connect() as conn:
        if database.backend == "postgresql":
            conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        source = conn.execute(
            "SELECT * FROM combined_review_submissions WHERE id=?", (submission_id,),
        ).fetchone()
        if source is None or str(source["campaign_id"] or ""):
            raise ValueError("仅允许关联明确指定的任务外联合提交。")
        source = dict(source)
        label_id = source["label_revision_id"] or source["acknowledged_label_revision_id"]
        if int(label_id or 0) != int(label_revision_id) or int(source["model_review_revision_id"]) != int(model_review_revision_id):
            raise ValueError("原始标签或模型复核版本与修复清单不一致。")
        key = f"association-repair:{submission_id}"
        audit = {"source_submission_id": str(submission_id), "campaign_id": campaign_id,
                 "label_revision_id": int(label_revision_id),
                 "model_review_revision_id": int(model_review_revision_id),
                 "source_fingerprint": source["idempotency_fingerprint"],
                 "actor": actor, "reason": reason}
        digest = hashlib.sha256(json.dumps(audit, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        replay = conn.execute(
            "SELECT id, campaign_id, idempotency_fingerprint FROM combined_review_submissions WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        receipt = {**audit, "fingerprint": digest, "original_preserved": True}
        if replay is not None:
            if str(replay["campaign_id"]) != campaign_id or str(replay["idempotency_fingerprint"]) != digest:
                raise AnnotationConflictError("此提交已经关联到不同任务或修复清单发生变化。")
            return {**receipt, "duplicate": True, "applied": True,
                    "submission_group_id": str(replay["id"])}
        campaign = conn.execute("SELECT * FROM issue_work_splits WHERE id=?", (campaign_id,)).fetchone()
        if (campaign is None or campaign["purpose"] != "model_review" or
            campaign["workflow_mode"] != "model_review_and_case_label" or
            campaign["lifecycle"] != "active" or campaign["legacy_read_only"] or
            str(campaign["evaluation_run_id"]) != str(source["model_run_id"])):
            raise ValueError("目标必须是同 Run 的有效联合复核任务。")
        assignment = conn.execute(
            """SELECT assigned_at FROM review_work_assignments
               WHERE split_id=? AND issue_id=? AND lower(assignee)=lower(?)""",
            (campaign_id, source["issue_id"], source["reviewer"]),
        ).fetchone()
        def timestamp(value):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if assignment is None or timestamp(assignment["assigned_at"]) > timestamp(source["created_at"]):
            raise ValueError("原始提交时该 Issue 未分配给此复核人。")
        if conn.execute(
            "SELECT 1 FROM campaign_issue_members WHERE campaign_id=? AND issue_id=?",
            (campaign_id, source["issue_id"]),
        ).fetchone() is None:
            raise ValueError("Issue 不在任务冻结范围内。")
        if conn.execute(
            """SELECT 1 FROM campaign_assignment_audit WHERE campaign_id=? AND issue_id=?
               AND changed_at>? AND action IN ('reassigned','unassigned')""",
            (campaign_id, source["issue_id"], source["created_at"]),
        ).fetchone():
            raise ValueError("提交后存在转派记录，需人工核实，拒绝自动关联。")
        model = conn.execute("SELECT * FROM model_review_revisions WHERE id=?", (model_review_revision_id,)).fetchone()
        label = conn.execute(
            """SELECT revision.*, label_case.issue_id FROM label_revisions revision
               JOIN label_cases label_case ON label_case.id=revision.label_case_id WHERE revision.id=?""",
            (label_revision_id,),
        ).fetchone()
        if (model is None or label is None or str(model["campaign_id"] or "") or
            str(model["issue_id"]) != source["issue_id"] or str(label["issue_id"]) != source["issue_id"] or
            str(model["model_run_id"]) != str(source["model_run_id"]) or
            str(model["reviewer"]).lower() != str(source["reviewer"]).lower() or
            str(label["author"]).lower() != str(source["reviewer"]).lower() or
            str(label["label_case_id"]) != source["label_case_id"]):
            raise ValueError("原始提交的 Issue、Run、复核人或标签关联不一致。")
        if conn.execute(
            "SELECT 1 FROM label_import_suppressed_revisions WHERE revision_id=?", (label_revision_id,),
        ).fetchone():
            raise ValueError("标签版本已被抑制，不能关联。")
        identity = (campaign_id, source["issue_id"], source["reviewer"])
        if conn.execute(
            "SELECT 1 FROM combined_review_progress WHERE campaign_id=? AND issue_id=? AND lower(reviewer)=lower(?)",
            identity,
        ).fetchone() or conn.execute(
            "SELECT 1 FROM model_review_heads WHERE campaign_id=? AND issue_id=? AND lower(reviewer)=lower(?)",
            identity,
        ).fetchone():
            raise AnnotationConflictError("目标已有复核或进度，拒绝覆盖。")
        if not apply:
            return {**receipt, "duplicate": False, "applied": False,
                    "issue_id": source["issue_id"], "reviewer": source["reviewer"]}
        if expected_fingerprint != digest:
            raise AnnotationConflictError("修复清单 fingerprint 不匹配；请先执行 dry-run。")
        now = utc_now()
        values = dict(model)
        values.pop("id")
        values.update(campaign_id=campaign_id, work_split_id=campaign_id,
                      reference_id=str(campaign["reference_id"] or ""),
                      supersedes_id=None, created_at=now)
        for column, value in values.items():
            if isinstance(value, (dict, list)):
                values[column] = _json(value)
        sql = f"INSERT INTO model_review_revisions ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})"
        if database.backend == "postgresql":
            sql += " RETURNING id"
        cursor = conn.execute(sql, list(values.values()))
        model_id = int(cursor.fetchone()["id"]) if database.backend == "postgresql" else int(cursor.lastrowid)
        conn.execute(
            """INSERT INTO model_review_heads
               (model_run_id, issue_id, campaign_id, reference_id, reviewer, revision_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (source["model_run_id"], source["issue_id"], campaign_id, values["reference_id"],
             source["reviewer"], model_id, now),
        )
        group_id = str(uuid4())
        conn.execute(
            """INSERT INTO combined_review_submissions
               (id, campaign_id, issue_id, reviewer, model_run_id, model_review_revision_id,
                label_case_id, label_revision_id, acknowledged_label_revision_id, case_action,
                idempotency_key, idempotency_fingerprint, created_by_source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 'acknowledged', ?, ?, ?, ?)""",
            (group_id, campaign_id, source["issue_id"], source["reviewer"], source["model_run_id"],
             model_id, source["label_case_id"], label_revision_id, key, digest,
             _json({"kind": "association_repair", **audit}), now),
        )
        conn.execute(
            """INSERT INTO combined_review_progress
               (campaign_id, issue_id, reviewer, model_review_submitted, case_label_acknowledged,
                model_review_revision_id, case_label_revision_id, submission_group_id,
                model_review_submitted_at, case_label_acknowledged_at, updated_at)
               VALUES (?, ?, ?, true, true, ?, ?, ?, ?, ?, ?)""",
            (*identity, model_id, label_revision_id, group_id, source["created_at"], source["created_at"], now),
        )
        database._mark_labeling_change(conn)
        return {**receipt, "duplicate": False, "applied": True, "submission_group_id": group_id,
                "new_model_review_revision_id": model_id}
