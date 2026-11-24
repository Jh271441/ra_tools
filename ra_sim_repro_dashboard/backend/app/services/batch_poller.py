"""Batch polling, result verification, and publication reconciliation."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.domain.metrics import summarize_population
from app.models import ReleaseSimulationBatch
from app.services import (
    release_backfill,
    release_workflow as w,
    result_integration,
    result_publication,
)

logger = logging.getLogger(__name__)


def poll_batches(db, config):
    for batch in db.scalars(
        select(ReleaseSimulationBatch).where(
            ReleaseSimulationBatch.status.in_(
                ["running", "verifying", "submitting", "submission_uncertain"]
            )
        )
    ).all():
        try:
            if batch.status in ("submitting", "submission_uncertain"):
                receipt = w.driver_call(config, "receipt", batch.payload)
                if receipt.get("fingerprint") == batch.fingerprint and receipt.get("job_id"):
                    batch.payload = {**batch.payload, "job_id": receipt["job_id"]}
                    batch.status = "running"
                    db.commit()
                else:
                    batch.status = "submission_uncertain"
                    db.commit()
                    continue
            result = w.driver_call(config, "poll", batch.payload)
            if result.get("fingerprint") != batch.fingerprint or str(result.get("job_id")) != str(
                batch.payload["job_id"]
            ):
                raise ValueError("结果与提交批次不匹配")
            state = result.get("status")
            if state == "audited":
                if not release_backfill.frozen_snapshot_valid(db, batch):
                    raise ValueError("当前来源或场景输入与提交快照不一致，停止结果导入")
                # Existing multi-job comparisons/publication decisions are immutable
                # here; refreshing those requires their explicit integration plan.
                if batch.payload.get("result_import"):
                    raise ValueError("已有评测整合记录，请按原整合计划核验")
                export = result.get("execution_export") or {}
                if str(export.get("job_id")) != str(batch.payload["job_id"]):
                    raise ValueError("核验导出与提交 Job 不匹配")
                result_integration.import_executions(
                    db, batch.payload, [export], int(batch.payload["job_id"])
                )
            elif state == "complete":
                expected = {s["scenario_id"] for s in batch.payload["scenarios"]}
                if (
                    result.get("quality_gate_passed") is not True
                    or set(result.get("results", {})) != expected
                ):
                    batch.status = "quality_failed"
                    batch.payload = {
                        **batch.payload,
                        "error": "结果覆盖或质量门禁未通过",
                    }
                else:
                    for row in result["results"].values():
                        if not all(
                            isinstance(row.get(k), bool) for k in ("sim_triggered", "reproduced")
                        ) or row.get("precision_label") not in ("TP", "FP", "FN", "TN"):
                            raise ValueError("仿真结果不完整")
                    summary = summarize_population(
                        batch.payload["issues"],
                        batch.payload["scenarios"],
                        result["results"],
                    )
                    batch.payload = {
                        **batch.payload,
                        "results": result["results"],
                        "summary": summary,
                    }
                    batch.status = "complete" if summary["available"] else "quality_failed"
            elif state in ("running", "verifying"):
                batch.status = state
                batch.payload = {**batch.payload, "quality": result.get("quality", {})}
            elif state == "failed":
                # Legacy drivers used failed for a single task while the job was
                # still running. Never freeze monitoring on that ambiguous signal.
                batch.status = "verifying"
                batch.payload = {**batch.payload, "quality": result.get("quality", {})}
            elif state == "cancelled":
                batch.status = "cancelled"
            else:
                raise ValueError("结果驱动返回未知核验状态")
            batch.payload = {k: v for k, v in batch.payload.items() if k != "last_poll_error"}
            db.commit()
        except Exception as exc:
            logger.exception(
                "poll_batches failed batch=%s release=%s status=%s",
                batch.fingerprint,
                batch.release,
                batch.status,
            )
            db.rollback()
            batch.payload = {
                **batch.payload,
                "last_poll_error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
            }
            db.commit()

    result_publication.reconcile_publications(db, config)
