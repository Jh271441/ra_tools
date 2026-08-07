from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any, Iterable, Sequence

from .shared import (
    LABELS,
    REVIEW_STATUSES,
    AnnotationConflictError,
    _EXPECTED_ANNOTATION_UNSET,
    _json,
    _json_load,
    utc_now,
)


class DatabaseReviewMixin:
    def list_missing_evidence_catalog(
        self, *, include_inactive: bool = True
    ) -> list[dict[str, Any]]:
        """Return the shared missing-evidence entries.

        Entries are soft-deleted so historical annotations can continue to
        resolve their opaque keys and display the original label.  Callers
        that render an editable catalog can filter ``active`` themselves, or
        request only active entries with ``include_inactive=False``.
        """

        where = "" if include_inactive else "WHERE active"

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT key, label, hint, created_by, created_at, active
                FROM missing_evidence_catalog
                {where}
                ORDER BY created_at ASC, label ASC
                """
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def list_review_tag_catalog(
        self, *, include_inactive: bool = True
    ) -> list[dict[str, Any]]:
        """Return shared, user-created scene tag definitions."""

        where = "" if include_inactive else "WHERE active"
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT key, label, hint, section, group_key, created_by, created_at, active
                FROM review_tag_catalog
                {where}
                ORDER BY created_at ASC, label ASC
                """
            ).fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]

    def create_review_tag(
        self,
        *,
        label: str,
        hint: str,
        section: str,
        group_key: str,
        created_by: str,
    ) -> dict[str, Any]:
        normalized_label = str(label or "").strip()
        normalized_hint = str(hint or "").strip()
        normalized_section = str(section or "scene").strip()
        normalized_group = str(group_key or "environment").strip()
        normalized_author = str(created_by or "").strip()
        if not normalized_label:
            raise ValueError("场景标签标题不能为空。")
        if len(normalized_label) > 48 or re.search(r"[\x00-\x1f\x7f]", normalized_label):
            raise ValueError("场景标签标题长度或字符不合法。")
        if len(normalized_hint) > 160 or re.search(r"[\x00-\x1f\x7f]", normalized_hint):
            raise ValueError("场景标签说明长度或字符不合法。")
        managed_groups = {
            "environment": "scene",
            "self_intent": "scene",
            "false_trigger": "interaction_decision",
            "true_trigger": "interaction_decision",
            "ra": "egress",
            "no_assist": "egress",
        }
        expected_section = managed_groups.get(normalized_group)
        if expected_section is None or normalized_section != expected_section:
            raise ValueError("场景标签分组不合法。")
        if not normalized_author:
            raise ValueError("创建人不能为空。")
        key = f"custom:tag:{uuid.uuid4().hex}"
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT key FROM review_tag_catalog WHERE label = ? AND active",
                (normalized_label,),
            ).fetchone()
            if existing:
                raise ValueError("该场景标签标题已经存在。")
            try:
                conn.execute(
                    """
                    INSERT INTO review_tag_catalog (
                        key, label, hint, section, group_key, created_by, created_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, TRUE)
                    """,
                    (
                        key,
                        normalized_label,
                        normalized_hint,
                        normalized_section,
                        normalized_group,
                        normalized_author,
                        now,
                    ),
                )
            except Exception as exc:
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise ValueError("该场景标签标题已经存在。") from exc
                raise
            row = conn.execute(
                """
                SELECT key, label, hint, section, group_key, created_by, created_at, active
                FROM review_tag_catalog WHERE key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("场景标签目录写入后无法读取。")
        return {name: row[name] for name in row.keys()}

    def update_review_tag(
        self,
        *,
        key: str,
        label: str,
        hint: str,
        section: str,
        group_key: str,
        updated_by: str,
    ) -> dict[str, Any]:
        normalized_key = str(key or "").strip()
        normalized_label = str(label or "").strip()
        normalized_hint = str(hint or "").strip()
        normalized_section = str(section or "scene").strip()
        normalized_group = str(group_key or "environment").strip()
        normalized_author = str(updated_by or "").strip()
        if not normalized_key:
            raise ValueError("场景标签 key 不能为空。")
        if not normalized_label:
            raise ValueError("场景标签标题不能为空。")
        if len(normalized_label) > 48 or re.search(r"[\x00-\x1f\x7f]", normalized_label):
            raise ValueError("场景标签标题长度或字符不合法。")
        if len(normalized_hint) > 160 or re.search(r"[\x00-\x1f\x7f]", normalized_hint):
            raise ValueError("场景标签说明长度或字符不合法。")
        managed_groups = {
            "environment": "scene",
            "self_intent": "scene",
            "false_trigger": "interaction_decision",
            "true_trigger": "interaction_decision",
            "ra": "egress",
            "no_assist": "egress",
        }
        expected_section = managed_groups.get(normalized_group)
        # Legacy axes (e.g. group=legacy) may keep their original section/group.
        if expected_section is not None and normalized_section != expected_section:
            raise ValueError("场景标签分组不合法。")
        if expected_section is None and normalized_section in {
            "scene",
            "interaction_decision",
            "egress",
        }:
            raise ValueError("场景标签分组不合法。")
        if not normalized_author:
            raise ValueError("编辑人不能为空。")
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT key FROM review_tag_catalog WHERE key = ?",
                (normalized_key,),
            ).fetchone()
            existing = conn.execute(
                "SELECT key FROM review_tag_catalog WHERE label = ? AND key <> ? AND active",
                (normalized_label, normalized_key),
            ).fetchone()
            if existing:
                raise ValueError("该场景标签标题已经存在。")
            try:
                if current:
                    conn.execute(
                        """
                        UPDATE review_tag_catalog
                        SET label = ?, hint = ?, section = ?, group_key = ?, active = TRUE
                        WHERE key = ?
                        """,
                        (
                            normalized_label,
                            normalized_hint,
                            normalized_section,
                            normalized_group,
                            normalized_key,
                        ),
                    )
                else:
                    # Upsert override for built-in catalog keys not yet in the table.
                    conn.execute(
                        """
                        INSERT INTO review_tag_catalog (
                            key, label, hint, section, group_key, created_by, created_at, active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, TRUE)
                        """,
                        (
                            normalized_key,
                            normalized_label,
                            normalized_hint,
                            normalized_section,
                            normalized_group,
                            normalized_author,
                            utc_now(),
                        ),
                    )
            except Exception as exc:
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise ValueError("该场景标签标题已经存在。") from exc
                raise
            row = conn.execute(
                """
                SELECT key, label, hint, section, group_key, created_by, created_at, active
                FROM review_tag_catalog WHERE key = ?
                """,
                (normalized_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("场景标签目录更新后无法读取。")
        return {name: row[name] for name in row.keys()}

    def delete_review_tag(
        self,
        *,
        key: str,
        deleted_by: str,
        label: str = "",
        hint: str = "",
        section: str = "scene",
        group_key: str = "environment",
    ) -> dict[str, Any]:
        """Soft-delete a shared entry; built-ins get an inactive override row."""

        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("场景标签 key 不能为空。")
        if not str(deleted_by or "").strip():
            raise ValueError("删除人不能为空。")
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT key FROM review_tag_catalog WHERE key = ?",
                (normalized_key,),
            ).fetchone()
            if current:
                conn.execute(
                    "UPDATE review_tag_catalog SET active = FALSE WHERE key = ?",
                    (normalized_key,),
                )
            else:
                normalized_label = str(label or "").strip()
                if not normalized_label:
                    raise ValueError("场景标签标题不能为空。")
                conn.execute(
                    """
                    INSERT INTO review_tag_catalog (
                        key, label, hint, section, group_key, created_by, created_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
                    """,
                    (
                        normalized_key,
                        normalized_label,
                        str(hint or "").strip(),
                        str(section or "scene").strip() or "scene",
                        str(group_key or "environment").strip() or "environment",
                        str(deleted_by).strip(),
                        utc_now(),
                    ),
                )
            row = conn.execute(
                """
                SELECT key, label, hint, section, group_key, created_by, created_at, active
                FROM review_tag_catalog WHERE key = ?
                """,
                (normalized_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("场景标签目录删除后无法读取。")
        return {name: row[name] for name in row.keys()}

    def create_missing_evidence(
        self, *, label: str, hint: str, created_by: str
    ) -> dict[str, Any]:
        """Create one shared missing-evidence definition.

        The key is immutable and deliberately opaque so changing the display
        text never changes historical annotation values.
        """

        normalized_label = str(label or "").strip()
        normalized_hint = str(hint or "").strip()
        normalized_author = str(created_by or "").strip()
        if not normalized_label:
            raise ValueError("缺失信息标题不能为空。")
        if len(normalized_label) > 48 or re.search(r"[\x00-\x1f\x7f]", normalized_label):
            raise ValueError("缺失信息标题长度或字符不合法。")
        if len(normalized_hint) > 160 or re.search(r"[\x00-\x1f\x7f]", normalized_hint):
            raise ValueError("缺失信息说明长度或字符不合法。")
        if not normalized_author:
            raise ValueError("创建人不能为空。")
        now = utc_now()
        key = f"custom:{uuid.uuid4().hex}"
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT key FROM missing_evidence_catalog WHERE label = ?",
                (normalized_label,),
            ).fetchone()
            if existing:
                raise ValueError("该缺失信息标题已经存在。")
            try:
                conn.execute(
                    """
                    INSERT INTO missing_evidence_catalog (
                        key, label, hint, created_by, created_at, active
                    ) VALUES (?, ?, ?, ?, ?, TRUE)
                    """,
                    (key, normalized_label, normalized_hint, normalized_author, now),
                )
            except Exception as exc:
                # Keep concurrent duplicate creation a user-facing conflict,
                # while allowing real connection/schema errors to propagate.
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise ValueError("该缺失信息标题已经存在。") from exc
                raise
            row = conn.execute(
                """
                SELECT key, label, hint, created_by, created_at, active
                FROM missing_evidence_catalog
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("缺失信息目录写入后无法读取。")
        return {key: row[key] for key in row.keys()}

    def update_missing_evidence(
        self, *, key: str, label: str, hint: str, updated_by: str
    ) -> dict[str, Any]:
        """Update a shared entry while keeping its stable key unchanged."""

        normalized_key = str(key or "").strip()
        normalized_label = str(label or "").strip()
        normalized_hint = str(hint or "").strip()
        normalized_author = str(updated_by or "").strip()
        if not normalized_key:
            raise ValueError("缺失信息 key 不能为空。")
        if not normalized_label:
            raise ValueError("缺失信息标题不能为空。")
        if len(normalized_label) > 48 or re.search(r"[\x00-\x1f\x7f]", normalized_label):
            raise ValueError("缺失信息标题长度或字符不合法。")
        if len(normalized_hint) > 160 or re.search(r"[\x00-\x1f\x7f]", normalized_hint):
            raise ValueError("缺失信息说明长度或字符不合法。")
        if not normalized_author:
            raise ValueError("编辑人不能为空。")
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT key FROM missing_evidence_catalog WHERE key = ?",
                (normalized_key,),
            ).fetchone()
            existing = conn.execute(
                "SELECT key FROM missing_evidence_catalog WHERE label = ? AND key <> ?",
                (normalized_label, normalized_key),
            ).fetchone()
            if existing:
                raise ValueError("该缺失信息标题已经存在。")
            try:
                if current:
                    conn.execute(
                        """
                        UPDATE missing_evidence_catalog
                        SET label = ?, hint = ?, active = TRUE
                        WHERE key = ?
                        """,
                        (normalized_label, normalized_hint, normalized_key),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO missing_evidence_catalog (
                            key, label, hint, created_by, created_at, active
                        ) VALUES (?, ?, ?, ?, ?, TRUE)
                        """,
                        (
                            normalized_key,
                            normalized_label,
                            normalized_hint,
                            normalized_author,
                            utc_now(),
                        ),
                    )
            except Exception as exc:
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise ValueError("该缺失信息标题已经存在。") from exc
                raise
            row = conn.execute(
                """
                SELECT key, label, hint, created_by, created_at, active
                FROM missing_evidence_catalog
                WHERE key = ?
                """,
                (normalized_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("缺失信息目录更新后无法读取。")
        return {name: row[name] for name in row.keys()}

    def delete_missing_evidence(
        self,
        *,
        key: str,
        deleted_by: str,
        label: str = "",
        hint: str = "",
    ) -> dict[str, Any]:
        """Soft-delete a shared entry and retain it for historical reviews."""

        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("缺失信息 key 不能为空。")
        if not str(deleted_by or "").strip():
            raise ValueError("删除人不能为空。")
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT key FROM missing_evidence_catalog WHERE key = ?",
                (normalized_key,),
            ).fetchone()
            if current:
                conn.execute(
                    "UPDATE missing_evidence_catalog SET active = FALSE WHERE key = ?",
                    (normalized_key,),
                )
            else:
                normalized_label = str(label or "").strip()
                normalized_hint = str(hint or "").strip()
                if not normalized_label:
                    raise ValueError("缺失信息标题不能为空。")
                try:
                    conn.execute(
                        """
                        INSERT INTO missing_evidence_catalog (
                            key, label, hint, created_by, created_at, active
                        ) VALUES (?, ?, ?, ?, ?, FALSE)
                        """,
                        (
                            normalized_key,
                            normalized_label,
                            normalized_hint,
                            str(deleted_by).strip(),
                            utc_now(),
                        ),
                    )
                except Exception as exc:
                    if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                        raise ValueError("该缺失信息标题已经存在。") from exc
                    raise
            row = conn.execute(
                """
                SELECT key, label, hint, created_by, created_at, active
                FROM missing_evidence_catalog
                WHERE key = ?
                """,
                (normalized_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("缺失信息目录删除后无法读取。")
        return {name: row[name] for name in row.keys()}

    def list_reviewers(
        self,
        baseline_scope: str | Sequence[str] = "",
        model_run_id: str = "",
        *,
        baseline_scopes: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        # When a Run is selected, reviewer facets must use the same strict
        # annotation scope as the analysis rows.  Do not attribute legacy
        # (empty model_run_id) annotations to a selected Run.
        params: list[Any] = [model_run_id] if model_run_id else []
        scopes = self._normalize_baseline_scopes(
            baseline_scopes,
            baseline_scope=baseline_scope if isinstance(baseline_scope, str) else "",
        )
        if not scopes and isinstance(baseline_scope, (list, tuple)):
            scopes = self._normalize_baseline_scopes(baseline_scope)
        scope_filter = ""
        if scopes:
            clause, scope_params = self._scope_in_sql(scopes)
            scope_filter = f"AND {clause}"
            params.extend(scope_params)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ann.author,
                       SUM(CASE WHEN ann.author_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN ann.author_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count,
                       COUNT(*) AS review_count
                FROM issues i
                {self._latest_annotation_join(model_run_id)}
                WHERE ann.id IS NOT NULL
                  AND TRIM(ann.author) != ''
                  {scope_filter}
                GROUP BY ann.author
                ORDER BY review_count DESC, ann.author ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "name": str(row["author"]),
                "verified": bool(row["verified_count"])
                and not bool(row["unverified_count"]),
                "verified_count": int(row["verified_count"] or 0),
                "unverified_count": int(row["unverified_count"] or 0),
                "review_count": int(row["review_count"] or 0),
            }
            for row in rows
        ]

    @staticmethod
    def _latest_annotation_join(model_run_id: str = "") -> str:
        normalized_run = str(model_run_id or "").strip()
        if normalized_run:
            # A selected model Run is an explicit Review namespace.  Legacy
            # unbound rows stay unbound and must never leak into another Run's
            # latest-review, reviewer, cluster, or aggregate queries.
            run_clause = "AND a.model_run_id = ?"
        else:
            run_clause = ""
        return """
            LEFT JOIN annotations ann
              ON ann.id = (
                  SELECT a.id FROM annotations a
                  WHERE a.issue_id = i.issue_id
                  {run_clause}
                  ORDER BY a.id DESC LIMIT 1
              )
        """.format(run_clause=run_clause)

    def create_annotation(
        self,
        *,
        issue_id: str,
        model_run_id: str = "",
        label: str,
        review_status: str,
        tags: list[str],
        missing_evidence: list[str],
        note: str,
        author: str,
        author_source: str = "legacy",
        author_verified: bool = False,
        attachments: list[dict[str, Any]] | None = None,
        is_excluded: bool = False,
        expected_previous_annotation_id: int | None | object = _EXPECTED_ANNOTATION_UNSET,
    ) -> dict[str, Any]:
        if label and label not in LABELS:
            raise ValueError(f"不支持的标注标签: {label}")
        if review_status not in REVIEW_STATUSES:
            raise ValueError(f"不支持的 review 状态: {review_status}")
        if not author.strip():
            raise ValueError("复核人不能为空。")
        model_run_id = str(model_run_id or "").strip()
        tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
        missing_evidence = sorted(
            {str(item).strip() for item in missing_evidence if str(item).strip()}
        )
        attachments = attachments or []
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            if model_run_id:
                model_run = conn.execute(
                    "SELECT id FROM model_runs WHERE id = ?", (model_run_id,)
                ).fetchone()
                if model_run is None:
                    raise ValueError("模型 Run 不存在。")
            previous = conn.execute(
                """
                SELECT id FROM annotations
                WHERE issue_id = ? AND model_run_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (issue_id, model_run_id),
            ).fetchone()
            if expected_previous_annotation_id is not _EXPECTED_ANNOTATION_UNSET:
                expected_id = expected_previous_annotation_id
                if expected_id in (None, "", 0, "0"):
                    expected_id = None
                else:
                    try:
                        expected_id = int(expected_id)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("expected_previous_annotation_id 不合法。") from exc
                    if expected_id <= 0:
                        raise ValueError("expected_previous_annotation_id 不合法。")
                current_id = int(previous["id"]) if previous else None
                if current_id != expected_id:
                    current_text = f"#{current_id}" if current_id is not None else "无"
                    expected_text = f"#{expected_id}" if expected_id is not None else "无"
                    raise AnnotationConflictError(
                        "该 Issue 在当前 Model Run 下已被其他人更新；"
                        f"当前版本为 {current_text}，你编辑时为 {expected_text}。"
                        "请刷新 Review 后再保存。"
                    )
            annotation_sql = """
                INSERT INTO annotations (
                    issue_id, model_run_id, label, review_status, is_excluded,
                    tags_json, missing_evidence_json, note, author, author_source,
                    author_verified, supersedes_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                annotation_sql += " RETURNING id"
            cursor = conn.execute(
                annotation_sql,
                (
                    issue_id,
                    model_run_id,
                    label or None,
                    review_status,
                    bool(is_excluded),
                    _json(tags),
                    _json(missing_evidence),
                    note.strip(),
                    author.strip(),
                    author_source.strip() or "legacy",
                    bool(author_verified),
                    previous["id"] if previous else None,
                    now,
                ),
            )
            annotation_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            conn.execute("UPDATE issues SET updated_at = ? WHERE issue_id = ?", (now, issue_id))
            for attachment in attachments:
                conn.execute(
                    """
                    INSERT INTO review_attachments (
                        id, annotation_id, original_name, stored_name,
                        media_type, size_bytes, width, height, sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(attachment["id"]),
                        annotation_id,
                        str(attachment.get("original_name") or ""),
                        str(attachment["stored_name"]),
                        str(attachment["media_type"]),
                        int(attachment["size_bytes"]),
                        int(attachment["width"]),
                        int(attachment["height"]),
                        str(attachment["sha256"]),
                        now,
                    ),
                )
            row = conn.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,)).fetchone()
        result = self._annotation_dict(row)
        result["attachments"] = [
            {
                **attachment,
                "annotation_id": annotation_id,
                "created_at": now,
            }
            for attachment in attachments
        ]
        return result

    def delete_annotation(
        self,
        *,
        issue_id: str,
        annotation_id: int,
    ) -> dict[str, Any] | None:
        """Delete one review version and reconnect its superseding chain."""
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotations WHERE id = ? AND issue_id = ?",
                (annotation_id, issue_id),
            ).fetchone()
            if row is None:
                return None
            attachments = conn.execute(
                "SELECT * FROM review_attachments WHERE annotation_id = ? ORDER BY created_at ASC",
                (annotation_id,),
            ).fetchall()
            conn.execute(
                "UPDATE annotations SET supersedes_id = ? WHERE supersedes_id = ?",
                (row["supersedes_id"], annotation_id),
            )
            conn.execute(
                "DELETE FROM annotations WHERE id = ? AND issue_id = ?",
                (annotation_id, issue_id),
            )
            conn.execute(
                "UPDATE issues SET updated_at = ? WHERE issue_id = ?",
                (now, issue_id),
            )
        result = self._annotation_dict(row)
        result["attachments"] = [self._attachment_dict(item) for item in attachments]
        return result

    def get_review_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
        return self._attachment_dict(row) if row else None

    def review_attachment_storage_bytes(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM review_attachments"
            ).fetchone()
        return int(row["total"] or 0)

    @staticmethod
    def _annotation_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "issue_id": row["issue_id"],
            "model_run_id": (
                str(row["model_run_id"] or "")
                if "model_run_id" in row.keys()
                else ""
            ),
            "label": row["label"] or "",
            "review_status": row["review_status"] if "review_status" in row.keys() else "pending",
            "is_excluded": bool(row["is_excluded"]) if "is_excluded" in row.keys() else False,
            "tags": _json_load(row["tags_json"], []),
            "missing_evidence": _json_load(
                row["missing_evidence_json"] if "missing_evidence_json" in row.keys() else "[]", []
            ),
            "note": row["note"],
            "author": row["author"],
            "author_source": (
                row["author_source"] if "author_source" in row.keys() else "legacy"
            ),
            "author_verified": bool(row["author_verified"])
            if "author_verified" in row.keys()
            else False,
            "supersedes_id": row["supersedes_id"],
            "created_at": row["created_at"],
        }
