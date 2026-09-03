"""AutoTriage HTTP helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from ..autotriage_source import AutoTriageSourceError, normalise_batch_id
from ..db import LABELS
from ..import_parsing import normalize_model_row
from ..sanitization import redact_sensitive_fields
from ..runtime import autotriage_source
from .common import _as_text
from .external_links import _safe_autotriage_batch


def _fetch_autotriage_snapshot(batch_ref: Any) -> dict[str, Any]:
    batch_id = normalise_batch_id(batch_ref)
    batch = autotriage_source.fetch_batch(batch_id)
    source_rows = autotriage_source.fetch_results(batch_id)
    safe_batch = _safe_autotriage_batch(batch)
    rows: list[dict[str, Any]] = []
    rejected = 0
    seen: set[str] = set()
    for source_row in source_rows:
        redacted_row = redact_sensitive_fields(source_row)
        normalized = normalize_model_row(redacted_row)
        explicit_success = source_row.get("success")
        row_failed = explicit_success is False or (
            isinstance(explicit_success, str)
            and explicit_success.strip().lower() in {"false", "0", "failed"}
        )
        if (
            row_failed
            or normalized is None
            or normalized.get("model_label") not in LABELS
        ):
            rejected += 1
            continue
        issue_id = _as_text(normalized.get("issue_id"))
        if issue_id in seen:
            raise AutoTriageSourceError(
                f"AutoTriage Batch {batch_id} 含重复 Issue：{issue_id}。"
            )
        seen.add(issue_id)
        normalized["raw"] = redacted_row
        rows.append(normalized)
    if not rows:
        raise AutoTriageSourceError(
            "该 AutoTriage Batch 没有可导入的三分类预测结果。"
        )

    def platform_count(field: str) -> int:
        try:
            count = int(batch.get(field) or 0)
        except (TypeError, ValueError):
            raise AutoTriageSourceError(
                f"AutoTriage Batch 的 {field} 非法。"
            )
        if count < 0:
            raise AutoTriageSourceError(
                f"AutoTriage Batch 的 {field} 不能为负数。"
            )
        return count

    declared_total = platform_count("total_count")
    completed_total = platform_count("completed_count")
    failed_total = platform_count("failed_count")
    platform_status = _as_text(batch.get("status")).lower()
    partial = bool(
        rejected
        or failed_total
        or platform_status not in {"completed", "succeeded"}
        or (declared_total and len(source_rows) != declared_total)
        or (declared_total and completed_total != declared_total)
        or (declared_total and len(rows) != declared_total)
    )
    fingerprint_rows = [
        {
            "issue_id": row["issue_id"],
            "trip_id": row["trip_id"],
            "model_label": row["model_label"],
            "model_reason": row["model_reason"],
            "model_confidence": row["model_confidence"],
            "model_extra": row["model_extra"],
        }
        for row in sorted(rows, key=lambda item: item["issue_id"])
    ]
    fingerprint = {
        "schema_version": "autotriage-snapshot-v1",
        "batch_id": batch_id,
        "batch": safe_batch,
        "predictions": fingerprint_rows,
        "source_result_count": len(source_rows),
        "rejected_result_count": rejected,
    }
    source_sha256 = hashlib.sha256(
        json.dumps(
            fingerprint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    coverage = {
        "declared_total": declared_total,
        "completed_total": completed_total,
        "failed_total": failed_total,
        "platform_status": platform_status,
        "source_result_count": len(source_rows),
        "accepted_result_count": len(rows),
        "rejected_result_count": rejected,
        "unique_issue_count": len(seen),
        "partial": partial,
    }
    return {
        "batch_id": batch_id,
        "batch": safe_batch,
        "rows": rows,
        "coverage": coverage,
        "source_sha256": source_sha256,
    }
