"""Run collection workflow: evaluation_create. Transaction ownership remains in methods."""
from __future__ import annotations
import hashlib
import time
import uuid
from typing import Any, Sequence
from .shared import LABELS, _json_load, utc_now
from .run_collection_rules import RunCollectionConflictError


class RunEvaluationCreateMixin:
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
        """Create or reuse one frozen evaluation, retrying PG serialization races.

        Separate ``Database`` instances have separate Python locks.  Two workers
        can therefore race while materializing the same content-addressed
        Workset before the unique Evaluation context is inserted.  PostgreSQL
        correctly aborts one repeatable-read transaction with SQLSTATE 40001;
        retry the complete transaction so it observes and reuses the committed
        Workset and context.  Other database errors remain fail-closed.
        """

        attempts = 3 if self.backend == "postgresql" else 1
        for attempt in range(attempts):
            try:
                return self._create_run_evaluation_once(
                    collection_id=collection_id,
                    collection_revision=collection_revision,
                    workset_id=workset_id,
                    workset_issue_ids=workset_issue_ids,
                    baseline_scopes=baseline_scopes,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    reference_ids=reference_ids,
                    excluded_issue_ids=excluded_issue_ids,
                    scoring_policy=scoring_policy,
                    selection_source_run_id=selection_source_run_id,
                    comparison_reference_run_id=comparison_reference_run_id,
                    actor=actor,
                    actor_source=actor_source,
                    actor_verified=actor_verified,
                    idempotency_key=idempotency_key,
                )
            except BaseException as exc:
                retryable = False
                current: BaseException | None = exc
                visited: set[int] = set()
                while current is not None and id(current) not in visited:
                    visited.add(id(current))
                    sqlstate = str(getattr(current, "sqlstate", "") or "")
                    if sqlstate in {"40001", "40P01"}:
                        retryable = True
                        break
                    current = current.__cause__ or current.__context__
                if not retryable or attempt + 1 >= attempts:
                    raise
                time.sleep(0.02 * (attempt + 1))
        raise RuntimeError("unreachable evaluation retry state")

    def _create_run_evaluation_once(
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
            shared_label_items: dict[str, dict[str, Any]] = {}
            for scope in scopes:
                shared_label_items.update(
                    self.project_issue_label_states(
                        scope,
                        scope_members[scope],
                        include_sources=True,
                        connection=conn,
                    )
                )
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
                missing_snapshots = sorted(set(scopes) - set(active_gt))
                if missing_snapshots:
                    raise ValueError(
                        "正式 Evaluation 要求每个 scope 存在 active GT snapshot；"
                        "缺少：" + ", ".join(missing_snapshots) + "。"
                    )
                for issue_id, projection in shared_label_items.items():
                    if str(projection.get("state") or "") != "resolved":
                        continue
                    expected = str(projection.get("expected_output") or "")
                    gt_label = str(active_gt_items.get(issue_id) or "")
                    projection["gt_relation"] = (
                        "fills_missing_gt" if expected and not gt_label
                        else "matches_gt" if expected and expected == gt_label
                        else "differs_from_gt" if expected and gt_label
                        else "unknown"
                    )

            # A Run Evaluation owns a real frozen Workset. Keep one immutable
            # scope row per dataset so S4 Campaign adapters can validate exact
            # membership and per-scope snapshot provenance without parsing a
            # public response body.
            if workset_id:
                existing_scope_rows = conn.execute(
                    "SELECT baseline_scope FROM review_workset_scopes WHERE workset_id = ?",
                    (workset_id,),
                ).fetchall()
                existing_scopes = {
                    str(row["baseline_scope"] or "") for row in existing_scope_rows
                }
                for ordinal, scope in enumerate(scopes, 1):
                    if scope in existing_scopes:
                        continue
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
                existing_content = conn.execute(
                    "SELECT id FROM run_evaluation_contexts WHERE context_sha256 = ? "
                    "ORDER BY created_at ASC, id ASC LIMIT 1",
                    (context_sha,),
                ).fetchone()
                if existing_content is not None:
                    return self._run_evaluation_payload_conn(
                        conn, str(existing_content["id"]), page=1,
                        page_size=100, search=""
                    )
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
                projection = shared_label_items.get(issue_id) or {
                    "state": "none", "expected_output": "", "gt_relation": "unknown",
                    "method": "single", "source_task_ids": [],
                    "source_revision_ids": [], "sources": [],
                }
                shared_state = str(projection.get("state") or "none")
                shared_expected = str(projection.get("expected_output") or "")
                shared_relation = str(projection.get("gt_relation") or "unknown")
                shared_method = str(projection.get("method") or "single")
                shared_source = {
                    "reference_type": "shared_label_projection",
                    "baseline_scope": str(issue.get("baseline_scope") or ""),
                    "source_task_ids": list(projection.get("source_task_ids") or []),
                    "source_revision_ids": list(projection.get("source_revision_ids") or []),
                    "sources": list(projection.get("sources") or []),
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
