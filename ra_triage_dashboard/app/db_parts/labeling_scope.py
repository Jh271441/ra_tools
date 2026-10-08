"""Labeling scope storage; composed by DatabaseLabelingMixin."""
from __future__ import annotations
import hashlib
from collections import defaultdict
from typing import Any, Sequence
from uuid import uuid4
from .shared import LabelAnnotationConflictError, _json, _json_load, utc_now
from .labeling_shared import _clean_values


class LabelingScopeMixin:
    def _mark_labeling_change(self, conn: Any) -> None:
        # SQLite tables have the standard row triggers installed by init().
        # PostgreSQL migration 042 deliberately stays within the guarded
        # additive-DDL release contract, so these writes advance the shared
        # revision explicitly in the same transaction.
        if self.backend == "postgresql":
            conn.execute(
                "UPDATE dashboard_change_revision SET revision = revision + 1, updated_at = now() WHERE id = 1"
            )
        self._mark_change_topic(conn, "labeling")

    def labeling_scope_states(
        self, baseline_scopes: Sequence[str] = ()
    ) -> list[dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        where = ""
        params: list[Any] = []
        if scopes:
            where = f"WHERE baseline_scope IN ({', '.join('?' for _ in scopes)})"
            params.extend(scopes)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM labeling_scope_state {where} ORDER BY baseline_scope",
                params,
            ).fetchall()
        return [
            {
                "baseline_scope": str(row["baseline_scope"] or ""),
                "status": str(row["status"] or "shadow"),
                "policy_version": str(row["policy_version"] or ""),
                "epoch": int(row["epoch"] or 0),
                "source_inventory_sha256": str(row["source_inventory_sha256"] or ""),
                "updated_by": str(row["updated_by"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    def active_labeling_scopes(self) -> tuple[str, ...]:
        return tuple(
            item["baseline_scope"]
            for item in self.labeling_scope_states()
            if item["status"] == "active"
        )

    def set_labeling_scope_state(
        self,
        *,
        baseline_scope: str,
        status: str,
        policy_version: str,
        source_inventory_sha256: str,
        updated_by: str,
        expected_epoch: int | None = None,
    ) -> dict[str, Any]:
        scope = str(baseline_scope or "").strip()
        normalized_status = str(status or "").strip()
        if not scope or normalized_status not in {"shadow", "active", "paused"}:
            raise ValueError("标注范围状态不合法。")
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM labeling_scope_state WHERE baseline_scope = ?"
                + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                (scope,),
            ).fetchone()
            current_epoch = int(current["epoch"] or 0) if current else 0
            if expected_epoch is not None and int(expected_epoch) != current_epoch:
                raise LabelAnnotationConflictError(
                    f"标注范围 epoch 已变化：当前 {current_epoch}，请求 {expected_epoch}。"
                )
            state_changed = bool(
                current
                and (
                    str(current["status"]) != normalized_status
                    or str(current["policy_version"] or "") != str(policy_version or "")
                    or str(current["source_inventory_sha256"] or "")
                    != str(source_inventory_sha256 or "")
                )
            )
            next_epoch = current_epoch + (1 if state_changed else 0)
            if current is None and normalized_status == "active":
                next_epoch = 1
            now = utc_now()
            conn.execute(
                """
                INSERT INTO labeling_scope_state (
                    baseline_scope, status, policy_version, epoch,
                    source_inventory_sha256, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(baseline_scope) DO UPDATE SET
                    status = excluded.status,
                    policy_version = excluded.policy_version,
                    epoch = excluded.epoch,
                    source_inventory_sha256 = excluded.source_inventory_sha256,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    scope,
                    normalized_status,
                    str(policy_version or ""),
                    next_epoch,
                    str(source_inventory_sha256 or ""),
                    str(updated_by or ""),
                    now,
                ),
            )
            self._mark_labeling_change(conn)
        return self.labeling_scope_states([scope])[0]

    def activate_labeling_scope(
        self,
        *,
        baseline_scope: str,
        policy_version: str,
        source_inventory_sha256: str,
        updated_by: str,
        expected_epoch: int,
        verify_inventory: Any,
    ) -> dict[str, Any]:
        """Flip one scope to active only while its source inventory still
        matches the reconciled fingerprint, inside the epoch-guarded
        transaction that performs the switch."""
        scope = str(baseline_scope or "").strip()
        if not scope:
            raise ValueError("标注范围不合法。")
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM labeling_scope_state WHERE baseline_scope = ?"
                + (" FOR UPDATE" if self.backend == "postgresql" else ""),
                (scope,),
            ).fetchone()
            if current is None:
                raise ValueError("该数据集尚未回填，不能激活。")
            if str(current["status"]) == "active":
                raise ValueError("该数据集已处于激活状态。")
            current_epoch = int(current["epoch"] or 0)
            if int(expected_epoch) != current_epoch:
                raise LabelAnnotationConflictError(
                    f"标注范围 epoch 已变化：当前 {current_epoch}，请求 {expected_epoch}。"
                )
            fingerprint = str(verify_inventory(conn) or "")
            if (
                fingerprint != str(source_inventory_sha256 or "")
                or fingerprint != str(current["source_inventory_sha256"] or "")
            ):
                raise LabelAnnotationConflictError(
                    "激活时源数据与对账结果不一致；请重新 reconcile。"
                )
            now = utc_now()
            conn.execute(
                """
                UPDATE labeling_scope_state SET
                    status = 'active', policy_version = ?, epoch = ?,
                    source_inventory_sha256 = ?, updated_by = ?, updated_at = ?
                WHERE baseline_scope = ?
                """,
                (
                    str(policy_version or ""),
                    current_epoch + 1,
                    fingerprint,
                    str(updated_by or ""),
                    now,
                    scope,
                ),
            )
            self._mark_labeling_change(conn)
        return self.labeling_scope_states([scope])[0]

    def create_review_workset(
        self,
        *,
        baseline_scope: str,
        issue_ids: Sequence[str],
        name: str = "",
        selection_source_run_id: str = "",
        source_filter: dict[str, Any] | None = None,
        created_by: str = "",
        created_by_source: str = "legacy",
        created_by_verified: bool = False,
    ) -> dict[str, Any]:
        scope = str(baseline_scope or "").strip()
        ordered = list(dict.fromkeys(str(value or "").strip() for value in issue_ids))
        ordered = [value for value in ordered if value]
        if not scope or not ordered:
            raise ValueError("工作集必须包含数据集和至少一个 Issue。")
        digest = hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()
        source_run = str(selection_source_run_id or "").strip()
        with self._write_lock, self.connect() as conn:
            by_id: dict[str, str] = {}
            for offset in range(0, len(ordered), 500):
                batch = ordered[offset : offset + 500]
                placeholders = ", ".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT issue_id, baseline_scope FROM issues WHERE issue_id IN ({placeholders})",
                    batch,
                ).fetchall()
                by_id.update({str(row["issue_id"]): str(row["baseline_scope"] or "") for row in rows})
            missing = [item for item in ordered if item not in by_id]
            wrong_scope = [item for item in ordered if by_id.get(item) != scope]
            if missing:
                raise ValueError("工作集包含不存在的 Issue：" + "、".join(missing[:10]))
            if wrong_scope:
                raise ValueError("工作集包含其他数据集的 Issue：" + "、".join(wrong_scope[:10]))
            existing = conn.execute(
                """
                SELECT * FROM review_worksets
                WHERE baseline_scope = ? AND selection_source_run_id = ?
                  AND members_sha256 = ? AND member_count = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (scope, source_run, digest, len(ordered)),
            ).fetchone()
            if existing is not None:
                return self.get_review_workset(str(existing["id"])) or {}
            workset_id = f"workset-{uuid4().hex}"
            now = utc_now()
            conn.execute(
                """
                INSERT INTO review_worksets (
                    id, baseline_scope, name, selection_source_run_id,
                    source_filter_json, member_count, members_sha256,
                    created_by, created_by_source, created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workset_id,
                    scope,
                    str(name or "").strip()[:160],
                    source_run,
                    _json(source_filter or {}),
                    len(ordered),
                    digest,
                    str(created_by or "").strip(),
                    str(created_by_source or "legacy").strip() or "legacy",
                    bool(created_by_verified),
                    now,
                ),
            )
            conn.executemany(
                "INSERT INTO review_workset_items (workset_id, issue_id, ordinal) VALUES (?, ?, ?)",
                [(workset_id, issue_id, ordinal) for ordinal, issue_id in enumerate(ordered, 1)],
            )
            self._mark_labeling_change(conn)
        return self.get_review_workset(workset_id) or {}

    def get_review_workset(self, workset_id: str) -> dict[str, Any] | None:
        normalized = str(workset_id or "").strip()
        if not normalized:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM review_worksets WHERE id = ?", (normalized,)).fetchone()
            items = conn.execute(
                "SELECT issue_id, ordinal FROM review_workset_items WHERE workset_id = ? ORDER BY ordinal",
                (normalized,),
            ).fetchall()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "baseline_scope": str(row["baseline_scope"]),
            "name": str(row["name"] or ""),
            "selection_source_run_id": str(row["selection_source_run_id"] or ""),
            "source_filter": _json_load(row["source_filter_json"], {}),
            "member_count": int(row["member_count"] or 0),
            "members_sha256": str(row["members_sha256"] or ""),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
            "items": [
                {"issue_id": str(item["issue_id"]), "ordinal": int(item["ordinal"])}
                for item in items
            ],
        }

    def bind_labeling_task(self, *, task_id: str, workset_id: str) -> None:
        task = str(task_id or "").strip()
        workset = str(workset_id or "").strip()
        with self._write_lock, self.connect() as conn:
            split = conn.execute("SELECT model_run_id FROM issue_work_splits WHERE id = ?", (task,)).fetchone()
            if split is None:
                raise ValueError("标注任务不存在。")
            if conn.execute("SELECT 1 FROM review_worksets WHERE id = ?", (workset,)).fetchone() is None:
                raise ValueError("工作集不存在。")
            conn.execute(
                """
                UPDATE issue_work_splits
                SET task_kind = 'labeling', workset_id = ?,
                    selection_source_run_id = model_run_id
                WHERE id = ?
                """,
                (workset, task),
            )
            self._mark_labeling_change(conn)

    def create_labeling_task(
        self,
        *,
        workset_id: str,
        assignments: Sequence[dict[str, Any]],
        created_by: str,
        seed: int | None,
        reviewers_per_issue: int,
        overlap_ratio: float,
        created_by_source: str = "legacy",
        created_by_verified: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        workset = self.get_review_workset(workset_id)
        if workset is None:
            raise ValueError("工作集不存在。")
        actor = str(created_by or "").strip()
        if not actor:
            raise ValueError("任务创建人不能为空。")
        allowed = {item["issue_id"] for item in workset["items"]}
        assignments_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
        now = utc_now()
        for member in assignments:
            assignee = str(member.get("name") or "").strip().lower()
            if not assignee:
                continue
            items = member.get("items") or [
                {"issue_id": issue_id, "assignment_kind": "base", "ordinal": ordinal}
                for ordinal, issue_id in enumerate(member.get("issue_ids") or (), 1)
            ]
            for item in items:
                issue_id = str(item.get("issue_id") or "").strip()
                if issue_id not in allowed:
                    raise ValueError(f"任务分配包含工作集外 Issue：{issue_id}")
                assignments_by_issue[issue_id].append({
                    "assignee": assignee,
                    "assignment_kind": str(item.get("assignment_kind") or "base"),
                })
        assignment_count = sum(len(items) for items in assignments_by_issue.values())
        if not assignment_count:
            raise ValueError("任务分配不能为空。")
        reviewer_count = max(1, int(reviewers_per_issue))
        campaign = self.create_campaign(
            spec={
                "purpose": "labeling",
                "name": str(workset.get("name") or "").strip(),
                "workset_id": workset_id,
                "seed": seed,
                "filters": workset.get("source_filter") or {},
                "overlap_ratio": float(overlap_ratio),
                "members": [
                    {
                        "issue_id": str(item["issue_id"]),
                        "ordinal": int(item["ordinal"] or index),
                        "assignees": assignments_by_issue.get(str(item["issue_id"]), []),
                    }
                    for index, item in enumerate(workset["items"], 1)
                ],
            },
            actor=actor,
            actor_source=created_by_source,
            actor_verified=created_by_verified,
            idempotency_key=idempotency_key,
        )
        campaign_meta = campaign["campaign"]
        return {
            "id": campaign_meta["id"],
            "campaign_id": campaign_meta["id"],
            "purpose": "labeling",
            "name": campaign_meta["name"],
            "workset_id": workset_id,
            "member_count": int(campaign["progress"].get("member_count") or 0),
            "assignment_count": assignment_count,
            "reviewers_per_issue": reviewer_count,
            "overlap_ratio": float(overlap_ratio),
            "created_by": actor,
            "created_at": str(campaign_meta.get("created_at") or now),
            "lifecycle": campaign_meta.get("lifecycle"),
            "config_revision": campaign_meta.get("config_revision"),
            "progress": campaign.get("progress") or {},
        }

    def list_labeling_tasks(self, baseline_scopes: Sequence[str] = ()) -> list[dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        where = "WHERE split.task_kind = 'labeling'"
        params: list[Any] = []
        if scopes:
            where += f" AND workset.baseline_scope IN ({', '.join('?' for _ in scopes)})"
            params.extend(scopes)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT split.id, split.created_by, split.created_at, split.mode,
                       split.reviewers_per_issue, split.overlap_ratio,
                       split.assignment_count, split.workset_id,
                       workset.selection_source_run_id AS workset_selection_source_run_id,
                       split.selection_source_run_id,
                       workset.baseline_scope, workset.name, workset.member_count,
                       workset.members_sha256
                FROM issue_work_splits split
                JOIN review_worksets workset ON workset.id = split.workset_id
                {where}
                ORDER BY split.created_at DESC, split.id DESC
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "name": str(row["name"] or ""),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "workset_id": str(row["workset_id"] or ""),
                "member_count": int(row["member_count"] or 0),
                "members_sha256": str(row["members_sha256"] or ""),
                "selection_source_run_id": str(
                    row["workset_selection_source_run_id"]
                    or row["selection_source_run_id"] or ""
                ),
                "mode": str(row["mode"] or "single"),
                "reviewers_per_issue": int(row["reviewers_per_issue"] or 1),
                "overlap_ratio": float(row["overlap_ratio"] or 0),
                "assignment_count": int(row["assignment_count"] or 0),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def labeling_task_progress(
        self, baseline_scopes: Sequence[str], task_ids: Sequence[str]
    ) -> dict[str, dict[str, Any]]:
        scopes = _clean_values(baseline_scopes)
        tasks = _clean_values(task_ids)
        if not scopes or not tasks:
            return {}
        roster: dict[str, dict[str, int]] = {task: {} for task in tasks}
        placeholders = ", ".join("?" for _ in tasks)
        with self.connect() as conn:
            assignment_rows = conn.execute(
                f"""
                SELECT split_id, lower(trim(assignee)) AS assignee,
                       COUNT(DISTINCT issue_id) AS assigned_count
                FROM review_work_assignments
                WHERE split_id IN ({placeholders}) AND trim(assignee) != ''
                GROUP BY split_id, lower(trim(assignee))
                """,
                tasks,
            ).fetchall()
        for row in assignment_rows:
            split_id = str(row["split_id"])
            if split_id in roster:
                roster[split_id][str(row["assignee"])] = int(row["assigned_count"] or 0)
        progress: dict[str, dict[str, Any]] = {}
        for task in tasks:
            projected, _ = self._project_labeling_cases(
                baseline_scopes=scopes, task_id=task
            )
            total = len(projected)
            resolved = 0
            conflict = 0
            labeled_by_assignee: dict[str, int] = {}
            for item in projected:
                state = item["label_state"]
                if state == "resolved":
                    resolved += 1
                elif state == "conflict":
                    conflict += 1
                seen: set[str] = set()
                for case in item["label_cases"]:
                    for head in case["resolution"].get("heads") or []:
                        author = str(head["author"] or "").strip().lower()
                        if author and author not in seen:
                            seen.add(author)
                            labeled_by_assignee[author] = (
                                labeled_by_assignee.get(author, 0) + 1
                            )
            assignees = [
                {
                    "name": name,
                    "total": count,
                    "labeled": labeled_by_assignee.get(name, 0),
                }
                for name, count in sorted(roster.get(task, {}).items())
            ]
            progress[task] = {
                "total": total,
                "resolved": resolved,
                "conflict": conflict,
                "pending": total - resolved - conflict,
                "assignees": assignees,
            }
        return progress
