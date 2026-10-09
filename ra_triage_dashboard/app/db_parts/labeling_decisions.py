"""Labeling decisions storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
from typing import Any, Sequence
from .shared import (
    LABELS,
    LabelAnnotationConflictError,
    _json,
    _json_load,
    utc_now,
)
from .labeling_shared import _clean_values, _source_fingerprint


class LabelingDecisionsMixin:
    def _resolve_loaded_label_case(
        self,
        *,
        heads: Sequence[dict[str, Any]],
        assigned_authors: Sequence[str],
        latest_resolution: Any = None,
        result_revision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        heads = list(heads)
        assigned_authors = list(assigned_authors)
        source_ids = sorted(int(item["id"]) for item in heads)
        original_conflict = len({item.get("expected_output") for item in heads if item.get("expected_output") in LABELS}) > 1
        adjudication = None
        if latest_resolution is not None:
            expected_sources = sorted(
                int(value) for value in _json_load(latest_resolution["source_revision_ids_json"], [])
            )
            adjudication = {
                "id": int(latest_resolution["id"]),
                "created_by": str(latest_resolution["created_by"] or ""),
                "created_by_source": str(latest_resolution["created_by_source"] or "legacy"),
                "created_by_verified": bool(latest_resolution["created_by_verified"]),
                "created_at": str(latest_resolution["created_at"] or ""),
                "source_revision_ids": expected_sources,
                "stale": expected_sources != source_ids or result_revision is None,
                "result": result_revision,
            }
            if not adjudication["stale"]:
                output = str(adjudication["result"].get("expected_output") or "")
                return {
                    "state": "resolved",
                    "method": "adjudication",
                    "expected_output": output,
                    "result_revision": adjudication["result"],
                    "heads": heads,
                    "assigned_count": len(assigned_authors) if assigned_authors else len(heads),
                    "submitted_count": len(heads),
                    "adjudication": adjudication,
                    "original_conflict": original_conflict,
                }
        assigned_count = len(assigned_authors) if assigned_authors else (1 if heads else 0)
        submitted_count = len(heads)
        valid_outputs = [item["expected_output"] for item in heads if item["expected_output"] in LABELS]
        if adjudication and adjudication["stale"]:
            state = "stale"
            method = "adjudication"
            output = ""
            result_revision = None
        elif not heads or (assigned_authors and submitted_count < assigned_count):
            state = "pending"
            method = "consensus" if assigned_count > 1 else "single"
            output = ""
            result_revision = heads[-1] if heads else None
        elif len(valid_outputs) < submitted_count:
            state = "pending"
            method = "consensus" if assigned_count > 1 else "single"
            output = ""
            result_revision = heads[-1]
        elif len(set(valid_outputs)) > 1:
            state = "conflict"
            method = "consensus"
            output = ""
            result_revision = None
        else:
            state = "resolved"
            method = "consensus" if assigned_count > 1 else "single"
            output = valid_outputs[0] if valid_outputs else ""
            result_revision = max(heads, key=lambda item: int(item["id"]))
        return {
            "state": state,
            "method": method,
            "expected_output": output,
            "result_revision": result_revision,
            "heads": heads,
            "assigned_count": assigned_count,
            "submitted_count": submitted_count,
            "original_conflict": original_conflict,
            "adjudication": adjudication,
        }

    @staticmethod
    def _issue_label_decision_dict(row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "baseline_scope": str(row["baseline_scope"] or ""),
            "issue_id": str(row["issue_id"] or ""),
            "expected_output": str(row["expected_output"] or ""),
            "source_case_ids": [
                str(value) for value in _json_load(row["source_case_ids_json"], [])
            ],
            "source_revision_ids": [
                int(value) for value in _json_load(row["source_revision_ids_json"], [])
            ],
            "source_fingerprint": str(row["source_fingerprint"] or ""),
            "rationale": str(row["rationale"] or ""),
            "supersedes_id": (
                int(row["supersedes_id"])
                if row["supersedes_id"] not in (None, "")
                else None
            ),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
        }

    def list_issue_label_decisions(
        self, *, baseline_scope: str, issue_id: str
    ) -> list[dict[str, Any]]:
        scope = str(baseline_scope or "").strip()
        issue_key = str(issue_id or "").strip()
        if not scope or not issue_key:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM issue_label_decisions "
                "WHERE baseline_scope = ? AND issue_id = ? ORDER BY id DESC",
                (scope, issue_key),
            ).fetchall()
        return [self._issue_label_decision_dict(row) for row in rows]

    def adjudicate_issue_label(
        self,
        *,
        baseline_scope: str,
        issue_id: str,
        expected_output: str,
        rationale: str,
        actor: str,
        actor_source: str,
        actor_verified: bool,
        expected_source_fingerprint: str,
        expected_previous_decision_id: int | None = None,
    ) -> dict[str, Any]:
        scope = str(baseline_scope or "").strip()
        issue_key = str(issue_id or "").strip()
        output = str(expected_output or "").strip()
        explanation = str(rationale or "").strip()
        reviewer = str(actor or "").strip().lower()
        if not actor_verified or not reviewer:
            raise PermissionError("Issue 标签裁决需要已验证 writer 或管理员。")
        if output not in LABELS:
            raise ValueError("Issue 标签裁决必须选择合法三分类结果。")
        if not explanation:
            raise ValueError("Issue 标签裁决必须填写裁决依据。")
        if len(explanation) > 8000:
            raise ValueError("裁决依据不能超过 8000 个字符。")
        with self._write_lock, self.connect() as conn:
            issue_sql = (
                "SELECT issue_id, baseline_scope FROM issues "
                "WHERE issue_id = ? AND baseline_scope = ?"
            )
            if self.backend == "postgresql":
                issue_sql += " FOR UPDATE"
            issue = conn.execute(issue_sql, (issue_key, scope)).fetchone()
            if issue is None:
                raise ValueError("Issue 不存在或不属于当前数据集。")
            active = conn.execute(
                "SELECT status FROM labeling_scope_state WHERE baseline_scope = ?",
                (scope,),
            ).fetchone()
            if active is None or str(active["status"] or "") != "active":
                raise PermissionError("当前数据集尚未启用 Case 标注写入。")
            projection = self.project_issue_label_states(
                scope, [issue_key], include_sources=True, connection=conn
            )[issue_key]
            sources = list(projection.get("sources") or [])
            if not sources:
                raise ValueError("当前 Issue 还没有可裁决的标注来源。")
            incomplete = [
                source for source in sources
                if source.get("task_id")
                and str(source.get("state") or "pending") != "resolved"
            ]
            if incomplete:
                raise ValueError(
                    "仍有任务来源未完成或未裁决，不能跳过任务结果直接做 Issue 裁决。"
                )
            source_fingerprint = str(projection.get("source_fingerprint") or "")
            if not source_fingerprint or source_fingerprint != str(
                expected_source_fingerprint or ""
            ):
                raise LabelAnnotationConflictError(
                    "标注来源已变化，请刷新后重新裁决。"
                )
            previous_row = conn.execute(
                "SELECT * FROM issue_label_decisions "
                "WHERE baseline_scope = ? AND issue_id = ? ORDER BY id DESC LIMIT 1",
                (scope, issue_key),
            ).fetchone()
            previous_id = int(previous_row["id"]) if previous_row is not None else None
            if previous_id != expected_previous_decision_id:
                raise LabelAnnotationConflictError(
                    "Issue 标签裁决已变化，请刷新后重新提交。"
                )
            source_case_ids = sorted(
                str(source.get("label_case_id") or "") for source in sources
                if str(source.get("label_case_id") or "")
            )
            source_revision_ids = sorted(
                {
                    int(value)
                    for source in sources
                    for value in source.get("source_revision_ids") or []
                }
            )
            now = utc_now()
            sql = """
                INSERT INTO issue_label_decisions (
                    baseline_scope, issue_id, expected_output,
                    source_case_ids_json, source_revision_ids_json,
                    source_fingerprint, rationale, supersedes_id,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                sql += " RETURNING id"
            cursor = conn.execute(
                sql,
                (
                    scope,
                    issue_key,
                    output,
                    _json(source_case_ids),
                    _json(source_revision_ids),
                    source_fingerprint,
                    explanation,
                    previous_id,
                    reviewer,
                    str(actor_source or "legacy"),
                    bool(actor_verified),
                    now,
                ),
            )
            decision_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            self._mark_labeling_change(conn)
            row = conn.execute(
                "SELECT * FROM issue_label_decisions WHERE id = ?",
                (decision_id,),
            ).fetchone()
            refreshed = self.project_issue_label_states(
                scope, [issue_key], include_sources=True, connection=conn
            )[issue_key]
        return {
            "decision": self._issue_label_decision_dict(row),
            "label_state": refreshed,
        }

    def adjudicate_label_case(
        self,
        *,
        label_case_id: str,
        source_revision_ids: Sequence[int],
        expected_output: str,
        tags: Sequence[str],
        evidence_gaps: Sequence[str],
        rationale: str,
        is_excluded: bool,
        actor: str,
        actor_source: str,
        actor_verified: bool,
        expected_previous_resolution_id: int | None = None,
    ) -> dict[str, Any]:
        label = str(expected_output or "").strip()
        if label not in LABELS:
            raise ValueError("裁决必须选择有效的期望输出。")
        normalized_rationale = str(rationale or "").strip()
        if len(normalized_rationale) > 8000:
            raise ValueError("裁决依据不能超过 8000 个字符。")
        normalized_sources = sorted({int(value) for value in source_revision_ids})
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            case_row = conn.execute(
                "SELECT * FROM label_cases WHERE id = ?"
                + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                (label_case_id,),
            ).fetchone()
            if case_row is None:
                raise ValueError("标注 Case 不存在。")
            current = self._resolve_label_case_with_conn(conn, case_row)
            if not str(case_row["task_id"] or ""):
                raise ValueError("自由标注无需任务冲突裁决。")
            campaign = conn.execute(
                "SELECT purpose, lifecycle, legacy_read_only FROM issue_work_splits WHERE id = ?",
                (str(case_row["task_id"]),),
            ).fetchone()
            if (
                campaign is None
                or bool(campaign["legacy_read_only"])
                or str(campaign["lifecycle"] or "active") != "active"
                or str(campaign["purpose"] or "labeling") != "labeling"
            ):
                raise ValueError("该 Campaign 当前只读，不能提交标注裁决。")
            if current["state"] not in {"conflict", "stale"}:
                raise ValueError("当前任务标注没有需要裁决的冲突。")
            current_sources = sorted(int(item["id"]) for item in current["heads"])
            if normalized_sources != current_sources or not normalized_sources:
                raise LabelAnnotationConflictError("参与裁决的标注版本已变化，请刷新后重新裁决。")
            previous_resolution = conn.execute(
                "SELECT id FROM label_resolutions WHERE label_case_id = ? ORDER BY id DESC LIMIT 1",
                (label_case_id,),
            ).fetchone()
            previous_resolution_id = int(previous_resolution["id"]) if previous_resolution else None
            if previous_resolution_id != expected_previous_resolution_id:
                raise LabelAnnotationConflictError("该 Case 已有更新的裁决，请刷新后重试。")
            previous_actor_revision = conn.execute(
                """
                SELECT id FROM label_revisions
                WHERE label_case_id = ? AND lower(author) = lower(?)
                ORDER BY id DESC LIMIT 1
                """,
                (label_case_id, actor),
            ).fetchone()
            revision_sql = """
                INSERT INTO label_revisions (
                    label_case_id, expected_output, tags_json, evidence_gaps_json,
                    rationale, is_excluded, author, author_source,
                    author_verified, revision_kind, supersedes_id,
                    source_annotation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'adjudication', ?, NULL, ?)
            """
            if self.backend == "postgresql":
                revision_sql += " RETURNING id"
            revision_cursor = conn.execute(
                revision_sql,
                (
                    label_case_id,
                    label,
                    _json(_clean_values(tags)),
                    _json(_clean_values(evidence_gaps)),
                    normalized_rationale,
                    bool(is_excluded),
                    str(actor or "").strip(),
                    str(actor_source or "legacy").strip() or "legacy",
                    bool(actor_verified),
                    int(previous_actor_revision["id"]) if previous_actor_revision else None,
                    now,
                ),
            )
            revision_id = int(revision_cursor.fetchone()["id"]) if self.backend == "postgresql" else int(revision_cursor.lastrowid)
            resolution_sql = """
                INSERT INTO label_resolutions (
                    label_case_id, method, result_revision_id,
                    source_revision_ids_json, source_fingerprint, supersedes_id,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, 'adjudication', ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                resolution_sql += " RETURNING id"
            resolution_cursor = conn.execute(
                resolution_sql,
                (
                    label_case_id,
                    revision_id,
                    _json(normalized_sources),
                    _source_fingerprint(normalized_sources),
                    previous_resolution_id,
                    str(actor or "").strip(),
                    str(actor_source or "legacy").strip() or "legacy",
                    bool(actor_verified),
                    now,
                ),
            )
            resolution_id = int(resolution_cursor.fetchone()["id"]) if self.backend == "postgresql" else int(resolution_cursor.lastrowid)
            self._mark_labeling_change(conn)
        result = self.get_label_case(label_case_id)
        if result is None:
            raise RuntimeError("裁决保存后无法读取。")
        result["saved_resolution_id"] = resolution_id
        return result
