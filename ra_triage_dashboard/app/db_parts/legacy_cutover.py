"""S6 legacy Review cutover classification and canonical read services.

The service is additive: source annotations/comments/tasks remain untouched and
new classification/policy/receipt rows are append-only.  Business endpoints
can use these helpers without reusing the old ``latest annotation`` fallback.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any, Sequence

from .shared import LABELS, _json, _json_load, model_label_matches_gt, utc_now


LEGACY_CLASSIFICATIONS = {
    "model_review_mapped",
    "label_history_mapped",
    "legacy_mixed",
    "legacy_unbound_history",
    "legacy_task_history",
}
LEGACY_POLICIES = {"legacy", "shadow", "canonical"}
S6_POLICY_VERSION = "legacy-cutover-v1"


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DatabaseLegacyCutoverMixin:
    """Append-only legacy mapping plus canonical read projections."""

    @staticmethod
    def _legacy_policy_row(row: Any) -> dict[str, Any]:
        return {
            "baseline_scope": str(row["baseline_scope"] or ""),
            "policy": str(row["policy"] or "legacy"),
            "epoch": int(row["epoch"] or 0),
            "policy_version": str(row["policy_version"] or ""),
            "inventory_sha256": str(row["inventory_sha256"] or ""),
            "updated_by": str(row["updated_by"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "last_receipt": _json_load(row["last_receipt_json"], {}),
        }

    def legacy_scope_inventory(self, scopes: Sequence[str]) -> dict[str, Any]:
        normalized = sorted({str(scope or "").strip() for scope in scopes if str(scope or "").strip()})
        if not normalized:
            return {"scopes": [], "inventory_sha256": _sha([]), "items": []}
        placeholders = ", ".join("?" for _ in normalized)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT annotation.id, issue.baseline_scope, annotation.issue_id,
                       annotation.model_run_id, annotation.work_split_id,
                       annotation.label, annotation.review_status,
                       annotation.is_excluded, annotation.tags_json,
                       annotation.missing_evidence_json, annotation.note,
                       annotation.author, annotation.created_at
                FROM annotations annotation
                JOIN issues issue ON issue.issue_id = annotation.issue_id
                WHERE issue.baseline_scope IN ({placeholders})
                ORDER BY annotation.id
                """,
                normalized,
            ).fetchall()
        items = [
            {
                "id": int(row["id"]),
                "baseline_scope": str(row["baseline_scope"] or ""),
                "issue_id": str(row["issue_id"] or ""),
                "model_run_id": str(row["model_run_id"] or ""),
                "work_split_id": str(row["work_split_id"] or ""),
                "label": str(row["label"] or ""),
                "review_status": str(row["review_status"] or ""),
                "is_excluded": bool(row["is_excluded"]),
                "tags": _json_load(row["tags_json"], []),
                "missing_evidence": _json_load(row["missing_evidence_json"], []),
                "note": str(row["note"] or ""),
                "author": str(row["author"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]
        by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            by_scope[item["baseline_scope"]].append(item)
        return {
            "scopes": normalized,
            "inventory_sha256": _sha(items),
            "items": items,
            "counts_by_scope": {
                scope: {
                    "annotation_count": len(by_scope.get(scope, [])),
                    "issue_count": len({item["issue_id"] for item in by_scope.get(scope, [])}),
                }
                for scope in normalized
            },
        }

    @staticmethod
    def _classify_legacy_item(item: dict[str, Any]) -> str:
        has_model = bool(item.get("model_run_id"))
        has_task = bool(item.get("work_split_id"))
        has_label_axis = bool(
            item.get("label")
            or item.get("tags")
            or item.get("missing_evidence")
            or item.get("is_excluded")
            or item.get("note")
        )
        if has_model and has_label_axis:
            return "legacy_mixed"
        if has_model:
            return "model_review_mapped"
        if has_task:
            return "legacy_task_history" if not has_label_axis else "legacy_mixed"
        if has_label_axis:
            return "label_history_mapped"
        return "legacy_unbound_history"

    def classify_legacy_annotations(
        self,
        *,
        scopes: Sequence[str],
        policy_version: str = S6_POLICY_VERSION,
        actor: str = "s6-inventory",
        apply: bool = False,
    ) -> dict[str, Any]:
        inventory = self.legacy_scope_inventory(scopes)
        classified: list[dict[str, Any]] = []
        with self.connect() as conn:
            for item in inventory["items"]:
                classification = self._classify_legacy_item(item)
                target_type = ""
                target_id = ""
                evidence: dict[str, Any] = {
                    "source_annotation_id": item["id"],
                    "model_run_id": item["model_run_id"],
                    "work_split_id": item["work_split_id"],
                    "has_label_axis": classification in {"label_history_mapped", "legacy_mixed"},
                }
                if classification == "model_review_mapped":
                    target = conn.execute(
                        "SELECT id, campaign_id, reference_id FROM model_review_revisions "
                        "WHERE legacy_annotation_id = ? ORDER BY id DESC LIMIT 1",
                        (item["id"],),
                    ).fetchone()
                    if target is not None:
                        target_type, target_id = "model_review_revision", str(target["id"])
                        evidence.update({"campaign_id": str(target["campaign_id"] or ""), "reference_id": str(target["reference_id"] or "")})
                    else:
                        evidence["mapping_status"] = "unresolved_model_review"
                elif classification == "label_history_mapped":
                    target = conn.execute(
                        "SELECT id, label_case_id FROM label_revisions "
                        "WHERE source_annotation_id = ? ORDER BY id DESC LIMIT 1",
                        (item["id"],),
                    ).fetchone()
                    if target is not None:
                        target_type, target_id = "label_revision", str(target["id"])
                        evidence["label_case_id"] = str(target["label_case_id"] or "")
                    else:
                        evidence["mapping_status"] = "unresolved_label_history"
                classified.append({
                    **item,
                    "classification": classification,
                    "target_domain_type": target_type,
                    "target_domain_id": target_id,
                    "policy_version": str(policy_version),
                    "inventory_sha256": str(inventory["inventory_sha256"]),
                    "evidence": evidence,
                })
                if apply:
                    conn.execute(
                        """
                        INSERT INTO legacy_review_classifications (
                            source_annotation_id, baseline_scope, classification,
                            target_domain_type, target_domain_id, policy_version,
                            inventory_sha256, evidence_json, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_annotation_id, policy_version) DO NOTHING
                        """,
                        (
                            item["id"], item["baseline_scope"], classification,
                            target_type, target_id, str(policy_version),
                            inventory["inventory_sha256"], _json(evidence), actor, utc_now(),
                        ),
                    )
            if apply:
                if self.backend == "postgresql":
                    conn.execute("UPDATE dashboard_change_revision SET revision = revision + 1, updated_at = now() WHERE id = 1")
                self._mark_change_topic(conn, "legacy_cutover")
        counts: dict[str, int] = defaultdict(int)
        for item in classified:
            counts[item["classification"]] += 1
        return {
            "policy_version": str(policy_version),
            "inventory_sha256": inventory["inventory_sha256"],
            "scopes": inventory["scopes"],
            "counts": dict(sorted(counts.items())),
            "items": classified,
            "applied": bool(apply),
        }

    def legacy_classifications(self, scopes: Sequence[str], policy_version: str = S6_POLICY_VERSION) -> list[dict[str, Any]]:
        normalized = sorted({str(scope or "").strip() for scope in scopes if str(scope or "").strip()})
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM legacy_review_classifications WHERE baseline_scope IN ({placeholders}) AND policy_version = ? ORDER BY source_annotation_id",
                (*normalized, str(policy_version)),
            ).fetchall()
        return [
            {key: (_json_load(row[key], {}) if key.endswith("_json") else row[key]) for key in row.keys()}
            for row in rows
        ]

    def legacy_read_policies(self, scopes: Sequence[str] = ()) -> list[dict[str, Any]]:
        normalized = sorted({str(scope or "").strip() for scope in scopes if str(scope or "").strip()})
        where = "" if not normalized else f"WHERE baseline_scope IN ({', '.join('?' for _ in normalized)})"
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM legacy_read_policies {where} ORDER BY baseline_scope", normalized).fetchall()
        return [self._legacy_policy_row(row) for row in rows]

    def set_legacy_read_policy(
        self, *, baseline_scope: str, policy: str, policy_version: str,
        inventory_sha256: str, updated_by: str, expected_epoch: int | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope = str(baseline_scope or "").strip()
        normalized = str(policy or "").strip().lower()
        if not scope or normalized not in LEGACY_POLICIES:
            raise ValueError("legacy read policy 不合法。")
        with self._write_lock, self.connect() as conn:
            lock = " FOR UPDATE" if self.backend == "postgresql" else ""
            current = conn.execute(f"SELECT * FROM legacy_read_policies WHERE baseline_scope = ?{lock}", (scope,)).fetchone()
            epoch = int(current["epoch"] or 0) if current else 0
            if expected_epoch is not None and int(expected_epoch) != epoch:
                raise ValueError(f"legacy read policy epoch 已变化：当前 {epoch}，请求 {expected_epoch}。")
            next_epoch = epoch + (1 if current is None or str(current["policy"] or "") != normalized or str(current["policy_version"] or "") != str(policy_version or "") else 0)
            conn.execute(
                """
                INSERT INTO legacy_read_policies (
                    baseline_scope, policy, epoch, policy_version, inventory_sha256,
                    updated_by, updated_at, last_receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(baseline_scope) DO UPDATE SET
                    policy=excluded.policy, epoch=excluded.epoch,
                    policy_version=excluded.policy_version, inventory_sha256=excluded.inventory_sha256,
                    updated_by=excluded.updated_by, updated_at=excluded.updated_at,
                    last_receipt_json=excluded.last_receipt_json
                """,
                (scope, normalized, next_epoch, str(policy_version or ""), str(inventory_sha256 or ""), str(updated_by or ""), utc_now(), _json(receipt or {})),
            )
            if self.backend == "postgresql":
                conn.execute("UPDATE dashboard_change_revision SET revision = revision + 1, updated_at = now() WHERE id = 1")
            self._mark_change_topic(conn, "legacy_cutover")
            row = conn.execute("SELECT * FROM legacy_read_policies WHERE baseline_scope = ?", (scope,)).fetchone()
        return self._legacy_policy_row(row)

    def record_legacy_shadow_receipt(
        self, *, baseline_scope: str, component: str, policy_version: str,
        inventory_sha256: str, legacy_count: int, canonical_count: int,
        diffs: Sequence[dict[str, Any]] = (), expected_diffs: Sequence[str] = (),
        actor: str = "s6-shadow",
    ) -> dict[str, Any]:
        diff_rows = list(diffs or [])
        status = "pass" if not diff_rows else "expected_diff" if all(str(item.get("kind") or "") in set(expected_diffs or ()) for item in diff_rows if isinstance(item, dict)) else "fail"
        receipt = {
            "id": f"s6-shadow-{uuid.uuid4().hex}", "baseline_scope": str(baseline_scope),
            "component": str(component), "policy_version": str(policy_version),
            "inventory_sha256": str(inventory_sha256), "legacy_count": int(legacy_count),
            "canonical_count": int(canonical_count), "diff_count": len(diff_rows),
            "status": status, "expected_diffs": list(expected_diffs or ()),
            "diffs": diff_rows, "created_by": actor, "created_at": utc_now(),
        }
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO legacy_shadow_receipts (id, baseline_scope, component, policy_version, inventory_sha256, legacy_count, canonical_count, diff_count, status, expected_diff_json, diff_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt["id"], receipt["baseline_scope"], receipt["component"], receipt["policy_version"], receipt["inventory_sha256"], receipt["legacy_count"], receipt["canonical_count"], receipt["diff_count"], receipt["status"], _json(receipt["expected_diffs"]), _json(diff_rows), actor, receipt["created_at"]),
            )
        return receipt

    def legacy_shadow_receipts(self, scopes: Sequence[str] = (), component: str = "") -> list[dict[str, Any]]:
        normalized = sorted({str(scope or "").strip() for scope in scopes if str(scope or "").strip()})
        where: list[str] = []
        params: list[Any] = []
        if normalized:
            where.append(f"baseline_scope IN ({', '.join('?' for _ in normalized)})")
            params.extend(normalized)
        if component:
            where.append("component = ?")
            params.append(str(component))
        query = "SELECT * FROM legacy_shadow_receipts" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                **{key: row[key] for key in row.keys() if not key.endswith("_json")},
                "expected_diffs": _json_load(row["expected_diff_json"], []),
                "diffs": _json_load(row["diff_json"], []),
            }
            for row in rows
        ]

    def legacy_shadow_compare(self, *, scopes: Sequence[str], component: str = "") -> dict[str, Any]:
        normalized = sorted({str(scope or "").strip() for scope in scopes if str(scope or "").strip()})
        inventory = self.legacy_scope_inventory(normalized)
        classifications = self.legacy_classifications(normalized)
        canonical_count = sum(
            1 for item in classifications
            if str(item.get("classification") or "") in {"model_review_mapped", "label_history_mapped"}
        )
        legacy_count = len(inventory.get("items") or [])
        diffs = [
            {"kind": "legacy_mixed", "source_annotation_id": item.get("source_annotation_id")}
            for item in classifications if str(item.get("classification") or "") == "legacy_mixed"
        ]
        return {
            "component": str(component or "all"),
            "scopes": normalized,
            "legacy_count": legacy_count,
            "canonical_count": canonical_count,
            "diff_count": len(diffs),
            "diffs": diffs[:500],
            "expected_diff_kinds": ["legacy_mixed", "legacy_unbound_history", "legacy_task_history"],
        }

    def canonical_issue_projection(
        self, *, issue_id: str, model_run_id: str = "", campaign_id: str = "",
        reference_id: str = "", reviewer: str = "", baseline_scope: str = "",
    ) -> dict[str, Any] | None:
        issue_key = str(issue_id or "").strip()
        with self.connect() as conn:
            issue = conn.execute("SELECT * FROM issues WHERE issue_id = ?", (issue_key,)).fetchone()
            if issue is None:
                return None
            scope = str(baseline_scope or issue["baseline_scope"] or "")
            shared = self.project_issue_label_states(scope, [issue_key], include_sources=True, connection=conn).get(issue_key, {})
            review = None
            if model_run_id:
                params = (str(model_run_id), issue_key, str(campaign_id or ""), str(reference_id or ""), str(reviewer or "").lower())
                row = conn.execute(
                    """
                    SELECT revision.* FROM model_review_heads head
                    JOIN model_review_revisions revision ON revision.id = head.revision_id
                    WHERE head.model_run_id = ? AND head.issue_id = ?
                      AND head.campaign_id = ? AND head.reference_id = ?
                      AND lower(head.reviewer) = ?
                    """, params,
                ).fetchone()
                review = self._model_review_dict(row) if row is not None else None
            classification = conn.execute(
                "SELECT * FROM legacy_review_classifications WHERE source_annotation_id IN (SELECT id FROM annotations WHERE issue_id = ?) ORDER BY source_annotation_id DESC LIMIT 20",
                (issue_key,),
            ).fetchall()
        return {
            "issue": {"issue_id": issue_key, "baseline_scope": scope, "gt_label": str(issue["gt_label"] or "")},
            "shared_label": shared,
            "model_review": review,
            "campaign_context": {"campaign_id": str(campaign_id or ""), "reference_id": str(reference_id or ""), "reviewer": str(reviewer or "")},
            "legacy_classifications": [{key: (_json_load(row[key], {}) if key.endswith("_json") else row[key]) for key in row.keys()} for row in classification],
        }

    def resolve_legacy_evidence(self, *, kind: str, value: str) -> dict[str, Any] | None:
        normalized_kind = str(kind or "").strip().lower()
        raw = str(value or "").strip()
        if not raw:
            return None
        with self.connect() as conn:
            if normalized_kind == "annotation":
                row = conn.execute("SELECT * FROM annotations WHERE id = ?", (int(raw),)).fetchone()
                if row is None:
                    return None
                classification = conn.execute("SELECT * FROM legacy_review_classifications WHERE source_annotation_id = ? ORDER BY created_at DESC LIMIT 1", (int(raw),)).fetchone()
                return {"kind": kind, "source_id": int(raw), "classification": ({key: (_json_load(classification[key], {}) if key.endswith("_json") else classification[key]) for key in classification.keys()} if classification else None), "canonical_projection": self.canonical_issue_projection(issue_id=str(row["issue_id"]), model_run_id=str(row["model_run_id"] or ""), reviewer=str(row["author"] or ""))}
            if normalized_kind == "comment":
                row = conn.execute("SELECT * FROM review_comments WHERE id = ?", (int(raw),)).fetchone()
                return {"kind": kind, "source_id": int(raw), "comment": ({key: row[key] for key in row.keys()} if row else None)} if row else None
            if normalized_kind in {"task", "split"}:
                row = conn.execute("SELECT * FROM issue_work_splits WHERE id = ?", (raw,)).fetchone()
                return {"kind": kind, "source_id": raw, "task": ({key: row[key] for key in row.keys()} if row else None)} if row else None
        return None

    def legacy_exclusion_projection(self, *, scopes: Sequence[str], policy_version: str = S6_POLICY_VERSION) -> list[dict[str, Any]]:
        normalized = sorted({str(scope or "").strip() for scope in scopes if str(scope or "").strip()})
        result: list[dict[str, Any]] = []
        for scope in normalized:
            with self.connect() as conn:
                rows = conn.execute("SELECT issue_id FROM issues WHERE baseline_scope = ? ORDER BY issue_id", (scope,)).fetchall()
            issue_ids = [str(row["issue_id"]) for row in rows]
            projections = self.project_issue_label_states(scope, issue_ids, include_sources=False)
            # Canonical label conflict/stale cannot be a writable Trail candidate.
            for issue_id in issue_ids:
                projection = projections.get(issue_id, {})
                state = str(projection.get("state") or "none")
                if state in {"conflict", "stale", "pending"}:
                    exclusion_state = state if state in {"conflict", "stale"} else "candidate"
                    source_domain = "label"
                else:
                    exclusion_state = "none"
                    source_domain = ""
                result.append({"baseline_scope": scope, "issue_id": issue_id, "state": exclusion_state, "source_domain": source_domain, "writable": exclusion_state in {"none", "excluded"}, "policy_version": policy_version})
        return result
