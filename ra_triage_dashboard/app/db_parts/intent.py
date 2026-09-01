from __future__ import annotations

from typing import Any

from .shared import IntentAnnotationConflictError, utc_now


ROUTING_INTENTS = ("left_turn", "right_turn", "straight", "u_turn", "parking")
LANE_CHANGE_INTENTS = ("lane_change", "no_lane_change")


class DatabaseIntentMixin:
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

    def get_intent_labels(self, dataset_id: str, case_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
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

    def intent_label_summaries(self, dataset_id: str) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
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
        with self._write_lock, self.connect() as conn:
            head = conn.execute(
                """
                SELECT current_revision_id FROM intent_label_heads
                WHERE dataset_id = ? AND case_id = ?
                """,
                (dataset_id, case_id),
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
                    author.strip(),
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
