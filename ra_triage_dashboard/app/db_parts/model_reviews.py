"""Run-bound model diagnosis revisions and indexed current heads."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from .shared import AnnotationConflictError, _EXPECTED_ANNOTATION_UNSET, _json, _json_load, utc_now


MODEL_REVIEW_STATUSES = {
    "pending",
    "in_progress",
    "completed",
    "blocked_by_label",
}
MODEL_REVIEW_PUBLIC_ID_OFFSET = 4_000_000_000_000_000


def model_review_label_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


class DatabaseModelReviewMixin:
    @staticmethod
    def _model_review_public_id(revision_id: Any) -> int:
        return MODEL_REVIEW_PUBLIC_ID_OFFSET + int(revision_id)

    @staticmethod
    def _model_review_storage_id(public_id: Any) -> int | None:
        try:
            value = int(public_id)
        except (TypeError, ValueError):
            return None
        if value <= MODEL_REVIEW_PUBLIC_ID_OFFSET:
            return None
        return value - MODEL_REVIEW_PUBLIC_ID_OFFSET

    @staticmethod
    def _model_review_legacy_status(status: str) -> str:
        if status == "completed":
            return "reviewed"
        if status == "blocked_by_label":
            return "needs_gt_review"
        return "pending"

    @classmethod
    def _model_review_dict(cls, row: Any) -> dict[str, Any]:
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        revision_id = int(row["id"])
        supersedes_id = row["supersedes_id"]
        legacy_base = row["legacy_base_annotation_id"]
        attachments = (
            _json_load(row["attachments_json"], [])
            if "attachments_json" in keys
            else []
        )
        status = str(row["status"] or "pending")
        return {
            "id": cls._model_review_public_id(revision_id),
            "storage_id": revision_id,
            "review_domain": "model_review",
            "issue_id": str(row["issue_id"] or ""),
            "model_run_id": str(row["model_run_id"] or ""),
            "campaign_id": str(row["campaign_id"] or ""),
            "reference_id": str(row["reference_id"] or ""),
            "work_split_id": str(row["work_split_id"] or ""),
            "model_review_status": status,
            "review_status": cls._model_review_legacy_status(status),
            "reason": str(row["reason"] or ""),
            "note": str(row["reason"] or ""),
            "missing_evidence": _json_load(row["missing_evidence_json"], []),
            "label_state_fingerprint": str(row["label_state_fingerprint"] or ""),
            "label_state": _json_load(row["label_state_json"], {}),
            "reviewer": str(row["reviewer"] or ""),
            "author": str(row["reviewer"] or ""),
            "reviewer_source": str(row["reviewer_source"] or "legacy"),
            "author_source": str(row["reviewer_source"] or "legacy"),
            "reviewer_verified": bool(row["reviewer_verified"]),
            "author_verified": bool(row["reviewer_verified"]),
            "supersedes_id": (
                cls._model_review_public_id(supersedes_id)
                if supersedes_id is not None
                else int(legacy_base) if legacy_base is not None else None
            ),
            "legacy_base_annotation_id": (
                int(legacy_base) if legacy_base is not None else None
            ),
            "legacy_annotation_id": (
                int(row["legacy_annotation_id"])
                if row["legacy_annotation_id"] is not None
                else None
            ),
            "created_at": str(row["created_at"] or ""),
            "label": "",
            "expected_output": "",
            "tags": [],
            "is_excluded": False,
            "mentions": [],
            "attachments": attachments,
        }

    def create_model_review(
        self,
        *,
        issue_id: str,
        model_run_id: str,
        status: str,
        reason: str,
        missing_evidence: Sequence[str],
        reviewer: str,
        reviewer_source: str = "legacy",
        reviewer_verified: bool = False,
        campaign_id: str = "",
        reference_id: str = "",
        work_split_id: str = "",
        label_state: dict[str, Any] | None = None,
        expected_previous_annotation_id: int | None | object = _EXPECTED_ANNOTATION_UNSET,
        attachments: list[dict[str, Any]] | None = None,
        legacy_annotation_id: int | None = None,
    ) -> dict[str, Any]:
        issue_id = str(issue_id or "").strip()
        model_run_id = str(model_run_id or "").strip()
        campaign_id = str(campaign_id or "").strip()
        reference_id = str(reference_id or "").strip()
        work_split_id = str(work_split_id or "").strip()
        reviewer = str(reviewer or "").strip().lower()
        status = str(status or "pending").strip().lower()
        if not issue_id or not model_run_id:
            raise ValueError("Model Review requires issue_id and model_run_id")
        if status not in MODEL_REVIEW_STATUSES:
            raise ValueError("不支持的模型复核状态。")
        if not reviewer:
            raise ValueError("复核人不能为空。")
        evidence = sorted(
            dict.fromkeys(
                str(item or "").strip()
                for item in missing_evidence
                if str(item or "").strip()
            )
        )
        label_state = dict(label_state or {})
        if str(label_state.get("state") or "") in {"conflict", "stale"}:
            status = "blocked_by_label"
        label_fingerprint = model_review_label_fingerprint(label_state)
        attachments = list(attachments or [])
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            issue_sql = "SELECT issue_id FROM issues WHERE issue_id = ?"
            if self.backend == "postgresql":
                # Serialize first submissions as well as updates when no head
                # row exists yet; a process-local lock alone cannot protect
                # multiple Uvicorn workers.
                issue_sql += " FOR UPDATE"
            issue = conn.execute(
                issue_sql, (issue_id,)
            ).fetchone()
            run = conn.execute(
                "SELECT id FROM model_runs WHERE id = ?", (model_run_id,)
            ).fetchone()
            if issue is None:
                raise ValueError("Issue 不存在。")
            if run is None:
                raise ValueError("模型 Run 不存在。")
            head = conn.execute(
                """
                SELECT head.revision_id, revision.work_split_id
                FROM model_review_heads head
                JOIN model_review_revisions revision ON revision.id = head.revision_id
                WHERE head.model_run_id = ? AND head.issue_id = ?
                  AND head.campaign_id = ? AND head.reference_id = ?
                  AND lower(head.reviewer) = lower(?)
                """,
                (model_run_id, issue_id, campaign_id, reference_id, reviewer),
            ).fetchone()
            current_public_id = (
                self._model_review_public_id(head["revision_id"]) if head else None
            )
            legacy_base: int | None = None
            if head is None:
                legacy = conn.execute(
                    """
                    SELECT id FROM annotations
                    WHERE issue_id = ? AND model_run_id = ?
                      AND work_split_id = ? AND lower(author) = lower(?)
                    ORDER BY id DESC LIMIT 1
                    """,
                    (issue_id, model_run_id, work_split_id, reviewer),
                ).fetchone()
                legacy_base = int(legacy["id"]) if legacy else None
                current_public_id = legacy_base
            if expected_previous_annotation_id is not _EXPECTED_ANNOTATION_UNSET:
                raw_expected = expected_previous_annotation_id
                expected = None if raw_expected in (None, "", 0, "0") else int(raw_expected)
                if expected != current_public_id:
                    raise AnnotationConflictError(
                        "该 Issue 在当前 Model Run 下已被其他人更新；请刷新 Review 后再保存。"
                    )
            insert_sql = """
                INSERT INTO model_review_revisions (
                    model_run_id, issue_id, campaign_id, reference_id,
                    work_split_id, status, reason, missing_evidence_json,
                    label_state_fingerprint, label_state_json, reviewer,
                    reviewer_source, reviewer_verified, supersedes_id,
                    legacy_base_annotation_id, legacy_annotation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                insert_sql += " RETURNING id"
            cursor = conn.execute(
                insert_sql,
                (
                    model_run_id, issue_id, campaign_id, reference_id,
                    work_split_id, status, str(reason or "").strip(), _json(evidence),
                    label_fingerprint, _json(label_state), reviewer,
                    str(reviewer_source or "legacy").strip() or "legacy",
                    bool(reviewer_verified), int(head["revision_id"]) if head else None,
                    legacy_base, int(legacy_annotation_id) if legacy_annotation_id else None,
                    now,
                ),
            )
            revision_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            conn.execute(
                """
                INSERT INTO model_review_heads (
                    model_run_id, issue_id, campaign_id, reference_id,
                    reviewer, revision_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_run_id, issue_id, campaign_id, reference_id, reviewer)
                DO UPDATE SET revision_id = excluded.revision_id,
                              updated_at = excluded.updated_at
                """,
                (model_run_id, issue_id, campaign_id, reference_id, reviewer, revision_id, now),
            )
            for attachment in attachments:
                conn.execute(
                    """
                    INSERT INTO model_review_attachments (
                        id, revision_id, original_name, stored_name, media_type,
                        size_bytes, width, height, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(attachment["id"]), revision_id,
                        str(attachment.get("original_name") or ""),
                        str(attachment["stored_name"]), str(attachment["media_type"]),
                        int(attachment["size_bytes"]), int(attachment["width"]),
                        int(attachment["height"]), str(attachment["sha256"]), now,
                    ),
                )
            self._mark_change_topic(conn, "review")
            row = conn.execute(
                "SELECT * FROM model_review_revisions WHERE id = ?", (revision_id,)
            ).fetchone()
        result = self._model_review_dict(row)
        result["attachments"] = [
            {**attachment, "annotation_id": result["id"], "created_at": now}
            for attachment in attachments
        ]
        return result

    def model_review_revisions(
        self, *, issue_id: str, model_run_id: str = ""
    ) -> list[dict[str, Any]]:
        where = "WHERE issue_id = ?"
        params: list[Any] = [str(issue_id or "").strip()]
        if str(model_run_id or "").strip():
            where += " AND model_run_id = ?"
            params.append(str(model_run_id or "").strip())
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM model_review_revisions {where} ORDER BY id DESC",
                params,
            ).fetchall()
        return [self._model_review_dict(row) for row in rows]

    def current_model_review(
        self,
        *,
        issue_id: str,
        model_run_id: str,
        reviewer: str = "",
        campaign_id: str = "",
        reference_id: str = "",
    ) -> dict[str, Any] | None:
        where = [
            "head.issue_id = ?", "head.model_run_id = ?",
            "head.campaign_id = ?", "head.reference_id = ?",
        ]
        params: list[Any] = [issue_id, model_run_id, campaign_id, reference_id]
        if str(reviewer or "").strip():
            where.append("lower(head.reviewer) = lower(?)")
            params.append(str(reviewer).strip())
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT revision.* FROM model_review_heads head
                JOIN model_review_revisions revision ON revision.id = head.revision_id
                WHERE {' AND '.join(where)}
                ORDER BY revision.id DESC LIMIT 1
                """,
                params,
            ).fetchone()
        return self._model_review_dict(row) if row else None

    def current_model_reviews(
        self, *, issue_ids: Sequence[str], model_run_id: str
    ) -> dict[str, dict[str, Any]]:
        cleaned = list(dict.fromkeys(str(item or "").strip() for item in issue_ids if str(item or "").strip()))
        if not cleaned or not str(model_run_id or "").strip():
            return {}
        result: dict[str, dict[str, Any]] = {}
        with self.connect() as conn:
            for offset in range(0, len(cleaned), 400):
                batch = cleaned[offset : offset + 400]
                rows = conn.execute(
                    f"""
                    SELECT revision.* FROM model_review_heads head
                    JOIN model_review_revisions revision ON revision.id = head.revision_id
                    WHERE head.model_run_id = ?
                      AND head.issue_id IN ({', '.join('?' for _ in batch)})
                    ORDER BY revision.issue_id, revision.id DESC
                    """,
                    (model_run_id, *batch),
                ).fetchall()
                for row in rows:
                    issue_id = str(row["issue_id"])
                    result.setdefault(issue_id, self._model_review_dict(row))
        return result

    def get_model_review_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_record_attachments WHERE id = ?",
                (str(attachment_id or "").strip(),),
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def model_review_shadow_comparison(
        self, *, model_run_id: str, baseline_scopes: Sequence[str]
    ) -> dict[str, Any]:
        scopes = self._normalize_baseline_scopes(baseline_scopes)
        if not scopes:
            return {"items": [], "counts": {"matched": 0, "different": 0, "new_only": 0}}
        clause, scope_params = self._scope_in_sql(scopes, "issue.baseline_scope")
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT revision.issue_id, revision.status, revision.reason,
                       revision.missing_evidence_json, revision.reviewer,
                       legacy.id AS legacy_id, legacy.review_status AS legacy_status,
                       legacy.note AS legacy_reason,
                       legacy.missing_evidence_json AS legacy_missing_evidence_json,
                       legacy.author AS legacy_reviewer
                FROM model_review_heads head
                JOIN model_review_revisions revision ON revision.id = head.revision_id
                JOIN issues issue ON issue.issue_id = revision.issue_id
                LEFT JOIN annotations legacy ON legacy.id = (
                    SELECT candidate.id FROM annotations candidate
                    WHERE candidate.issue_id = revision.issue_id
                      AND candidate.model_run_id = revision.model_run_id
                      AND candidate.work_split_id = revision.work_split_id
                      AND lower(candidate.author) = lower(revision.reviewer)
                    ORDER BY candidate.id DESC LIMIT 1
                )
                WHERE revision.model_run_id = ? AND {clause}
                ORDER BY revision.issue_id, revision.reviewer
                """,
                (model_run_id, *scope_params),
            ).fetchall()
        items = []
        counts = {"matched": 0, "different": 0, "new_only": 0}
        for row in rows:
            legacy_exists = row["legacy_id"] is not None
            same = bool(
                legacy_exists
                and str(row["reason"] or "") == str(row["legacy_reason"] or "")
                and _json_load(row["missing_evidence_json"], []) == _json_load(row["legacy_missing_evidence_json"], [])
                and str(row["reviewer"] or "").lower() == str(row["legacy_reviewer"] or "").lower()
            )
            state = "matched" if same else "different" if legacy_exists else "new_only"
            counts[state] += 1
            items.append({"issue_id": str(row["issue_id"]), "state": state, "legacy_present": legacy_exists})
        return {"items": items, "counts": counts}

    def model_review_facets(
        self, *, model_run_id: str, baseline_scopes: Sequence[str]
    ) -> dict[str, Any]:
        scopes = self._normalize_baseline_scopes(baseline_scopes)
        if not scopes:
            return {"statuses": [], "reviewers": [], "total": 0}
        clause, scope_params = self._scope_in_sql(scopes, "issue.baseline_scope")
        with self.connect() as conn:
            status_rows = conn.execute(
                f"""
                SELECT revision.status AS value, COUNT(*) AS count
                FROM model_review_heads head
                JOIN model_review_revisions revision ON revision.id = head.revision_id
                JOIN issues issue ON issue.issue_id = revision.issue_id
                WHERE revision.model_run_id = ? AND {clause}
                GROUP BY revision.status ORDER BY revision.status
                """,
                (model_run_id, *scope_params),
            ).fetchall()
            reviewer_rows = conn.execute(
                f"""
                SELECT revision.reviewer AS value, COUNT(*) AS count,
                       SUM(CASE WHEN revision.reviewer_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN revision.reviewer_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count
                FROM model_review_heads head
                JOIN model_review_revisions revision ON revision.id = head.revision_id
                JOIN issues issue ON issue.issue_id = revision.issue_id
                WHERE revision.model_run_id = ? AND {clause}
                GROUP BY revision.reviewer ORDER BY COUNT(*) DESC, revision.reviewer
                """,
                (model_run_id, *scope_params),
            ).fetchall()
        statuses = [
            {"value": str(row["value"]), "count": int(row["count"] or 0)}
            for row in status_rows
        ]
        reviewers = [
            {
                "value": str(row["value"]),
                "count": int(row["count"] or 0),
                "verified_count": int(row["verified_count"] or 0),
                "unverified_count": int(row["unverified_count"] or 0),
            }
            for row in reviewer_rows
        ]
        return {
            "statuses": statuses,
            "reviewers": reviewers,
            "total": sum(item["count"] for item in statuses),
        }
