"""Immutable Trail intents with append-only, per-attempt receipts."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from contextlib import nullcontext

from .shared import _json_load


def audit_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class DatabaseTrailHistoryMixin:
    def import_legacy_trail_history(self, connection=None):
        """Idempotent local-only migration. Old records never become rollback authority."""
        with self._write_lock, (nullcontext(connection) if connection is not None else self.connect()) as conn:
            rows = conn.execute("""SELECT h.* FROM trail_issue_exclusion_history h
                WHERE NOT EXISTS (SELECT 1 FROM trail_operations o WHERE o.id = h.operation_id)""").fetchall()
            for row in rows:
                entries = _json_load(row["entries_json"], [])
                by_id = {str(e.get("issue_id") or ""): e for e in entries if isinstance(e, dict) and e.get("issue_id")}
                if not by_id:
                    continue
                created = row["created_at"]
                if not hasattr(created, "isoformat"):
                    created = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                created = created.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
                inserted = conn.execute("""INSERT INTO trail_operations
                    (id, created_at, actor, actor_source, actor_verified, source, parent_id, reason, fingerprint, item_count)
                    VALUES (?, ?, ?, ?, ?, 'legacy', NULL, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                    (row["operation_id"], str(created), row["actor"], row["actor_source"], bool(row["actor_verified"]),
                     row["message"], hashlib.sha256(encoded(entries).encode()).hexdigest(), len(by_id)))
                if inserted.rowcount != 1:
                    continue
                for issue, entry in by_id.items():
                    # This is a recorded intent/comment, NOT a verified remote after-value.
                    conn.execute("""INSERT INTO trail_operation_items
                        (operation_id, issue_id, field, before_json, after_json) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(operation_id, issue_id) DO NOTHING""",
                        (row["operation_id"], issue, "ra_stuck_auto_result_info", "{}",
                         encoded({"should_exclude_comment": entry.get("comment", "")})))
                outcomes = {issue: "succeeded" if entry.get("status") in {"synced", "synced_not_in_dashboard"} else "unknown" for issue, entry in by_id.items()}
                status = "succeeded" if all(v == "succeeded" for v in outcomes.values()) else "partial" if "succeeded" in outcomes.values() else "unknown"
                self._trail_event(conn, row["operation_id"], status, outcomes)

    def begin_trail_operation(self, *, operation_id, actor, actor_source,
                              actor_verified, source, items, parent_id=None, reason=""):
        if not items or len(items) > 200 or len({i["issue_id"] for i in items}) != len(items):
            raise ValueError("Invalid Trail audit items")
        items = sorted(items, key=lambda item: item["issue_id"])
        fingerprint = hashlib.sha256(encoded(items).encode()).hexdigest()
        with self._write_lock, self.connect() as conn:
            if self.backend == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            conn.execute("""INSERT INTO trail_operations
                (id, created_at, actor, actor_source, actor_verified, source, parent_id, reason, fingerprint, item_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""",
                (operation_id, audit_now(), actor, actor_source, bool(actor_verified), source,
                 parent_id, reason, fingerprint, len(items)))
            row = conn.execute("SELECT * FROM trail_operations WHERE id = ?", (operation_id,)).fetchone()
            # A retry may contain only the still-pending subset. Never replace the first snapshots.
            if row["actor"] != actor or row["source"] != source or row["parent_id"] != parent_id or row["reason"] != reason:
                raise ValueError("Trail operation identity conflict")
            existing = conn.execute("SELECT * FROM trail_operation_items WHERE operation_id = ?", (operation_id,)).fetchall()
            if existing:
                by_id = {r["issue_id"]: r for r in existing}
                for item in items:
                    old = by_id.get(item["issue_id"])
                    if old is None or old["field"] != item["field"] or old["after_json"] != encoded(item["after"]) or old["before_json"] != encoded(item["before"]):
                        raise ValueError("Trail operation snapshot conflict")
                return
            for item in items:
                conn.execute("""INSERT INTO trail_operation_items
                    (operation_id, issue_id, field, before_json, after_json) VALUES (?, ?, ?, ?, ?)""",
                    (operation_id, item["issue_id"], item["field"], encoded(item["before"]), encoded(item["after"])))
            self._trail_event(conn, operation_id, "pending", {i["issue_id"]: "pending" for i in items})

    @staticmethod
    def _trail_event(conn, operation_id, status, outcomes, actor=None, actor_source=None):
        if actor is None:
            operation = conn.execute("SELECT actor, actor_source FROM trail_operations WHERE id = ?", (operation_id,)).fetchone()
            actor, actor_source = operation["actor"], operation["actor_source"]
        conn.execute("""INSERT INTO trail_operation_events
            (id, operation_id, created_at, status, actor, actor_source, outcomes_json) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, operation_id, audit_now(), status, actor, actor_source or "", encoded(outcomes)))

    def append_trail_event(self, operation_id, status, outcomes, *, actor=None, actor_source=None):
        if status not in {"pending", "succeeded", "partial", "unknown", "conflict"}:
            raise ValueError("Invalid Trail event status")
        with self._write_lock, self.connect() as conn:
            previous = {}
            for row in conn.execute("SELECT outcomes_json FROM trail_operation_events WHERE operation_id = ? ORDER BY created_at, id", (operation_id,)).fetchall():
                previous.update(json.loads(row["outcomes_json"]))
            previous.update(outcomes)
            if previous and all(value == "succeeded" for value in previous.values()):
                status = "succeeded"
            elif "succeeded" in previous.values():
                status = "partial"
            self._trail_event(conn, operation_id, status, outcomes, actor, actor_source)

    def trail_operation(self, operation_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM trail_operations WHERE id = ?", (operation_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["items"] = [{"issue_id": r["issue_id"], "field": r["field"],
                "before": json.loads(r["before_json"]), "after": json.loads(r["after_json"])}
                for r in conn.execute("SELECT * FROM trail_operation_items WHERE operation_id = ? ORDER BY issue_id", (operation_id,)).fetchall()]
            result["events"] = [{"id": r["id"], "created_at": r["created_at"], "status": r["status"], "actor": r["actor"], "actor_source": r["actor_source"],
                "outcomes": json.loads(r["outcomes_json"])} for r in conn.execute(
                "SELECT * FROM trail_operation_events WHERE operation_id = ? ORDER BY created_at, id", (operation_id,)).fetchall()]
            result["children"] = [dict(r) for r in conn.execute(
                "SELECT id, created_at, actor FROM trail_operations WHERE parent_id = ? ORDER BY created_at, id", (operation_id,)).fetchall()]
        result["outcomes"] = {}
        for event in result["events"]:
            result["outcomes"].update(event["outcomes"])
        values = list(result["outcomes"].values())
        result["status"] = "succeeded" if values and all(v == "succeeded" for v in values) else "partial" if "succeeded" in values else (result["events"][-1]["status"] if result["events"] else "pending")
        return result

    def list_trail_operations(self, *, issue_id="", actor="", source="", status="", since="", until="", page=1, page_size=20):
        where, params = [], []
        for column, value in (("actor", actor), ("source", source)):
            if value:
                where.append(f"o.{column} = ?")
                params.append(value)
        if issue_id:
            where.append("EXISTS (SELECT 1 FROM trail_operation_items i WHERE i.operation_id = o.id AND i.issue_id = ?)")
            params.append(issue_id)
        for operator, value in ((">=", since), ("<=", until)):
            if value:
                where.append(f"o.created_at {operator} ?")
                params.append(value)
        if status:
            where.append("(SELECT e.status FROM trail_operation_events e WHERE e.operation_id = o.id ORDER BY e.created_at DESC, e.id DESC LIMIT 1) = ?")
            params.append(status)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM trail_operations o" + clause, params).fetchone()["n"]
            rows = conn.execute("SELECT o.* FROM trail_operations o" + clause + " ORDER BY o.created_at DESC, o.id DESC LIMIT ? OFFSET ?", (*params, page_size, (page-1)*page_size)).fetchall()
            started = conn.execute("SELECT MIN(created_at) AS started FROM trail_operations WHERE source <> 'legacy'").fetchone()["started"]
        items = []
        for row in rows:
            detail = self.trail_operation(row["id"])
            items.append({**dict(row), "status": detail["status"], "succeeded_count": sum(v == "succeeded" for v in detail["outcomes"].values())})
        return {"items": items, "total": total, "page": page, "page_size": page_size, "started_at": started}
