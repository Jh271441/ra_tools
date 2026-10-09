"""Copy only Case/GT label signals from legacy mixed Review rows."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Any, Sequence

from .db_parts.shared import LABELS, _json, _json_load, utc_now


MIGRATION_VERSION = "legacy-case-label-copy-v2"
SOURCE_TYPE = "legacy_model_review"


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _scopes(values: Sequence[str]) -> list[str]:
    return sorted({str(value or "").strip() for value in values if str(value or "").strip()})


def _rows_on_connection(conn: Any, scopes: Sequence[str]) -> list[dict[str, Any]]:
    normalized = _scopes(scopes)
    if not normalized:
        return []
    placeholders = ", ".join("?" for _ in normalized)
    rows = conn.execute(
        f"""
            SELECT issue.baseline_scope, annotation.*, issue.gt_label,
                   issue.gt_source, active.snapshot_id AS gt_snapshot_id,
                   snapshot_item.gt_label AS snapshot_gt_label
            FROM annotations annotation
            JOIN issues issue ON issue.issue_id = annotation.issue_id
            LEFT JOIN gt_snapshot_active active
              ON active.baseline_scope = issue.baseline_scope
            LEFT JOIN gt_snapshot_items snapshot_item
              ON snapshot_item.snapshot_id = active.snapshot_id
             AND snapshot_item.baseline_scope = issue.baseline_scope
             AND snapshot_item.issue_id = issue.issue_id
            WHERE issue.baseline_scope IN ({placeholders})
            ORDER BY issue.baseline_scope, annotation.issue_id,
                     lower(annotation.author), annotation.created_at, annotation.id
            """,
        normalized,
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = {key: row[key] for key in row.keys()}
        explicit = str(item.get("label") or "").strip()
        frozen_gt = str(item.get("snapshot_gt_label") or item.get("gt_label") or "").strip()
        derived = explicit if explicit in LABELS else ""
        label_source = "explicit" if derived else "none"
        if not derived and str(item.get("review_status") or "") == "reviewed" and frozen_gt in LABELS:
            derived = frozen_gt
            label_source = "matches_gt"
        item["frozen_gt_label"] = frozen_gt
        item["derived_label"] = derived
        item["label_source"] = label_source
        result.append(item)
    return result


def _rows(database: Any, scopes: Sequence[str]) -> list[dict[str, Any]]:
    with database.connect() as conn:
        return _rows_on_connection(conn, scopes)


def _source_inventory(rows: Sequence[dict[str, Any]]) -> str:
    fields = (
        "id", "baseline_scope", "issue_id", "model_run_id", "work_split_id",
        "label", "review_status", "is_excluded", "tags_json",
        "missing_evidence_json", "mentions_json", "note", "author",
        "author_source", "author_verified", "supersedes_id", "created_at",
        "gt_snapshot_id", "frozen_gt_label", "gt_source",
    )
    return _sha([{key: row.get(key) for key in fields} for row in rows])


def plan_legacy_label_copy(database: Any, *, scopes: Sequence[str]) -> dict[str, Any]:
    rows = _rows(database, scopes)
    reports: list[dict[str, Any]] = []
    plans: dict[str, dict[str, Any]] = {}
    for scope in _scopes(scopes):
        scoped = [row for row in rows if str(row.get("baseline_scope") or "") == scope]
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in scoped:
            reviewer = str(row.get("author") or "").strip().lower() or "<unknown>"
            groups[(str(row.get("issue_id") or ""), reviewer)].append(row)
        votes: list[dict[str, Any]] = []
        reviewer_conflicts: list[dict[str, Any]] = []
        by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
        relevant_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
        pending_issues: set[str] = set()
        for (issue_id, normalized_reviewer), sources in groups.items():
            labels = sorted({str(row.get("derived_label") or "") for row in sources if row.get("derived_label")})
            relevant = [
                row for row in sources
                if row.get("derived_label") or str(row.get("review_status") or "") == "needs_gt_review"
            ]
            if relevant:
                relevant_by_issue[issue_id].extend(relevant)
            if any(str(row.get("review_status") or "") == "needs_gt_review" for row in sources):
                pending_issues.add(issue_id)
            labeled_sources = [row for row in sources if row.get("derived_label")]
            if len(labels) == 1:
                vote = {
                    "issue_id": issue_id,
                    "reviewer": str(labeled_sources[-1].get("author") or normalized_reviewer),
                    "normalized_reviewer": normalized_reviewer,
                    "state": "resolved",
                    "expected_output": labels[0],
                    "sources": labeled_sources,
                }
                votes.append(vote)
                by_issue[issue_id].append(vote)
            elif len(labels) > 1:
                vote = {
                    "issue_id": issue_id,
                    "reviewer": str(labeled_sources[-1].get("author") or normalized_reviewer),
                    "normalized_reviewer": normalized_reviewer,
                    "state": "conflict",
                    "expected_output": "",
                    "sources": labeled_sources,
                    "labels": labels,
                }
                votes.append(vote)
                reviewer_conflicts.append(vote)
                by_issue[issue_id].append(vote)
        cases: list[dict[str, Any]] = []
        resolved_cases = 0
        conflict_cases = 0
        for issue_id, relevant_sources in sorted(relevant_by_issue.items()):
            issue_votes = by_issue.get(issue_id, [])
            resolved_labels = {
                vote["expected_output"] for vote in issue_votes
                if vote["state"] == "resolved" and vote["expected_output"] in LABELS
            }
            conflict = any(vote["state"] == "conflict" for vote in issue_votes) or len(resolved_labels) > 1
            if conflict:
                state, expected_output = "conflict", ""
                conflict_cases += 1
            elif len(resolved_labels) == 1:
                state, expected_output = "resolved", next(iter(resolved_labels))
                resolved_cases += 1
            else:
                state, expected_output = "pending", ""
            representative = relevant_sources[-1]
            cases.append({
                "issue_id": issue_id,
                "state": state,
                "expected_output": expected_output,
                "gt_review_pending": issue_id in pending_issues,
                "pending_adjudication": conflict,
                "frozen_gt_snapshot_id": str(representative.get("gt_snapshot_id") or ""),
                "frozen_gt_label": str(representative.get("frozen_gt_label") or ""),
                "frozen_gt_source": str(representative.get("gt_source") or ""),
                "source_ids": sorted({int(row["id"]) for row in relevant_sources}),
                "reviewer_vote_count": len(issue_votes),
            })
        effective_sources = sum(1 for row in scoped if row.get("derived_label"))
        stats = {
            "scanned_reviews": len(scoped),
            "effective_label_sources": effective_sources,
            "reviewer_dedup_votes": sum(1 for vote in votes if vote["state"] == "resolved"),
            "resolved_cases": resolved_cases,
            "gt_review_pending_cases": len(pending_issues),
            "conflict_cases": conflict_cases,
            "pending_adjudication_cases": conflict_cases,
            "skipped_no_label_sources": len(scoped) - effective_sources,
            "same_reviewer_conflicts": len(reviewer_conflicts),
        }
        plans[scope] = {
            "scope": scope,
            "rows": scoped,
            "votes": votes,
            "cases": cases,
            "source_inventory_sha256": _source_inventory(scoped),
            "stats": stats,
        }
        reports.append({"baseline_scope": scope, **stats})
    return {"migration_version": MIGRATION_VERSION, "source_type": SOURCE_TYPE, "reports": reports, "plans": plans}


def _stable_id(prefix: str, *values: Any) -> str:
    return f"{prefix}-{_sha([str(value or '') for value in values])[:24]}"


def apply_legacy_label_copy(
    database: Any, *, scopes: Sequence[str], imported_by: str = "migration"
) -> dict[str, Any]:
    planned = plan_legacy_label_copy(database, scopes=scopes)
    applied: list[dict[str, Any]] = []
    with database._write_lock, database.connect() as conn:
        for scope in _scopes(scopes):
            plan = planned["plans"].get(scope) or {}
            batch_id = _stable_id("label-import", scope, MIGRATION_VERSION)
            existing = conn.execute(
                "SELECT * FROM label_import_batches WHERE baseline_scope = ? AND source_type = ? AND migration_version = ?",
                (scope, SOURCE_TYPE, MIGRATION_VERSION),
            ).fetchone()
            if existing is not None:
                if str(existing["source_inventory_sha256"] or "") != str(plan.get("source_inventory_sha256") or ""):
                    raise ValueError(f"{scope} 的 legacy Review 源清单已变化；请使用新的 migration version。")
                applied.append({
                    "baseline_scope": scope,
                    "batch_id": str(existing["id"]),
                    "status": str(existing["status"]),
                    "inserted_votes": 0,
                    "inserted_sources": 0,
                    "duplicate": True,
                    "stats": _json_load(existing["stats_json"], {}),
                })
                continue
            now = utc_now()
            dataset_id = scope.removeprefix("release").split("_", 1)[0]
            conn.execute(
                """
                INSERT INTO label_import_batches (
                    id, baseline_scope, name, source_type, migration_version,
                    status, source_inventory_sha256, stats_json, imported_by,
                    created_at, imported_at
                ) VALUES (?, ?, ?, ?, ?, 'importing', ?, '{}', ?, ?, ?)
                """,
                (
                    batch_id, scope, f"历史判错复核标签导入 · {dataset_id}",
                    SOURCE_TYPE, MIGRATION_VERSION,
                    str(plan.get("source_inventory_sha256") or ""),
                    str(imported_by or "migration"), now, now,
                ),
            )
            cases_by_issue = {item["issue_id"]: item for item in plan.get("cases", [])}
            votes_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for vote in plan.get("votes", []):
                votes_by_issue[vote["issue_id"]].append(vote)
            inserted_votes = 0
            inserted_sources = 0
            for issue_id, case_state in cases_by_issue.items():
                case_id = _stable_id("legacy-label", scope, issue_id, MIGRATION_VERSION)
                conn.execute(
                    """
                    INSERT INTO label_cases (
                        id, baseline_scope, issue_id, task_id, source_run_id,
                        seen_gt_label, seen_gt_source, created_at
                    ) VALUES (?, ?, ?, ?, '', ?, ?, ?)
                    ON CONFLICT(baseline_scope, issue_id, task_id, source_run_id) DO NOTHING
                    """,
                    (
                        case_id, scope, issue_id, batch_id,
                        case_state["frozen_gt_label"], case_state["frozen_gt_source"], now,
                    ),
                )
                case_row = conn.execute(
                    "SELECT id FROM label_cases WHERE baseline_scope=? AND issue_id=? AND task_id=? AND source_run_id=''",
                    (scope, issue_id, batch_id),
                ).fetchone()
                case_id = str(case_row["id"])
                vote_ids: dict[str, str] = {}
                for vote in votes_by_issue.get(issue_id, []):
                    source_ids = sorted(int(row["id"]) for row in vote["sources"])
                    vote_id = _stable_id("legacy-vote", batch_id, issue_id, vote["normalized_reviewer"])
                    sql = """
                        INSERT INTO label_revisions (
                            label_case_id, expected_output, tags_json, evidence_gaps_json,
                            rationale, is_excluded, author, author_source,
                            author_verified, revision_kind, supersedes_id,
                            source_annotation_id, created_at
                        ) VALUES (?, ?, '[]', '[]', '', ?, ?, ?, ?, 'legacy', NULL, NULL, ?)
                    """
                    if database.backend == "postgresql":
                        sql += " RETURNING id"
                    cursor = conn.execute(
                        sql,
                        (
                            case_id, vote["expected_output"] or None, False,
                            vote["reviewer"], SOURCE_TYPE,
                            all(bool(row.get("author_verified")) for row in vote["sources"]),
                            max(str(row.get("created_at") or now) for row in vote["sources"]),
                        ),
                    )
                    revision_id = int(cursor.fetchone()["id"]) if database.backend == "postgresql" else int(cursor.lastrowid)
                    conn.execute(
                        """
                        INSERT INTO label_import_votes (
                            id, batch_id, label_case_id, label_revision_id,
                            baseline_scope, issue_id, reviewer, normalized_reviewer,
                            state, expected_output, source_fingerprint, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            vote_id, batch_id, case_id, revision_id, scope, issue_id,
                            vote["reviewer"], vote["normalized_reviewer"], vote["state"],
                            vote["expected_output"] or None, _sha(source_ids), now,
                        ),
                    )
                    vote_ids[vote["normalized_reviewer"]] = vote_id
                    inserted_votes += 1
                relevant = [
                    row for row in plan.get("rows", [])
                    if str(row.get("issue_id") or "") == issue_id
                    and (row.get("derived_label") or str(row.get("review_status") or "") == "needs_gt_review")
                ]
                for source in relevant:
                    normalized_reviewer = str(source.get("author") or "").strip().lower() or "<unknown>"
                    conn.execute(
                        """
                        INSERT INTO label_import_sources (
                            batch_id, source_annotation_id, vote_id, label_case_id,
                            source_run_id, source_work_split_id, source_label,
                            source_review_status, source_reviewer, source_created_at,
                            migration_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(batch_id, source_annotation_id) DO NOTHING
                        """,
                        (
                            batch_id, int(source["id"]), vote_ids.get(normalized_reviewer), case_id,
                            str(source.get("model_run_id") or ""), str(source.get("work_split_id") or ""),
                            str(source.get("derived_label") or ""), str(source.get("review_status") or ""),
                            str(source.get("author") or ""), str(source.get("created_at") or now), MIGRATION_VERSION,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO label_migration_map (
                            source_table, source_id, target_table, target_id,
                            policy_version, created_at
                        ) VALUES ('annotations', ?, 'label_import_votes', ?, ?, ?)
                        ON CONFLICT(source_table, source_id, target_table, policy_version)
                        DO UPDATE SET target_id = excluded.target_id
                        """,
                        (
                            str(source["id"]), vote_ids.get(normalized_reviewer) or case_id,
                            MIGRATION_VERSION, now,
                        ),
                    )
                    inserted_sources += 1
                conn.execute(
                    """
                    INSERT INTO label_import_case_states (
                        batch_id, baseline_scope, issue_id, state, expected_output,
                        gt_review_pending, pending_adjudication,
                        frozen_gt_snapshot_id, frozen_gt_label, frozen_gt_source,
                        source_ids_json, reviewer_vote_count, source_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id, scope, issue_id, case_state["state"],
                        case_state["expected_output"] or None,
                        bool(case_state["gt_review_pending"]), bool(case_state["pending_adjudication"]),
                        case_state["frozen_gt_snapshot_id"] or None,
                        case_state["frozen_gt_label"], case_state["frozen_gt_source"],
                        _json(case_state["source_ids"]), int(case_state["reviewer_vote_count"]),
                        _sha(case_state["source_ids"]), now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO label_import_suppressed_revisions (batch_id, revision_id, created_at)
                SELECT ?, revision.id, ?
                FROM label_revisions revision
                JOIN label_cases label_case ON label_case.id = revision.label_case_id
                WHERE label_case.baseline_scope = ?
                  AND revision.source_annotation_id IS NOT NULL
                ON CONFLICT(batch_id, revision_id) DO NOTHING
                """,
                (batch_id, now, scope),
            )
            stats = dict(plan.get("stats") or {})
            conn.execute(
                """
                UPDATE label_import_batches
                SET status='imported', stats_json=?, imported_at=?
                WHERE id=?
                """,
                (_json(stats), now, batch_id),
            )
            database._mark_labeling_change(conn)
            applied.append({
                "baseline_scope": scope,
                "batch_id": batch_id,
                "status": "imported",
                "inserted_votes": inserted_votes,
                "inserted_sources": inserted_sources,
                "duplicate": False,
                "stats": stats,
            })
    planned.pop("plans", None)
    return {**planned, "applied": applied}


def reconcile_legacy_label_copy_activation(
    database: Any, *, baseline_scope: str
) -> dict[str, Any]:
    scope = str(baseline_scope or "").strip()
    if not scope:
        return {"passed": False, "errors": ["没有数据集范围。"]}
    planned = plan_legacy_label_copy(database, scopes=[scope])
    plan = planned.get("plans", {}).get(scope) or {}
    errors: list[str] = []
    with database.connect() as conn:
        batch = conn.execute(
            """
            SELECT * FROM label_import_batches
            WHERE baseline_scope=? AND source_type=? AND migration_version=?
            """,
            (scope, SOURCE_TYPE, MIGRATION_VERSION),
        ).fetchone()
        active = conn.execute(
            """
            SELECT active.snapshot_id, snapshot.content_sha256,
                   snapshot.member_count, snapshot.valid_label_count
            FROM gt_snapshot_active active
            JOIN gt_snapshots snapshot ON snapshot.id=active.snapshot_id
            WHERE active.baseline_scope=? AND snapshot.baseline_scope=?
            """,
            (scope, scope),
        ).fetchone()
        issue_count = int(conn.execute(
            "SELECT COUNT(*) n FROM issues WHERE baseline_scope=?", (scope,)
        ).fetchone()["n"])
        snapshot_item_count = int(conn.execute(
            """
            SELECT COUNT(*) n FROM gt_snapshot_items item
            JOIN gt_snapshot_active active ON active.snapshot_id=item.snapshot_id
            WHERE active.baseline_scope=? AND item.baseline_scope=?
            """,
            (scope, scope),
        ).fetchone()["n"])
        counts = {"votes": 0, "sources": 0, "case_states": 0}
        if batch is not None:
            batch_id = str(batch["id"])
            counts = {
                "votes": int(conn.execute("SELECT COUNT(*) n FROM label_import_votes WHERE batch_id=?", (batch_id,)).fetchone()["n"]),
                "sources": int(conn.execute("SELECT COUNT(*) n FROM label_import_sources WHERE batch_id=?", (batch_id,)).fetchone()["n"]),
                "case_states": int(conn.execute("SELECT COUNT(*) n FROM label_import_case_states WHERE batch_id=?", (batch_id,)).fetchone()["n"]),
            }
    if batch is None:
        errors.append("缺少 legacy-case-label-copy-v2 导入批次。")
        batch_data: dict[str, Any] = {}
    else:
        batch_data = {key: batch[key] for key in batch.keys()}
        if str(batch["status"] or "") != "imported":
            errors.append("历史标签导入批次尚未完成。")
        if str(batch["source_inventory_sha256"] or "") != str(plan.get("source_inventory_sha256") or ""):
            errors.append("源 inventory fingerprint 与导入批次不一致。")
    if active is None:
        errors.append("缺少 active GT snapshot。")
        active_data: dict[str, Any] = {}
    else:
        active_data = {key: active[key] for key in active.keys()}
        if int(active["member_count"] or 0) != issue_count or snapshot_item_count != issue_count:
            errors.append("GT snapshot membership 与数据集 Issue 数不一致。")
    expected_counts = {
        "votes": len(plan.get("votes") or []),
        "sources": sum(
            1 for row in plan.get("rows") or []
            if row.get("derived_label") or str(row.get("review_status") or "") == "needs_gt_review"
        ),
        "case_states": len(plan.get("cases") or []),
    }
    if counts != expected_counts:
        errors.append("imported vote/source/state 数量与 dry-run 不一致。")
    stats = dict(plan.get("stats") or {})
    if batch and _json_load(batch["stats_json"], {}) != stats:
        errors.append("导入批次 stats 与当前 dry-run 不一致。")
    return {
        "passed": not errors,
        "policy_version": MIGRATION_VERSION,
        "baseline_scope": scope,
        "source_inventory_sha256": str(plan.get("source_inventory_sha256") or ""),
        "batch": batch_data,
        "gt_snapshot": active_data,
        "issue_count": issue_count,
        "snapshot_item_count": snapshot_item_count,
        "import_counts": counts,
        "expected_import_counts": expected_counts,
        "stats": stats,
        "errors": errors,
    }


def activate_legacy_label_copy_scope(
    database: Any, *, baseline_scope: str, actor: str
) -> dict[str, Any]:
    scope = str(baseline_scope or "").strip()
    preflight = reconcile_legacy_label_copy_activation(database, baseline_scope=scope)
    result: dict[str, Any] = {
        "passed": False,
        "preflight": preflight,
        "shadow_state": None,
        "reconciliation": None,
        "activation": None,
        "receipt": None,
    }
    if not preflight["passed"]:
        return result
    existing = database.labeling_scope_states([scope])
    if existing and existing[0]["status"] == "active":
        if (
            existing[0]["policy_version"] == MIGRATION_VERSION
            and existing[0]["source_inventory_sha256"] == preflight["source_inventory_sha256"]
        ):
            result.update(passed=True, shadow_state=existing[0], reconciliation=preflight, activation=existing[0])
            return result
        result["preflight"]["errors"].append("该 scope 已由其他 policy 激活。")
        return result
    expected_epoch = int(existing[0]["epoch"] if existing else 0)
    shadow = database.set_labeling_scope_state(
        baseline_scope=scope,
        status="shadow",
        policy_version=MIGRATION_VERSION,
        source_inventory_sha256=preflight["source_inventory_sha256"],
        updated_by=actor,
        expected_epoch=expected_epoch,
    )
    result["shadow_state"] = shadow
    reconciliation = reconcile_legacy_label_copy_activation(database, baseline_scope=scope)
    result["reconciliation"] = reconciliation
    if not reconciliation["passed"]:
        return result

    def verify_inventory(conn: Any) -> str:
        return _source_inventory(_rows_on_connection(conn, [scope]))

    activation = database.activate_labeling_scope(
        baseline_scope=scope,
        policy_version=MIGRATION_VERSION,
        source_inventory_sha256=reconciliation["source_inventory_sha256"],
        updated_by=actor,
        expected_epoch=int(shadow["epoch"]),
        verify_inventory=verify_inventory,
    )
    receipt = database.record_legacy_shadow_receipt(
        baseline_scope=scope,
        component="legacy_label_copy_activation",
        policy_version=MIGRATION_VERSION,
        inventory_sha256=reconciliation["source_inventory_sha256"],
        legacy_count=int(reconciliation["stats"].get("scanned_reviews") or 0),
        canonical_count=int(reconciliation["import_counts"].get("case_states") or 0),
        actor=actor,
    )
    result.update(passed=True, activation=activation, receipt=receipt)
    return result
