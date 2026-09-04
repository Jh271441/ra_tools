from __future__ import annotations

from typing import Any

from .shared import IntentAnnotationConflictError, utc_now


ROUTING_INTENTS = ("left_turn", "right_turn", "straight", "u_turn", "parking")
LANE_CHANGE_INTENTS = ("lane_change", "no_lane_change")


class DatabaseIntentMixin:
    def list_intent_assignment_assignees(
        self, dataset_id: str, experiment_id: str = ""
    ) -> list[dict[str, Any]]:
        """Return active experiment owners without exposing their answers."""

        with self.connect() as conn:
            experiment_filter = " AND experiment.id = ?" if experiment_id else ""
            parameters = (dataset_id, experiment_id) if experiment_id else (dataset_id,)
            rows = conn.execute(
                f"""
                SELECT assignment.username,
                       COUNT(DISTINCT assignment.case_id) AS case_count,
                       COUNT(DISTINCT assignment.experiment_id) AS experiment_count
                FROM intent_experiment_assignments assignment
                JOIN intent_experiments experiment
                  ON experiment.id = assignment.experiment_id
                WHERE experiment.dataset_id = ? AND experiment.status = 'active'
                  {experiment_filter}
                GROUP BY assignment.username
                ORDER BY assignment.username ASC
                """,
                parameters,
            ).fetchall()
        return [
            {
                "username": str(row["username"]),
                "case_count": int(row["case_count"] or 0),
                "experiment_count": int(row["experiment_count"] or 0),
            }
            for row in rows
        ]

    def intent_assigned_case_ids(
        self,
        dataset_id: str,
        usernames: list[str] | tuple[str, ...],
        experiment_id: str = "",
    ) -> tuple[str, ...]:
        """Return cases assigned to every selected owner in one active experiment."""

        normalized = tuple(
            dict.fromkeys(
                str(username or "").strip().lower() for username in usernames
                if str(username or "").strip()
            )
        )
        if not normalized:
            return ()
        placeholders = ", ".join("?" for _ in normalized)
        experiment_filter = " AND experiment.id = ?" if experiment_id else ""
        parameters: tuple[Any, ...] = (dataset_id, *normalized)
        if experiment_id:
            parameters = (*parameters, experiment_id)
        parameters = (*parameters, len(normalized))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT assignment.case_id
                FROM intent_experiment_assignments assignment
                JOIN intent_experiments experiment
                  ON experiment.id = assignment.experiment_id
                WHERE experiment.dataset_id = ? AND experiment.status = 'active'
                  AND assignment.username IN ({placeholders})
                  {experiment_filter}
                GROUP BY assignment.experiment_id, assignment.case_id
                HAVING COUNT(DISTINCT assignment.username) = ?
                ORDER BY MIN(assignment.ordinal) ASC, assignment.case_id ASC
                """,
                parameters,
            ).fetchall()
        return tuple(dict.fromkeys(str(row["case_id"]) for row in rows))

    def intent_experiment_case_ids(
        self, dataset_id: str, experiment_id: str
    ) -> tuple[str, ...]:
        """Return the immutable Case subset for one active assignment."""

        if not experiment_id:
            return ()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT assignment.case_id
                FROM intent_experiment_assignments assignment
                JOIN intent_experiments experiment
                  ON experiment.id = assignment.experiment_id
                WHERE experiment.dataset_id = ? AND experiment.id = ?
                  AND experiment.status = 'active'
                GROUP BY assignment.case_id
                ORDER BY MIN(assignment.ordinal) ASC, assignment.case_id ASC
                """,
                (dataset_id, experiment_id),
            ).fetchall()
        return tuple(str(row["case_id"]) for row in rows)

    def list_intent_experiments(
        self, dataset_id: str | list[str] | tuple[str, ...] = ""
    ) -> list[dict[str, Any]]:
        if isinstance(dataset_id, (list, tuple)):
            dataset_ids = [str(item).strip() for item in dataset_id if str(item).strip()]
        elif dataset_id:
            dataset_ids = [str(dataset_id).strip()]
        else:
            dataset_ids = []
        parameters: tuple[Any, ...] = tuple(dataset_ids)
        where = ""
        if dataset_ids:
            placeholders = ", ".join("?" for _ in dataset_ids)
            where = f"WHERE experiment.dataset_id IN ({placeholders})"
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT experiment.*,
                       COUNT(assignment.case_id) AS assignment_count,
                       COUNT(DISTINCT assignment.username) AS member_count
                FROM intent_experiments experiment
                LEFT JOIN intent_experiment_assignments assignment
                  ON assignment.experiment_id = experiment.id
                {where}
                GROUP BY experiment.id
                ORDER BY experiment.created_at DESC, experiment.id DESC
                """,
                parameters,
            ).fetchall()
            assignment_rows = conn.execute(
                f"""
                SELECT assignment.experiment_id, assignment.username,
                       assignment.assignment_kind, COUNT(*) AS case_count
                FROM intent_experiment_assignments assignment
                JOIN intent_experiments experiment
                  ON experiment.id = assignment.experiment_id
                {where}
                GROUP BY experiment_id, username, assignment_kind
                ORDER BY experiment_id, username, assignment_kind
                """,
                parameters,
            ).fetchall()
            update_rows = conn.execute(
                f"""
                SELECT update_record.*
                FROM intent_experiment_updates update_record
                JOIN intent_experiments experiment
                  ON experiment.id = update_record.experiment_id
                {where}
                ORDER BY update_record.id DESC
                """,
                parameters,
            ).fetchall()
            progress_rows = conn.execute(
                f"""
                SELECT experiment.id AS experiment_id,
                       COUNT(assignment.case_id) AS total_count,
                       SUM(CASE WHEN head.current_revision_id IS NOT NULL THEN 1 ELSE 0 END)
                           AS started_count,
                       SUM(CASE WHEN head.current_revision_id IS NOT NULL AND (
                           (experiment.label_scope = 'routing'
                            AND COALESCE(revision.routing_default, '') <> '')
                           OR (experiment.label_scope = 'lane_change'
                               AND COALESCE(revision.lane_change_default, '') <> '')
                           OR (experiment.label_scope = 'all'
                               AND COALESCE(revision.routing_default, '') <> ''
                               AND COALESCE(revision.lane_change_default, '') <> '')
                       ) THEN 1 ELSE 0 END) AS completed_count
                FROM intent_experiments experiment
                LEFT JOIN intent_experiment_assignments assignment
                  ON assignment.experiment_id = experiment.id
                LEFT JOIN intent_user_label_heads head
                  ON head.dataset_id = experiment.dataset_id
                 AND head.case_id = assignment.case_id
                 AND head.username = assignment.username
                LEFT JOIN intent_label_revisions revision
                  ON revision.id = head.current_revision_id
                {where}
                GROUP BY experiment.id
                """,
                parameters,
            ).fetchall()
        members_by_experiment: dict[str, dict[str, dict[str, int]]] = {}
        for item in assignment_rows:
            experiment = members_by_experiment.setdefault(str(item["experiment_id"]), {})
            member = experiment.setdefault(
                str(item["username"]), {"base": 0, "cross": 0, "full": 0}
            )
            member[str(item["assignment_kind"])] = int(item["case_count"] or 0)
        updates_by_experiment: dict[str, list[dict[str, Any]]] = {}
        for item in update_rows:
            updates_by_experiment.setdefault(str(item["experiment_id"]), []).append(
                {
                    "id": int(item["id"]),
                    "old_name": str(item["old_name"]),
                    "new_name": str(item["new_name"]),
                    "old_label_scope": str(item["old_label_scope"]),
                    "new_label_scope": str(item["new_label_scope"]),
                    "updated_by": str(item["updated_by"]),
                    "created_at": str(item["created_at"]),
                }
            )
        progress_by_experiment = {
            str(item["experiment_id"]): {
                "total": int(item["total_count"] or 0),
                "started": int(item["started_count"] or 0),
                "completed": int(item["completed_count"] or 0),
            }
            for item in progress_rows
        }
        result = []
        for row in rows:
            experiment_id = str(row["id"])
            progress = progress_by_experiment.get(
                experiment_id, {"total": 0, "started": 0, "completed": 0}
            )
            progress["partial"] = max(0, progress["started"] - progress["completed"])
            progress["pending"] = max(0, progress["total"] - progress["started"])
            progress["percent"] = round(
                progress["completed"] * 100 / progress["total"], 1
            ) if progress["total"] else 0.0
            member_stats = [
                {
                    "username": username,
                    **counts,
                    "total": sum(counts.values()),
                }
                for username, counts in sorted(
                    members_by_experiment.get(experiment_id, {}).items()
                )
            ]
            result.append(
                {
                    "id": experiment_id,
                    "dataset_id": str(row["dataset_id"]),
                    "name": str(row["name"]),
                    "annotation_mode": str(row["annotation_mode"]),
                    "label_scope": str(row["label_scope"] or "all"),
                    "overlap_ratio": float(row["overlap_ratio"] or 0),
                    "overlap_reviewers": int(row["overlap_reviewers"] or 2),
                    "case_count": int(row["case_count"] or 0),
                    "status": str(row["status"]),
                    "seed": int(row["seed"]),
                    "created_by": str(row["created_by"]),
                    "created_at": str(row["created_at"]),
                    "closed_by": str(row["closed_by"] or ""),
                    "closed_at": str(row["closed_at"] or ""),
                    "assignment_count": int(row["assignment_count"] or 0),
                    "member_count": int(row["member_count"] or 0),
                    "members": member_stats,
                    "updates": updates_by_experiment.get(experiment_id, []),
                    "update_count": len(updates_by_experiment.get(experiment_id, [])),
                    "progress": progress,
                }
            )
        return result

    def create_intent_experiment(
        self,
        *,
        experiment_id: str,
        dataset_id: str,
        name: str,
        annotation_mode: str,
        overlap_ratio: float,
        case_count: int,
        seed: int,
        assignments: list[dict[str, Any]],
        created_by: str,
        created_by_source: str,
        created_by_verified: bool,
        overlap_reviewers: int = 2,
        label_scope: str = "all",
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_experiments (
                    id, dataset_id, name, annotation_mode, label_scope, overlap_ratio, overlap_reviewers,
                    case_count, status, seed, created_by, created_by_source,
                    created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    dataset_id,
                    name,
                    annotation_mode,
                    label_scope,
                    overlap_ratio,
                    overlap_reviewers,
                    case_count,
                    seed,
                    created_by,
                    created_by_source,
                    bool(created_by_verified),
                    now,
                ),
            )
            conn.executemany(
                """
                INSERT INTO intent_experiment_assignments (
                    experiment_id, username, case_id, assignment_kind,
                    ordinal, assigned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        experiment_id,
                        item["username"],
                        item["case_id"],
                        item["assignment_kind"],
                        item["ordinal"],
                        now,
                    )
                    for item in assignments
                ],
            )
        return next(
            item for item in self.list_intent_experiments(dataset_id)
            if item["id"] == experiment_id
        )

    def update_intent_experiment(
        self,
        experiment_id: str,
        *,
        name: str,
        label_scope: str,
        updated_by: str,
        updated_by_source: str,
        updated_by_verified: bool,
    ) -> dict[str, Any] | None:
        """Edit presentation/task scope without changing the allocation snapshot."""

        now = utc_now()
        with self._write_lock, self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM intent_experiments WHERE id = ?",
                (experiment_id,),
            ).fetchone()
            if current is None:
                return None
            if str(current["status"]) != "active":
                raise ValueError("已关闭实验不能修改。")
            old_name = str(current["name"])
            old_label_scope = str(current["label_scope"] or "all")
            dataset_id = str(current["dataset_id"])
            if old_name != name or old_label_scope != label_scope:
                conn.execute(
                    """
                    UPDATE intent_experiments
                    SET name = ?, label_scope = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (name, label_scope, experiment_id),
                )
                conn.execute(
                    """
                    INSERT INTO intent_experiment_updates (
                        experiment_id, old_name, new_name,
                        old_label_scope, new_label_scope,
                        updated_by, updated_by_source, updated_by_verified, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        old_name,
                        name,
                        old_label_scope,
                        label_scope,
                        updated_by,
                        updated_by_source,
                        bool(updated_by_verified),
                        now,
                    ),
                )
        return next(
            item for item in self.list_intent_experiments(dataset_id)
            if item["id"] == experiment_id
        )

    def close_intent_experiment(
        self, experiment_id: str, *, closed_by: str
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE intent_experiments
                SET status = 'closed', closed_by = ?, closed_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (closed_by, now, experiment_id),
            )
            if cursor.rowcount <= 0:
                row = conn.execute(
                    "SELECT dataset_id FROM intent_experiments WHERE id = ?",
                    (experiment_id,),
                ).fetchone()
                if row is None:
                    return None
                dataset_id = str(row["dataset_id"])
            else:
                row = conn.execute(
                    "SELECT dataset_id FROM intent_experiments WHERE id = ?",
                    (experiment_id,),
                ).fetchone()
                dataset_id = str(row["dataset_id"])
        return next(
            item for item in self.list_intent_experiments(dataset_id)
            if item["id"] == experiment_id
        )

    @staticmethod
    def _intent_revision_dict(row: Any, overrides: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "revision_id": int(row["id"]),
            "dataset_id": str(row["dataset_id"]),
            "case_id": str(row["case_id"]),
            "routing_default": str(row["routing_default"] or ""),
            "lane_change_default": str(row["lane_change_default"] or ""),
            "author": str(row["author"] or ""),
            "author_source": str(row["author_source"] or ""),
            "author_verified": bool(row["author_verified"]),
            "supersedes_id": int(row["supersedes_id"]) if row["supersedes_id"] else None,
            "created_at": str(row["created_at"] or ""),
            "overrides": overrides,
        }

    def get_intent_labels(
        self, dataset_id: str, case_id: str, username: str = ""
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            normalized_username = str(username or "").strip().lower()
            if normalized_username:
                row = conn.execute(
                    """
                    SELECT revision.*
                    FROM intent_user_label_heads head
                    JOIN intent_label_revisions revision
                      ON revision.id = head.current_revision_id
                    WHERE head.dataset_id = ? AND head.case_id = ?
                      AND head.username = ?
                    """,
                    (dataset_id, case_id, normalized_username),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT revision.*
                    FROM intent_label_heads head
                    JOIN intent_label_revisions revision
                      ON revision.id = head.current_revision_id
                    WHERE head.dataset_id = ? AND head.case_id = ?
                    """,
                    (dataset_id, case_id),
                ).fetchone()
            if row is None:
                return None
            override_rows = conn.execute(
                """
                SELECT timepoint_id, offset_ms, routing_intent, lane_change_intent
                FROM intent_frame_overrides
                WHERE revision_id = ?
                ORDER BY offset_ms ASC, timepoint_id ASC
                """,
                (row["id"],),
            ).fetchall()
        overrides = [
            {
                "timepoint_id": str(item["timepoint_id"]),
                "offset_ms": int(item["offset_ms"]),
                "routing_intent": str(item["routing_intent"] or ""),
                "lane_change_intent": str(item["lane_change_intent"] or ""),
            }
            for item in override_rows
        ]
        return self._intent_revision_dict(row, overrides)

    def intent_label_heads(self, dataset_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT case_id, current_revision_id
                FROM intent_label_heads
                WHERE dataset_id = ?
                """,
                (dataset_id,),
            ).fetchall()
        return {str(row["case_id"]): int(row["current_revision_id"]) for row in rows}

    def intent_label_summaries(
        self, dataset_id: str, username: str = ""
    ) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            normalized_username = str(username or "").strip().lower()
            if normalized_username:
                rows = conn.execute(
                    """
                    SELECT head.case_id, head.current_revision_id, head.updated_at,
                           revision.routing_default, revision.lane_change_default
                    FROM intent_user_label_heads head
                    JOIN intent_label_revisions revision
                      ON revision.id = head.current_revision_id
                    WHERE head.dataset_id = ? AND head.username = ?
                    """,
                    (dataset_id, normalized_username),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT head.case_id, head.current_revision_id, head.updated_at,
                           revision.routing_default, revision.lane_change_default
                    FROM intent_label_heads head
                    JOIN intent_label_revisions revision
                      ON revision.id = head.current_revision_id
                    WHERE head.dataset_id = ?
                    """,
                    (dataset_id,),
                ).fetchall()
        return {
            str(row["case_id"]): {
                "revision_id": int(row["current_revision_id"]),
                "updated_at": str(row["updated_at"] or ""),
                "routing_default": str(row["routing_default"] or ""),
                "lane_change_default": str(row["lane_change_default"] or ""),
            }
            for row in rows
        }

    def save_intent_labels(
        self,
        *,
        dataset_id: str,
        case_id: str,
        routing_default: str,
        lane_change_default: str,
        overrides: list[dict[str, Any]],
        expected_revision_id: int | None,
        author: str,
        author_source: str = "legacy",
        author_verified: bool = False,
    ) -> dict[str, Any]:
        routing_default = str(routing_default or "").strip()
        lane_change_default = str(lane_change_default or "").strip()
        if routing_default and routing_default not in ROUTING_INTENTS:
            raise ValueError("Routing 意图标签不合法。")
        if lane_change_default and lane_change_default not in LANE_CHANGE_INTENTS:
            raise ValueError("自车变道意图标签不合法。")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in overrides:
            timepoint_id = str(raw.get("timepoint_id") or "").strip()
            if not timepoint_id or timepoint_id in seen:
                raise ValueError("单帧覆盖包含空或重复 timepoint_id。")
            seen.add(timepoint_id)
            try:
                offset_ms = int(raw.get("offset_ms"))
            except (TypeError, ValueError) as exc:
                raise ValueError("单帧覆盖 offset_ms 不合法。") from exc
            routing = str(raw.get("routing_intent") or "").strip()
            lane_change = str(raw.get("lane_change_intent") or "").strip()
            if routing and routing not in ROUTING_INTENTS:
                raise ValueError("单帧 Routing 意图标签不合法。")
            if lane_change and lane_change not in LANE_CHANGE_INTENTS:
                raise ValueError("单帧自车变道意图标签不合法。")
            # Keep the snapshot sparse. A value equal to the aggregate default
            # has no independent meaning and is removed server-side.
            if routing == routing_default:
                routing = ""
            if lane_change == lane_change_default:
                lane_change = ""
            if not routing and not lane_change:
                continue
            normalized.append(
                {
                    "timepoint_id": timepoint_id,
                    "offset_ms": offset_ms,
                    "routing_intent": routing,
                    "lane_change_intent": lane_change,
                }
            )
        normalized.sort(key=lambda item: (item["offset_ms"], item["timepoint_id"]))
        now = utc_now()
        normalized_author = author.strip().lower() or "anonymous"
        with self._write_lock, self.connect() as conn:
            head = conn.execute(
                """
                SELECT current_revision_id FROM intent_user_label_heads
                WHERE dataset_id = ? AND case_id = ? AND username = ?
                """,
                (dataset_id, case_id, normalized_author),
            ).fetchone()
            current_revision_id = int(head["current_revision_id"]) if head else None
            if current_revision_id != expected_revision_id:
                raise IntentAnnotationConflictError(
                    "该 Case 已被其他标注者更新，请刷新后重新确认。"
                )
            sql = """
                INSERT INTO intent_label_revisions (
                    dataset_id, case_id, routing_default, lane_change_default,
                    author, author_source, author_verified, supersedes_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                sql += " RETURNING id"
            cursor = conn.execute(
                sql,
                (
                    dataset_id,
                    case_id,
                    routing_default or None,
                    lane_change_default or None,
                    normalized_author,
                    author_source.strip() or "legacy",
                    bool(author_verified),
                    current_revision_id,
                    now,
                ),
            )
            revision_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            for item in normalized:
                conn.execute(
                    """
                    INSERT INTO intent_frame_overrides (
                        revision_id, timepoint_id, offset_ms,
                        routing_intent, lane_change_intent
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        revision_id,
                        item["timepoint_id"],
                        item["offset_ms"],
                        item["routing_intent"] or None,
                        item["lane_change_intent"] or None,
                    ),
                )
            conn.execute(
                """
                INSERT INTO intent_user_label_heads (
                    dataset_id, case_id, username, current_revision_id,
                    version, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(dataset_id, case_id, username) DO UPDATE SET
                    current_revision_id = excluded.current_revision_id,
                    version = intent_user_label_heads.version + 1,
                    updated_at = excluded.updated_at
                """,
                (dataset_id, case_id, normalized_author, revision_id, now),
            )
            conn.execute(
                """
                INSERT INTO intent_label_heads (
                    dataset_id, case_id, current_revision_id, version, updated_at
                ) VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(dataset_id, case_id) DO UPDATE SET
                    current_revision_id = excluded.current_revision_id,
                    version = intent_label_heads.version + 1,
                    updated_at = excluded.updated_at
                """,
                (dataset_id, case_id, revision_id, now),
            )
            row = conn.execute(
                "SELECT * FROM intent_label_revisions WHERE id = ?",
                (revision_id,),
            ).fetchone()
        return self._intent_revision_dict(row, normalized)

    def delete_intent_labels(
        self,
        *,
        dataset_id: str,
        case_id: str,
        username: str,
        expected_revision_id: int,
        deleted_by: str,
        deleted_by_source: str = "legacy",
        deleted_by_verified: bool = False,
    ) -> dict[str, Any] | None:
        """Remove one person's current head while retaining immutable history."""

        normalized_username = str(username or "").strip().lower()
        normalized_actor = str(deleted_by or "").strip().lower()
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT revision.*
                FROM intent_user_label_heads head
                JOIN intent_label_revisions revision
                  ON revision.id = head.current_revision_id
                WHERE head.dataset_id = ? AND head.case_id = ?
                  AND head.username = ?
                """,
                (dataset_id, case_id, normalized_username),
            ).fetchone()
            if row is None:
                return None
            current_revision_id = int(row["id"])
            if current_revision_id != int(expected_revision_id):
                raise IntentAnnotationConflictError(
                    "该 Case 的当前标注已变化，请刷新后重新确认删除。"
                )
            override_rows = conn.execute(
                """
                SELECT timepoint_id, offset_ms, routing_intent, lane_change_intent
                FROM intent_frame_overrides
                WHERE revision_id = ?
                ORDER BY offset_ms ASC, timepoint_id ASC
                """,
                (current_revision_id,),
            ).fetchall()
            audit_sql = """
                INSERT INTO intent_label_deletions (
                    dataset_id, case_id, username, deleted_revision_id,
                    deleted_by, deleted_by_source, deleted_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            if self.backend == "postgresql":
                audit_sql += " RETURNING id"
            cursor = conn.execute(
                audit_sql,
                (
                    dataset_id,
                    case_id,
                    normalized_username,
                    current_revision_id,
                    normalized_actor,
                    str(deleted_by_source or "legacy").strip() or "legacy",
                    bool(deleted_by_verified),
                    now,
                ),
            )
            deletion_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
            conn.execute(
                """
                DELETE FROM intent_user_label_heads
                WHERE dataset_id = ? AND case_id = ? AND username = ?
                  AND current_revision_id = ?
                """,
                (dataset_id, case_id, normalized_username, current_revision_id),
            )
            replacement = conn.execute(
                """
                SELECT current_revision_id, updated_at
                FROM intent_user_label_heads
                WHERE dataset_id = ? AND case_id = ?
                ORDER BY updated_at DESC, current_revision_id DESC
                LIMIT 1
                """,
                (dataset_id, case_id),
            ).fetchone()
            if replacement is None:
                conn.execute(
                    "DELETE FROM intent_label_heads WHERE dataset_id = ? AND case_id = ?",
                    (dataset_id, case_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE intent_label_heads
                    SET current_revision_id = ?, version = version + 1, updated_at = ?
                    WHERE dataset_id = ? AND case_id = ?
                    """,
                    (
                        int(replacement["current_revision_id"]),
                        str(replacement["updated_at"]),
                        dataset_id,
                        case_id,
                    ),
                )
        overrides = [
            {
                "timepoint_id": str(item["timepoint_id"]),
                "offset_ms": int(item["offset_ms"]),
                "routing_intent": str(item["routing_intent"] or ""),
                "lane_change_intent": str(item["lane_change_intent"] or ""),
            }
            for item in override_rows
        ]
        return {
            "deletion_id": deletion_id,
            "deleted_revision": self._intent_revision_dict(row, overrides),
            "deleted_at": now,
        }

    def delete_intent_labels_bulk(
        self,
        *,
        targets: list[dict[str, Any]],
        deleted_by: str,
        deleted_by_source: str = "legacy",
        deleted_by_verified: bool = False,
    ) -> list[dict[str, Any]]:
        """Atomically remove multiple current heads after validating every revision."""

        normalized_actor = str(deleted_by or "").strip().lower()
        normalized_source = str(deleted_by_source or "legacy").strip() or "legacy"
        now = utc_now()
        prepared: list[dict[str, Any]] = []
        with self._write_lock, self.connect() as conn:
            for target in targets:
                dataset_id = str(target["dataset_id"])
                case_id = str(target["case_id"])
                username = str(target["username"]).strip().lower()
                expected_revision_id = int(target["expected_revision_id"])
                row = conn.execute(
                    """
                    SELECT revision.id
                    FROM intent_user_label_heads head
                    JOIN intent_label_revisions revision
                      ON revision.id = head.current_revision_id
                    WHERE head.dataset_id = ? AND head.case_id = ?
                      AND head.username = ?
                    """,
                    (dataset_id, case_id, username),
                ).fetchone()
                if row is None or int(row["id"]) != expected_revision_id:
                    raise IntentAnnotationConflictError(
                        "部分标注已变化或不存在，未删除任何记录，请刷新后重试。"
                    )
                prepared.append({
                    "dataset_id": dataset_id,
                    "case_id": case_id,
                    "username": username,
                    "revision_id": expected_revision_id,
                })

            for target in prepared:
                audit_sql = """
                    INSERT INTO intent_label_deletions (
                        dataset_id, case_id, username, deleted_revision_id,
                        deleted_by, deleted_by_source, deleted_by_verified, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """
                if self.backend == "postgresql":
                    audit_sql += " RETURNING id"
                cursor = conn.execute(
                    audit_sql,
                    (
                        target["dataset_id"],
                        target["case_id"],
                        target["username"],
                        target["revision_id"],
                        normalized_actor,
                        normalized_source,
                        bool(deleted_by_verified),
                        now,
                    ),
                )
                deletion_id = (
                    int(cursor.fetchone()["id"])
                    if self.backend == "postgresql"
                    else int(cursor.lastrowid)
                )
                cursor = conn.execute(
                    """
                    DELETE FROM intent_user_label_heads
                    WHERE dataset_id = ? AND case_id = ? AND username = ?
                      AND current_revision_id = ?
                    """,
                    (
                        target["dataset_id"],
                        target["case_id"],
                        target["username"],
                        target["revision_id"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise IntentAnnotationConflictError(
                        "部分标注已变化，未删除任何记录，请刷新后重试。"
                    )
                replacement = conn.execute(
                    """
                    SELECT current_revision_id, updated_at
                    FROM intent_user_label_heads
                    WHERE dataset_id = ? AND case_id = ?
                    ORDER BY updated_at DESC, current_revision_id DESC
                    LIMIT 1
                    """,
                    (target["dataset_id"], target["case_id"]),
                ).fetchone()
                if replacement is None:
                    conn.execute(
                        "DELETE FROM intent_label_heads WHERE dataset_id = ? AND case_id = ?",
                        (target["dataset_id"], target["case_id"]),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE intent_label_heads
                        SET current_revision_id = ?, version = version + 1, updated_at = ?
                        WHERE dataset_id = ? AND case_id = ?
                        """,
                        (
                            int(replacement["current_revision_id"]),
                            str(replacement["updated_at"]),
                            target["dataset_id"],
                            target["case_id"],
                        ),
                    )
                target["deletion_id"] = deletion_id
                target["deleted_at"] = now
        return prepared

    def list_intent_contributors(
        self, dataset_id: str, case_id: str
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT head.username, head.version, head.updated_at, revision.*
                FROM intent_user_label_heads head
                JOIN intent_label_revisions revision
                  ON revision.id = head.current_revision_id
                WHERE head.dataset_id = ? AND head.case_id = ?
                ORDER BY head.updated_at ASC, head.username ASC
                """,
                (dataset_id, case_id),
            ).fetchall()
            override_rows = conn.execute(
                """
                SELECT frame.*
                FROM intent_frame_overrides frame
                JOIN intent_user_label_heads head
                  ON head.current_revision_id = frame.revision_id
                WHERE head.dataset_id = ? AND head.case_id = ?
                ORDER BY frame.revision_id, frame.offset_ms, frame.timepoint_id
                """,
                (dataset_id, case_id),
            ).fetchall()
        overrides_by_revision: dict[int, list[dict[str, Any]]] = {}
        for item in override_rows:
            overrides_by_revision.setdefault(int(item["revision_id"]), []).append(
                {
                    "timepoint_id": str(item["timepoint_id"]),
                    "offset_ms": int(item["offset_ms"]),
                    "routing_intent": str(item["routing_intent"] or ""),
                    "lane_change_intent": str(item["lane_change_intent"] or ""),
                }
            )
        return [
            {
                "username": str(row["username"]),
                "revision_id": int(row["id"]),
                "version": int(row["version"]),
                "routing_default": str(row["routing_default"] or ""),
                "lane_change_default": str(row["lane_change_default"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "overrides": overrides_by_revision.get(int(row["id"]), []),
            }
            for row in rows
        ]

    def intent_report_rows(self, dataset_id: str) -> dict[str, Any]:
        """Bounded bulk reads; never open per-case media or issue N+1 queries."""
        with self.connect() as conn:
            heads = conn.execute(
                """SELECT head.case_id, head.username, revision.id AS revision_id,
                          revision.routing_default, revision.lane_change_default,
                          head.updated_at
                   FROM intent_user_label_heads head
                   JOIN intent_label_revisions revision ON revision.id = head.current_revision_id
                   WHERE head.dataset_id = ? ORDER BY head.case_id, head.username""",
                (dataset_id,),
            ).fetchall()
            overrides = conn.execute(
                """SELECT frame.* FROM intent_frame_overrides frame
                   JOIN intent_user_label_heads head ON head.current_revision_id = frame.revision_id
                   WHERE head.dataset_id = ? ORDER BY frame.offset_ms, frame.timepoint_id""",
                (dataset_id,),
            ).fetchall()
            assignments = conn.execute(
                """SELECT assignment.case_id, assignment.username, experiment.id AS experiment_id,
                          experiment.status
                   FROM intent_experiment_assignments assignment
                   JOIN intent_experiments experiment ON experiment.id = assignment.experiment_id
                   WHERE experiment.dataset_id = ?""",
                (dataset_id,),
            ).fetchall()
            comments = conn.execute(
                """SELECT id, case_id, body, author, reply_to_id, created_at
                   FROM (
                       SELECT comment.*,
                              ROW_NUMBER() OVER (
                                  PARTITION BY comment.case_id ORDER BY comment.id DESC
                              ) AS comment_rank
                       FROM intent_case_comments comment
                       WHERE comment.dataset_id = ?
                   ) recent
                   WHERE comment_rank <= 3
                   ORDER BY case_id, id ASC""",
                (dataset_id,),
            ).fetchall()
        by_revision: dict[int, list[dict[str, Any]]] = {}
        for row in overrides:
            by_revision.setdefault(int(row["revision_id"]), []).append({
                "offset_ms": int(row["offset_ms"]), "timepoint_id": str(row["timepoint_id"]),
                "routing_intent": str(row["routing_intent"] or ""),
                "lane_change_intent": str(row["lane_change_intent"] or ""),
            })
        return {
            "heads": [{**dict(row), "updated_at": str(row["updated_at"]),
                       "overrides": by_revision.get(int(row["revision_id"]), [])} for row in heads],
            "assignments": [dict(row) for row in assignments],
            "comments": [
                {
                    "id": int(row["id"]),
                    "case_id": str(row["case_id"]),
                    "body": str(row["body"]),
                    "author": str(row["author"]),
                    "reply_to_id": int(row["reply_to_id"]) if row["reply_to_id"] else None,
                    "created_at": str(row["created_at"]),
                }
                for row in comments
            ],
        }

    def list_intent_case_assignees(self, dataset_id: str, case_id: str) -> list[str]:
        """Return active-experiment owners for one Case, without their answers."""

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT assignment.username
                FROM intent_experiment_assignments assignment
                JOIN intent_experiments experiment
                  ON experiment.id = assignment.experiment_id
                WHERE experiment.dataset_id = ? AND assignment.case_id = ?
                  AND experiment.status = 'active'
                ORDER BY assignment.username ASC
                """,
                (dataset_id, case_id),
            ).fetchall()
        return [str(row["username"]) for row in rows]

    def intent_case_has_active_experiment(self, dataset_id: str, case_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM intent_experiment_assignments assignment
                JOIN intent_experiments experiment
                  ON experiment.id = assignment.experiment_id
                WHERE experiment.dataset_id = ? AND assignment.case_id = ?
                  AND experiment.status = 'active'
                LIMIT 1
                """,
                (dataset_id, case_id),
            ).fetchone()
        return row is not None

    def search_intent_comments(
        self,
        dataset_id: str,
        query: str,
        *,
        username: str,
        reveal_answers: bool,
        experiment_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Reveal-safe comment search. Blind Cases only expose the caller's rows."""

        needle = str(query or "").strip()
        if not needle:
            return []
        needle = needle[:80]
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        current = str(username or "").strip().lower()
        bounded_limit = max(1, min(int(limit), 50))
        experiment_clause = ""
        parameters: list[Any] = [dataset_id, dataset_id, pattern]
        if experiment_id:
            experiment_clause = """
                  AND comment.case_id IN (
                    SELECT assignment.case_id
                    FROM intent_experiment_assignments assignment
                    WHERE assignment.experiment_id = ?
                  )
            """
            parameters.append(experiment_id)
        parameters.extend([int(bool(reveal_answers)), current, bounded_limit])
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT comment.id, comment.case_id, comment.body, comment.author,
                       comment.created_at
                FROM intent_case_comments comment
                LEFT JOIN (
                    SELECT DISTINCT assignment.case_id
                    FROM intent_experiment_assignments assignment
                    JOIN intent_experiments experiment
                      ON experiment.id = assignment.experiment_id
                    WHERE experiment.dataset_id = ? AND experiment.status = 'active'
                ) blind ON blind.case_id = comment.case_id
                WHERE comment.dataset_id = ?
                  AND LOWER(comment.body) LIKE LOWER(?) ESCAPE '\\'
                  {experiment_clause}
                  AND (? = 1 OR blind.case_id IS NULL OR comment.author = ?)
                ORDER BY comment.id DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        hits = []
        lowered = needle.lower()
        for row in rows:
            body = str(row["body"] or "")
            index = body.lower().find(lowered)
            start = max(0, index - 24) if index >= 0 else 0
            snippet = body[start:start + 120]
            if start > 0:
                snippet = "…" + snippet
            if start + 120 < len(body):
                snippet = snippet + "…"
            hits.append({
                "id": int(row["id"]),
                "case_id": str(row["case_id"]),
                "author": str(row["author"]),
                "body": body,
                "snippet": snippet,
                "created_at": str(row["created_at"] or ""),
            })
        return hits

    def list_intent_comments(
        self, dataset_id: str, case_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT comment.*, parent.author AS reply_to_author,
                       parent.body AS reply_to_body
                FROM intent_case_comments comment
                LEFT JOIN intent_case_comments parent
                  ON parent.id = comment.reply_to_id
                WHERE comment.dataset_id = ? AND comment.case_id = ?
                ORDER BY comment.id ASC
                LIMIT ?
                """,
                (dataset_id, case_id, bounded_limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "body": str(row["body"]),
                "author": str(row["author"]),
                "author_verified": bool(row["author_verified"]),
                "reply_to_id": int(row["reply_to_id"]) if row["reply_to_id"] else None,
                "reply_to_author": str(row["reply_to_author"] or "")
                if "reply_to_author" in row.keys()
                else "",
                "reply_to_body": str(row["reply_to_body"] or "")
                if "reply_to_body" in row.keys()
                else "",
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def create_intent_comment(
        self,
        *,
        dataset_id: str,
        case_id: str,
        body: str,
        author: str,
        author_source: str,
        author_verified: bool,
        reply_to_id: int | None = None,
    ) -> dict[str, Any]:
        normalized_body = str(body or "").strip()
        if not normalized_body:
            raise ValueError("评论内容不能为空。")
        if len(normalized_body) > 3500:
            raise ValueError("评论内容不能超过 3500 个字符。")
        normalized_author = str(author or "").strip().lower()
        if not normalized_author:
            raise ValueError("评论人不能为空。")
        normalized_reply_to_id = int(reply_to_id) if reply_to_id is not None else None
        now = utc_now()
        sql = """
            INSERT INTO intent_case_comments (
                dataset_id, case_id, body, author, author_source,
                author_verified, reply_to_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        if self.backend == "postgresql":
            sql += " RETURNING id"
        parent_author = ""
        parent_body = ""
        with self._write_lock, self.connect() as conn:
            if normalized_reply_to_id is not None:
                parent = conn.execute(
                    """
                    SELECT id, author, body FROM intent_case_comments
                    WHERE id = ? AND dataset_id = ? AND case_id = ?
                    """,
                    (normalized_reply_to_id, dataset_id, case_id),
                ).fetchone()
                if parent is None:
                    raise ValueError("只能回复当前 Case 下的评论。")
                parent_author = str(parent["author"] or "")
                parent_body = str(parent["body"] or "")
            cursor = conn.execute(
                sql,
                (
                    dataset_id,
                    case_id,
                    normalized_body,
                    normalized_author,
                    str(author_source or "legacy").strip() or "legacy",
                    bool(author_verified),
                    normalized_reply_to_id,
                    now,
                ),
            )
            comment_id = (
                int(cursor.fetchone()["id"])
                if self.backend == "postgresql"
                else int(cursor.lastrowid)
            )
        return {
            "id": comment_id,
            "body": normalized_body,
            "author": normalized_author,
            "author_verified": bool(author_verified),
            "reply_to_id": normalized_reply_to_id,
            "reply_to_author": parent_author,
            "reply_to_body": parent_body,
            "created_at": now,
        }
