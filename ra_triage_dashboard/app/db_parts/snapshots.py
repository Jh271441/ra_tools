"""Immutable GT and local Label result snapshot storage.

Snapshots are content addressed, append only facts. Current GT overlay tables
remain the fast read cache; the snapshot active pointer is the reproducible
reference used by later evaluation and export flows.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable, Sequence
from uuid import uuid4

from .shared import LABELS, _json, _json_load, utc_now


SNAPSHOT_GT_MODES = {"strict", "sparse"}
SNAPSHOT_LABEL_STATES = {"none", "pending", "resolved", "conflict", "stale"}
SNAPSHOT_LABEL_METHODS = {"single", "consensus", "adjudication"}


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_membership_sha(issue_ids: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(issue_ids))).encode("utf-8")).hexdigest()


class DatabaseSnapshotMixin:
    def _lock_gt_snapshot_head_with_conn(self, conn: Any, scope: str) -> Any:
        sync_lock_sql = (
            "SELECT baseline_scope FROM gt_sync_state WHERE baseline_scope = ? FOR UPDATE"
            if self.backend == "postgresql"
            else "SELECT baseline_scope FROM gt_sync_state WHERE baseline_scope = ?"
        )
        conn.execute(sync_lock_sql, (scope,)).fetchone()
        active_lock_sql = (
            "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ? FOR UPDATE"
            if self.backend == "postgresql"
            else "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ?"
        )
        return conn.execute(active_lock_sql, (scope,)).fetchone()

    @staticmethod
    def _gt_snapshot_dict(row: Any, *, active: bool = False) -> dict[str, Any]:
        row_keys = set(row.keys()) if hasattr(row, "keys") else set()
        activation = None
        if "active_activated_at" in row_keys and row["active_activated_at"] is not None:
            activation = {
                "activated_at": str(row["active_activated_at"] or ""),
                "activated_by": str(row["active_activated_by"] or ""),
                "activated_by_source": str(row["active_activated_by_source"] or ""),
                "activated_by_verified": bool(row["active_activated_by_verified"]),
                "activation_reason": str(row["active_activation_reason"] or ""),
            }
        return {
            "id": str(row["id"] or ""),
            "baseline_scope": str(row["baseline_scope"] or ""),
            "gt_mode": str(row["gt_mode"] or "strict"),
            "source_name": str(row["source_name"] or "Trail"),
            "source_view_id": int(row["source_view_id"] or 0),
            "source_field": str(row["source_field"] or ""),
            "source_metadata": _json_load(row["source_metadata_json"], {}),
            "content_sha256": str(row["content_sha256"] or ""),
            "membership_sha256": str(row["membership_sha256"] or ""),
            "member_count": int(row["member_count"] or 0),
            "valid_label_count": int(row["valid_label_count"] or 0),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "system"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
            "active": bool(active),
            "activation": activation,
            "observation": (
                {
                    "status": str(row["observation_status"] or "not_started"),
                    "last_checked_at": str(row["observation_last_checked_at"] or ""),
                    "source_sha256": str(row["observation_source_sha256"] or ""),
                    "source_updated_at": str(row["observation_source_updated_at"] or ""),
                    "source_updated_by": str(row["observation_source_updated_by"] or ""),
                }
                if "observation_last_checked_at" in row_keys
                else None
            ),
        }

    @staticmethod
    def _label_result_snapshot_dict(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"] or ""),
            "baseline_scope": str(row["baseline_scope"] or ""),
            "workset_id": str(row["workset_id"] or ""),
            "workset_members_sha256": str(row["workset_members_sha256"] or ""),
            "content_sha256": str(row["content_sha256"] or ""),
            "member_count": int(row["member_count"] or 0),
            "resolved_count": int(row["resolved_count"] or 0),
            "pending_count": int(row["pending_count"] or 0),
            "conflict_count": int(row["conflict_count"] or 0),
            "stale_count": int(row["stale_count"] or 0),
            "unknown_count": int(row["unknown_count"] or 0),
            "coverage_status": str(row["coverage_status"] or "complete"),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
        }

    @staticmethod
    def _gt_snapshot_content_hash(
        *,
        baseline_scope: str,
        gt_mode: str,
        source_name: str,
        source_view_id: int,
        source_field: str,
        rows: dict[str, dict[str, str]],
    ) -> str:
        payload = {
            "baseline_scope": baseline_scope,
            "gt_mode": gt_mode,
            "source_contract": {
                "source_name": source_name,
                "source_view_id": int(source_view_id),
                "source_field": source_field,
            },
            "members": [
                [
                    issue_id,
                    str(rows[issue_id].get("gt_label") or ""),
                    str(rows[issue_id].get("source_updated_at") or ""),
                    str(rows[issue_id].get("source_updated_by") or ""),
                ]
                for issue_id in sorted(rows)
            ],
        }
        return _sha256_json(payload)

    def _create_or_reuse_gt_snapshot_with_conn(
        self,
        conn: Any,
        *,
        scope: str,
        gt_mode: str,
        source_name: str,
        source_view_id: int,
        source_field: str,
        rows: dict[str, dict[str, str]],
        source_metadata: dict[str, Any] | None = None,
        created_by: str = "",
        created_by_source: str = "system",
        created_by_verified: bool = False,
        activate: bool = True,
        activation_reason: str = "sync",
        mark_change: bool = True,
    ) -> dict[str, Any]:
        normalized_scope = str(scope or "").strip()
        mode = str(gt_mode or "strict").strip().lower()
        if not normalized_scope or mode not in SNAPSHOT_GT_MODES:
            raise ValueError("GT snapshot scope or mode is invalid")
        normalized_rows: dict[str, dict[str, str]] = {}
        for issue_id, raw in rows.items():
            key = str(issue_id or "").strip()
            if not key:
                raise ValueError("GT snapshot contains an empty issue_id")
            label = str((raw or {}).get("gt_label") or "").strip()
            if label and label not in LABELS:
                raise ValueError(f"GT snapshot contains invalid label: {key}={label!r}")
            if mode == "strict" and label not in LABELS:
                raise ValueError(f"strict GT snapshot has an empty label: {key}")
            normalized_rows[key] = {
                "gt_label": label,
                "source_updated_at": str((raw or {}).get("source_updated_at") or ""),
                "source_updated_by": str((raw or {}).get("source_updated_by") or ""),
            }
        if not normalized_rows:
            raise ValueError("GT snapshot membership must not be empty")
        current_members = {
            str(row["issue_id"] or "")
            for row in conn.execute(
                "SELECT issue_id FROM issues WHERE baseline_scope = ?",
                (normalized_scope,),
            ).fetchall()
        }
        if set(normalized_rows) != current_members:
            raise ValueError("GT snapshot membership must exactly match its baseline scope")
        content_sha = self._gt_snapshot_content_hash(
            baseline_scope=normalized_scope,
            gt_mode=mode,
            source_name=str(source_name or "Trail"),
            source_view_id=int(source_view_id),
            source_field=str(source_field or ""),
            rows=normalized_rows,
        )
        membership_sha = _snapshot_membership_sha(list(normalized_rows))
        source_meta = dict(source_metadata or {})
        source_meta.update(
            {
                "baseline_scope": normalized_scope,
                "gt_mode": mode,
                "source_name": str(source_name or "Trail"),
                "source_view_id": int(source_view_id),
                "source_field": str(source_field or ""),
            }
        )
        snapshot_id = f"gt-{content_sha}"
        now = utc_now()
        existing = conn.execute(
            "SELECT * FROM gt_snapshots WHERE baseline_scope = ? AND content_sha256 = ?",
            (normalized_scope, content_sha),
        ).fetchone()
        snapshot_created = existing is None
        if existing is None:
            conn.execute(
                """
                INSERT INTO gt_snapshots (
                    id, baseline_scope, gt_mode, source_name, source_view_id,
                    source_field, source_metadata_json, content_sha256,
                    membership_sha256, member_count, valid_label_count,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    normalized_scope,
                    mode,
                    str(source_name or "Trail"),
                    int(source_view_id),
                    str(source_field or ""),
                    _json(source_meta),
                    content_sha,
                    membership_sha,
                    len(normalized_rows),
                    sum(bool(item["gt_label"]) for item in normalized_rows.values()),
                    str(created_by or ""),
                    str(created_by_source or "system"),
                    bool(created_by_verified),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO gt_snapshot_items (
                    snapshot_id, baseline_scope, issue_id, ordinal,
                    gt_label, source_updated_at, source_updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        normalized_scope,
                        issue_id,
                        ordinal,
                        item["gt_label"],
                        item["source_updated_at"],
                        item["source_updated_by"],
                    )
                    for ordinal, (issue_id, item) in enumerate(
                        sorted(normalized_rows.items()), 1
                    )
                ],
            )
        else:
            snapshot_id = str(existing["id"])
        if activate:
            conn.execute(
                """
                INSERT INTO gt_sync_state (baseline_scope)
                VALUES (?) ON CONFLICT(baseline_scope) DO NOTHING
                """,
                (normalized_scope,),
            )
            current_active = self._lock_gt_snapshot_head_with_conn(
                conn, normalized_scope
            )
            current_active_id = (
                str(current_active["snapshot_id"] or "") if current_active else ""
            )
            if current_active_id != snapshot_id:
                conn.execute(
                    """
                INSERT INTO gt_snapshot_active (
                    baseline_scope, snapshot_id, activated_at, activated_by,
                    activated_by_source, activated_by_verified, activation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(baseline_scope) DO UPDATE SET
                    snapshot_id = excluded.snapshot_id,
                    activated_at = excluded.activated_at,
                    activated_by = excluded.activated_by,
                    activated_by_source = excluded.activated_by_source,
                    activated_by_verified = excluded.activated_by_verified,
                    activation_reason = excluded.activation_reason
                    """,
                    (
                        normalized_scope,
                        snapshot_id,
                        now,
                        str(created_by or ""),
                        str(created_by_source or "system"),
                        bool(created_by_verified),
                        str(activation_reason or "sync"),
                    ),
                )
                if mark_change:
                    self._mark_gt_sync_change(conn)
            elif snapshot_created:
                if mark_change:
                    self._mark_gt_sync_change(conn)
        row = conn.execute("SELECT * FROM gt_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if row is None:
            raise RuntimeError("GT snapshot disappeared after insert")
        if activate:
            row = conn.execute(
                """
                SELECT snapshot.*,
                       active.activated_at AS active_activated_at,
                       active.activated_by AS active_activated_by,
                       active.activated_by_source AS active_activated_by_source,
                       active.activated_by_verified AS active_activated_by_verified,
                       active.activation_reason AS active_activation_reason,
                       sync.status AS observation_status,
                       sync.last_checked_at AS observation_last_checked_at,
                       sync.source_sha256 AS observation_source_sha256,
                       sync.source_updated_at AS observation_source_updated_at,
                       sync.source_updated_by AS observation_source_updated_by
                FROM gt_snapshots snapshot
                JOIN gt_snapshot_active active ON active.snapshot_id = snapshot.id
                LEFT JOIN gt_sync_state sync ON sync.baseline_scope = snapshot.baseline_scope
                WHERE snapshot.id = ?
                """,
                (snapshot_id,),
            ).fetchone()
        result = self._gt_snapshot_dict(row, active=activate)
        result["active_snapshot_id"] = snapshot_id if activate else ""
        return result

    def get_active_gt_snapshot(self, baseline_scope: str) -> dict[str, Any] | None:
        scope = str(baseline_scope or "").strip()
        if not scope:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot.*,
                       active.activated_at AS active_activated_at,
                       active.activated_by AS active_activated_by,
                       active.activated_by_source AS active_activated_by_source,
                       active.activated_by_verified AS active_activated_by_verified,
                       active.activation_reason AS active_activation_reason,
                       sync.status AS observation_status,
                       sync.last_checked_at AS observation_last_checked_at,
                       sync.source_sha256 AS observation_source_sha256,
                       sync.source_updated_at AS observation_source_updated_at,
                       sync.source_updated_by AS observation_source_updated_by
                FROM gt_snapshot_active active
                JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
                LEFT JOIN gt_sync_state sync ON sync.baseline_scope = active.baseline_scope
                WHERE active.baseline_scope = ?
                """,
                (scope,),
            ).fetchone()
        return self._gt_snapshot_dict(row, active=True) if row is not None else None

    def _active_gt_snapshots_with_conn(
        self, conn: Any, baseline_scopes: Sequence[str]
    ) -> list[dict[str, Any]]:
        scopes = [
            str(item or "").strip()
            for item in baseline_scopes
            if str(item or "").strip()
        ]
        scopes = list(dict.fromkeys(scopes))
        if not scopes:
            return []
        rows = conn.execute(
            f"""
            SELECT snapshot.*,
                   active.activated_at AS active_activated_at,
                   active.activated_by AS active_activated_by,
                   active.activated_by_source AS active_activated_by_source,
                   active.activated_by_verified AS active_activated_by_verified,
                   active.activation_reason AS active_activation_reason,
                   sync.status AS observation_status,
                   sync.last_checked_at AS observation_last_checked_at,
                   sync.source_sha256 AS observation_source_sha256,
                   sync.source_updated_at AS observation_source_updated_at,
                   sync.source_updated_by AS observation_source_updated_by
            FROM gt_snapshot_active active
            JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
            LEFT JOIN gt_sync_state sync ON sync.baseline_scope = active.baseline_scope
            WHERE active.baseline_scope IN ({', '.join('?' for _ in scopes)})
            ORDER BY snapshot.baseline_scope
            """,
            scopes,
        ).fetchall()
        return [self._gt_snapshot_dict(row, active=True) for row in rows]

    def active_gt_snapshots(self, baseline_scopes: Sequence[str]) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return self._active_gt_snapshots_with_conn(conn, baseline_scopes)

    def get_gt_snapshot(
        self,
        snapshot_id: str,
        *,
        include_items: bool = False,
        item_limit: int = 100,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any] | None:
        normalized = str(snapshot_id or "").strip()
        if not normalized:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot.*,
                       active.activated_at AS active_activated_at,
                       active.activated_by AS active_activated_by,
                       active.activated_by_source AS active_activated_by_source,
                       active.activated_by_verified AS active_activated_by_verified,
                       active.activation_reason AS active_activation_reason,
                       sync.status AS observation_status,
                       sync.last_checked_at AS observation_last_checked_at,
                       sync.source_sha256 AS observation_source_sha256,
                       sync.source_updated_at AS observation_source_updated_at,
                       sync.source_updated_by AS observation_source_updated_by
                FROM gt_snapshots snapshot
                LEFT JOIN gt_snapshot_active active ON active.snapshot_id = snapshot.id
                LEFT JOIN gt_sync_state sync ON sync.baseline_scope = snapshot.baseline_scope
                WHERE snapshot.id = ?
                """,
                (normalized,),
            ).fetchone()
            if row is None:
                return None
            result = self._gt_snapshot_dict(row)
            result["active"] = row["active_activated_at"] is not None
            if include_items:
                normalized_page = max(1, min(int(page), 1_000_000))
                normalized_page_size = max(
                    1, min(int(page_size if page_size is not None else item_limit), 1000)
                )
                offset = (normalized_page - 1) * normalized_page_size
                total_row = conn.execute(
                    "SELECT COUNT(*) AS total FROM gt_snapshot_items WHERE snapshot_id = ?",
                    (normalized,),
                ).fetchone()
                total = int(total_row["total"] or 0)
                rows = conn.execute(
                    """
                    SELECT issue_id, ordinal, gt_label, source_updated_at, source_updated_by
                    FROM gt_snapshot_items WHERE snapshot_id = ? ORDER BY ordinal LIMIT ? OFFSET ?
                    """,
                    (normalized, normalized_page_size, offset),
                ).fetchall()
                result["items"] = [
                    {
                        "issue_id": str(item["issue_id"]),
                        "ordinal": int(item["ordinal"]),
                        "gt_label": str(item["gt_label"] or ""),
                        "source_updated_at": str(item["source_updated_at"] or ""),
                        "source_updated_by": str(item["source_updated_by"] or ""),
                    }
                    for item in rows
                ]
                result["items_total"] = total
                result["items_page"] = normalized_page
                result["items_page_size"] = normalized_page_size
                result["items_next_page"] = (
                    normalized_page + 1
                    if offset + len(rows) < total
                    else None
                )
        return result

    def gt_snapshot_item_labels(
        self, snapshot_id: str, issue_ids: Sequence[str]
    ) -> dict[str, str]:
        normalized = str(snapshot_id or "").strip()
        ids = list(dict.fromkeys(str(item or "").strip() for item in issue_ids if str(item or "").strip()))
        if not normalized or not ids:
            return {}
        result: dict[str, str] = {}
        with self.connect() as conn:
            for offset in range(0, len(ids), 400):
                batch = ids[offset : offset + 400]
                rows = conn.execute(
                    f"""
                    SELECT issue_id, gt_label FROM gt_snapshot_items
                    WHERE snapshot_id = ? AND issue_id IN ({', '.join('?' for _ in batch)})
                    """,
                    (normalized, *batch),
                ).fetchall()
                result.update(
                    {str(row["issue_id"]): str(row["gt_label"] or "") for row in rows}
                )
        return result

    def create_gt_snapshot_from_current(
        self,
        *,
        scope: str,
        gt_mode: str,
        source_name: str,
        source_view_id: int,
        source_field: str,
        created_by: str = "",
        created_by_source: str = "migration",
        created_by_verified: bool = False,
        activation_reason: str = "cutover_current",
    ) -> dict[str, Any]:
        normalized = str(scope or "").strip()
        with self._write_lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT issue_id, gt_label, gt_source FROM issues
                WHERE baseline_scope = ? ORDER BY issue_id
                """,
                (normalized,),
            ).fetchall()
            if not rows:
                raise ValueError(f"baseline scope has no members: {normalized}")
            materialized = {
                str(row["issue_id"]): {
                    "gt_label": str(row["gt_label"] or ""),
                    "source_updated_at": "",
                    "source_updated_by": str(row["gt_source"] or ""),
                }
                for row in rows
            }
            state_row = conn.execute(
                "SELECT * FROM gt_sync_state WHERE baseline_scope = ?",
                (normalized,),
            ).fetchone()
            status = (
                self._gt_sync_state_dict(state_row)
                if state_row is not None
                else self._default_gt_sync_status(normalized)
            )
            result = self._create_or_reuse_gt_snapshot_with_conn(
                conn,
                scope=normalized,
                gt_mode=gt_mode,
                source_name=source_name,
                source_view_id=source_view_id,
                source_field=source_field,
                rows=materialized,
                source_metadata={
                    "cutover": "current_overlay",
                    "observed_gt_sync_source_sha256": status.get("source_sha256", ""),
                    "observed_gt_sync_status": status.get("status", "not_started"),
                },
                created_by=created_by,
                created_by_source=created_by_source,
                created_by_verified=created_by_verified,
                activate=True,
                activation_reason=activation_reason,
            )
        return self.get_active_gt_snapshot(normalized) or result

    def _label_result_snapshot_source_rows(
        self,
        snapshot_id: str,
        issue_id: str,
        provenance: Sequence[dict[str, Any]],
    ) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for source in provenance:
            case_id = str(source["label_case_id"])
            revision_sources = [
                {"revision_id": None, "source_role": "case"},
                *source["revision_sources"],
            ]
            for revision_source in revision_sources:
                link = {
                    "issue_id": issue_id,
                    "label_case_id": case_id,
                    "task_id": str(source["task_id"]),
                    "resolution_id": source["resolution_id"],
                    "revision_id": revision_source["revision_id"],
                    "source_role": revision_source["source_role"],
                }
                rows.append(
                    (
                        snapshot_id,
                        issue_id,
                        case_id,
                        str(source["task_id"]),
                        source["resolution_id"],
                        revision_source["revision_id"],
                        str(revision_source["source_role"]),
                        _sha256_json(link),
                    )
                )
        return rows

    @staticmethod
    def _label_result_snapshot_provenance(
        sources: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            case_id = str(source.get("label_case_id") or "").strip()
            if not case_id:
                raise ValueError("Label snapshot source is missing label_case_id")
            adjudication = source.get("adjudication")
            adjudication = adjudication if isinstance(adjudication, dict) else {}
            raw_resolution_id = adjudication.get("id") or source.get("resolution_id")
            try:
                resolution_id = (
                    int(raw_resolution_id)
                    if raw_resolution_id not in (None, "")
                    else None
                )
            except (TypeError, ValueError):
                resolution_id = None
            try:
                result_revision_id = int(adjudication.get("result_revision_id") or 0)
            except (TypeError, ValueError):
                result_revision_id = 0
            revision_ids: set[int] = set()
            for value in source.get("source_revision_ids") or []:
                try:
                    revision_ids.add(int(value))
                except (TypeError, ValueError):
                    continue
            if result_revision_id:
                revision_ids.add(result_revision_id)
            resolution_input_ids: set[int] = set()
            for value in adjudication.get("source_revision_ids") or []:
                try:
                    resolution_input_ids.add(int(value))
                except (TypeError, ValueError):
                    continue
            revision_sources = []
            for revision_id in sorted(revision_ids | resolution_input_ids):
                source_roles = []
                if resolution_id and revision_id == result_revision_id:
                    source_roles.append("resolution_result")
                if resolution_id and revision_id in resolution_input_ids:
                    source_roles.append("resolution_input")
                if not source_roles:
                    source_roles.append("head")
                revision_sources.extend(
                    {"revision_id": revision_id, "source_role": source_role}
                    for source_role in source_roles
                )
            normalized.append(
                {
                    "label_case_id": case_id,
                    "task_id": str(source.get("task_id") or "").strip(),
                    "resolution_id": resolution_id,
                    "revision_sources": revision_sources,
                }
            )
        normalized.sort(
            key=lambda item: (
                item["label_case_id"],
                item["task_id"],
                item["resolution_id"] or 0,
                _sha256_json(item["revision_sources"]),
            )
        )
        return normalized

    def create_label_result_snapshot(
        self,
        *,
        workset_id: str,
        created_by: str,
        created_by_source: str = "legacy",
        created_by_verified: bool = False,
        allow_partial: bool = False,
    ) -> dict[str, Any]:
        workset = self.get_review_workset(workset_id)
        if workset is None:
            raise ValueError("Workset does not exist")
        scope = str(workset.get("baseline_scope") or "").strip()
        members = [str(item.get("issue_id") or "").strip() for item in workset.get("items") or []]
        members = [item for item in members if item]
        if not scope or not members:
            raise ValueError("Label snapshot requires a non-empty Workset")
        projections = self.project_issue_label_states(scope, members, include_sources=True)
        counts = defaultdict(int)
        content_items: list[list[Any]] = []
        provenance_by_issue: dict[str, list[dict[str, Any]]] = {}
        for issue_id in members:
            projection = projections.get(issue_id) or {
                "state": "none", "expected_output": "", "method": "single", "gt_relation": "unknown", "sources": []
            }
            state = str(projection.get("state") or "none")
            method = str(projection.get("method") or "single")
            if state not in SNAPSHOT_LABEL_STATES or method not in SNAPSHOT_LABEL_METHODS:
                raise ValueError(f"invalid label projection for {issue_id}")
            expected_output = str(projection.get("expected_output") or "")
            if expected_output and expected_output not in LABELS:
                raise ValueError(f"invalid expected output for {issue_id}")
            gt_relation = str(projection.get("gt_relation") or "unknown")
            if gt_relation not in {"matches_gt", "differs_from_gt", "fills_missing_gt", "unknown"}:
                raise ValueError(f"invalid GT relation for {issue_id}")
            provenance = self._label_result_snapshot_provenance(
                projection.get("sources") or []
            )
            provenance_by_issue[issue_id] = provenance
            counts[state] += 1
            content_items.append(
                [
                    issue_id,
                    state,
                    expected_output,
                    method,
                    gt_relation,
                    provenance,
                ]
            )
        unresolved_states = {"none", "pending", "conflict", "stale"}
        unresolved_count = sum(item[1] in unresolved_states for item in content_items)
        if not allow_partial and unresolved_count:
            coverage_summary = ", ".join(
                f"{state}={counts[state]}"
                for state in ("none", "pending", "conflict", "stale")
            )
            raise ValueError(
                "Label result snapshot requires all Workset members to be resolved; "
                f"unresolved={unresolved_count}/{len(members)} ({coverage_summary}); "
                "set allow_partial=true for a diagnostic snapshot"
            )
        content_sha = _sha256_json(
            {
                "baseline_scope": scope,
                "workset_id": str(workset["id"]),
                "members_sha256": str(workset.get("members_sha256") or ""),
                "items": content_items,
            }
        )
        snapshot_id = f"label-result-{content_sha}"
        coverage_status = "partial" if unresolved_count else "complete"
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM label_result_snapshots WHERE workset_id = ? AND content_sha256 = ?",
                (str(workset["id"]), content_sha),
            ).fetchone()
            if existing is not None:
                return self._label_result_snapshot_dict(existing)
            conn.execute(
                """
                INSERT INTO label_result_snapshots (
                    id, baseline_scope, workset_id, workset_members_sha256,
                    content_sha256, member_count, resolved_count, pending_count,
                    conflict_count, stale_count, unknown_count, coverage_status,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    scope,
                    str(workset["id"]),
                    str(workset.get("members_sha256") or ""),
                    content_sha,
                    len(members),
                    counts["resolved"],
                    counts["pending"],
                    counts["conflict"],
                    counts["stale"],
                    counts["none"],
                    coverage_status,
                    str(created_by or ""),
                    str(created_by_source or "legacy"),
                    bool(created_by_verified),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO label_result_snapshot_items (
                    snapshot_id, baseline_scope, issue_id, ordinal, state,
                    expected_output, method, gt_relation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        scope,
                        item[0],
                        ordinal,
                        item[1],
                        item[2] or None,
                        item[3],
                        item[4],
                    )
                    for ordinal, item in enumerate(content_items, 1)
                ],
            )
            source_rows: list[tuple[Any, ...]] = []
            for issue_id in members:
                source_rows.extend(
                    self._label_result_snapshot_source_rows(
                        snapshot_id,
                        issue_id,
                        provenance_by_issue.get(issue_id) or [],
                    )
                )
            if source_rows:
                conn.executemany(
                    """
                    INSERT INTO label_result_snapshot_sources (
                        snapshot_id, issue_id, label_case_id, task_id,
                        resolution_id, revision_id, source_role, source_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    source_rows,
                )
            self._mark_labeling_change(conn)
            row = conn.execute(
                "SELECT * FROM label_result_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return self._label_result_snapshot_dict(row)

    def get_label_result_snapshot(
        self,
        snapshot_id: str,
        *,
        include_items: bool = False,
        item_limit: int = 100,
        page: int = 1,
        page_size: int | None = None,
        include_sources: bool = False,
        source_page: int = 1,
        source_page_size: int = 100,
    ) -> dict[str, Any] | None:
        normalized = str(snapshot_id or "").strip()
        if not normalized:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM label_result_snapshots WHERE id = ?", (normalized,)
            ).fetchone()
            if row is None:
                return None
            result = self._label_result_snapshot_dict(row)
            if include_items:
                normalized_page = max(1, min(int(page), 1_000_000))
                normalized_page_size = max(
                    1, min(int(page_size if page_size is not None else item_limit), 1000)
                )
                offset = (normalized_page - 1) * normalized_page_size
                total_row = conn.execute(
                    "SELECT COUNT(*) AS total FROM label_result_snapshot_items WHERE snapshot_id = ?",
                    (normalized,),
                ).fetchone()
                total = int(total_row["total"] or 0)
                items = conn.execute(
                    """
                    SELECT issue_id, ordinal, state, expected_output, method, gt_relation
                    FROM label_result_snapshot_items WHERE snapshot_id = ?
                    ORDER BY ordinal LIMIT ? OFFSET ?
                    """,
                    (normalized, normalized_page_size, offset),
                ).fetchall()
                result["items"] = [
                    {
                        "issue_id": str(item["issue_id"]),
                        "ordinal": int(item["ordinal"]),
                        "state": str(item["state"]),
                        "expected_output": str(item["expected_output"] or ""),
                        "method": str(item["method"]),
                        "gt_relation": str(item["gt_relation"] or "unknown"),
                    }
                    for item in items
                ]
                result["items_total"] = total
                result["items_page"] = normalized_page
                result["items_page_size"] = normalized_page_size
                result["items_next_page"] = (
                    normalized_page + 1
                    if offset + len(items) < total
                    else None
                )
            if include_sources:
                normalized_source_page = max(1, min(int(source_page), 1_000_000))
                normalized_source_page_size = max(1, min(int(source_page_size), 1000))
                source_offset = (normalized_source_page - 1) * normalized_source_page_size
                source_total_row = conn.execute(
                    "SELECT COUNT(*) AS total FROM label_result_snapshot_sources WHERE snapshot_id = ?",
                    (normalized,),
                ).fetchone()
                source_total = int(source_total_row["total"] or 0)
                sources = conn.execute(
                    """
                    SELECT issue_id, label_case_id, task_id, resolution_id,
                           revision_id, source_role, source_key
                    FROM label_result_snapshot_sources
                    WHERE snapshot_id = ?
                    ORDER BY issue_id, label_case_id, source_role, revision_id
                    LIMIT ? OFFSET ?
                    """,
                    (normalized, normalized_source_page_size, source_offset),
                ).fetchall()
                result["sources"] = [
                    {
                        "issue_id": str(item["issue_id"]),
                        "label_case_id": str(item["label_case_id"]),
                        "task_id": str(item["task_id"] or ""),
                        "resolution_id": (
                            int(item["resolution_id"])
                            if item["resolution_id"] is not None
                            else None
                        ),
                        "revision_id": (
                            int(item["revision_id"])
                            if item["revision_id"] is not None
                            else None
                        ),
                        "source_role": str(item["source_role"]),
                        "source_key": str(item["source_key"]),
                    }
                    for item in sources
                ]
                result["sources_total"] = source_total
                result["sources_page"] = normalized_source_page
                result["sources_page_size"] = normalized_source_page_size
                result["sources_next_page"] = (
                    normalized_source_page + 1
                    if source_offset + len(sources) < source_total
                    else None
                )
        return result
