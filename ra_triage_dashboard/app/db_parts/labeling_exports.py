"""Labeling exports storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
import hashlib
import json
from collections import defaultdict
from typing import Any, Sequence
from uuid import uuid4
from .shared import LABELS, _json, _json_load, utc_now
from .snapshots import _sha256_json
from .labeling_shared import _clean_values


class LabelingExportsMixin:
    def label_gt_candidates(self, baseline_scopes: Sequence[str], *, include_non_updates: bool = False) -> list[dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT issue_id, baseline_scope, gt_label FROM issues WHERE baseline_scope IN ({', '.join('?' for _ in scopes)}) ORDER BY baseline_scope, issue_id",
                scopes,
            ).fetchall() if scopes else []
        cases_by_issue = self._batch_label_cases([str(row["issue_id"]) for row in rows])
        gt_by_issue = {str(row["issue_id"]): str(row["gt_label"] or "") for row in rows}
        scope_by_issue = {str(row["issue_id"]): str(row["baseline_scope"] or "") for row in rows}
        ids_by_scope: dict[str, list[str]] = defaultdict(list)
        for issue_id, scope in scope_by_issue.items():
            ids_by_scope[scope].append(issue_id)
        projected_by_issue: dict[str, dict[str, Any]] = {}
        for scope, scope_issue_ids in ids_by_scope.items():
            projected_by_issue.update(
                self.project_issue_label_states(
                    scope,
                    scope_issue_ids,
                    include_sources=True,
                    preloaded_cases=cases_by_issue,
                )
            )
        by_issue: dict[str, list[dict[str, Any]]] = {}
        blocked_by_issue: dict[str, list[dict[str, Any]]] = {}
        for issue_id, label_cases in cases_by_issue.items():
            for row in label_cases:
                resolution = row["resolution"]
                if resolution["state"] == "resolved" and resolution["expected_output"] in LABELS:
                    by_issue.setdefault(issue_id, []).append(
                        {
                            "label_case_id": str(row["id"]),
                            "baseline_scope": scope_by_issue.get(issue_id, ""),
                            "task_id": str(row["task_id"] or ""),
                            "source_run_id": str(row["source_run_id"] or ""),
                            "expected_output": resolution["expected_output"],
                            "method": resolution["method"],
                            "result_revision_id": int(resolution["result_revision"]["id"]),
                        }
                    )
                else:
                    blocked_by_issue.setdefault(issue_id, []).append(
                        {
                            "label_case_id": str(row["id"]),
                            "baseline_scope": scope_by_issue.get(issue_id, ""),
                            "task_id": str(row["task_id"] or ""),
                            "source_run_id": str(row["source_run_id"] or ""),
                            "state": str(resolution["state"] or "pending"),
                            "submitted_count": int(resolution["submitted_count"] or 0),
                            "assigned_count": int(resolution["assigned_count"] or 0),
                        }
                    )
        output: list[dict[str, Any]] = []
        for issue_id in sorted(set(by_issue) | set(blocked_by_issue) | (set(gt_by_issue) if include_non_updates else set())):
            sources = by_issue.get(issue_id, [])
            labels = {item["expected_output"] for item in sources}
            gt_label = gt_by_issue.get(issue_id, "")
            blockers = blocked_by_issue.get(issue_id, [])
            projection = projected_by_issue.get(issue_id) or {}
            decision = projection.get("decision") or None
            if not sources and not blockers and not decision:
                if include_non_updates:
                    output.append({"issue_id": issue_id, "status": "unlabeled", "gt_label": gt_label})
                continue
            if decision:
                if projection.get("state") != "resolved" or decision.get("stale"):
                    output.append(
                        {
                            "issue_id": issue_id,
                            "baseline_scope": scope_by_issue.get(issue_id, ""),
                            "status": "unresolved",
                            "gt_label": gt_label,
                            "sources": projection.get("sources") or [],
                            "blocked_sources": blockers,
                            "decision": decision,
                        }
                    )
                    continue
                expected = str(projection.get("expected_output") or "")
                if expected == gt_label:
                    if include_non_updates:
                        output.append({"issue_id": issue_id, "status": "unchanged", "gt_label": gt_label, "expected_output": expected})
                    continue
                output.append(
                    {
                        "issue_id": issue_id,
                        "baseline_scope": scope_by_issue.get(issue_id, ""),
                        "status": "ready",
                        "gt_label": gt_label,
                        "expected_output": expected,
                        "sources": projection.get("sources") or [],
                        "source_revision_ids": list(
                            projection.get("source_revision_ids") or []
                        ),
                        "decision": decision,
                        "decision_id": int(decision["id"]),
                    }
                )
                continue
            if blockers:
                output.append(
                    {
                        "issue_id": issue_id,
                        "baseline_scope": scope_by_issue.get(issue_id, ""),
                        "status": "unresolved",
                        "gt_label": gt_label,
                        "sources": sources,
                        "blocked_sources": blockers,
                    }
                )
                continue
            if len(labels) > 1:
                output.append(
                    {
                        "issue_id": issue_id,
                        "baseline_scope": scope_by_issue.get(issue_id, ""),
                        "status": "source_conflict",
                        "gt_label": gt_label,
                        "sources": sources,
                    }
                )
                continue
            expected = next(iter(labels))
            if expected == gt_label:
                if include_non_updates:
                    output.append({"issue_id": issue_id, "status": "unchanged", "gt_label": gt_label, "expected_output": expected})
                continue
            output.append(
                {
                    "issue_id": issue_id,
                    "baseline_scope": scope_by_issue.get(issue_id, ""),
                    "status": "ready",
                    "gt_label": gt_label,
                    "expected_output": expected,
                    "sources": sources,
                    "source_revision_ids": sorted(
                        int(source["result_revision_id"]) for source in sources
                    ),
                }
            )
        return output

    @staticmethod
    def _gt_candidate_fingerprint(candidate: dict[str, Any]) -> str:
        payload = {
            "issue_id": str(candidate.get("issue_id") or ""),
            "gt_label": str(candidate.get("gt_label") or ""),
            "expected_output": str(candidate.get("expected_output") or ""),
            "source_revision_ids": sorted(
                int(value) for value in candidate.get("source_revision_ids") or []
            ),
            "decision_id": candidate.get("decision_id"),
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def create_label_gt_export_preview(
        self,
        *,
        baseline_scopes: Sequence[str],
        issue_ids: Sequence[str] = (),
        created_by: str,
        created_by_source: str,
        created_by_verified: bool,
    ) -> dict[str, Any]:
        scopes = _clean_values(baseline_scopes)
        if not scopes:
            raise ValueError("至少选择一个 GT 数据集。")
        selected = set(_clean_values(issue_ids))
        scoped_candidates = [
            item for item in self.label_gt_candidates(scopes, include_non_updates=True)
            if not selected or str(item.get("issue_id") or "") in selected
        ]
        candidates = [item for item in scoped_candidates if item.get("status") == "ready"]
        counts = {key: 0 for key in ("ready", "unchanged", "pending", "conflict", "stale")}
        exclusions = []
        for candidate in scoped_candidates:
            status = candidate["status"]
            blocked_states = {item.get("state") for item in candidate.get("blocked_sources") or []}
            if status in {"ready", "unchanged"}:
                reason = status
            elif (candidate.get("decision") or {}).get("stale") or "stale" in blocked_states:
                reason = "stale"
            elif status == "source_conflict" or "conflict" in blocked_states or len({
                source.get("expected_output") for source in candidate.get("sources") or []
                if source.get("expected_output") in LABELS
            }) > 1:
                reason = "conflict"
            else:
                reason = "pending"
            counts[reason] += 1
            if reason != "ready":
                exclusions.append({"issue_id": candidate["issue_id"], "reason": reason})
        scope_summary = {"total": len(scoped_candidates), **counts, "excluded_count": len(exclusions), "exclusions": exclusions}
        if not candidates:
            return {"id": "", "status": "empty", "item_count": 0, "items": [], "scope_summary": scope_summary}

        active_snapshots = {
            scope: self.get_active_gt_snapshot(scope)
            for scope in scopes
        }
        missing_snapshots = [scope for scope, snapshot in active_snapshots.items() if not snapshot]
        if missing_snapshots:
            raise ValueError(
                "GT 导出需要每个数据集先有正式 GT snapshot；缺少："
                + "、".join(missing_snapshots)
            )
        snapshot_ids = {
            scope: str(snapshot["id"])
            for scope, snapshot in active_snapshots.items()
            if snapshot
        }
        snapshot_hashes = {
            scope: str(snapshot["content_sha256"])
            for scope, snapshot in active_snapshots.items()
            if snapshot
        }
        items: list[dict[str, Any]] = []
        for candidate in candidates:
            fingerprint = self._gt_candidate_fingerprint(candidate)
            scope = str(candidate.get("baseline_scope") or "")
            items.append(
                {
                    "issue_id": str(candidate["issue_id"]),
                    "baseline_scope": scope,
                    "old_gt_label": str(candidate.get("gt_label") or ""),
                    "expected_output": str(candidate["expected_output"]),
                    "source_revision_ids": sorted(
                        int(value)
                        for value in candidate.get("source_revision_ids") or []
                    ),
                    "source_fingerprint": fingerprint,
                    "source_gt_snapshot_id": snapshot_ids.get(scope, ""),
                    "decision_id": candidate.get("decision_id"),
                }
            )
        batch_fingerprint = _sha256_json({
            "source_gt_snapshot_ids": snapshot_ids,
            "items": [item["source_fingerprint"] for item in items],
        })
        batch_id = f"gt-export-{uuid4().hex}"
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO label_gt_export_batches (
                    id, baseline_scopes_json, source_fingerprint, status,
                    item_count, file_sha256, created_by, created_by_source,
                    created_by_verified, created_at, exported_at,
                    source_gt_snapshot_id, source_gt_snapshot_ids_json,
                    source_gt_snapshot_sha256, reconcile_status,
                    reconciled_at, reconciled_count, not_applied_count,
                    changed_again_count
                ) VALUES (?, ?, ?, 'preview', ?, '', ?, ?, ?, ?, NULL, ?, ?, ?, 'not_checked', NULL, 0, 0, 0)
                """,
                (
                    batch_id,
                    _json(scopes),
                    batch_fingerprint,
                    len(items),
                    str(created_by or ""),
                    str(created_by_source or "legacy"),
                    bool(created_by_verified),
                    now,
                    (next(iter(snapshot_ids.values())) if len(snapshot_ids) == 1 else None),
                    _json(snapshot_ids),
                    _sha256_json(snapshot_hashes),
                ),
            )
            conn.executemany(
                """
                INSERT INTO label_gt_export_items (
                    batch_id, issue_id, old_gt_label, expected_output,
                    source_revision_ids_json, source_fingerprint, decision_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        batch_id,
                        item["issue_id"],
                        item["old_gt_label"],
                        item["expected_output"],
                        _json(item["source_revision_ids"]),
                        item["source_fingerprint"],
                        item.get("decision_id"),
                    )
                    for item in items
                ],
            )
            conn.executemany(
                """
                INSERT INTO label_gt_export_source_snapshots (
                    batch_id, baseline_scope, snapshot_id, content_sha256
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (batch_id, scope, snapshot_ids[scope], snapshot_hashes[scope])
                    for scope in scopes
                ],
            )
            self._mark_labeling_change(conn)
        return {
            "id": batch_id,
            "status": "preview",
            "baseline_scopes": scopes,
            "source_fingerprint": batch_fingerprint,
            "source_gt_snapshot_id": (next(iter(snapshot_ids.values())) if len(snapshot_ids) == 1 else ""),
            "source_gt_snapshot_ids": snapshot_ids,
            "source_gt_snapshot_sha256": _sha256_json(snapshot_hashes),
            "source_gt_snapshots": [
                {
                    "baseline_scope": scope,
                    "snapshot_id": snapshot_ids[scope],
                    "content_sha256": snapshot_hashes[scope],
                }
                for scope in scopes
            ],
            "reconcile_status": "not_checked",
            "item_count": len(items),
            "items": items,
            "scope_summary": scope_summary,
            "created_by": str(created_by or ""),
            "created_at": now,
        }

    def get_label_gt_export_batch(self, batch_id: str) -> dict[str, Any] | None:
        normalized = str(batch_id or "").strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM label_gt_export_batches WHERE id = ?", (normalized,)
            ).fetchone()
            if row is None:
                return None
            item_rows = conn.execute(
                """
                SELECT item.*, issue.baseline_scope
                FROM label_gt_export_items item
                JOIN issues issue ON issue.issue_id = item.issue_id
                WHERE item.batch_id = ? ORDER BY item.issue_id
                """,
                (normalized,),
            ).fetchall()
            source_rows = conn.execute(
                """
                SELECT baseline_scope, snapshot_id, content_sha256
                FROM label_gt_export_source_snapshots
                WHERE batch_id = ? ORDER BY baseline_scope
                """,
                (normalized,),
            ).fetchall()
        return {
            "id": str(row["id"]),
            "baseline_scopes": _json_load(row["baseline_scopes_json"], []),
            "source_fingerprint": str(row["source_fingerprint"] or ""),
            "status": str(row["status"] or "preview"),
            "item_count": int(row["item_count"] or 0),
            "file_sha256": str(row["file_sha256"] or ""),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
            "exported_at": str(row["exported_at"] or ""),
            "source_gt_snapshot_id": str(row["source_gt_snapshot_id"] or ""),
            "source_gt_snapshot_ids": _json_load(row["source_gt_snapshot_ids_json"], {}),
            "source_gt_snapshot_sha256": str(row["source_gt_snapshot_sha256"] or ""),
            "reconcile_status": str(row["reconcile_status"] or "not_checked"),
            "reconcile_error": str(row["reconcile_error"] or ""),
            "reconciled_at": str(row["reconciled_at"] or ""),
            "reconciled_count": int(row["reconciled_count"] or 0),
            "not_applied_count": int(row["not_applied_count"] or 0),
            "changed_again_count": int(row["changed_again_count"] or 0),
            "source_gt_snapshots": [
                {
                    "baseline_scope": str(source["baseline_scope"]),
                    "snapshot_id": str(source["snapshot_id"]),
                    "content_sha256": str(source["content_sha256"]),
                }
                for source in source_rows
            ],
            "items": [
                {
                    "issue_id": str(item["issue_id"]),
                    "baseline_scope": str(item["baseline_scope"] or ""),
                    "old_gt_label": str(item["old_gt_label"] or ""),
                    "expected_output": str(item["expected_output"] or ""),
                    "source_revision_ids": _json_load(item["source_revision_ids_json"], []),
                    "source_fingerprint": str(item["source_fingerprint"] or ""),
                    "decision_id": (
                        int(item["decision_id"])
                        if item["decision_id"] not in (None, "")
                        else None
                    ),
                    "reconcile_status": str(item["reconcile_status"] or "not_checked"),
                    "reconciled_snapshot_id": str(item["reconciled_snapshot_id"] or ""),
                    "reconciled_at": str(item["reconciled_at"] or ""),
                }
                for item in item_rows
            ],
        }

    def validate_label_gt_export_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.get_label_gt_export_batch(batch_id)
        if batch is None:
            raise ValueError("GT 更新导出批次不存在。")
        current = {
            str(item["issue_id"]): item
            for item in self.label_gt_candidates(batch["baseline_scopes"])
            if item.get("status") == "ready"
        }
        stale: list[str] = []
        stored_snapshot_ids = {
            str(key): str(value or "")
            for key, value in (
                {
                    item["baseline_scope"]: item["snapshot_id"]
                    for item in batch.get("source_gt_snapshots") or []
                }
                or batch.get("source_gt_snapshot_ids")
                or {}
            ).items()
        }
        current_snapshot_ids = {}
        for scope in batch["baseline_scopes"]:
            snapshot = self.get_active_gt_snapshot(scope)
            current_snapshot_ids[scope] = str((snapshot or {}).get("id") or "")
        if stored_snapshot_ids != current_snapshot_ids:
            stale.extend(str(item["issue_id"]) for item in batch["items"])
        for item in batch["items"]:
            candidate = current.get(item["issue_id"])
            if candidate is None or self._gt_candidate_fingerprint(candidate) != item["source_fingerprint"]:
                stale.append(item["issue_id"])
        stale = list(dict.fromkeys(stale))
        if stale:
            with self._write_lock, self.connect() as conn:
                conn.execute(
                    "UPDATE label_gt_export_batches SET status = 'stale' WHERE id = ?",
                    (batch["id"],),
                )
                self._mark_labeling_change(conn)
            batch["status"] = "stale"
        batch["stale_issue_ids"] = stale
        return batch

    def mark_label_gt_exported(self, *, batch_id: str, file_sha256: str) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE label_gt_export_batches
                SET status = 'exported', file_sha256 = ?, exported_at = ?
                WHERE id = ? AND status = 'preview'
                """,
                (str(file_sha256 or ""), now, str(batch_id or "")),
            )
            self._mark_labeling_change(conn)
        return self.get_label_gt_export_batch(batch_id) or {}
