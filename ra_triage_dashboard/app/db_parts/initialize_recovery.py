"""Initialization phase: recovery. Uses the caller-owned lock and connection."""
from __future__ import annotations
from .shared import _json, _json_load, utc_now


def initialize_recovery(self, conn) -> None:
    interrupted_at = utc_now()
    # A hard restart can happen after an immutable manual-batch Run
    # commits but before the parent job/item linkage is finalized.
    # Recover that linkage first, then let the normal interruption
    # handling fail only items which truly have no persisted result.
    manual_runs = conn.execute(
        """
                SELECT id, metadata_json
                FROM model_runs
                WHERE kind = 'manual_batch'
                ORDER BY created_at DESC
                """
    ).fetchall()
    for run_row in manual_runs:
        metadata = _json_load(run_row["metadata_json"], {})
        if not isinstance(metadata, dict):
            continue
        batch_job_id = str(
            metadata.get("batch_prediction_job_id") or ""
        ).strip()
        if not batch_job_id:
            continue
        experiment = metadata.get("experiment")
        if not isinstance(experiment, dict):
            experiment = {}
        conn.execute(
            """
                    UPDATE batch_prediction_jobs
                    SET model_run_id = COALESCE(model_run_id, ?),
                        model_name = CASE WHEN TRIM(model_name) = '' THEN ? ELSE model_name END,
                        prompt_version = CASE WHEN TRIM(prompt_version) = '' THEN ? ELSE prompt_version END,
                        experiment_source = CASE
                            WHEN TRIM(experiment_source) = '' THEN ?
                            ELSE experiment_source
                        END,
                        config_sha256 = CASE
                            WHEN TRIM(config_sha256) = '' THEN ?
                            ELSE config_sha256
                        END
                    WHERE id = ?
                    """,
            (
                str(run_row["id"]),
                str(experiment.get("model_name") or ""),
                str(experiment.get("prompt_version") or ""),
                str(experiment.get("experiment_source") or ""),
                str(metadata.get("config_sha256") or ""),
                batch_job_id,
            ),
        )
    recoverable = conn.execute(
        """
                SELECT id, model_run_id
                FROM batch_prediction_jobs
                WHERE status = 'running'
                  AND model_run_id IS NOT NULL
                  AND TRIM(model_run_id) != ''
                """
    ).fetchall()
    for job_row in recoverable:
        predictions = conn.execute(
            """
                    SELECT issue_id, raw_json
                    FROM model_predictions
                    WHERE model_run_id = ?
                    """,
            (job_row["model_run_id"],),
        ).fetchall()
        for prediction in predictions:
            raw = _json_load(prediction["raw_json"], {})
            if not isinstance(raw, dict):
                raw = {}
            conn.execute(
                """
                        UPDATE batch_prediction_items
                        SET status = 'succeeded',
                            result_json = ?,
                            error_text = '',
                            started_at = COALESCE(started_at, ?),
                            finished_at = COALESCE(finished_at, ?)
                        WHERE job_id = ?
                          AND issue_id = ?
                          AND status = 'running'
                        """,
                (
                    _json(raw),
                    interrupted_at,
                    interrupted_at,
                    job_row["id"],
                    prediction["issue_id"],
                ),
            )
    # Preserve already-completed item results, but make every unfinished
    # item belonging to an interrupted job terminal.  Updating the
    # children first lets the parent query still identify queued/running
    # jobs without introducing a temporary migration marker.
    conn.execute(
        """
                UPDATE batch_prediction_items
                SET status = 'failed',
                    finished_at = ?,
                    error_text = CASE
                        WHEN TRIM(error_text) = '' THEN
                            '服务重启前 Batch 预测未完成。'
                        ELSE error_text
                    END
                WHERE status = 'running'
                  AND EXISTS (
                      SELECT 1
                      FROM batch_prediction_jobs bpj
                      WHERE bpj.id = batch_prediction_items.job_id
                        AND bpj.status = 'running'
                  )
                """,
        (interrupted_at,),
    )
    conn.execute(
        """
                UPDATE batch_prediction_jobs
                SET status = CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                        )
                         AND NOT EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                              AND bpi.status != 'succeeded'
                        ) THEN 'succeeded'
                        WHEN EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                              AND bpi.status = 'succeeded'
                        ) THEN 'partial'
                        ELSE 'failed'
                    END,
                    completed_count = (
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
                    ),
                    finished_at = ?,
                    error_text = CASE
                        WHEN NOT EXISTS (
                            SELECT 1
                            FROM batch_prediction_items bpi
                            WHERE bpi.job_id = batch_prediction_jobs.id
                              AND bpi.status != 'succeeded'
                        ) THEN error_text
                        WHEN TRIM(error_text) = '' THEN
                            '服务重启前 Batch 预测未完成；请重新创建任务。'
                        ELSE error_text
                    END
                WHERE status = 'running'
                """,
        (interrupted_at,),
    )
    conn.execute(
        """
                UPDATE batch_prediction_jobs
                SET publish_status = CASE
                        WHEN TRIM(autotriage_batch_id) != '' THEN 'partial'
                        ELSE 'failed'
                    END,
                    error_text = CASE
                        WHEN TRIM(error_text) = '' THEN
                            '服务重启前 AutoTriage 推送未完成；为避免重复建批，不会自动重试。'
                        ELSE error_text
                    END
                WHERE publish_status = 'running'
                """
    )
