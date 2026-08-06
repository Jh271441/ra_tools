from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Iterable, Sequence

from ..sanitization import redact_sensitive_fields
from .shared import BATCH_JOB_STATUSES, _json, _json_load, utc_now


class DatabaseBatchMixin:
    def create_job(
        self,
        *,
        issue_id: str,
        requested_by: str,
        model_name: str,
        base_url: str,
        config: dict[str, Any],
        requested_by_source: str = "legacy",
        requested_by_verified: bool = False,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO inference_jobs (
                    id, issue_id, status, requested_by, requested_by_source,
                    requested_by_verified, model_name, base_url, config_json, created_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    issue_id,
                    requested_by.strip(),
                    requested_by_source.strip() or "legacy",
                    bool(requested_by_verified),
                    model_name.strip(),
                    base_url.strip(),
                    _json(config),
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM inference_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row)

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_text: str = "",
        log_path: str = "",
    ) -> dict[str, Any] | None:
        now = utc_now()
        values: dict[str, Any] = {"status": status}
        if status == "running":
            values["started_at"] = now
        if status in {"succeeded", "failed"}:
            values["finished_at"] = now
        if result is not None:
            values["result_json"] = _json(result)
        if error_text:
            values["error_text"] = error_text
        if log_path:
            values["log_path"] = log_path
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self.connect() as conn:
            conn.execute(f"UPDATE inference_jobs SET {assignments} WHERE id = ?", (*values.values(), job_id))
            row = conn.execute("SELECT * FROM inference_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM inference_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_inference_jobs(
        self,
        *,
        requested_by: str = "",
        status: str = "",
        page_size: int = 100,
    ) -> dict[str, Any]:
        page_size = min(max(1, page_size), 500)
        where: list[str] = []
        params: list[Any] = []
        if requested_by.strip():
            where.append("requested_by = ?")
            params.append(requested_by.strip())
        if status in {"queued", "running", "succeeded", "failed"}:
            where.append("status = ?")
            params.append(status)
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM inference_jobs {condition}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT * FROM inference_jobs
                {condition}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, page_size),
            ).fetchall()
            requester_rows = conn.execute(
                """
                SELECT requested_by,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count,
                       COUNT(*) AS job_count
                FROM inference_jobs
                WHERE TRIM(requested_by) != ''
                GROUP BY requested_by
                ORDER BY job_count DESC, requested_by ASC
                """
            ).fetchall()
        return {
            "items": [self._job_dict(row) for row in rows],
            "total": int(total),
            "requesters": [
                {
                    "name": str(row["requested_by"]),
                    "verified": bool(row["verified_count"])
                    and not bool(row["unverified_count"]),
                    "verified_count": int(row["verified_count"] or 0),
                    "unverified_count": int(row["unverified_count"] or 0),
                    "job_count": int(row["job_count"] or 0),
                }
                for row in requester_rows
            ],
        }

    def create_batch_prediction_job(
        self,
        *,
        name: str,
        issue_ids: list[str],
        requested_by: str,
        requested_by_source: str = "legacy",
        requested_by_verified: bool = False,
        provider_id: str = "kylin",
        requested_model_id: str,
        resolved_model_id: str,
        model_source: str,
        catalog_sha256: str,
        model_validation_status: str = "legacy",
        prompt_version: str = "",
        prompt_template: str = "",
        prompt_template_sha256: str = "",
        prompt_mode: str = "",
        input_profile: str = "",
        input_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_issue_ids = [str(issue_id).strip() for issue_id in issue_ids]
        if not normalized_issue_ids or any(not issue_id for issue_id in normalized_issue_ids):
            raise ValueError("Batch 任务至少需要一个有效 issue_id。")
        if len(set(normalized_issue_ids)) != len(normalized_issue_ids):
            raise ValueError("Batch 任务中的 issue_id 不能重复。")

        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            known_issue_ids: set[str] = set()
            for offset in range(0, len(normalized_issue_ids), 500):
                chunk = normalized_issue_ids[offset : offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                known_issue_ids.update(
                    str(row["issue_id"])
                    for row in conn.execute(
                        f"SELECT issue_id FROM issues WHERE issue_id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            missing_issue_ids = [
                issue_id
                for issue_id in normalized_issue_ids
                if issue_id not in known_issue_ids
            ]
            if missing_issue_ids:
                preview = ", ".join(missing_issue_ids[:5])
                suffix = (
                    f" 等 {len(missing_issue_ids)} 个"
                    if len(missing_issue_ids) > 5
                    else ""
                )
                raise ValueError(f"Batch 任务包含未导入的 Issue：{preview}{suffix}")

            conn.execute(
                """
                INSERT INTO batch_prediction_jobs (
                    id, name, status, requested_by, requested_by_source,
                    requested_by_verified, total_count, provider_id, requested_model_id,
                    resolved_model_id, model_source, catalog_sha256,
                    model_validation_status, model_name, prompt_version,
                    prompt_template, prompt_template_sha256, prompt_mode,
                    input_profile, input_config_json, created_at
                ) VALUES (
                    ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    job_id,
                    name.strip() or f"Batch {now[:16].replace('T', ' ')} UTC",
                    requested_by.strip(),
                    requested_by_source.strip() or "legacy",
                    bool(requested_by_verified),
                    len(normalized_issue_ids),
                    str(provider_id or "kylin").strip().lower() or "kylin",
                    requested_model_id.strip(),
                    resolved_model_id.strip(),
                    model_source.strip() or "ra_model_gateway",
                    catalog_sha256.strip(),
                    model_validation_status.strip(),
                    resolved_model_id.strip(),
                    prompt_version.strip(),
                    prompt_template,
                    prompt_template_sha256.strip(),
                    prompt_mode.strip(),
                    input_profile.strip(),
                    _json(input_config),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO batch_prediction_items (
                    job_id, issue_id, ordinal, status
                ) VALUES (?, ?, ?, 'queued')
                """,
                [
                    (job_id, issue_id, ordinal)
                    for ordinal, issue_id in enumerate(normalized_issue_ids)
                ],
            )
        result = self.get_batch_prediction_job(job_id)
        if result is None:
            raise RuntimeError("Batch 任务创建后无法读取。")
        return result

    def update_batch_prediction_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        completed_count: int | None = None,
        success_count: int | None = None,
        failed_count: int | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        experiment_source: str | None = None,
        config_sha256: str | None = None,
        model_run_id: str | None = None,
        publish_status: str | None = None,
        autotriage_batch_id: str | None = None,
        autotriage_writer: str | None = None,
        summary: dict[str, Any] | None = None,
        error_text: str | None = None,
        log_path: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {}
        if status is not None:
            if status not in BATCH_JOB_STATUSES:
                raise ValueError(f"Batch 任务状态非法：{status}")
            values["status"] = status
            if status == "running":
                values["started_at"] = utc_now()
            if status in {"succeeded", "partial", "failed"}:
                values["finished_at"] = utc_now()
        if publish_status is not None and publish_status not in BATCH_PUBLISH_STATUSES:
            raise ValueError(f"Batch 推送状态非法：{publish_status}")
        for count_name, count_value in (
            ("completed_count", completed_count),
            ("success_count", success_count),
            ("failed_count", failed_count),
        ):
            if count_value is not None and int(count_value) < 0:
                raise ValueError(f"{count_name} 不能为负数。")
        for key, value in (
            (
                "completed_count",
                int(completed_count) if completed_count is not None else None,
            ),
            ("success_count", int(success_count) if success_count is not None else None),
            ("failed_count", int(failed_count) if failed_count is not None else None),
            ("model_name", model_name),
            ("prompt_version", prompt_version),
            ("experiment_source", experiment_source),
            ("config_sha256", config_sha256),
            ("model_run_id", model_run_id),
            ("publish_status", publish_status),
            ("autotriage_batch_id", autotriage_batch_id),
            ("autotriage_writer", autotriage_writer),
            ("error_text", error_text),
            ("log_path", log_path),
        ):
            if value is not None:
                values[key] = value
        if summary is not None:
            values["summary_json"] = _json(summary)
        if not values:
            return self.get_batch_prediction_job(job_id)
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                f"UPDATE batch_prediction_jobs SET {assignments} WHERE id = ?",
                (*values.values(), job_id),
            )
        return self.get_batch_prediction_job(job_id)

    @staticmethod
    def _refresh_batch_prediction_counts(
        conn: sqlite3.Connection,
        job_id: str,
    ) -> None:
        conn.execute(
            """
            UPDATE batch_prediction_jobs
            SET completed_count = (
                    SELECT COUNT(*)
                    FROM batch_prediction_items bpi
                    WHERE bpi.job_id = batch_prediction_jobs.id
                      AND bpi.status IN ('succeeded', 'failed')
                ),
                success_count = (
                    SELECT COUNT(*)
                    FROM batch_prediction_items bpi
                    WHERE bpi.job_id = batch_prediction_jobs.id
                      AND bpi.status = 'succeeded'
                ),
                failed_count = (
                    SELECT COUNT(*)
                    FROM batch_prediction_items bpi
                    WHERE bpi.job_id = batch_prediction_jobs.id
                      AND bpi.status = 'failed'
                )
            WHERE id = ?
            """,
            (job_id,),
        )

    def update_batch_prediction_items(
        self,
        job_id: str,
        results: list[dict[str, Any]],
    ) -> int:
        issue_ids = [str(result.get("issue_id") or "").strip() for result in results]
        if any(not issue_id for issue_id in issue_ids):
            raise ValueError("Batch 结果缺少 issue_id。")
        if len(set(issue_ids)) != len(issue_ids):
            raise ValueError("同一次 Batch 结果更新不能包含重复 issue_id。")

        finished_at = utc_now()
        updated = 0
        with self._write_lock, self.connect() as conn:
            for result in results:
                issue_id = str(result.get("issue_id") or "").strip()
                success = bool(result.get("success"))
                cursor = conn.execute(
                    """
                    UPDATE batch_prediction_items
                    SET status = ?,
                        result_json = ?,
                        error_text = ?,
                        started_at = COALESCE(started_at, ?),
                        finished_at = ?
                    WHERE job_id = ? AND issue_id = ?
                    """,
                    (
                        "succeeded" if success else "failed",
                        _json(result),
                        str(result.get("error") or ""),
                        finished_at,
                        finished_at,
                        job_id,
                        issue_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Batch 任务 {job_id} 不包含 issue_id={issue_id}。"
                    )
                updated += 1
            self._refresh_batch_prediction_counts(conn, job_id)
        return updated

    def update_batch_prediction_records(
        self,
        job_id: str,
        records: list[dict[str, Any]],
    ) -> int:
        updated = 0
        with self._write_lock, self.connect() as conn:
            for record in records:
                issue_id = str(record.get("issue_id") or "").strip()
                record_id = str(
                    record.get("record_id") or record.get("id") or ""
                ).strip()
                if not issue_id or not record_id:
                    continue
                cursor = conn.execute(
                    """
                    UPDATE batch_prediction_items
                    SET autotriage_record_id = ?
                    WHERE job_id = ? AND issue_id = ?
                    """,
                    (record_id, job_id, issue_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"Batch 任务 {job_id} 不包含 issue_id={issue_id}。"
                    )
                updated += 1
        return updated

    def next_queued_batch_prediction_job(self) -> dict[str, Any] | None:
        """Return the oldest durable prediction job waiting for the runner."""

        queue_order = "queue_order" if self.backend == "postgresql" else "rowid"
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT id
                FROM batch_prediction_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC, {queue_order} ASC
                LIMIT 1
                """
            ).fetchone()
        return self.get_batch_prediction_job(str(row["id"])) if row else None

    def get_batch_prediction_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM batch_prediction_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            items = conn.execute(
                """
                SELECT * FROM batch_prediction_items
                WHERE job_id = ?
                ORDER BY ordinal ASC
                """,
                (job_id,),
            ).fetchall()
        result = self._batch_job_dict(row)
        result["items"] = [self._batch_item_dict(item) for item in items]
        return result

    def list_batch_prediction_jobs(
        self,
        *,
        requested_by: str = "",
        status: str = "",
        model_id: str = "",
        prompt_version: str = "",
        prompt_mode: str = "",
        prompt_sha256: str = "",
        input_profile: str = "",
        page_size: int = 100,
    ) -> dict[str, Any]:
        page_size = min(max(1, page_size), 200)
        where: list[str] = []
        params: list[Any] = []
        if requested_by.strip():
            where.append("requested_by = ?")
            params.append(requested_by.strip())
        if status in BATCH_JOB_STATUSES:
            where.append("status = ?")
            params.append(status)
        if model_id.strip():
            where.append("(requested_model_id = ? OR resolved_model_id = ?)")
            params.extend((model_id.strip(), model_id.strip()))
        if prompt_version.strip():
            where.append("prompt_version = ?")
            params.append(prompt_version.strip())
        if prompt_mode.strip():
            where.append("prompt_mode = ?")
            params.append(prompt_mode.strip())
        if prompt_sha256.strip():
            where.append("prompt_template_sha256 = ?")
            params.append(prompt_sha256.strip())
        if input_profile.strip():
            where.append("input_profile = ?")
            params.append(input_profile.strip())
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM batch_prediction_jobs {condition}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT * FROM batch_prediction_jobs
                {condition}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, page_size),
            ).fetchall()
            requester_rows = conn.execute(
                """
                SELECT requested_by,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 1 ELSE 0 END)
                           AS verified_count,
                       SUM(CASE WHEN requested_by_verified = TRUE THEN 0 ELSE 1 END)
                           AS unverified_count,
                       COUNT(*) AS job_count
                FROM batch_prediction_jobs
                WHERE TRIM(requested_by) != ''
                GROUP BY requested_by
                ORDER BY job_count DESC, requested_by ASC
                """
            ).fetchall()
            model_rows = conn.execute(
                """
                SELECT model_id, COUNT(*) AS job_count
                FROM (
                    SELECT id, TRIM(requested_model_id) AS model_id
                    FROM batch_prediction_jobs
                    WHERE TRIM(requested_model_id) != ''
                    UNION
                    SELECT id, TRIM(resolved_model_id) AS model_id
                    FROM batch_prediction_jobs
                    WHERE TRIM(resolved_model_id) != ''
                ) AS model_catalog
                GROUP BY model_id
                ORDER BY job_count DESC, model_id ASC
                """
            ).fetchall()
            prompt_rows = conn.execute(
                """
                SELECT prompt_version, prompt_mode, prompt_template_sha256,
                       COUNT(*) AS job_count
                FROM batch_prediction_jobs
                WHERE TRIM(prompt_version) != ''
                GROUP BY prompt_version, prompt_mode, prompt_template_sha256
                ORDER BY job_count DESC, prompt_version ASC,
                         prompt_mode ASC, prompt_template_sha256 ASC
                """
            ).fetchall()
            input_rows = conn.execute(
                """
                SELECT input_profile, COUNT(*) AS job_count
                FROM batch_prediction_jobs
                WHERE TRIM(input_profile) != ''
                GROUP BY input_profile
                ORDER BY job_count DESC, input_profile ASC
                """
            ).fetchall()
        return {
            # List responses intentionally contain summaries only.  Item
            # results can be large and belong to the per-job detail endpoint.
            "items": [self._batch_job_dict(row) for row in rows],
            "total": int(total),
            "requesters": [
                {
                    "name": str(row["requested_by"]),
                    "verified": bool(row["verified_count"])
                    and not bool(row["unverified_count"]),
                    "verified_count": int(row["verified_count"] or 0),
                    "unverified_count": int(row["unverified_count"] or 0),
                    "job_count": int(row["job_count"] or 0),
                }
                for row in requester_rows
            ],
            "facets": {
                "models": [
                    {
                        "id": str(row["model_id"]),
                        "job_count": int(row["job_count"] or 0),
                    }
                    for row in model_rows
                ],
                "prompts": [
                    {
                        "version": str(row["prompt_version"]),
                        "mode": str(row["prompt_mode"] or ""),
                        "sha256": str(row["prompt_template_sha256"] or ""),
                        "job_count": int(row["job_count"] or 0),
                    }
                    for row in prompt_rows
                ],
                "input_profiles": [
                    {
                        "id": str(row["input_profile"]),
                        "job_count": int(row["job_count"] or 0),
                    }
                    for row in input_rows
                ],
            },
        }

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "issue_id": row["issue_id"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "requested_by_source": (
                row["requested_by_source"]
                if "requested_by_source" in row.keys()
                else "legacy"
            ),
            "requested_by_verified": bool(row["requested_by_verified"])
            if "requested_by_verified" in row.keys()
            else False,
            "model_name": row["model_name"],
            "config": redact_sensitive_fields(_json_load(row["config_json"], {})),
            "result": redact_sensitive_fields(_json_load(row["result_json"], {})),
            "error_text": row["error_text"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _batch_job_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "requested_by": row["requested_by"],
            "requested_by_source": row["requested_by_source"],
            "requested_by_verified": bool(row["requested_by_verified"]),
            "total_count": int(row["total_count"] or 0),
            "completed_count": int(row["completed_count"] or 0),
            "success_count": int(row["success_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
            "provider_id": row["provider_id"]
            if "provider_id" in row.keys()
            else "kylin",
            "requested_model_id": row["requested_model_id"]
            if "requested_model_id" in row.keys()
            else "",
            "resolved_model_id": row["resolved_model_id"]
            if "resolved_model_id" in row.keys()
            else "",
            "model_source": row["model_source"]
            if "model_source" in row.keys()
            else "legacy_server_default",
            "catalog_sha256": row["catalog_sha256"]
            if "catalog_sha256" in row.keys()
            else "",
            "model_validation_status": row["model_validation_status"]
            if "model_validation_status" in row.keys()
            else "",
            "model_name": row["model_name"],
            "prompt_version": row["prompt_version"],
            "prompt_template": row["prompt_template"]
            if "prompt_template" in row.keys()
            else "",
            "prompt_template_sha256": row["prompt_template_sha256"]
            if "prompt_template_sha256" in row.keys()
            else "",
            "prompt_mode": row["prompt_mode"]
            if "prompt_mode" in row.keys()
            else "",
            "input_profile": row["input_profile"]
            if "input_profile" in row.keys()
            else "",
            "input_config": redact_sensitive_fields(
                _json_load(
                    row["input_config_json"]
                    if "input_config_json" in row.keys()
                    else "{}",
                    {},
                )
            ),
            "experiment_source": row["experiment_source"],
            "config_sha256": row["config_sha256"],
            "model_run_id": row["model_run_id"] or "",
            "publish_status": row["publish_status"],
            "autotriage_batch_id": row["autotriage_batch_id"],
            "autotriage_writer": row["autotriage_writer"],
            "summary": redact_sensitive_fields(_json_load(row["summary_json"], {})),
            "error_text": row["error_text"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _batch_item_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "issue_id": row["issue_id"],
            "ordinal": int(row["ordinal"]),
            "status": row["status"],
            "result": redact_sensitive_fields(_json_load(row["result_json"], {})),
            "error_text": row["error_text"],
            "autotriage_record_id": row["autotriage_record_id"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @classmethod
    def _case_batch_job_dict(cls, row: sqlite3.Row) -> dict[str, Any]:
        result = cls._batch_job_dict(row)
        result["item"] = {
            "job_id": row["item_job_id"],
            "issue_id": row["item_issue_id"],
            "ordinal": int(row["item_ordinal"]),
            "status": row["item_status"],
            "result": redact_sensitive_fields(
                _json_load(row["item_result_json"], {})
            ),
            "error_text": row["item_error_text"],
            "autotriage_record_id": row["item_autotriage_record_id"],
            "started_at": row["item_started_at"],
            "finished_at": row["item_finished_at"],
        }
        return result
