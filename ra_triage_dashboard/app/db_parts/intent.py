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

    def list_intent_experiments(self, dataset_id: str = "") -> list[dict[str, Any]]:
        parameters: tuple[Any, ...] = ()
        where = ""
        if dataset_id:
            where = "WHERE experiment.dataset_id = ?"
            parameters = (dataset_id,)
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
                """
                SELECT experiment_id, username, assignment_kind, COUNT(*) AS case_count
                FROM intent_experiment_assignments
                GROUP BY experiment_id, username, assignment_kind
                ORDER BY experiment_id, username, assignment_kind
                """
            ).fetchall()
        members_by_experiment: dict[str, dict[str, dict[str, int]]] = {}
        for item in assignment_rows:
            experiment = members_by_experiment.setdefault(str(item["experiment_id"]), {})
            member = experiment.setdefault(
                str(item["username"]), {"base": 0, "cross": 0, "full": 0}
            )
            member[str(item["assignment_kind"])] = int(item["case_count"] or 0)
        result = []
        for row in rows:
            experiment_id = str(row["id"])
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
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO intent_experiments (
                    id, dataset_id, name, annotation_mode, overlap_ratio, overlap_reviewers,
                    case_count, status, seed, created_by, created_by_source,
                    created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    dataset_id,
                    name,
                    annotation_mode,
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
                    SELECT head.case_id, head.current_revision_id,
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
                    SELECT head.case_id, head.current_revision_id,
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
        return [
            {
                "username": str(row["username"]),
                "revision_id": int(row["id"]),
                "version": int(row["version"]),
                "routing_default": str(row["routing_default"] or ""),
                "lane_change_default": str(row["lane_change_default"] or ""),
                "updated_at": str(row["updated_at"] or ""),
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
        }

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

    def list_intent_comments(
        self, dataset_id: str, case_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM intent_case_comments
                WHERE dataset_id = ? AND case_id = ?
                ORDER BY id ASC
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
    ) -> dict[str, Any]:
        normalized_body = str(body or "").strip()
        if not normalized_body:
            raise ValueError("评论内容不能为空。")
        if len(normalized_body) > 1000:
            raise ValueError("评论内容不能超过 1000 个字符。")
        normalized_author = str(author or "").strip().lower()
        if not normalized_author:
            raise ValueError("评论人不能为空。")
        now = utc_now()
        sql = """
            INSERT INTO intent_case_comments (
                dataset_id, case_id, body, author, author_source,
                author_verified, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        if self.backend == "postgresql":
            sql += " RETURNING id"
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                sql,
                (
                    dataset_id,
                    case_id,
                    normalized_body,
                    normalized_author,
                    str(author_source or "legacy").strip() or "legacy",
                    bool(author_verified),
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
            "created_at": now,
        }
