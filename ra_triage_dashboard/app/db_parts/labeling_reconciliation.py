"""Labeling reconciliation storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Sequence
from .shared import utc_now


class LabelingReconciliationMixin:
    def reconcile_label_gt_export_batch(self, batch_id: str) -> dict[str, Any]:
        """Compare an exported batch with the current active GT snapshot.

        This is an observation/reconciliation write only. It never writes GT,
        Trail, or the active snapshot pointer.
        """
        batch = self.get_label_gt_export_batch(batch_id)
        if batch is None:
            raise ValueError("GT 更新导出批次不存在。")
        if batch.get("status") != "exported":
            raise ValueError("只有已下载的 GT 导出批次可以进行同步核对。")
        results = self._reconcile_label_gt_export_batches([str(batch["id"])])
        return results[0] if results else (self.get_label_gt_export_batch(batch_id) or {})

    def reconcile_label_gt_export_batches_for_scope(
        self, baseline_scope: str
    ) -> list[dict[str, Any]]:
        """Reconcile outstanding exported batches after one successful GT sync."""

        scope = str(baseline_scope or "").strip()
        if not scope:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT batch.id FROM label_gt_export_batches batch
                WHERE batch.status = 'exported'
                  AND batch.reconcile_status <> 'matched'
                  AND EXISTS (
                      SELECT 1 FROM label_gt_export_source_snapshots source
                      WHERE source.batch_id = batch.id AND source.baseline_scope = ?
                  )
                ORDER BY batch.created_at, batch.id
                """,
                (scope,),
            ).fetchall()
        ids = [str(row["id"]) for row in rows]
        results: list[dict[str, Any]] = []
        for offset in range(0, len(ids), 200):
            results.extend(self._reconcile_label_gt_export_batches(ids[offset : offset + 200]))
        return results

    def record_label_gt_export_reconcile_error_for_scope(
        self, baseline_scope: str, error_text: str
    ) -> int:
        scope = str(baseline_scope or "").strip()
        if not scope:
            return 0
        message = str(error_text or "GT export reconciliation failed").strip()[:2000]
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT batch.id FROM label_gt_export_batches batch
                WHERE batch.status = 'exported'
                  AND batch.reconcile_status <> 'matched'
                  AND EXISTS (
                      SELECT 1 FROM label_gt_export_source_snapshots source
                      WHERE source.batch_id = batch.id AND source.baseline_scope = ?
                  )
                """,
                (scope,),
            ).fetchall()
            ids = [str(row["id"]) for row in rows]
            if not ids:
                return 0
            for offset in range(0, len(ids), 200):
                batch = ids[offset : offset + 200]
                placeholders = ", ".join("?" for _ in batch)
                conn.execute(
                    f"UPDATE label_gt_export_items SET reconcile_status = 'error', "
                    f"reconciled_snapshot_id = NULL, reconciled_at = ? "
                    f"WHERE batch_id IN ({placeholders})",
                    (now, *batch),
                )
                conn.execute(
                    f"UPDATE label_gt_export_batches SET reconcile_status = 'error', "
                    f"reconcile_error = ?, reconciled_at = ?, reconciled_count = 0, "
                    f"not_applied_count = 0, changed_again_count = 0 "
                    f"WHERE id IN ({placeholders})",
                    (message, now, *batch),
                )
            self._mark_labeling_change(conn)
        return len(ids)

    def _reconcile_label_gt_export_batches(
        self, batch_ids: Sequence[str]
    ) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(item or "").strip() for item in batch_ids if str(item or "").strip()))
        if not ids:
            return []
        outcomes: dict[str, dict[str, Any]] = {}
        with self.connect() as conn:
            batch_rows = []
            for offset in range(0, len(ids), 400):
                chunk = ids[offset : offset + 400]
                batch_rows.extend(
                    conn.execute(
                        f"SELECT id, status FROM label_gt_export_batches "
                        f"WHERE id IN ({', '.join('?' for _ in chunk)})",
                        chunk,
                    ).fetchall()
                )
            found_ids = {str(row["id"]) for row in batch_rows}
            missing = sorted(set(ids) - found_ids)
            if missing:
                raise ValueError("GT 更新导出批次不存在：" + "、".join(missing))
            not_exported = [
                str(row["id"]) for row in batch_rows if str(row["status"] or "") != "exported"
            ]
            if not_exported:
                raise ValueError("只有已下载的 GT 导出批次可以进行同步核对。")
            item_rows = []
            source_rows = []
            for offset in range(0, len(ids), 200):
                chunk = ids[offset : offset + 200]
                placeholders = ", ".join("?" for _ in chunk)
                item_rows.extend(
                    conn.execute(
                        f"""
                        SELECT item.batch_id, item.issue_id, issue.baseline_scope,
                               item.old_gt_label, item.expected_output
                        FROM label_gt_export_items item
                        JOIN issues issue ON issue.issue_id = item.issue_id
                        WHERE item.batch_id IN ({placeholders})
                        ORDER BY item.batch_id, item.issue_id
                        """,
                        chunk,
                    ).fetchall()
                )
                source_rows.extend(
                    conn.execute(
                        f"SELECT batch_id, baseline_scope FROM label_gt_export_source_snapshots "
                        f"WHERE batch_id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            scopes = list(
                dict.fromkeys(
                    [str(row["baseline_scope"] or "") for row in item_rows]
                    + [str(row["baseline_scope"] or "") for row in source_rows]
                )
            )
            scopes = [scope for scope in scopes if scope]
            active_by_scope: dict[str, dict[str, str]] = {}
            if scopes:
                scope_placeholders = ", ".join("?" for _ in scopes)
                active_rows = conn.execute(
                    f"""
                    SELECT active.baseline_scope, snapshot.id AS snapshot_id,
                           snapshot.content_sha256
                    FROM gt_snapshot_active active
                    JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
                    WHERE active.baseline_scope IN ({scope_placeholders})
                    """,
                    scopes,
                ).fetchall()
                active_by_scope = {
                    str(row["baseline_scope"]): {
                        "snapshot_id": str(row["snapshot_id"]),
                        "content_sha256": str(row["content_sha256"]),
                    }
                    for row in active_rows
                }
            issue_ids = list(dict.fromkeys(str(row["issue_id"]) for row in item_rows))
            current_labels: dict[tuple[str, str], str] = {}
            for offset in range(0, len(issue_ids), 400):
                chunk = issue_ids[offset : offset + 400]
                if not chunk or not active_by_scope:
                    continue
                snapshot_ids = list(
                    dict.fromkeys(item["snapshot_id"] for item in active_by_scope.values())
                )
                snapshot_placeholders = ", ".join("?" for _ in snapshot_ids)
                issue_placeholders = ", ".join("?" for _ in chunk)
                label_rows = conn.execute(
                    f"""
                    SELECT item.baseline_scope, item.issue_id, item.gt_label
                    FROM gt_snapshot_items item
                    WHERE item.snapshot_id IN ({snapshot_placeholders})
                      AND item.issue_id IN ({issue_placeholders})
                    """,
                    (*snapshot_ids, *chunk),
                ).fetchall()
                current_labels.update(
                    {
                        (str(row["baseline_scope"]), str(row["issue_id"])):
                            str(row["gt_label"] or "")
                        for row in label_rows
                    }
                )

        items_by_batch: dict[str, list[Any]] = defaultdict(list)
        for item in item_rows:
            items_by_batch[str(item["batch_id"])].append(item)
        now = utc_now()
        for batch_id in ids:
            items = items_by_batch.get(batch_id, [])
            if not items:
                outcomes[batch_id] = {
                    "status": "error",
                    "error": "GT 导出批次没有候选条目。",
                    "now": now,
                    "counts": {"matched": 0, "not_applied": 0, "changed_again": 0},
                    "items": [],
                }
                continue
            counts = {"matched": 0, "not_applied": 0, "changed_again": 0}
            item_outcomes: list[tuple[str, str, str | None, str]] = []
            error = ""
            for item in items:
                issue_id = str(item["issue_id"])
                scope = str(item["baseline_scope"] or "")
                active = active_by_scope.get(scope)
                if not scope or active is None:
                    error = f"{issue_id}: no active GT snapshot for scope {scope or '(empty)'}"
                    break
                key = (scope, issue_id)
                if key not in current_labels:
                    error = f"{issue_id}: missing from active GT snapshot {active['snapshot_id']}"
                    break
                current_label = current_labels[key]
                target = str(item["expected_output"] or "")
                old = str(item["old_gt_label"] or "")
                if current_label == target:
                    status = "matched"
                elif current_label == old:
                    status = "not_applied"
                else:
                    status = "changed_again"
                counts[status] += 1
                item_outcomes.append(
                    (issue_id, status, active["snapshot_id"], now)
                )
            if error:
                outcomes[batch_id] = {
                    "status": "error",
                    "error": error,
                    "now": now,
                    "counts": {"matched": 0, "not_applied": 0, "changed_again": 0},
                    "items": [],
                }
            else:
                states = {status for _, status, _, _ in item_outcomes}
                outcomes[batch_id] = {
                    "status": next(iter(states)) if len(states) == 1 else "partial",
                    "error": "",
                    "now": now,
                    "counts": counts,
                    "items": item_outcomes,
                }

        with self._write_lock, self.connect() as conn:
            for batch_id, outcome in outcomes.items():
                if outcome["status"] == "error":
                    conn.execute(
                        """
                        UPDATE label_gt_export_items
                        SET reconcile_status = 'error', reconciled_snapshot_id = NULL,
                            reconciled_at = ?
                        WHERE batch_id = ?
                        """,
                        (outcome["now"], batch_id),
                    )
                    conn.execute(
                        """
                        UPDATE label_gt_export_batches
                        SET reconcile_status = 'error', reconcile_error = ?,
                            reconciled_at = ?, reconciled_count = 0,
                            not_applied_count = 0, changed_again_count = 0
                        WHERE id = ?
                        """,
                        (outcome["error"], outcome["now"], batch_id),
                    )
                else:
                    conn.executemany(
                        """
                        UPDATE label_gt_export_items
                        SET reconcile_status = ?, reconciled_snapshot_id = ?, reconciled_at = ?
                        WHERE batch_id = ? AND issue_id = ?
                        """,
                        [
                            (status, snapshot_id, stamp, batch_id, issue_id)
                            for issue_id, status, snapshot_id, stamp in outcome["items"]
                        ],
                    )
                    counts = outcome["counts"]
                    conn.execute(
                        """
                        UPDATE label_gt_export_batches
                        SET reconcile_status = ?, reconcile_error = '', reconciled_at = ?,
                            reconciled_count = ?, not_applied_count = ?,
                            changed_again_count = ?
                        WHERE id = ?
                        """,
                        (
                            outcome["status"],
                            outcome["now"],
                            counts["matched"],
                            counts["not_applied"],
                            counts["changed_again"],
                            batch_id,
                        ),
                    )
            self._mark_labeling_change(conn)
        results = []
        for batch_id, outcome in outcomes.items():
            result = self.get_label_gt_export_batch(batch_id) or {}
            result["reconcile_counts"] = outcome["counts"]
            if outcome["error"]:
                result["reconcile_error"] = outcome["error"]
            results.append(result)
        return results
