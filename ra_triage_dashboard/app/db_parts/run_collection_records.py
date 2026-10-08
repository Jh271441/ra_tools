"""Run collection workflow: records. Transaction ownership remains in methods."""
from __future__ import annotations
import uuid
from typing import Any, Sequence
from .shared import _json_load, utc_now
from .run_collection_rules import RunCollectionConflictError


class RunRecordsMixin:
    @staticmethod
    def _run_collection_snapshot(row: Any) -> dict[str, Any]:
        if row is None:
            return {"id": "", "name": "", "source_name": "", "kind": "", "created_at": ""}
        return {
            "id": str(row["id"] or ""),
            "name": str(row["name"] or ""),
            "source_name": str(row["source_name"] or ""),
            "kind": str(row["kind"] or ""),
            "schema_version": str(row["schema_version"] or ""),
            "source_sha256": str(row["source_sha256"] or ""),
            "created_at": str(row["created_at"] or ""),
            "available_at_revision": True,
        }

    def _collection_member_records(
        self,
        conn: Any,
        members: list[dict[str, Any]],
        *,
        previous_revision: tuple[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        previous: dict[str, dict[str, Any]] = {}
        if previous_revision:
            rows = conn.execute(
                "SELECT run_id, run_snapshot_json FROM run_collection_members "
                "WHERE collection_id = ? AND revision_no = ?",
                previous_revision,
            ).fetchall()
            previous = {
                str(row["run_id"]): _json_load(row["run_snapshot_json"], {})
                for row in rows
            }
        records: list[dict[str, Any]] = []
        for member in members:
            run_row = conn.execute(
                "SELECT id, name, source_name, kind, schema_version, source_sha256, created_at "
                "FROM model_runs WHERE id = ?",
                (member["run_id"],),
            ).fetchone()
            snapshot = (
                self._run_collection_snapshot(run_row)
                if run_row is not None
                else dict(previous.get(member["run_id"]) or {
                    "id": member["run_id"], "name": "", "source_name": "",
                    "kind": "", "created_at": "", "available_at_revision": False,
                })
            )
            records.append(member | {"run_snapshot": snapshot})
        return records

    def _insert_collection_revision(
        self,
        conn: Any,
        *,
        collection_id: str,
        revision_no: int,
        member_records: list[dict[str, Any]],
        actor: str,
        source: str,
        idempotency_key: str,
        idempotency_fingerprint: str,
        now: str,
    ) -> dict[str, str]:
        members_content = [
            {
                "ordinal": item["ordinal"], "run_id": item["run_id"],
                "role": item["role"], "is_reference": item["is_reference"],
                "run_snapshot": item["run_snapshot"],
            }
            for item in member_records
        ]
        members_sha = self._content_sha256(members_content)
        content = {"version": 1, "members": members_content}
        content_sha = self._content_sha256(content)
        conn.execute(
            """
            INSERT INTO run_collection_revisions (
                collection_id, revision_no, content_json, content_sha256,
                members_sha256, member_count, source, created_by, created_at,
                idempotency_key, idempotency_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_id, revision_no, self._canonical_json(content), content_sha,
                members_sha, len(member_records), source, actor, now,
                idempotency_key, idempotency_fingerprint,
            ),
        )
        conn.executemany(
            """
            INSERT INTO run_collection_members (
                collection_id, revision_no, ordinal, run_id, role,
                is_reference, run_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    collection_id, revision_no, item["ordinal"], item["run_id"],
                    item["role"], item["is_reference"],
                    self._canonical_json(item["run_snapshot"]),
                )
                for item in member_records
            ],
        )
        return {"members_sha256": members_sha, "content_sha256": content_sha}

    def _insert_run_collection_audit(
        self,
        conn: Any,
        *,
        collection_id: str,
        action: str,
        actor: str,
        actor_source: str = "legacy",
        actor_verified: bool = False,
        source: str,
        revision_no: int = 0,
        context_id: str = "",
        detail: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO run_collection_audit (
                id, collection_id, action, revision_no, context_id,
                actor, actor_source, actor_verified, source, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), collection_id, action, int(revision_no), context_id,
                actor, actor_source, bool(actor_verified), str(source or "user"), self._canonical_json(detail or {}),
                created_at or utc_now(),
            ),
        )

    def _mark_run_collection_change(self, conn: Any) -> None:
        if self.backend == "postgresql":
            conn.execute(
                "UPDATE dashboard_change_revision SET revision = revision + 1, updated_at = now() WHERE id = 1"
            )
        self._mark_change_topic(conn, "run_collections")

    def _collection_payload(self, conn: Any, collection_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM run_collections WHERE id = ?", (collection_id,)
        ).fetchone()
        if row is None:
            return None
        revisions = conn.execute(
            "SELECT revision_no, content_sha256, members_sha256, source, created_by, created_at "
            "FROM run_collection_revisions WHERE collection_id = ? ORDER BY revision_no DESC",
            (collection_id,),
        ).fetchall()
        revision_items = conn.execute(
            """
            SELECT member.collection_id, member.revision_no, member.ordinal,
                   member.run_id, member.role, member.is_reference,
                   member.run_snapshot_json, live.id AS live_run_id
            FROM run_collection_members member
            LEFT JOIN model_runs live ON live.id = member.run_id
            WHERE member.collection_id = ?
            ORDER BY member.revision_no DESC, member.ordinal ASC
            """,
            (collection_id,),
        ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for member in revision_items:
            snapshot = _json_load(member["run_snapshot_json"], {})
            grouped.setdefault(int(member["revision_no"]), []).append({
                "ordinal": int(member["ordinal"]),
                "run_id": str(member["run_id"]),
                "role": str(member["role"] or ""),
                "is_reference": bool(member["is_reference"]),
                "available_now": member["live_run_id"] is not None,
                "run": snapshot if isinstance(snapshot, dict) else {},
            })
        history = [
            {
                "revision": int(item["revision_no"]),
                "content_sha256": str(item["content_sha256"] or ""),
                "members_sha256": str(item["members_sha256"] or ""),
                "source": str(item["source"] or "user"),
                "created_by": str(item["created_by"] or ""),
                "created_at": str(item["created_at"] or ""),
                "members": grouped.get(int(item["revision_no"]), []),
            }
            for item in revisions
        ]
        current_revision = int(row["current_revision"] or 0)
        current = next((item for item in history if item["revision"] == current_revision), None)
        audit_rows = conn.execute(
            "SELECT action, revision_no, context_id, actor, actor_source, actor_verified, "
            "source, detail_json, created_at FROM run_collection_audit "
            "WHERE collection_id = ? ORDER BY created_at, id",
            (collection_id,),
        ).fetchall()
        return {
            "id": str(row["id"]),
            "name": str(row["name"] or ""),
            "description": str(row["description"] or ""),
            "current_revision": current_revision,
            "metadata_revision": int(row["metadata_revision"] or 0),
            "created_by": str(row["created_by"] or ""),
            "created_by_source": str(row["created_by_source"] or "legacy"),
            "created_by_verified": bool(row["created_by_verified"]),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "current": current or {"revision": current_revision, "members": []},
            "history": history,
            "audit": [
                {
                    "action": str(item["action"] or ""),
                    "revision": int(item["revision_no"] or 0),
                    "context_id": str(item["context_id"] or ""),
                    "actor": str(item["actor"] or ""),
                    "actor_source": str(item["actor_source"] or "legacy"),
                    "actor_verified": bool(item["actor_verified"]),
                    "source": str(item["source"] or ""),
                    "detail": _json_load(item["detail_json"], {}),
                    "created_at": str(item["created_at"] or ""),
                }
                for item in audit_rows
            ],
        }

    def create_run_collection(
        self,
        *,
        name: str,
        members: Sequence[Any],
        description: str = "",
        actor: str = "",
        actor_source: str = "legacy",
        actor_verified: bool = False,
        source: str = "user",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_name = str(name or "").strip()[:160]
        if not normalized_name:
            raise ValueError("Collection 名称不能为空。")
        normalized_members = self._normalize_collection_members(members)
        description = str(description or "").strip()[:2000]
        key = str(idempotency_key or "").strip()[:160]
        actor = str(actor or "").strip()[:160]
        fingerprint = self._content_sha256({
            "name": normalized_name, "description": description,
            "members": normalized_members, "source": str(source or "user"),
        })
        collection_id = str(uuid.uuid4())
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            if key:
                prior = conn.execute(
                    "SELECT id, idempotency_fingerprint FROM run_collections WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if prior:
                    if str(prior["idempotency_fingerprint"] or "") != fingerprint:
                        raise RunCollectionConflictError("Idempotency-Key 已被不同 Collection 请求使用。")
                    existing_id = str(prior["id"])
                else:
                    existing_id = ""
            else:
                existing_id = ""
            if existing_id:
                result = self._collection_payload(conn, existing_id)
            else:
                conn.execute(
                    """
                    INSERT INTO run_collections (
                        id, name, description, current_revision, created_by,
                        created_by_source, created_by_verified,
                        created_at, updated_at, idempotency_key, idempotency_fingerprint
                    ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (collection_id, normalized_name, description, actor, actor_source,
                     bool(actor_verified), now, now, key, fingerprint),
                )
                if conn.execute("SELECT 1 FROM run_collections WHERE id = ?", (collection_id,)).fetchone():
                    records = self._collection_member_records(conn, normalized_members)
                    self._insert_collection_revision(
                        conn, collection_id=collection_id, revision_no=1,
                        member_records=records, actor=actor, source=str(source or "user"),
                        idempotency_key="", idempotency_fingerprint="", now=now,
                    )
                    conn.execute(
                        "UPDATE run_collections SET current_revision = 1 WHERE id = ?",
                        (collection_id,),
                    )
                    self._insert_run_collection_audit(
                        conn, collection_id=collection_id, action="created", actor=actor,
                        actor_source=actor_source, actor_verified=actor_verified,
                        source=str(source or "user"), revision_no=1,
                        detail={"name": normalized_name, "members_count": len(records)}, created_at=now,
                    )
                    self._mark_run_collection_change(conn)
                    result = self._collection_payload(conn, collection_id)
                elif key:
                    prior = conn.execute(
                        "SELECT id, idempotency_fingerprint FROM run_collections WHERE idempotency_key = ?",
                        (key,),
                    ).fetchone()
                    if prior is None or str(prior["idempotency_fingerprint"] or "") != fingerprint:
                        raise RunCollectionConflictError("Collection Idempotency-Key 已被不同请求使用。")
                    result = self._collection_payload(conn, str(prior["id"]))
                else:
                    raise RunCollectionConflictError("Run Collection ID 已存在。")
        assert result is not None
        return result

    def list_run_collections(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            ids = conn.execute(
                "SELECT id FROM run_collections ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            return [
                payload for item in ids
                if (payload := self._collection_payload(conn, str(item["id"]))) is not None
            ]

    def get_run_collection(self, collection_id: str) -> dict[str, Any] | None:
        normalized = str(collection_id or "").strip()
        with self.connect() as conn:
            return self._collection_payload(conn, normalized) if normalized else None

    def rename_run_collection(
        self,
        *,
        collection_id: str,
        expected_revision: int,
        expected_metadata_revision: int = 0,
        name: str,
        description: str,
        actor: str = "",
        actor_source: str = "legacy",
        actor_verified: bool = False,
    ) -> dict[str, Any]:
        normalized_name = str(name or "").strip()[:160]
        if not normalized_name:
            raise ValueError("Collection 名称不能为空。")
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE run_collections
                SET name = ?, description = ?, updated_at = ?, metadata_revision = metadata_revision + 1
                WHERE id = ? AND current_revision = ? AND metadata_revision = ?
                """,
                (
                    normalized_name, str(description or "").strip()[:2000], now,
                    str(collection_id or "").strip(), int(expected_revision),
                    int(expected_metadata_revision),
                ),
            )
            if cursor.rowcount != 1:
                current = conn.execute(
                    "SELECT current_revision, metadata_revision FROM run_collections WHERE id = ?",
                    (str(collection_id or "").strip(),),
                ).fetchone()
                if current is None:
                    raise ValueError("Run Collection 不存在。")
                raise RunCollectionConflictError(
                    f"Collection metadata 已更新（revision r{expected_revision}, metadata revision {expected_metadata_revision} → {int(current['metadata_revision'])}）。"
                )
            self._insert_run_collection_audit(
                conn, collection_id=str(collection_id or "").strip(), action="renamed",
                actor=str(actor or "").strip(), actor_source=actor_source,
                actor_verified=actor_verified, source="metadata",
                revision_no=int(expected_revision),
                detail={"name": normalized_name, "description": str(description or "").strip()[:2000]},
                created_at=now,
            )
            self._mark_run_collection_change(conn)
            result = self._collection_payload(conn, str(collection_id or "").strip())
        assert result is not None
        return result

    def create_run_collection_revision(
        self,
        *,
        collection_id: str,
        expected_revision: int,
        members: Sequence[Any],
        actor: str = "",
        actor_source: str = "legacy",
        actor_verified: bool = False,
        source: str = "user",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized = self._normalize_collection_members(members)
        collection_id = str(collection_id or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        actor = str(actor or "").strip()[:160]
        source = str(source or "user").strip()[:32]
        fingerprint = self._content_sha256({"members": normalized, "source": source})
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            if key:
                prior = conn.execute(
                    "SELECT revision_no, idempotency_fingerprint FROM run_collection_revisions "
                    "WHERE collection_id = ? AND idempotency_key = ?",
                    (collection_id, key),
                ).fetchone()
                if prior:
                    if str(prior["idempotency_fingerprint"] or "") != fingerprint:
                        raise RunCollectionConflictError("Idempotency-Key 已被不同 Revision 请求使用。")
                    result = self._collection_payload(conn, collection_id)
                    assert result is not None
                    return result
            cursor = conn.execute(
                """
                UPDATE run_collections SET current_revision = current_revision + 1, updated_at = ?
                WHERE id = ? AND current_revision = ?
                """,
                (now, collection_id, int(expected_revision)),
            )
            if cursor.rowcount != 1:
                if key:
                    prior = conn.execute(
                        "SELECT idempotency_fingerprint FROM run_collection_revisions "
                        "WHERE collection_id = ? AND idempotency_key = ?",
                        (collection_id, key),
                    ).fetchone()
                    if prior is not None:
                        if str(prior["idempotency_fingerprint"] or "") != fingerprint:
                            raise RunCollectionConflictError("Idempotency-Key 已被不同 Revision 请求使用。")
                        result = self._collection_payload(conn, collection_id)
                        assert result is not None
                        return result
                current = conn.execute(
                    "SELECT current_revision FROM run_collections WHERE id = ?", (collection_id,)
                ).fetchone()
                if current is None:
                    raise ValueError("Run Collection 不存在。")
                raise RunCollectionConflictError(
                    f"Collection revision 已从 {expected_revision} 更新到 {int(current['current_revision'])}。"
                )
            revision_no = int(expected_revision) + 1
            records = self._collection_member_records(
                conn, normalized, previous_revision=(collection_id, int(expected_revision))
            )
            self._insert_collection_revision(
                conn, collection_id=collection_id, revision_no=revision_no,
                member_records=records, actor=actor, source=source,
                idempotency_key=key, idempotency_fingerprint=fingerprint, now=now,
            )
            self._insert_run_collection_audit(
                conn, collection_id=collection_id, action="revision_created", actor=actor,
                actor_source=actor_source, actor_verified=actor_verified,
                source=source, revision_no=revision_no,
                detail={"idempotency_key": key, "members_count": len(records)}, created_at=now,
            )
            self._mark_run_collection_change(conn)
            result = self._collection_payload(conn, collection_id)
        assert result is not None
        return result
