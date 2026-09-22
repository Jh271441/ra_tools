from __future__ import annotations

import hashlib
import json
import math
import uuid
from typing import Any, Sequence

from .shared import LABELS, MODEL_LABELS, _json_load, model_label_matches_gt, utc_now


class RunCollectionConflictError(ValueError):
    """An optimistic revision or idempotency check failed."""


class DatabaseRunCollectionsMixin:
    MAX_COLLECTION_RUNS = 32
    MAX_EVALUATION_ITEMS = 50000
    RUN_EVALUATION_POLICY_VERSION = "run-evaluation-v1"

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _content_sha256(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical_json(value).encode("utf-8")).hexdigest()

    @classmethod
    def _normalize_collection_members(cls, members: Sequence[Any]) -> list[dict[str, Any]]:
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
            raise ValueError("Collection members 必须为数组。")
        if not members or len(members) > cls.MAX_COLLECTION_RUNS:
            raise ValueError(f"Collection 必须包含 1 到 {cls.MAX_COLLECTION_RUNS} 个 Run。")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        reference_count = 0
        for ordinal, raw in enumerate(members, 1):
            item = {"run_id": raw} if isinstance(raw, str) else raw
            if not isinstance(item, dict):
                raise ValueError(f"第 {ordinal} 个 Collection member 格式无效。")
            run_id = str(item.get("run_id") or item.get("id") or "").strip()
            if not run_id or len(run_id) > 160:
                raise ValueError(f"第 {ordinal} 个 Collection member 缺少有效 Run ID。")
            if run_id in seen:
                raise ValueError("Collection 中不能重复添加同一个 Run。")
            seen.add(run_id)
            role = str(item.get("role") or "").strip()[:48]
            is_reference = bool(item.get("is_reference", item.get("reference", False)))
            reference_count += int(is_reference)
            normalized.append({
                "ordinal": ordinal,
                "run_id": run_id,
                "role": role,
                "is_reference": is_reference,
            })
        if reference_count > 1:
            raise ValueError("Collection 最多只能标记一个参考 Run。")
        return normalized

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

    @staticmethod
    def _evaluation_policy(reference_type: str, supplied: dict[str, Any] | None) -> dict[str, Any]:
        policy = {
            "version": "run-evaluation-v1",
            "label_normalization_version": "triage-labels-v1",
            "valid_reference_labels": list(LABELS),
            "valid_prediction_labels": list(MODEL_LABELS),
            "missing_predictions": "NONE; incorrect; included when any selected Run has a supported output",
            "unknown_labels": "UNKNOWN; incorrect; counted separately and not treated as a supported output",
            "exclusions": "remove issue from accuracy, confusion and transition denominators",
            "accuracy_denominator": "v1 pairwise union: valid non-excluded reference items with a supported output from at least one Collection Run",
            "supported_coverage_denominator": "all valid non-excluded reference items for each Run, including absent and UNKNOWN outputs",
            "transition_status": "P means prediction matches frozen reference; F includes missing and unknown output",
        }
        if supplied:
            if not isinstance(supplied, dict):
                raise ValueError("scoring_policy 必须是 JSON 对象。")
            if str(supplied.get("version") or policy["version"]) != policy["version"]:
                raise ValueError("不支持的 scoring_policy 版本。")
            for key, value in supplied.items():
                if key in policy and key not in {"version"} and value != policy[key]:
                    raise ValueError(f"scoring_policy 不允许覆盖已定义语义：{key}。")
                if key not in policy and key not in {"display_name", "notes", "extensions"}:
                    raise ValueError(f"scoring_policy 不支持字段：{key}。")
                if key in {"display_name", "notes", "extensions"}:
                    policy[key] = value
        return policy

    @staticmethod
    def _chunks(values: Sequence[str], size: int = 400):
        for start in range(0, len(values), size):
            yield values[start : start + size]

    def create_run_evaluation(
        self,
        *,
        collection_id: str,
        collection_revision: int | None = None,
        workset_id: str = "",
        workset_issue_ids: Sequence[str] = (),
        baseline_scopes: Sequence[str] = (),
        reference_type: str = "gt",
        reference_id: str = "",
        reference_ids: dict[str, str] | Sequence[dict[str, Any]] | None = None,
        excluded_issue_ids: Sequence[str] | None = None,
        scoring_policy: dict[str, Any] | None = None,
        selection_source_run_id: str = "",
        comparison_reference_run_id: str = "",
        actor: str = "",
        actor_source: str = "legacy",
        actor_verified: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        collection_id = str(collection_id or "").strip()
        workset_id = str(workset_id or "").strip()
        reference_type = str(reference_type or "gt").strip().lower()
        reference_id = str(reference_id or "").strip()
        if reference_type not in {"gt", "label_result", "run"}:
            raise ValueError("reference_type 必须为 gt 或 label_result。")
        if reference_type == "run":
            raise ValueError("正式 Evaluation 不支持 reference_type=run；Run 只能作为 comparison_reference_run_id 用于 P2F/F2P。")
        normalized_reference_ids: dict[str, str] = {}
        if isinstance(reference_ids, dict):
            normalized_reference_ids = {
                str(scope or "").strip(): str(value or "").strip()
                for scope, value in reference_ids.items()
                if str(scope or "").strip() and str(value or "").strip()
            }
        elif isinstance(reference_ids, Sequence) and not isinstance(reference_ids, (str, bytes)):
            normalized_reference_ids = {
                str(item.get("baseline_scope") or "").strip(): str(item.get("reference_id") or "").strip()
                for item in reference_ids if isinstance(item, dict)
                and str(item.get("baseline_scope") or "").strip()
                and str(item.get("reference_id") or "").strip()
            }
        if reference_type == "label_result" and not reference_id and not normalized_reference_ids:
            raise ValueError("该 reference_type 需要 reference_id。")
        if reference_type == "gt" and reference_id:
            raise ValueError("GT reference_id 由创建时冻结的 active snapshot 自动确定。")
        source_run_id = str(selection_source_run_id or "").strip()
        comparison_reference_run_id = str(comparison_reference_run_id or "").strip()
        key = str(idempotency_key or "").strip()[:160]
        actor = str(actor or "").strip()[:160]
        now = utc_now()
        context_id = f"evaluation-{uuid.uuid4()}"
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            else:
                conn.execute("BEGIN IMMEDIATE")

            collection = conn.execute(
                "SELECT current_revision FROM run_collections WHERE id = ?", (collection_id,)
            ).fetchone()
            if collection is None:
                raise ValueError("Run Collection 不存在。")
            revision_no = int(collection_revision or collection["current_revision"] or 0)
            revision = conn.execute(
                "SELECT * FROM run_collection_revisions WHERE collection_id = ? AND revision_no = ?",
                (collection_id, revision_no),
            ).fetchone()
            if revision is None:
                raise ValueError("Run Collection revision 不存在。")
            member_rows = conn.execute(
                """
                SELECT member.*, live.id AS live_run_id
                FROM run_collection_members member
                LEFT JOIN model_runs live ON live.id = member.run_id
                WHERE member.collection_id = ? AND member.revision_no = ?
                ORDER BY member.ordinal
                """,
                (collection_id, revision_no),
            ).fetchall()
            members = []
            for row in member_rows:
                snapshot = _json_load(row["run_snapshot_json"], {})
                members.append({
                    "ordinal": int(row["ordinal"]), "run_id": str(row["run_id"]),
                    "role": str(row["role"] or ""), "is_reference": bool(row["is_reference"]),
                    "available_now": row["live_run_id"] is not None,
                    "run": snapshot if isinstance(snapshot, dict) else {},
                })
            if not members:
                raise ValueError("Run Collection revision 没有成员。")
            member_run_ids = [item["run_id"] for item in members]
            if not comparison_reference_run_id:
                comparison_reference_run_id = next(
                    (item["run_id"] for item in members if item["is_reference"]), ""
                )
            if comparison_reference_run_id and comparison_reference_run_id not in member_run_ids:
                raise ValueError("comparison_reference_run_id 必须属于该 Collection revision。")

            label_results: dict[str, Any] = {}
            if reference_type == "label_result":
                requested_label_ids = dict(normalized_reference_ids)
                if reference_id and not requested_label_ids:
                    requested_label_ids[""] = reference_id
                for requested_scope, snapshot_id in requested_label_ids.items():
                    label_result = conn.execute(
                        "SELECT * FROM label_result_snapshots WHERE id = ?", (snapshot_id,)
                    ).fetchone()
                    if label_result is None:
                        raise ValueError("Label result snapshot 不存在。")
                    snapshot_workset_id = str(label_result["workset_id"] or "")
                    if workset_id and workset_id != snapshot_workset_id:
                        raise ValueError("Label result snapshot 与 Workset 不匹配。")
                    if requested_scope and str(label_result["baseline_scope"] or "") != requested_scope:
                        raise ValueError("Label result snapshot 与数据集 scope 不匹配。")
                    label_results[str(label_result["baseline_scope"] or requested_scope)] = label_result
                if len(label_results) == 1 and not workset_id:
                    workset_id = str(next(iter(label_results.values()))["workset_id"] or "")

            if workset_id:
                workset = conn.execute(
                    "SELECT * FROM review_worksets WHERE id = ?", (workset_id,)
                ).fetchone()
                if workset is None:
                    raise ValueError("Workset 不存在。")
                issue_rows = conn.execute(
                    "SELECT issue_id FROM review_workset_items WHERE workset_id = ? ORDER BY ordinal",
                    (workset_id,),
                ).fetchall()
                issue_ids = [str(row["issue_id"]) for row in issue_rows]
                original_workset_issue_ids = list(issue_ids)
                scope_rows = conn.execute(
                    "SELECT baseline_scope FROM review_workset_scopes WHERE workset_id = ? ORDER BY ordinal",
                    (workset_id,),
                ).fetchall()
                scopes = [str(row["baseline_scope"] or "") for row in scope_rows if str(row["baseline_scope"] or "")]
                if not scopes and str(workset["baseline_scope"] or ""):
                    scopes = [str(workset["baseline_scope"] or "")]
            elif workset_issue_ids:
                issue_ids = list(dict.fromkeys(str(item or "").strip() for item in workset_issue_ids if str(item or "").strip()))
                original_workset_issue_ids = None
                scopes = []
            else:
                original_workset_issue_ids = None
                scopes = self._normalize_baseline_scopes(baseline_scopes)
                if not scopes:
                    raise ValueError("Evaluation 必须绑定一个 Workset 或至少一个 baseline_scope。")
                clause = ", ".join("?" for _ in scopes)
                found = conn.execute(
                    f"SELECT issue_id FROM issues WHERE baseline_scope IN ({clause}) ORDER BY issue_id",
                    tuple(scopes),
                ).fetchall()
                issue_ids = [str(row["issue_id"]) for row in found]
            if not issue_ids:
                raise ValueError("Workset 不能为空。")
            if len(issue_ids) > self.MAX_EVALUATION_ITEMS:
                raise ValueError(f"Workset 最多支持 {self.MAX_EVALUATION_ITEMS} 个 Issue。")

            issue_map: dict[str, dict[str, Any]] = {}
            for batch in self._chunks(issue_ids):
                placeholders = ", ".join("?" for _ in batch)
                rows = conn.execute(
                    f"SELECT issue_id, baseline_scope, gt_label FROM issues WHERE issue_id IN ({placeholders})",
                    tuple(batch),
                ).fetchall()
                issue_map.update({
                    str(row["issue_id"]): {
                        "baseline_scope": str(row["baseline_scope"] or ""),
                        "gt_label": str(row["gt_label"] or ""),
                    }
                    for row in rows
                })
            scopes = sorted({
                issue_map.get(issue_id, {}).get("baseline_scope", "")
                for issue_id in issue_ids
                if issue_map.get(issue_id, {}).get("baseline_scope", "")
            } | {scope for scope in scopes if scope})

            if source_run_id:
                source_run = conn.execute("SELECT id FROM model_runs WHERE id = ?", (source_run_id,)).fetchone()
                if source_run is None:
                    raise ValueError("Workset selection source Run 不存在或已删除。")
                selected = set()
                for batch in self._chunks(issue_ids):
                    placeholders = ", ".join("?" for _ in batch)
                    rows = conn.execute(
                        f"SELECT issue_id FROM model_predictions WHERE model_run_id = ? AND issue_id IN ({placeholders})",
                        (source_run_id, *batch),
                    ).fetchall()
                    selected.update(str(row["issue_id"]) for row in rows)
                issue_ids = [issue_id for issue_id in issue_ids if issue_id in selected]
                issue_map = {issue_id: issue_map.get(issue_id, {}) for issue_id in issue_ids}
                if not issue_ids:
                    raise ValueError("Selection source Run 在 Workset 中没有输出。")

            scopes = sorted({
                issue_map.get(issue_id, {}).get("baseline_scope", "")
                for issue_id in issue_ids
                if issue_map.get(issue_id, {}).get("baseline_scope", "")
            })
            scope_members = {
                scope: [issue_id for issue_id in issue_ids
                        if str((issue_map.get(issue_id) or {}).get("baseline_scope") or "") == scope]
                for scope in scopes
            }
            scope_members = {scope: members for scope, members in scope_members.items() if members}
            scopes = sorted(scope_members)
            if not scopes:
                raise ValueError("Workset 成员没有有效 baseline scope。")
            all_members_digest = hashlib.sha256("\n".join(issue_ids).encode("utf-8")).hexdigest()
            scopes_digest = self._content_sha256([
                {"baseline_scope": scope, "issue_ids": scope_members[scope]}
                for scope in scopes
            ])
            if not workset_id or (source_run_id and issue_ids != (original_workset_issue_ids or [])):
                existing_workset = conn.execute(
                    """
                    SELECT id FROM review_worksets
                    WHERE selection_source_run_id = ?
                      AND members_sha256 = ? AND member_count = ?
                      AND scope_count = ? AND scopes_sha256 = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (source_run_id, all_members_digest, len(issue_ids),
                     len(scopes), scopes_digest),
                ).fetchone()
                if existing_workset is not None:
                    workset_id = str(existing_workset["id"])
                else:
                    workset_id = f"run-evaluation-workset-{uuid.uuid4().hex}"
                    scope_mode = "multi" if len(scopes) > 1 else "single"
                    conn.execute(
                        """
                        INSERT INTO review_worksets (
                            id, baseline_scope, name, selection_source_run_id,
                            source_filter_json, member_count, members_sha256,
                            scope_mode, scope_count, scopes_sha256, selection_metadata_json,
                            created_by, created_by_source, created_by_verified, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            workset_id, scopes[0] if len(scopes) == 1 else "",
                            f"Evaluation {collection_id[:8]} r{revision_no}"[:160],
                            source_run_id,
                            self._canonical_json({
                                "source": "run_evaluation", "collection_id": collection_id,
                                "collection_revision": revision_no,
                                "selection_source_run_id": source_run_id,
                                "baseline_scopes": scopes,
                            }),
                            len(issue_ids), all_members_digest, scope_mode, len(scopes), scopes_digest,
                            self._canonical_json({"source": "run_evaluation", "baseline_scopes": scopes}),
                            actor,
                            str(actor_source or "run_evaluation"), bool(actor_verified), now,
                        ),
                    )
                    conn.executemany(
                        "INSERT INTO review_workset_items (workset_id, issue_id, ordinal) VALUES (?, ?, ?)",
                        [(workset_id, issue_id, ordinal) for ordinal, issue_id in enumerate(issue_ids, 1)],
                    )
                    self._mark_labeling_change(conn)

            if reference_type == "label_result" and label_results and not workset_id:
                raise ValueError("Label result snapshot 必须保留其原始 Workset。")
            label_result_items: dict[str, dict[str, Any]] = {}
            if reference_type == "label_result":
                for scope, label_result in label_results.items():
                    rows = conn.execute(
                        "SELECT issue_id, state, expected_output, method, gt_relation, ordinal "
                        "FROM label_result_snapshot_items WHERE snapshot_id = ? ORDER BY ordinal",
                        (str(label_result["id"]),),
                    ).fetchall()
                    for row in rows:
                        label_result_items[str(row["issue_id"])] = {
                            "label": str(row["expected_output"] or ""),
                            "valid": str(row["state"] or "") == "resolved" and str(row["expected_output"] or "") in LABELS,
                            "state": str(row["state"] or "none"),
                            "method": str(row["method"] or ""),
                            "gt_relation": str(row["gt_relation"] or "unknown"),
                            "scope": scope,
                            "snapshot_id": str(label_result["id"]),
                            "snapshot_sha256": str(label_result["content_sha256"] or ""),
                        }

            active_gt: dict[str, dict[str, Any]] = {}
            active_gt_items: dict[str, str] = {}
            if reference_type == "gt" and scopes:
                placeholders = ", ".join("?" for _ in scopes)
                rows = conn.execute(
                    """
                    SELECT snap.id, snap.baseline_scope, snap.gt_mode, snap.content_sha256,
                           snap.membership_sha256, active.activated_at
                    FROM gt_snapshot_active active
                    JOIN gt_snapshots snap ON snap.id = active.snapshot_id
                    WHERE active.baseline_scope IN (%s)
                    """ % placeholders,
                    tuple(scopes),
                ).fetchall()
                active_gt = {
                    str(row["baseline_scope"]): {
                        "baseline_scope": str(row["baseline_scope"]),
                        "id": str(row["id"]), "gt_mode": str(row["gt_mode"]),
                        "content_sha256": str(row["content_sha256"]),
                        "membership_sha256": str(row["membership_sha256"]),
                        "activated_at": str(row["activated_at"] or ""),
                    }
                    for row in rows
                }
                snapshot_ids = [item["id"] for item in active_gt.values()]
                if snapshot_ids:
                    placeholders = ", ".join("?" for _ in snapshot_ids)
                    rows = conn.execute(
                        f"SELECT issue_id, gt_label FROM gt_snapshot_items WHERE snapshot_id IN ({placeholders})",
                        tuple(snapshot_ids),
                    ).fetchall()
                    active_gt_items = {
                        str(row["issue_id"]): str(row["gt_label"] or "") for row in rows
                    }
                # Older fixtures may only have the mutable issue GT cache. Turn
                # that cache into a content-addressed active snapshot before
                # freezing the Evaluation, so every official reference is a
                # real GT snapshot (and later GT syncs cannot rewrite history).
                for scope in scopes:
                    if scope in active_gt:
                        continue
                    scope_rows = conn.execute(
                        "SELECT issue_id, gt_label FROM issues WHERE baseline_scope = ? ORDER BY issue_id",
                        (scope,),
                    ).fetchall()
                    snapshot_rows = {
                        str(row["issue_id"]): {"gt_label": str(row["gt_label"] or "")}
                        for row in scope_rows
                    }
                    if not snapshot_rows:
                        raise ValueError(f"数据集 {scope} 没有可冻结的 GT snapshot。")
                    gt_mode = "strict" if all(item["gt_label"] in LABELS for item in snapshot_rows.values()) else "sparse"
                    self._create_or_reuse_gt_snapshot_with_conn(
                        conn,
                        scope=scope,
                        gt_mode=gt_mode,
                        source_name="Dashboard issue GT cache",
                        source_view_id=0,
                        source_field="issues.gt_label",
                        rows=snapshot_rows,
                        source_metadata={"created_for": "run_evaluation"},
                        created_by=actor,
                        created_by_source=str(actor_source or "run_evaluation"),
                        created_by_verified=bool(actor_verified),
                        activate=True,
                        activation_reason="run_evaluation_freeze",
                        mark_change=False,
                        scope_lock_held=True,
                    )
                rows = conn.execute(
                    """
                    SELECT snap.id, snap.baseline_scope, snap.gt_mode, snap.content_sha256,
                           snap.membership_sha256, active.activated_at
                    FROM gt_snapshot_active active
                    JOIN gt_snapshots snap ON snap.id = active.snapshot_id
                    WHERE active.baseline_scope IN (%s)
                    """ % placeholders,
                    tuple(scopes),
                ).fetchall()
                active_gt = {
                    str(row["baseline_scope"]): {
                        "baseline_scope": str(row["baseline_scope"]),
                        "id": str(row["id"]), "gt_mode": str(row["gt_mode"]),
                        "content_sha256": str(row["content_sha256"]),
                        "membership_sha256": str(row["membership_sha256"]),
                        "activated_at": str(row["activated_at"] or ""),
                    }
                    for row in rows
                }
                snapshot_ids = [item["id"] for item in active_gt.values()]
                placeholders = ", ".join("?" for _ in snapshot_ids)
                rows = conn.execute(
                    f"SELECT issue_id, gt_label FROM gt_snapshot_items WHERE snapshot_id IN ({placeholders})",
                    tuple(snapshot_ids),
                ).fetchall()
                active_gt_items = {
                    str(row["issue_id"]): str(row["gt_label"] or "") for row in rows
                }

            # A Run Evaluation owns a real frozen Workset. Keep one immutable
            # scope row per dataset so S4 Campaign adapters can validate exact
            # membership and per-scope snapshot provenance without parsing a
            # public response body.
            if workset_id:
                for ordinal, scope in enumerate(scopes, 1):
                    members_for_scope = scope_members.get(scope, [])
                    scope_members_sha = hashlib.sha256(
                        "\n".join(members_for_scope).encode("utf-8")
                    ).hexdigest()
                    gt_snapshot = active_gt.get(scope) or {}
                    label_snapshot = label_results.get(scope) or {}
                    label_snapshot_id = (
                        str(label_snapshot["id"] or "") if label_snapshot else ""
                    )
                    label_snapshot_sha = (
                        str(label_snapshot["content_sha256"] or "") if label_snapshot else ""
                    )
                    conn.execute(
                        """
                        INSERT INTO review_workset_scopes (
                            workset_id, baseline_scope, ordinal, member_count,
                            members_sha256, gt_snapshot_id, gt_snapshot_sha256,
                            label_result_snapshot_id, label_result_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(workset_id, baseline_scope) DO NOTHING
                        """,
                        (
                            workset_id, scope, ordinal, len(members_for_scope),
                            scope_members_sha, str(gt_snapshot.get("id") or ""),
                            str(gt_snapshot.get("content_sha256") or ""),
                            label_snapshot_id,
                            label_snapshot_sha,
                        ),
                    )

            run_query_ids = list(dict.fromkeys(
                member_run_ids
                + ([comparison_reference_run_id] if comparison_reference_run_id else [])
                + ([source_run_id] if source_run_id else [])
            ))
            prediction_map: dict[tuple[str, str], dict[str, Any]] = {}
            if run_query_ids:
                run_clause = ", ".join("?" for _ in run_query_ids)
                for batch in self._chunks(issue_ids, 300):
                    issue_clause = ", ".join("?" for _ in batch)
                    rows = conn.execute(
                        f"""
                        SELECT model_run_id, issue_id, model_label, model_reason,
                               model_confidence
                        FROM model_predictions
                        WHERE model_run_id IN ({run_clause}) AND issue_id IN ({issue_clause})
                        """,
                        (*run_query_ids, *batch),
                    ).fetchall()
                    for row in rows:
                        prediction_map[(str(row["model_run_id"]), str(row["issue_id"]))] = {
                            "present": True,
                            "label": str(row["model_label"] or ""),
                            "reason": str(row["model_reason"] or ""),
                            "confidence": row["model_confidence"],
                        }

            model_review_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
            if member_run_ids:
                run_clause = ", ".join("?" for _ in member_run_ids)
                for batch in self._chunks(issue_ids, 300):
                    issue_clause = ", ".join("?" for _ in batch)
                    rows = conn.execute(
                        f"""
                        SELECT revision.model_run_id, revision.issue_id, revision.status,
                               revision.reviewer, revision.reason, revision.created_at,
                               revision.campaign_id, revision.reference_id
                        FROM model_review_heads head
                        JOIN model_review_revisions revision ON revision.id = head.revision_id
                        WHERE revision.model_run_id IN ({run_clause})
                          AND revision.issue_id IN ({issue_clause})
                        ORDER BY revision.created_at, revision.id
                        """,
                        (*member_run_ids, *batch),
                    ).fetchall()
                    for row in rows:
                        review_key = (str(row["model_run_id"]), str(row["issue_id"]))
                        model_review_map.setdefault(review_key, []).append({
                            "status": str(row["status"] or "pending"),
                            "reviewer": str(row["reviewer"] or ""),
                            "reason": str(row["reason"] or ""),
                            "created_at": str(row["created_at"] or ""),
                            "campaign_id": str(row["campaign_id"] or ""),
                            "reference_id": str(row["reference_id"] or ""),
                        })

            if reference_type == "run":
                reference_run = conn.execute("SELECT id FROM model_runs WHERE id = ?", (reference_id,)).fetchone()
                if reference_run is None:
                    raise ValueError("Reference Run 不存在或已删除。")

            reference_items: dict[str, dict[str, Any]] = {}
            for issue_id in issue_ids:
                issue = issue_map.get(issue_id) or {}
                scope = str(issue.get("baseline_scope") or "")
                if reference_type == "gt":
                    label = active_gt_items.get(issue_id, "")
                    valid = label in LABELS
                elif reference_type == "label_result":
                    label_result_item = label_result_items.get(issue_id) or {}
                    label = str(label_result_item.get("label") or "")
                    valid = bool(label_result_item.get("valid"))
                reference_items[issue_id] = {"label": label, "valid": valid}

            workset_payload = {
                "version": 1,
                "workset_id": workset_id,
                "baseline_scopes": scopes,
                "selection_source_run_id": source_run_id,
                "issue_ids": issue_ids,
                "member_count": len(issue_ids),
                "members_sha256": all_members_digest,
                "scope_items": [
                    {
                        "baseline_scope": scope,
                        "issue_ids": list(scope_members.get(scope, [])),
                        "member_count": len(scope_members.get(scope, [])),
                        "members_sha256": hashlib.sha256(
                            "\n".join(scope_members.get(scope, [])).encode("utf-8")
                        ).hexdigest(),
                    }
                    for scope in scopes
                ],
            }
            workset_sha = self._content_sha256(workset_payload)
            if reference_type == "gt":
                scope_references = [active_gt[scope] for scope in sorted(active_gt)]
            else:
                scope_references = [
                    {
                        "baseline_scope": scope,
                        "id": str(label_results[scope]["id"]),
                        "content_sha256": str(label_results[scope]["content_sha256"] or ""),
                        "member_count": int(label_results[scope]["member_count"] or 0),
                        "coverage_status": str(label_results[scope]["coverage_status"] or ""),
                    }
                    for scope in sorted(label_results)
                ]
                if len(scope_references) != len(scopes):
                    raise ValueError("Label result reference 必须为每个 Workset scope 提供冻结 snapshot。")
            reference_set_sha = self._content_sha256(scope_references)
            if not reference_id:
                reference_id = (
                    str(scope_references[0]["id"])
                    if len(scope_references) == 1
                    else f"reference-set:{reference_set_sha}"
                )
            reference_payload = {
                "version": 1,
                "type": reference_type,
                "id": reference_id,
                "scope_snapshots": scope_references,
                "gt_snapshots": [active_gt[scope] for scope in sorted(active_gt)] if reference_type == "gt" else [],
                "label_result_snapshots": scope_references if reference_type == "label_result" else [],
                "items": [
                    [issue_id, reference_items[issue_id]["label"], reference_items[issue_id]["valid"]]
                    for issue_id in issue_ids
                ],
            }
            reference_sha = self._content_sha256(reference_payload)

            if excluded_issue_ids is None:
                excluded_candidates = set()
                rows = conn.execute(
                    """
                    SELECT annotation.issue_id
                    FROM annotations annotation
                    JOIN (SELECT issue_id, MAX(id) AS latest_id FROM annotations GROUP BY issue_id) latest
                      ON latest.latest_id = annotation.id
                    WHERE annotation.is_excluded = TRUE
                    """
                ).fetchall()
                excluded_candidates = {str(row["issue_id"]) for row in rows}
            else:
                excluded_candidates = {
                    str(item or "").strip() for item in excluded_issue_ids if str(item or "").strip()
                }
            excluded_set = excluded_candidates.intersection(issue_ids)
            exclusions_payload = sorted(excluded_set)
            exclusion_sha = self._content_sha256({"version": 1, "issue_ids": exclusions_payload})
            conn.execute(
                "INSERT INTO run_evaluation_exclusion_snapshots (content_sha256, version, issue_count, created_at) "
                "VALUES (?, 1, ?, ?) ON CONFLICT(content_sha256) DO NOTHING",
                (exclusion_sha, len(exclusions_payload), now),
            )
            existing_exclusion_items = conn.execute(
                "SELECT COUNT(*) AS item_count FROM run_evaluation_exclusion_items WHERE content_sha256 = ?",
                (exclusion_sha,),
            ).fetchone()
            if int(existing_exclusion_items["item_count"] or 0) == 0 and exclusions_payload:
                conn.executemany(
                    "INSERT INTO run_evaluation_exclusion_items (content_sha256, issue_id, ordinal) VALUES (?, ?, ?)",
                    [(exclusion_sha, issue_id, ordinal) for ordinal, issue_id in enumerate(exclusions_payload, 1)],
                )

            policy = self._evaluation_policy(reference_type, scoring_policy)
            policy_sha = self._content_sha256(policy)
            collection_sha = str(revision["content_sha256"] or "")
            idempotency_fingerprint = self._content_sha256({
                "collection_id": collection_id, "collection_revision": revision_no,
                "collection_sha256": collection_sha, "workset_sha256": workset_sha,
                "reference_sha256": reference_sha, "scoring_policy_sha256": policy_sha,
                "exclusion_sha256": exclusion_sha,
                "comparison_reference_run_id": comparison_reference_run_id,
            })
            if key:
                prior = conn.execute(
                    "SELECT id, idempotency_fingerprint FROM run_evaluation_contexts WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if prior:
                    if str(prior["idempotency_fingerprint"] or "") != idempotency_fingerprint:
                        raise RunCollectionConflictError("Idempotency-Key 已被不同 Evaluation 请求使用。")
                    return self._run_evaluation_payload_conn(conn, str(prior["id"]), page=1, page_size=100, search="")

            context_payload = {
                "collection_id": collection_id, "collection_revision": revision_no,
                "collection_sha256": collection_sha, "workset_sha256": workset_sha,
                "reference_sha256": reference_sha, "scoring_policy_sha256": policy_sha,
                "exclusion_sha256": exclusion_sha,
                "comparison_reference_run_id": comparison_reference_run_id,
            }
            context_sha = self._content_sha256(context_payload)
            reusable = conn.execute(
                "SELECT id FROM run_evaluation_contexts WHERE context_sha256 = ? "
                "ORDER BY created_at ASC, id ASC LIMIT 1",
                (context_sha,),
            ).fetchone()
            if reusable is not None:
                # Content idempotency is independent of Idempotency-Key:
                # retries made with a new transport key must still reuse the
                # same immutable historical context.
                return self._run_evaluation_payload_conn(
                    conn, str(reusable["id"]), page=1, page_size=100, search=""
                )
            cursor = conn.execute(
                """
                INSERT INTO run_evaluation_contexts (
                id, collection_id, collection_revision, collection_sha256,
                    workset_id, workset_json, workset_sha256, item_count,
                    reference_type, reference_id, reference_json, reference_sha256,
                    scoring_policy_json, scoring_policy_version, scoring_policy_sha256,
                    exclusion_sha256, exclusion_version, selection_source_run_id,
                    comparison_reference_run_id, context_sha256,
                    idempotency_key, idempotency_fingerprint, created_by,
                    created_by_source, created_by_verified, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    context_id, collection_id, revision_no, collection_sha,
                    workset_id, self._canonical_json(workset_payload), workset_sha, len(issue_ids),
                    reference_type, reference_id, self._canonical_json(reference_payload), reference_sha,
                    self._canonical_json(policy), policy["version"], policy_sha,
                    exclusion_sha, source_run_id, comparison_reference_run_id,
                    context_sha, key, idempotency_fingerprint, actor,
                    str(actor_source or "legacy"), bool(actor_verified), now,
                ),
            )
            if cursor.rowcount != 1:
                if key:
                    prior = conn.execute(
                        "SELECT id, idempotency_fingerprint FROM run_evaluation_contexts "
                        "WHERE idempotency_key = ?",
                        (key,),
                    ).fetchone()
                    if prior is not None and str(prior["idempotency_fingerprint"] or "") == idempotency_fingerprint:
                        return self._run_evaluation_payload_conn(conn, str(prior["id"]), page=1, page_size=100, search="")
                    raise RunCollectionConflictError("Evaluation Idempotency-Key 已被不同请求使用。")
                raise RunCollectionConflictError("Evaluation Context ID 已存在。")
            item_rows = []
            for ordinal, issue_id in enumerate(issue_ids, 1):
                issue = issue_map.get(issue_id) or {}
                shared_source: dict[str, Any] = {}
                if reference_type == "gt":
                    snapshot = active_gt.get(str(issue.get("baseline_scope") or ""), {})
                    shared_state = "resolved" if reference_items[issue_id]["valid"] else "none"
                    shared_expected = reference_items[issue_id]["label"]
                    shared_relation = "matches_gt" if shared_expected in LABELS else "unknown"
                    shared_method = "gt_snapshot"
                    shared_source = {
                        "reference_type": "gt_snapshot",
                        "baseline_scope": str(issue.get("baseline_scope") or ""),
                        "snapshot_id": str(snapshot.get("id") or ""),
                        "snapshot_sha256": str(snapshot.get("content_sha256") or ""),
                    }
                else:
                    label_result_item = label_result_items.get(issue_id) or {}
                    shared_state = str(label_result_item.get("state") or "none")
                    shared_expected = str(label_result_item.get("label") or "")
                    shared_relation = str(label_result_item.get("gt_relation") or "unknown")
                    shared_method = str(label_result_item.get("method") or "")
                    shared_source = {
                        "reference_type": "label_result_snapshot",
                        "baseline_scope": str(label_result_item.get("scope") or issue.get("baseline_scope") or ""),
                        "snapshot_id": str(label_result_item.get("snapshot_id") or ""),
                        "snapshot_sha256": str(label_result_item.get("snapshot_sha256") or ""),
                    }
                shared_payload = {
                    "state": shared_state,
                    "expected_output": shared_expected,
                    "gt_relation": shared_relation,
                    "method": shared_method,
                    "source": shared_source,
                }
                predictions = {
                    run_id: prediction_map[(run_id, issue_id)]
                    for run_id in member_run_ids
                    if (run_id, issue_id) in prediction_map
                }
                model_reviews = {
                    run_id: model_review_map[(run_id, issue_id)]
                    for run_id in member_run_ids
                    if (run_id, issue_id) in model_review_map
                }
                item_rows.append((
                    context_id, ordinal, issue_id,
                    str(issue.get("baseline_scope") or ""),
                    reference_items[issue_id]["label"], reference_items[issue_id]["valid"],
                    issue_id in excluded_set, self._canonical_json(predictions),
                    self._canonical_json(model_reviews),
                    shared_state, shared_expected, shared_relation, shared_method,
                    self._canonical_json(shared_source), self._content_sha256(shared_payload),
                ))
            conn.executemany(
                """
                INSERT INTO run_evaluation_items (
                    context_id, ordinal, issue_id, baseline_scope, reference_label,
                    reference_valid, excluded, predictions_json, model_review_json,
                    shared_label_state, shared_label_expected_output,
                    shared_label_gt_relation, shared_label_method,
                    shared_label_source_json, shared_label_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                item_rows,
            )
            self._insert_run_collection_audit(
                conn, collection_id=collection_id, action="evaluation_created", actor=actor,
                actor_source=actor_source, actor_verified=actor_verified,
                source="evaluation", revision_no=revision_no, context_id=context_id,
                detail={
                    "context_sha256": context_sha, "workset_sha256": workset_sha,
                    "reference_sha256": reference_sha, "exclusion_sha256": exclusion_sha,
                    "scoring_policy_sha256": policy_sha,
                }, created_at=now,
            )
            self._mark_run_collection_change(conn)
            return self._run_evaluation_payload_conn(conn, context_id, page=1, page_size=100, search="")

    def _run_evaluation_payload_conn(
        self,
        conn: Any,
        context_id: str,
        *,
        page: int,
        page_size: int,
        search: str,
        include_items: bool = True,
        include_all_items: bool = False,
    ) -> dict[str, Any] | None:
        context = conn.execute(
            "SELECT * FROM run_evaluation_contexts WHERE id = ?", (context_id,)
        ).fetchone()
        if context is None:
            return None
        members_rows = conn.execute(
            """
            SELECT member.*, live.id AS live_run_id
            FROM run_collection_members member
            LEFT JOIN model_runs live ON live.id = member.run_id
            WHERE member.collection_id = ? AND member.revision_no = ?
            ORDER BY member.ordinal
            """,
            (str(context["collection_id"]), int(context["collection_revision"])),
        ).fetchall()
        members = [
            {
                "ordinal": int(row["ordinal"]), "run_id": str(row["run_id"]),
                "role": str(row["role"] or ""), "is_reference": bool(row["is_reference"]),
                "available_now": row["live_run_id"] is not None,
                "run": _json_load(row["run_snapshot_json"], {}),
            }
            for row in members_rows
        ]
        all_items = conn.execute(
            "SELECT * FROM run_evaluation_items WHERE context_id = ? ORDER BY ordinal",
            (context_id,),
        ).fetchall()
        policy = _json_load(context["scoring_policy_json"], {})
        reference_labels = list(MODEL_LABELS if context["reference_type"] == "run" else LABELS)
        prediction_columns = [*MODEL_LABELS, "NONE", "UNKNOWN"]
        matrix: dict[str, dict[str, dict[str, int]]] = {
            item["run_id"]: {
                label: {prediction: 0 for prediction in prediction_columns}
                for label in reference_labels
            }
            for item in members
        }
        metrics: dict[str, dict[str, Any]] = {
            item["run_id"]: {
                "run_id": item["run_id"], "run": item["run"],
                "available_now": item["available_now"],
                "reference_denominator": 0, "valid_reference_count": 0,
                "pairwise_union_denominator": 0,
                "prediction_count": 0, "supported_count": 0,
                "missing_count": 0,
                "absent_prediction_count": 0, "unknown_count": 0, "correct_count": 0,
                "accuracy": 0.0, "coverage": 0.0, "workset_coverage": 0.0,
                "supported_coverage": 0.0, "absent_count": 0,
                "confusion": [], "transitions_vs_reference": None,
            }
            for item in members
        }
        valid_non_excluded_count = 0
        scorable_issue_ids: set[str] = set()
        workset_missing_count = 0
        workset_unknown_count = 0
        for row in all_items:
            if not bool(row["reference_valid"]) or bool(row["excluded"]):
                continue
            valid_non_excluded_count += 1
            predictions = _json_load(row["predictions_json"], {})
            if not isinstance(predictions, dict):
                predictions = {}
            if any(
                bool((predictions.get(member["run_id"]) or {}).get("present"))
                and str((predictions.get(member["run_id"]) or {}).get("label") or "") in MODEL_LABELS
                for member in members
            ):
                scorable_issue_ids.add(str(row["issue_id"]))
            else:
                predictions = _json_load(row["predictions_json"], {})
                if not isinstance(predictions, dict):
                    predictions = {}
                present_values = [
                    bool((predictions.get(member["run_id"]) or {}).get("present"))
                    for member in members
                ]
                supported_values = [
                    present and str((predictions.get(member["run_id"]) or {}).get("label") or "") in MODEL_LABELS
                    for present, member in zip(present_values, members)
                ]
                if not any(present_values):
                    workset_missing_count += 1
                elif not any(supported_values):
                    workset_unknown_count += 1
        reference_run_id = str(context["comparison_reference_run_id"] or "")
        transition_counts = (
            {
                run_id: {"P2P": 0, "P2F": 0, "F2P": 0, "F2F": 0}
                for run_id in metrics if run_id != reference_run_id
            }
            if reference_run_id else {}
        )
        filtered_items = []
        normalized_search = str(search or "").strip().lower()[:128]
        for row in all_items:
            issue_id = str(row["issue_id"])
            reference_label = str(row["reference_label"] or "")
            valid = bool(row["reference_valid"])
            excluded = bool(row["excluded"])
            predictions = _json_load(row["predictions_json"], {})
            if not isinstance(predictions, dict):
                predictions = {}
            model_reviews = _json_load(row["model_review_json"], {})
            if not isinstance(model_reviews, dict):
                model_reviews = {}
            if valid and not excluded:
                ref_metric_label = reference_label if reference_label in reference_labels else ""
                if ref_metric_label:
                    for member in members:
                        run_id = member["run_id"]
                        metric = metrics[run_id]
                        metric["valid_reference_count"] += 1
                        prediction = predictions.get(run_id) or {}
                        present = bool(prediction.get("present"))
                        label = str(prediction.get("label") or "") if present else ""
                        if not present:
                            bucket = "NONE"
                            metric["missing_count"] += 1
                            metric["absent_prediction_count"] += 1
                            metric["absent_count"] += 1
                        elif label not in MODEL_LABELS:
                            bucket = "UNKNOWN"
                            metric["unknown_count"] += 1
                            metric["missing_count"] += 1
                        else:
                            bucket = label
                            metric["prediction_count"] += 1
                            metric["supported_count"] += 1
                        if issue_id not in scorable_issue_ids:
                            continue
                        metric["reference_denominator"] += 1
                        metric["pairwise_union_denominator"] += 1
                        if label in MODEL_LABELS and model_label_matches_gt(label, reference_label):
                            metric["correct_count"] += 1
                        if ref_metric_label in matrix[run_id]:
                            matrix[run_id][ref_metric_label][bucket] += 1
                if issue_id in scorable_issue_ids and reference_run_id in metrics:
                    ref_prediction = predictions.get(reference_run_id) or {}
                    ref_label = str(ref_prediction.get("label") or "") if ref_prediction.get("present") else ""
                    ref_correct = bool(ref_label in MODEL_LABELS and model_label_matches_gt(ref_label, reference_label))
                    for run_id in metrics:
                        if run_id == reference_run_id or run_id not in transition_counts:
                            continue
                        prediction = predictions.get(run_id) or {}
                        label = str((prediction or {}).get("label") or "") if (prediction or {}).get("present") else ""
                        candidate_correct = bool(label in MODEL_LABELS and model_label_matches_gt(label, reference_label))
                        transition = ("P" if ref_correct else "F") + "2" + ("P" if candidate_correct else "F")
                        transition_counts[run_id][transition] += 1
            enriched_predictions = {}
            for member in members:
                run_id = member["run_id"]
                prediction = predictions.get(run_id) or {"present": False, "label": ""}
                label = str(prediction.get("label") or "")
                known = bool(prediction.get("present")) and label in MODEL_LABELS
                enriched_predictions[run_id] = {
                    "present": bool(prediction.get("present")),
                    "label": label if known else ("UNKNOWN" if prediction.get("present") else "NONE"),
                    "reason": str(prediction.get("reason") or ""),
                    "confidence": prediction.get("confidence"),
                    "correct": bool(valid and known and model_label_matches_gt(label, reference_label)),
                    "model_reviews": model_reviews.get(run_id, []),
                }
            if normalized_search and normalized_search not in issue_id.lower():
                continue
            filtered_items.append({
                "ordinal": int(row["ordinal"]), "issue_id": issue_id,
                "baseline_scope": str(row["baseline_scope"] or ""),
                "reference_label": reference_label,
                "reference_valid": valid, "excluded": excluded,
                "shared_label": {
                    "state": str(row["shared_label_state"] or "none"),
                    "expected_output": str(row["shared_label_expected_output"] or ""),
                    "gt_relation": str(row["shared_label_gt_relation"] or "unknown"),
                    "method": str(row["shared_label_method"] or ""),
                    "source": _json_load(row["shared_label_source_json"], {}),
                    "sha256": str(row["shared_label_sha256"] or ""),
                },
                "predictions": enriched_predictions,
            })
        for run_id, metric in metrics.items():
            denominator = int(metric["reference_denominator"])
            metric["accuracy"] = metric["correct_count"] / denominator if denominator else 0.0
            metric["coverage"] = metric["prediction_count"] / denominator if denominator else 0.0
            metric["workset_coverage"] = (
                metric["prediction_count"] / metric["valid_reference_count"]
                if metric["valid_reference_count"] else 0.0
            )
            metric["supported_coverage"] = (
                metric["supported_count"] / metric["valid_reference_count"]
                if metric["valid_reference_count"] else 0.0
            )
            metric["coverage_semantics"] = "pairwise_union" if denominator else "no_supported_output"
            metric["confusion"] = [
                {"reference_label": label, "cells": matrix[run_id][label], "total": sum(matrix[run_id][label].values())}
                for label in reference_labels
            ]
            if run_id in transition_counts:
                metric["transitions_vs_reference"] = transition_counts[run_id]
        page_size = min(max(int(page_size), 1), self.MAX_EVALUATION_ITEMS if include_all_items else 100)
        page = max(int(page), 1)
        total = len(filtered_items)
        page_count = max(1, math.ceil(total / page_size))
        page = min(page, page_count)
        offset = (page - 1) * page_size
        stored_workset = _json_load(context["workset_json"], {})
        stored_reference = _json_load(context["reference_json"], {})
        if include_all_items:
            public_workset = stored_workset
            public_reference_snapshot = stored_reference
        else:
            scope_items = stored_workset.get("scope_items") if isinstance(stored_workset, dict) else []
            public_workset = {
                "version": int(stored_workset.get("version") or 1) if isinstance(stored_workset, dict) else 1,
                "workset_id": str(stored_workset.get("workset_id") or context["workset_id"]) if isinstance(stored_workset, dict) else str(context["workset_id"] or ""),
                "baseline_scopes": list(stored_workset.get("baseline_scopes") or []) if isinstance(stored_workset, dict) else [],
                "scope_count": len(scope_items or (stored_workset.get("baseline_scopes") if isinstance(stored_workset, dict) else [])),
                "member_count": len(all_items),
                "selection_source_run_id": str(context["selection_source_run_id"] or ""),
                "members_sha256": str(stored_workset.get("members_sha256") or context["workset_sha256"] or ""),
                "scope_items": [
                    {
                        "baseline_scope": str(item.get("baseline_scope") or ""),
                        "member_count": int(item.get("member_count") or len(item.get("issue_ids") or [])),
                        "members_sha256": str(item.get("members_sha256") or ""),
                    }
                    for item in (scope_items or [])
                    if isinstance(item, dict)
                ],
            }
            public_reference_snapshot = {
                "version": int(stored_reference.get("version") or 1) if isinstance(stored_reference, dict) else 1,
                "type": str(stored_reference.get("type") or context["reference_type"]) if isinstance(stored_reference, dict) else str(context["reference_type"]),
                "id": str(stored_reference.get("id") or context["reference_id"] or "") if isinstance(stored_reference, dict) else str(context["reference_id"] or ""),
                "scope_snapshots": [
                    {
                        "baseline_scope": str(item.get("baseline_scope") or ""),
                        "id": str(item.get("id") or ""),
                        "content_sha256": str(item.get("content_sha256") or ""),
                        "membership_sha256": str(item.get("membership_sha256") or ""),
                        "member_count": int(item.get("member_count") or 0),
                    }
                    for item in (stored_reference.get("scope_snapshots") or [])
                    if isinstance(item, dict)
                ],
                "item_count": len(all_items),
            }
        result = {
            "id": str(context["id"]),
            "collection_id": str(context["collection_id"]),
            "collection_revision": int(context["collection_revision"]),
            "collection_sha256": str(context["collection_sha256"] or ""),
            "workset": public_workset,
            "workset_sha256": str(context["workset_sha256"] or ""),
            "reference": {
                "type": str(context["reference_type"]),
                "id": str(context["reference_id"] or ""),
                "snapshot": public_reference_snapshot,
                "sha256": str(context["reference_sha256"] or ""),
            },
            "scoring_policy": policy,
            "scoring_policy_version": str(context["scoring_policy_version"]),
            "scoring_policy_sha256": str(context["scoring_policy_sha256"] or ""),
            "exclusion": {
                "version": int(context["exclusion_version"] or 1),
                "sha256": str(context["exclusion_sha256"] or ""),
            },
            "selection_source_run_id": str(context["selection_source_run_id"] or ""),
            "selection_bias_warning": (
                f"Workset 由 Run {context['selection_source_run_id']} 的输出筛选，存在来源 Run 选择偏差。"
                if context["selection_source_run_id"] else ""
            ),
            "comparison_reference_run_id": reference_run_id,
            "reference_official": str(context["reference_type"] or "") in {"gt", "label_result"},
            "metric_semantics": (
                "official_snapshot_accuracy_with_pairwise_union_coverage"
                if str(context["reference_type"] or "") in {"gt", "label_result"}
                else "legacy_prediction_agreement_non_official"
            ),
            "context_sha256": str(context["context_sha256"] or ""),
            "created_by": str(context["created_by"] or ""),
            "created_by_source": str(context["created_by_source"] or "legacy"),
            "created_by_verified": bool(context["created_by_verified"]),
            "created_at": str(context["created_at"] or ""),
            "members": members,
            "summary": {
                "workset_count": len(all_items),
                "valid_reference_count": sum(1 for row in all_items if bool(row["reference_valid"]) and not bool(row["excluded"])),
                "excluded_count": sum(1 for row in all_items if bool(row["excluded"])),
                "reference_denominator": next(iter(metrics.values()))["reference_denominator"] if metrics else 0,
                "pairwise_union_denominator": (
                    next(iter(metrics.values()))["pairwise_union_denominator"] if metrics else 0
                ),
                "workset_missing_count": workset_missing_count,
                "workset_unknown_count": workset_unknown_count,
                "coverage_note": "准确率/旧版 Pairwise coverage 使用至少一个 Run 有 supported output 的 union denominator；每 Run supported_coverage 使用全部 valid reference。",
                "runs": list(metrics.values()),
            },
            "items": filtered_items[offset : offset + page_size] if include_items else [],
            "total": total,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
        }
        return result

    def get_run_evaluation(
        self,
        context_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str = "",
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._run_evaluation_payload_conn(
                conn, str(context_id or "").strip(), page=page,
                page_size=page_size, search=search,
            )

    def get_run_evaluation_task_context(self, context_id: str) -> dict[str, Any] | None:
        """Return the complete frozen context for internal Campaign adapters.

        The public detail endpoint deliberately returns compact Workset and
        reference summaries. Campaign creation still needs the frozen member
        set, so it uses this internal service method inside the same database
        boundary instead of trusting a client supplied full JSON payload.
        """
        with self.connect() as conn:
            return self._run_evaluation_payload_conn(
                conn, str(context_id or "").strip(), page=1,
                page_size=self.MAX_EVALUATION_ITEMS, search="",
                include_all_items=True,
            )

    def list_run_evaluations(
        self,
        *,
        collection_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_collection_id = str(collection_id or "").strip()
        safe_limit = min(max(int(limit), 1), 500)
        where = "WHERE collection_id = ?" if normalized_collection_id else ""
        params: tuple[Any, ...] = (normalized_collection_id, safe_limit) if where else (safe_limit,)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, collection_id, collection_revision, collection_sha256,
                       workset_id, workset_sha256, reference_type, reference_id,
                       reference_sha256, scoring_policy_version, scoring_policy_sha256,
                       exclusion_sha256, comparison_reference_run_id, context_sha256,
                       created_by, created_at
                FROM run_evaluation_contexts
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]), "collection_id": str(row["collection_id"]),
                "collection_revision": int(row["collection_revision"]),
                "collection_sha256": str(row["collection_sha256"] or ""),
                "workset_id": str(row["workset_id"] or ""),
                "workset_sha256": str(row["workset_sha256"] or ""),
                "reference_type": str(row["reference_type"] or ""),
                "reference_id": str(row["reference_id"] or ""),
                "reference_sha256": str(row["reference_sha256"] or ""),
                "scoring_policy_version": str(row["scoring_policy_version"] or ""),
                "scoring_policy_sha256": str(row["scoring_policy_sha256"] or ""),
                "exclusion_sha256": str(row["exclusion_sha256"] or ""),
                "comparison_reference_run_id": str(row["comparison_reference_run_id"] or ""),
                "context_sha256": str(row["context_sha256"] or ""),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def export_run_evaluation(self, context_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            payload = self._run_evaluation_payload_conn(
                conn, str(context_id or "").strip(), page=1,
                page_size=self.MAX_EVALUATION_ITEMS, search="", include_all_items=True,
            )
        if payload is not None:
            payload["generated_at"] = utc_now()
            payload["export_provenance"] = {
                "collection_id": payload["collection_id"],
                "collection_revision": payload["collection_revision"],
                "collection_sha256": payload["collection_sha256"],
                "workset_id": str(payload["workset"].get("workset_id") or ""),
                "workset_member_count": int(payload["workset"].get("member_count") or len(payload.get("items") or [])),
                "workset_sha256": payload["workset_sha256"],
                "workset_scope_items": payload["workset"].get("scope_items") or [],
                "reference_type": payload["reference"]["type"],
                "reference_id": payload["reference"]["id"],
                "reference_scope_snapshots": payload["reference"].get("snapshot", {}).get("scope_snapshots") or [],
                "reference_sha256": payload["reference"]["sha256"],
                "scoring_policy_version": payload["scoring_policy_version"],
                "scoring_policy_sha256": payload["scoring_policy_sha256"],
                "exclusion_sha256": payload["exclusion"]["sha256"],
                "context_sha256": payload["context_sha256"],
            }
        return payload
