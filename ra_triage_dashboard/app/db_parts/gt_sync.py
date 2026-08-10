from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from .shared import LABELS, utc_now


class DatabaseGtSyncMixin:
    """Persist and atomically apply authoritative GT snapshots."""

    @staticmethod
    def _default_gt_sync_status(scope: str) -> dict[str, Any]:
        return {
            "baseline_scope": scope,
            "status": "not_started",
            "source_name": "Trail",
            "source_view_id": 1000,
            "source_field": "ra_merge_result",
            "source_sha256": "",
            "source_row_count": 0,
            "source_updated_at": "",
            "source_updated_by": "",
            "last_checked_at": "",
            "last_applied_at": "",
            "last_check_change_count": 0,
            "last_applied_change_count": 0,
            "last_trigger": "",
            "requested_by": "",
            "requested_by_source": "",
            "requested_by_verified": False,
            "message": "尚未从 Trail 同步权威 GT。",
            "error_text": "",
        }

    @staticmethod
    def _gt_sync_state_dict(row: Any) -> dict[str, Any]:
        return {
            "baseline_scope": str(row["baseline_scope"] or ""),
            "status": str(row["status"] or "not_started"),
            "source_name": str(row["source_name"] or "Trail"),
            "source_view_id": int(row["source_view_id"] or 0),
            "source_field": str(row["source_field"] or "ra_merge_result"),
            "source_sha256": str(row["source_sha256"] or ""),
            "source_row_count": int(row["source_row_count"] or 0),
            "source_updated_at": str(row["source_updated_at"] or ""),
            "source_updated_by": str(row["source_updated_by"] or ""),
            "last_checked_at": str(row["last_checked_at"] or ""),
            "last_applied_at": str(row["last_applied_at"] or ""),
            "last_check_change_count": int(row["last_check_change_count"] or 0),
            "last_applied_change_count": int(row["last_applied_change_count"] or 0),
            "last_trigger": str(row["last_trigger"] or ""),
            "requested_by": str(row["requested_by"] or ""),
            "requested_by_source": str(row["requested_by_source"] or ""),
            "requested_by_verified": bool(row["requested_by_verified"]),
            "message": str(row["message"] or ""),
            "error_text": str(row["error_text"] or ""),
        }

    def gt_sync_status(self, scope: str) -> dict[str, Any]:
        normalized = str(scope or "").strip()
        if not normalized:
            return self._default_gt_sync_status("")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM gt_sync_state WHERE baseline_scope = ?",
                (normalized,),
            ).fetchone()
        return (
            self._gt_sync_state_dict(row)
            if row is not None
            else self._default_gt_sync_status(normalized)
        )

    def gt_sync_overlay(self, scope: str) -> dict[str, dict[str, str]]:
        normalized = str(scope or "").strip()
        if not normalized:
            return {}
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT issue_id, gt_label, source_updated_at, source_updated_by
                FROM gt_sync_labels
                WHERE baseline_scope = ?
                ORDER BY issue_id
                """,
                (normalized,),
            ).fetchall()
        return {
            str(row["issue_id"]): {
                "gt_label": str(row["gt_label"] or ""),
                "source_updated_at": str(row["source_updated_at"] or ""),
                "source_updated_by": str(row["source_updated_by"] or ""),
            }
            for row in rows
        }

    def merge_gt_sync_overlay(
        self, scope: str, rows: Iterable[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        overlay = self.gt_sync_overlay(scope)
        merged: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            issue_id = str(row.get("issue_id") or "").strip()
            authoritative = overlay.get(issue_id)
            if authoritative and authoritative["gt_label"] in LABELS:
                row["gt_label"] = authoritative["gt_label"]
                row["gt_source"] = "Trail view 1000:ra_merge_result"
            merged.append(row)
        return merged

    def apply_gt_sync_snapshot(
        self,
        *,
        scope: str,
        rows: Iterable[dict[str, Any]],
        source_name: str,
        source_view_id: int,
        source_field: str,
        trigger: str,
        requested_by: str,
        requested_by_source: str,
        requested_by_verified: bool,
    ) -> dict[str, Any]:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            raise ValueError("GT 同步 baseline scope 不能为空。")

        materialized: dict[str, dict[str, str]] = {}
        for raw in rows:
            issue_id = str(raw.get("issue_id") or "").strip()
            label = str(raw.get("gt_label") or "").strip()
            if not issue_id:
                raise ValueError("GT 同步结果包含空 issue_id。")
            if issue_id in materialized:
                raise ValueError(f"GT 同步结果包含重复 issue_id: {issue_id}")
            if label not in LABELS:
                raise ValueError(f"GT 同步结果包含非法三分类标签: {issue_id}={label!r}")
            materialized[issue_id] = {
                "gt_label": label,
                "source_updated_at": str(raw.get("source_updated_at") or "").strip(),
                "source_updated_by": str(raw.get("source_updated_by") or "").strip(),
            }

        checked_at = utc_now()
        digest_payload = [
            [issue_id, materialized[issue_id]["gt_label"]]
            for issue_id in sorted(materialized)
        ]
        source_hash = hashlib.sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        with self._write_lock, self.connect() as conn:
            current_rows = conn.execute(
                """
                SELECT issue_id, gt_label
                FROM issues
                WHERE baseline_scope = ?
                ORDER BY issue_id
                """,
                (normalized_scope,),
            ).fetchall()
            current = {
                str(row["issue_id"]): str(row["gt_label"] or "")
                for row in current_rows
            }
            expected_ids = set(current)
            returned_ids = set(materialized)
            if expected_ids != returned_ids:
                missing = sorted(expected_ids - returned_ids)
                extra = sorted(returned_ids - expected_ids)
                raise ValueError(
                    "GT 同步必须完整覆盖当前 baseline；"
                    f"当前 {len(expected_ids)} 条，返回 {len(returned_ids)} 条，"
                    f"缺失 {len(missing)} 条，额外 {len(extra)} 条。"
                )

            previous_row = conn.execute(
                "SELECT * FROM gt_sync_state WHERE baseline_scope = ?",
                (normalized_scope,),
            ).fetchone()
            previous = (
                self._gt_sync_state_dict(previous_row)
                if previous_row is not None
                else self._default_gt_sync_status(normalized_scope)
            )
            conn.execute(
                """
                INSERT INTO gt_sync_state (baseline_scope)
                VALUES (?)
                ON CONFLICT(baseline_scope) DO NOTHING
                """,
                (normalized_scope,),
            )
            changed = [
                issue_id
                for issue_id in sorted(materialized)
                if current.get(issue_id) != materialized[issue_id]["gt_label"]
            ]
            snapshot_changed = previous["source_sha256"] != source_hash
            if snapshot_changed:
                conn.execute(
                    "DELETE FROM gt_sync_labels WHERE baseline_scope = ?",
                    (normalized_scope,),
                )
                conn.executemany(
                    """
                    INSERT INTO gt_sync_labels (
                        baseline_scope, issue_id, gt_label,
                        source_updated_at, source_updated_by, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            normalized_scope,
                            issue_id,
                            materialized[issue_id]["gt_label"],
                            materialized[issue_id]["source_updated_at"] or None,
                            materialized[issue_id]["source_updated_by"],
                            checked_at,
                        )
                        for issue_id in sorted(materialized)
                    ],
                )

            gt_source = f"{source_name} view {source_view_id}:{source_field}"
            for issue_id in changed:
                conn.execute(
                    """
                    UPDATE issues
                    SET gt_label = ?, gt_source = ?, updated_at = ?
                    WHERE issue_id = ? AND baseline_scope = ?
                    """,
                    (
                        materialized[issue_id]["gt_label"],
                        gt_source,
                        checked_at,
                        issue_id,
                        normalized_scope,
                    ),
                )

            changed_source_times = sorted(
                {
                    materialized[issue_id]["source_updated_at"]
                    for issue_id in changed
                    if materialized[issue_id]["source_updated_at"]
                }
            )
            changed_source_users = sorted(
                {
                    materialized[issue_id]["source_updated_by"]
                    for issue_id in changed
                    if materialized[issue_id]["source_updated_by"]
                }
            )
            source_updated_at = (
                changed_source_times[-1]
                if changed_source_times
                else previous["source_updated_at"]
            )
            source_updated_by = (
                "、".join(changed_source_users)
                if changed_source_users
                else previous["source_updated_by"]
            )
            applied_at = (
                checked_at
                if snapshot_changed or changed
                else previous["last_applied_at"]
            )
            applied_count = (
                len(changed)
                if snapshot_changed or changed
                else previous["last_applied_change_count"]
            )
            message = (
                f"已从 {source_name} view {source_view_id} 完整校验 "
                f"{len(materialized)} 条 GT，本次更新 {len(changed)} 条。"
            )
            values = (
                normalized_scope,
                "ready",
                source_name,
                int(source_view_id),
                source_field,
                source_hash,
                len(materialized),
                source_updated_at or None,
                source_updated_by,
                checked_at,
                applied_at or None,
                len(changed),
                applied_count,
                trigger,
                requested_by,
                requested_by_source,
                bool(requested_by_verified),
                message,
                "",
            )
            conn.execute(
                """
                INSERT INTO gt_sync_state (
                    baseline_scope, status, source_name, source_view_id,
                    source_field, source_sha256, source_row_count,
                    source_updated_at, source_updated_by, last_checked_at,
                    last_applied_at, last_check_change_count,
                    last_applied_change_count, last_trigger, requested_by,
                    requested_by_source, requested_by_verified, message,
                    error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(baseline_scope) DO UPDATE SET
                    status = excluded.status,
                    source_name = excluded.source_name,
                    source_view_id = excluded.source_view_id,
                    source_field = excluded.source_field,
                    source_sha256 = excluded.source_sha256,
                    source_row_count = excluded.source_row_count,
                    source_updated_at = excluded.source_updated_at,
                    source_updated_by = excluded.source_updated_by,
                    last_checked_at = excluded.last_checked_at,
                    last_applied_at = excluded.last_applied_at,
                    last_check_change_count = excluded.last_check_change_count,
                    last_applied_change_count = excluded.last_applied_change_count,
                    last_trigger = excluded.last_trigger,
                    requested_by = excluded.requested_by,
                    requested_by_source = excluded.requested_by_source,
                    requested_by_verified = excluded.requested_by_verified,
                    message = excluded.message,
                    error_text = excluded.error_text
                """,
                values,
            )

        return self.gt_sync_status(normalized_scope)

    def record_gt_sync_failure(
        self,
        *,
        scope: str,
        error_text: str,
        source_name: str,
        source_view_id: int,
        source_field: str,
        trigger: str,
        requested_by: str,
        requested_by_source: str,
        requested_by_verified: bool,
    ) -> dict[str, Any]:
        normalized_scope = str(scope or "").strip()
        checked_at = utc_now()
        previous = self.gt_sync_status(normalized_scope)
        message = f"权威 GT 同步失败：{str(error_text or '').strip()}"
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO gt_sync_state (
                    baseline_scope, status, source_name, source_view_id,
                    source_field, source_sha256, source_row_count,
                    source_updated_at, source_updated_by, last_checked_at,
                    last_applied_at, last_check_change_count,
                    last_applied_change_count, last_trigger, requested_by,
                    requested_by_source, requested_by_verified, message,
                    error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(baseline_scope) DO UPDATE SET
                    status = excluded.status,
                    source_name = excluded.source_name,
                    source_view_id = excluded.source_view_id,
                    source_field = excluded.source_field,
                    last_checked_at = excluded.last_checked_at,
                    last_check_change_count = 0,
                    last_trigger = excluded.last_trigger,
                    requested_by = excluded.requested_by,
                    requested_by_source = excluded.requested_by_source,
                    requested_by_verified = excluded.requested_by_verified,
                    message = excluded.message,
                    error_text = excluded.error_text
                """,
                (
                    normalized_scope,
                    "failed",
                    source_name,
                    int(source_view_id),
                    source_field,
                    previous["source_sha256"],
                    previous["source_row_count"],
                    previous["source_updated_at"] or None,
                    previous["source_updated_by"],
                    checked_at,
                    previous["last_applied_at"] or None,
                    0,
                    previous["last_applied_change_count"],
                    trigger,
                    requested_by,
                    requested_by_source,
                    bool(requested_by_verified),
                    message,
                    str(error_text or "").strip()[:2000],
                ),
            )
        return self.gt_sync_status(normalized_scope)
