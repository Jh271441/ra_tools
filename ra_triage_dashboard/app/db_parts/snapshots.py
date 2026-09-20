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


class SnapshotConflictError(RuntimeError):
    """The active snapshot changed since a caller's read."""


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
    @staticmethod
    def _gt_snapshot_dict(row: Any, *, active: bool = False) -> dict[str, Any]:
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
                [issue_id, str(rows[issue_id].get("gt_label") or "")]
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
            lock_sql = (
                "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ? FOR UPDATE"
                if self.backend == "postgresql"
                else "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ?"
            )
            current_active = conn.execute(lock_sql, (normalized_scope,)).fetchone()
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
        row = conn.execute("SELECT * FROM gt_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if row is None:
            raise RuntimeError("GT snapshot disappeared after insert")
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
                SELECT snapshot.* FROM gt_snapshot_active active
                JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
                WHERE active.baseline_scope = ?
                """,
                (scope,),
            ).fetchone()
        return self._gt_snapshot_dict(row, active=True) if row is not None else None

    def active_gt_snapshots(self, baseline_scopes: Sequence[str]) -> list[dict[str, Any]]:
        scopes = [str(item or "").strip() for item in baseline_scopes if str(item or "").strip()]
        scopes = list(dict.fromkeys(scopes))
        if not scopes:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT snapshot.* FROM gt_snapshot_active active
                JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
                WHERE active.baseline_scope IN ({', '.join('?' for _ in scopes)})
                ORDER BY snapshot.baseline_scope
                """,
                scopes,
            ).fetchall()
        return [self._gt_snapshot_dict(row, active=True) for row in rows]

    def activate_gt_snapshot(
        self,
        *,
        baseline_scope: str,
        snapshot_id: str,
        expected_previous_snapshot_id: str | None = None,
        activated_by: str = "",
        activated_by_source: str = "system",
        activated_by_verified: bool = False,
        activation_reason: str = "manual",
    ) -> dict[str, Any]:
        scope = str(baseline_scope or "").strip()
        target = str(snapshot_id or "").strip()
        if not scope or not target:
            raise ValueError("baseline_scope and snapshot_id are required")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            snapshot = conn.execute(
                "SELECT * FROM gt_snapshots WHERE id = ? AND baseline_scope = ?",
                (target, scope),
            ).fetchone()
            if snapshot is None:
                raise ValueError("GT snapshot does not exist for this scope")
            lock_sql = (
                "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ? FOR UPDATE"
                if self.backend == "postgresql"
                else "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ?"
            )
            current = conn.execute(lock_sql, (scope,)).fetchone()
            current_id = str(current["snapshot_id"] or "") if current else ""
            if expected_previous_snapshot_id is not None and str(
                expected_previous_snapshot_id or ""
            ) != current_id:
                raise SnapshotConflictError(
                    f"active GT snapshot changed: current={current_id or 'none'}"
                )
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
                    scope,
                    target,
                    now,
                    str(activated_by or ""),
                    str(activated_by_source or "system"),
                    bool(activated_by_verified),
                    str(activation_reason or "manual"),
                ),
            )
            self._mark_change_topic(conn, "gt_sync")
        return self.get_active_gt_snapshot(scope) or {}

    def get_gt_snapshot(
        self, snapshot_id: str, *, include_items: bool = False, item_limit: int = 100
    ) -> dict[str, Any] | None:
        normalized = str(snapshot_id or "").strip()
        if not normalized:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM gt_snapshots WHERE id = ?", (normalized,)).fetchone()
            if row is None:
                return None
            result = self._gt_snapshot_dict(row)
            active = conn.execute(
                "SELECT 1 FROM gt_snapshot_active WHERE snapshot_id = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            result["active"] = active is not None
            if include_items:
                rows = conn.execute(
                    """
                    SELECT issue_id, ordinal, gt_label, source_updated_at, source_updated_by
                    FROM gt_snapshot_items WHERE snapshot_id = ? ORDER BY ordinal LIMIT ?
                    """,
                    (normalized, max(1, min(int(item_limit), 1000))),
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
            status = self.gt_sync_status(normalized)
            return self._create_or_reuse_gt_snapshot_with_conn(
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

    def _label_result_snapshot_source_rows(
        self,
        snapshot_id: str,
        issue_id: str,
        sources: Sequence[dict[str, Any]],
    ) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for source in sources:
            case_id = str(source.get("label_case_id") or "").strip()
            if not case_id:
                continue
            resolution = source.get("adjudication") or {}
            resolution_id = resolution.get("id")
            try:
                resolution_id = int(resolution_id) if resolution_id not in (None, "") else None
            except (TypeError, ValueError):
                resolution_id = None
            revision_ids = []
            for value in source.get("source_revision_ids") or []:
                try:
                    revision_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            for revision_id in revision_ids or [None]:
                rows.append(
                    (
                        snapshot_id,
                        issue_id,
                        case_id,
                        resolution_id,
                        revision_id,
                        "resolution" if resolution_id else "head",
                    )
                )
        return rows

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
        for ordinal, issue_id in enumerate(members, 1):
            projection = projections.get(issue_id) or {
                "state": "none", "expected_output": "", "method": "single", "gt_relation": "unknown", "sources": []
            }
            state = str(projection.get("state") or "none")
            method = str(projection.get("method") or "single")
            if state not in SNAPSHOT_LABEL_STATES or method not in SNAPSHOT_LABEL_METHODS:
                raise ValueError(f"invalid label projection for {issue_id}")
            counts[state] += 1
            content_items.append(
                [
                    issue_id,
                    state,
                    str(projection.get("expected_output") or ""),
                    method,
                    str(projection.get("gt_relation") or "unknown"),
                    sorted(int(item) for item in projection.get("source_revision_ids") or []),
                ]
            )
        unresolved_states = {"none", "pending", "conflict", "stale"}
        if not allow_partial and any(item[1] in unresolved_states for item in content_items):
            raise ValueError(
                "Label result snapshot requires all Workset members to be resolved; "
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
        coverage_status = "complete"
        if any(item[1] != "resolved" for item in content_items):
            coverage_status = "partial" if allow_partial else "complete"
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
                        projections.get(issue_id, {}).get("sources") or [],
                    )
                )
            if source_rows:
                conn.executemany(
                    """
                    INSERT INTO label_result_snapshot_sources (
                        snapshot_id, issue_id, label_case_id, resolution_id,
                        revision_id, source_role
                    ) VALUES (?, ?, ?, ?, ?, ?)
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
        self, snapshot_id: str, *, include_items: bool = False, item_limit: int = 100
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
                items = conn.execute(
                    """
                    SELECT issue_id, ordinal, state, expected_output, method, gt_relation
                    FROM label_result_snapshot_items WHERE snapshot_id = ?
                    ORDER BY ordinal LIMIT ?
                    """,
                    (normalized, max(1, min(int(item_limit), 1000))),
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
        return result
