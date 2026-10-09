#!/usr/bin/env python3
"""Build a deterministic, guarded 10% Manual S3 PostgreSQL smoke database.

The target must already be a fresh logical restore. The default is dry-run;
``--apply`` is required for pruning. The script refuses non-local connections
and database names that do not contain ``smoke`` or ``manual_s3``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database
from app.db_parts.snapshots import _snapshot_membership_sha


SCOPES = (
    ("0508", "release0508_1071_20260729", "strict"),
    ("0206", "release0206_1326_20260729", "strict"),
    ("0626", "release0626_300_spotcheck", "strict"),
    ("0522", "release0522_100_20260908", "strict"),
    ("0821", "release0821_1242_20260908", "sparse"),
)
POSTGRES_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "postgres"
PIN_ISSUE = "cn35638989"
PIN_RUNS = (
    "d4b519b7-ea35-4589-9139-9e1631403a8b",
    "95dc9002-16cc-46b5-aa13-84dcf0e5db5a",
)
SAFE_DATABASE_RE = re.compile(
    r"^manual_s3_smoke(?:_[a-z0-9][a-z0-9_-]*)?$", re.IGNORECASE
)
SAFE_HOSTS = {"", "127.0.0.1", "::1", "localhost"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", required=True)
    parser.add_argument("--seed", default="manual-s3-v1")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def read_url_file(path: Path) -> str:
    path = path.expanduser().absolute()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("database URL file must be an owned regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("database URL file must be 0600")
        value = os.read(descriptor, 16 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(value) > 16 * 1024:
        raise RuntimeError("database URL file is too large")
    result = value.decode("utf-8").strip()
    if not result:
        raise RuntimeError("database URL file is empty")
    return result


def stable_rank(seed: str, scope: str, issue_id: str) -> str:
    return hashlib.sha256(f"{seed}\0{scope}\0{issue_id}".encode()).hexdigest()


def require_safe_target(database_name: str, host: str) -> None:
    if not SAFE_DATABASE_RE.fullmatch(str(database_name or "")):
        raise RuntimeError(f"refusing unsafe database name: {database_name}")
    if str(host or "") not in SAFE_HOSTS:
        raise RuntimeError(f"refusing non-local database host: {host}")


def selected_table_sql(selected: set[str]) -> tuple[str, list[str]]:
    ordered = sorted(selected)
    return ", ".join("?" for _ in ordered), ordered


def table_exists(connection: Any, table: str) -> bool:
    row = connection.execute(
        "SELECT to_regclass(?) AS name", (f"public.{table}",)
    ).fetchone()
    return bool(row and row["name"])


def table_columns(connection: Any, table: str) -> set[str]:
    rows = connection.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?
        """,
        (table,),
    ).fetchall()
    return {str(row["column_name"]) for row in rows}


def rebuild_split_snapshots(connection: Any) -> None:
    rows = connection.execute(
        "SELECT id FROM issue_work_splits ORDER BY id"
    ).fetchall()
    for row in rows:
        split_id = str(row["id"])
        assignments = connection.execute(
            """
            SELECT assignee, assignment_kind, ordinal, issue_id
            FROM review_work_assignments WHERE split_id = ?
            ORDER BY assignee, ordinal, issue_id
            """,
            (split_id,),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for assignment in assignments:
            grouped.setdefault(str(assignment["assignee"]), []).append(
                {
                    "issue_id": str(assignment["issue_id"]),
                    "assignment_kind": str(assignment["assignment_kind"]),
                    "ordinal": int(assignment["ordinal"]),
                }
            )
        members = [
            {
                "name": name,
                "count": len(items),
                "requested_count": len(items),
                "mode": "fixed",
                "items": items,
            }
            for name, items in grouped.items()
        ]
        connection.execute(
            """
            UPDATE issue_work_splits
            SET total_count = ?, assignment_count = ?, assignees_json = ?
            WHERE id = ?
            """,
            (
                len({str(item["issue_id"]) for item in assignments}),
                len(assignments),
                json.dumps(members, ensure_ascii=False),
                split_id,
            ),
        )


def rebuild_worksets(connection: Any) -> None:
    rows = connection.execute("SELECT id FROM review_worksets ORDER BY id").fetchall()
    for row in rows:
        workset_id = str(row["id"])
        items = connection.execute(
            "SELECT issue_id FROM review_workset_items WHERE workset_id = ? ORDER BY ordinal",
            (workset_id,),
        ).fetchall()
        issue_ids = [str(item["issue_id"]) for item in items]
        connection.execute(
            "UPDATE review_worksets SET member_count = ?, members_sha256 = ? WHERE id = ?",
            (len(issue_ids), _snapshot_membership_sha(issue_ids), workset_id),
        )


def seed_synthetic_stale_label_state(database: Database, issue_id: str) -> dict[str, Any]:
    """Create one explicit smoke-only stale adjudication on a sampled Issue."""

    issue = database.get_issue(issue_id)
    if issue is None:
        raise RuntimeError("synthetic stale-state Issue disappeared")
    identity = hashlib.sha256(f"manual-s3-stale\0{issue_id}".encode()).hexdigest()[:16]
    split_id = f"manual-s3-stale-{identity}"
    now = datetime.now(timezone.utc).isoformat()
    workset = database.create_review_workset(
        baseline_scope=str(issue.get("baseline_scope") or ""),
        issue_ids=[issue_id],
        name="Smoke-only stale-state fixture",
        source_filter={"manual_s3_smoke_synthetic_state": "stale"},
        created_by="manual_s3_smoke_builder",
        created_by_source="smoke",
        created_by_verified=False,
    )
    names = ("manual_s3_smoke_a", "manual_s3_smoke_b")
    split_members = [
        {
            "name": name,
            "count": 1,
            "requested_count": 1,
            "mode": "fixed",
            "items": [
                {
                    "issue_id": issue_id,
                    "assignment_kind": "base" if index == 0 else "cross",
                    "ordinal": 1,
                }
            ],
        }
        for index, name in enumerate(names)
    ]
    with database._write_lock, database.connect() as connection:
        connection.execute(
            """
            INSERT INTO issue_work_splits (
                id, created_by, created_at, seed, total_count, filter_json,
                assignees_json, mode, reviewers_per_issue, model_run_id,
                assignment_count, overlap_ratio, task_kind, workset_id,
                selection_source_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                split_id, "manual_s3_smoke_builder", now, 0, 1,
                json.dumps({"smoke_synthetic_state": "stale"}),
                json.dumps(split_members), "blind", 2, "", 2, 1.0,
                "labeling", str(workset["id"]), "",
            ),
        )
        for index, name in enumerate(names):
            connection.execute(
                """
                INSERT INTO review_work_assignments (
                    split_id, issue_id, assignee, assignment_kind, ordinal,
                    assigned_by, assigned_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(split_id, issue_id, assignee) DO NOTHING
                """,
                (
                    split_id, issue_id, name,
                    "base" if index == 0 else "cross",
                    "manual_s3_smoke_builder", now,
                ),
            )
    first = database.create_label_revision(
        issue_id=issue_id, expected_output="误触发", tags=[], evidence_gaps=[],
        rationale="smoke-only stale-state source A", is_excluded=False,
        author=names[0], author_source="smoke", author_verified=False,
        task_id=split_id, expected_previous_revision_id=None,
    )
    second = database.create_label_revision(
        issue_id=issue_id, expected_output="正确触发", tags=[], evidence_gaps=[],
        rationale="smoke-only stale-state source B", is_excluded=False,
        author=names[1], author_source="smoke", author_verified=False,
        task_id=split_id, expected_previous_revision_id=None,
    )
    label_case_id = str((first.get("label_case") or {}).get("id") or "")
    if not label_case_id:
        raise RuntimeError("synthetic stale-state Label Case was not created")
    database.adjudicate_label_case(
        label_case_id=label_case_id,
        source_revision_ids=[int(first["id"]), int(second["id"])],
        expected_output="误触发", tags=[], evidence_gaps=[],
        rationale="smoke-only adjudication before a later source revision",
        is_excluded=False, actor="manual_s3_smoke_admin",
        actor_source="smoke", actor_verified=False,
        expected_previous_resolution_id=None,
    )
    later = database.create_label_revision(
        issue_id=issue_id, expected_output="无需协助", tags=[], evidence_gaps=[],
        rationale="smoke-only later source revision makes adjudication stale",
        is_excluded=False, author=names[0], author_source="smoke",
        author_verified=False, task_id=split_id,
        expected_previous_revision_id=int(first["id"]),
    )
    state = database.project_issue_label_states(
        str(issue.get("baseline_scope") or ""), [issue_id], include_sources=False
    ).get(issue_id, {})
    if str(state.get("state") or "") != "stale":
        raise RuntimeError("synthetic shared Label state did not resolve to stale")
    return {
        "issue_id": issue_id,
        "baseline_scope": str(issue.get("baseline_scope") or ""),
        "state": "stale",
        "task_id": split_id,
        "source_revision_ids": [int(first["id"]), int(second["id"])],
        "later_revision_id": int(later["id"]),
        "synthetic": True,
    }


def orphan_checks(connection: Any) -> list[dict[str, Any]]:
    constraints = connection.execute(
        """
        SELECT constraint_name, table_name, foreign_table_name,
               column_names, foreign_column_names
        FROM (
            SELECT con.conname AS constraint_name,
                   child.relname AS table_name,
                   parent.relname AS foreign_table_name,
                   ARRAY(
                       SELECT child_att.attname FROM unnest(con.conkey) WITH ORDINALITY key(attnum, ord)
                       JOIN pg_attribute child_att
                         ON child_att.attrelid = con.conrelid AND child_att.attnum = key.attnum
                       ORDER BY key.ord
                   ) AS column_names,
                   ARRAY(
                       SELECT parent_att.attname FROM unnest(con.confkey) WITH ORDINALITY key(attnum, ord)
                       JOIN pg_attribute parent_att
                         ON parent_att.attrelid = con.confrelid AND parent_att.attnum = key.attnum
                       ORDER BY key.ord
                   ) AS foreign_column_names
            FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = child.relnamespace AND ns.nspname = 'public'
            JOIN pg_class parent ON parent.oid = con.confrelid
            WHERE con.contype = 'f'
        ) constraints
        ORDER BY table_name, constraint_name
        """
    ).fetchall()
    failures: list[dict[str, Any]] = []
    for row in constraints:
        child_columns = list(row["column_names"])
        parent_columns = list(row["foreign_column_names"])
        join = " AND ".join(
            f'parent."{parent}" = child."{child}"'
            for child, parent in zip(child_columns, parent_columns)
        )
        nonnull = " AND ".join(f'child."{column}" IS NOT NULL' for column in child_columns)
        first_parent = parent_columns[0]
        count = connection.execute(
            f'''SELECT COUNT(*) AS count FROM "{row["table_name"]}" child
                LEFT JOIN "{row["foreign_table_name"]}" parent ON {join}
                WHERE {nonnull} AND parent."{first_parent}" IS NULL'''
        ).fetchone()["count"]
        if int(count or 0):
            failures.append(
                {"constraint": str(row["constraint_name"]), "count": int(count)}
            )
    return failures


def main() -> int:
    args = parse_args()
    database = Database(
        read_url_file(Path(args.database_url_file)),
        postgres_migrations_dir=POSTGRES_MIGRATIONS_DIR,
        pool_size=2,
    )
    manifest_path = Path(args.manifest).expanduser().absolute()
    try:
        with database.connect() as connection:
            identity = connection.execute(
                "SELECT current_database() AS name, COALESCE(inet_server_addr()::text, '') AS host"
            ).fetchone()
            previous_smoke = connection.execute(
                "SELECT COUNT(*) AS count FROM gt_sync_state WHERE message = 'manual_s3 smoke subset'"
            ).fetchone()
        db_name = str(identity["name"] or "")
        host = str(identity["host"] or "")
        require_safe_target(db_name, host)
        if int(previous_smoke["count"] or 0):
            raise RuntimeError("target already contains a smoke subset; restore a fresh logical backup first")

        if args.apply:
            database.init()
        with database.connect() as connection:
            scope_rows: dict[str, list[str]] = {}
            source_snapshots: dict[str, str] = {}
            selected: set[str] = set()
            hash_samples: dict[str, list[str]] = {}
            for baseline_id, scope, _mode in SCOPES:
                rows = connection.execute(
                    "SELECT issue_id FROM issues WHERE baseline_scope = ? ORDER BY issue_id",
                    (scope,),
                ).fetchall()
                issue_ids = [str(row["issue_id"]) for row in rows]
                scope_rows[scope] = issue_ids
                target = max(1, round(len(issue_ids) * 0.10))
                sampled = sorted(issue_ids, key=lambda value: stable_rank(args.seed, scope, value))[:target]
                hash_samples[scope] = sampled
                selected.update(sampled)
                active = connection.execute(
                    "SELECT snapshot_id FROM gt_snapshot_active WHERE baseline_scope = ?",
                    (scope,),
                ).fetchone()
                source_snapshots[scope] = str(active["snapshot_id"] or "") if active else ""

            pinned: dict[str, list[str]] = {
                "explicit_issue": [], "run_overlap": [], "label_states": [],
                "no_gt": [], "model_review_task": [], "case_labeling_task": [],
            }
            explicit = connection.execute(
                "SELECT issue_id FROM issues WHERE issue_id = ? AND baseline_scope IN (?, ?, ?, ?, ?)",
                (PIN_ISSUE, *(scope for _baseline_id, scope, _mode in SCOPES)),
            ).fetchone()
            if explicit is None:
                raise RuntimeError(
                    f"required pinned Issue is missing from smoke scopes: {PIN_ISSUE}"
                )
            pinned["explicit_issue"].append(PIN_ISSUE)
            selected.add(PIN_ISSUE)
            overlap = connection.execute(
                """
                SELECT left_prediction.issue_id
                FROM model_predictions left_prediction
                JOIN model_predictions right_prediction
                  ON right_prediction.issue_id = left_prediction.issue_id
                JOIN issues issue ON issue.issue_id = left_prediction.issue_id
                WHERE left_prediction.model_run_id = ? AND right_prediction.model_run_id = ?
                  AND issue.baseline_scope IN (?, ?, ?, ?, ?)
                ORDER BY left_prediction.issue_id
                """,
                (*PIN_RUNS, *(scope for _baseline_id, scope, _mode in SCOPES)),
            ).fetchall()
            overlap_ids = [str(row["issue_id"]) for row in overlap]
            if not overlap_ids:
                raise RuntimeError(
                    "required pinned Run overlap is missing from the five smoke scopes"
                )
            pinned["run_overlap"] = [
                min(
                    overlap_ids,
                    key=lambda issue_id: stable_rank(
                        args.seed, "pinned-run-overlap", issue_id
                    ),
                )
            ]
            selected.update(pinned["run_overlap"])

            all_ids = [item for values in scope_rows.values() for item in values]
            states_by_issue: dict[str, str] = {}
            for _baseline_id, scope, _mode in SCOPES:
                projections = database.project_issue_label_states(
                    scope, scope_rows[scope], include_sources=False
                )
                for issue_id, projection in projections.items():
                    states_by_issue[issue_id] = str(projection.get("state") or "none")
            required_states = ("resolved", "conflict", "pending", "stale")
            synthetic_label_states: list[dict[str, Any]] = []
            for state in required_states:
                candidate = next(
                    (issue_id for issue_id in all_ids if states_by_issue.get(issue_id) == state),
                    "",
                )
                synthetic = False
                if not candidate and state == "stale":
                    eligible = [
                        issue_id for issue_id in all_ids
                        if states_by_issue.get(issue_id, "none") not in {"resolved", "conflict", "pending"}
                    ]
                    if not eligible:
                        eligible = [
                            issue_id for issue_id in all_ids
                            if issue_id not in pinned["label_states"]
                        ]
                    candidate = min(
                        eligible,
                        key=lambda issue_id: stable_rank(
                            args.seed, "synthetic-stale-label", issue_id
                        ),
                    ) if eligible else ""
                    synthetic = bool(candidate)
                if not candidate:
                    raise RuntimeError(f"required shared Label state is missing: {state}")
                pinned["label_states"].append(candidate)
                selected.add(candidate)
                if synthetic:
                    synthetic_label_states.append({
                        "state": state, "issue_id": candidate,
                        "synthetic": True,
                    })
            no_gt = connection.execute(
                """
                SELECT issue_id FROM issues
                WHERE baseline_scope IN (?, ?, ?, ?, ?) AND COALESCE(gt_label, '') = ''
                ORDER BY issue_id LIMIT 1
                """,
                tuple(scope for _baseline_id, scope, _mode in SCOPES),
            ).fetchone()
            if no_gt:
                pinned["no_gt"].append(str(no_gt["issue_id"]))
                selected.add(str(no_gt["issue_id"]))
            else:
                raise RuntimeError("required sparse-scope no-GT Issue is missing")
            model_task = connection.execute(
                """
                SELECT assignment.issue_id FROM review_work_assignments assignment
                JOIN issue_work_splits split ON split.id = assignment.split_id
                JOIN issues issue ON issue.issue_id = assignment.issue_id
                WHERE TRIM(split.model_run_id) != ''
                  AND issue.baseline_scope IN (?, ?, ?, ?, ?)
                ORDER BY split.created_at DESC LIMIT 1
                """,
                tuple(scope for _baseline_id, scope, _mode in SCOPES),
            ).fetchone()
            if model_task is None:
                raise RuntimeError("required Run-bound model-review task Issue is missing from smoke scopes")
            pinned["model_review_task"].append(str(model_task["issue_id"]))
            selected.add(str(model_task["issue_id"]))
            label_task = connection.execute(
                """
                SELECT label_case.issue_id FROM label_cases label_case
                JOIN issues issue ON issue.issue_id = label_case.issue_id
                WHERE TRIM(label_case.task_id) != ''
                  AND issue.baseline_scope IN (?, ?, ?, ?, ?)
                ORDER BY label_case.created_at DESC LIMIT 1
                """,
                tuple(scope for _baseline_id, scope, _mode in SCOPES),
            ).fetchone()
            if label_task is None:
                raise RuntimeError("required Case-labeling task Issue is missing from smoke scopes")
            pinned["case_labeling_task"].append(str(label_task["issue_id"]))
            selected.add(str(label_task["issue_id"]))

            selected.intersection_update(all_ids)
            placeholders, selected_params = selected_table_sql(selected)
            per_scope = []
            for baseline_id, scope, _mode in SCOPES:
                hash_set = set(hash_samples[scope])
                final_ids = sorted(set(scope_rows[scope]).intersection(selected))
                additions = sorted(set(final_ids) - hash_set)
                per_scope.append(
                    {
                        "baseline_id": baseline_id,
                        "scope": scope,
                        "original_count": len(scope_rows[scope]),
                        "hash_sample_count": len(hash_set),
                        "pinned_addition_count": len(additions),
                        "final_count": len(final_ids),
                        "issue_ids_sha256": _snapshot_membership_sha(final_ids),
                        "hash_sample_issue_ids": sorted(hash_set),
                        "pinned_addition_issue_ids": additions,
                        "source_snapshot_id": source_snapshots[scope],
                    }
                )
            manifest = {
                "schema": "manual-s3-smoke-v1",
                "database": db_name,
                "host": host or "local_socket",
                "seed": args.seed,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "apply": bool(args.apply),
                "scopes": per_scope,
                "pins": pinned,
                "synthetic_label_states": synthetic_label_states,
                "selected_issue_count": len(selected),
                "selected_issue_ids_sha256": _snapshot_membership_sha(sorted(selected)),
                "source_run_ids": list(PIN_RUNS),
            }
            if not args.apply:
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
                return 0

            # All following operations are inside the already verified smoke DB.
            for table in (
                "review_notifications", "comment_notifications",
                "intent_comment_notifications", "batch_prediction_items",
                "batch_prediction_jobs", "inference_jobs",
                "label_result_snapshot_sources", "label_result_snapshot_items",
                "label_result_snapshots", "label_gt_export_source_snapshots",
                "label_gt_export_items", "label_gt_export_batches",
                "model_review_attachments", "label_attachments",
                "review_attachments", "comment_attachments",
            ):
                if table_exists(connection, table):
                    connection.execute(f'DELETE FROM "{table}"')

            connection.execute(
                f"DELETE FROM label_comment_links WHERE issue_id NOT IN ({placeholders})",
                selected_params,
            )
            connection.execute(
                f"DELETE FROM label_resolutions WHERE label_case_id IN "
                f"(SELECT id FROM label_cases WHERE issue_id NOT IN ({placeholders}))",
                selected_params,
            )
            connection.execute(
                f"DELETE FROM label_revisions WHERE label_case_id IN "
                f"(SELECT id FROM label_cases WHERE issue_id NOT IN ({placeholders}))",
                selected_params,
            )
            connection.execute(
                f"DELETE FROM label_cases WHERE issue_id NOT IN ({placeholders})",
                selected_params,
            )
            for table in (
                "model_review_heads", "model_review_revisions", "review_comments",
                "annotations", "model_predictions", "review_work_assignment_changes",
                "review_work_assignments", "review_workset_items",
                "issue_work_assignments", "gt_sync_labels",
                "trail_issue_exclusion_history",
            ):
                if table_exists(connection, table) and "issue_id" in table_columns(connection, table):
                    connection.execute(
                        f'DELETE FROM "{table}" WHERE issue_id NOT IN ({placeholders})',
                        selected_params,
                    )

            # Intent state is a separate product dataset; do not retain unrelated rows.
            for table in (
                "intent_user_label_heads", "intent_label_heads", "intent_label_deletions",
                "intent_frame_overrides", "intent_label_revisions",
                "intent_experiment_assignments", "intent_experiment_updates",
                "intent_experiments", "intent_case_comments",
            ):
                if table_exists(connection, table):
                    connection.execute(f'DELETE FROM "{table}"')

            connection.execute("DELETE FROM issue_work_splits WHERE id NOT IN (SELECT DISTINCT split_id FROM review_work_assignments)")
            connection.execute("DELETE FROM review_worksets WHERE id NOT IN (SELECT DISTINCT workset_id FROM review_workset_items)")
            rebuild_split_snapshots(connection)
            rebuild_worksets(connection)
            connection.execute(
                """
                DELETE FROM label_migration_map
                WHERE (target_table = 'label_revisions' AND target_id NOT IN (
                    SELECT CAST(id AS text) FROM label_revisions
                )) OR (target_table = 'review_worksets' AND target_id NOT IN (
                    SELECT id FROM review_worksets
                )) OR (source_table = 'issue_work_splits' AND source_id NOT IN (
                    SELECT id FROM issue_work_splits
                )) OR (source_table = 'annotations' AND source_id NOT IN (
                    SELECT CAST(id AS text) FROM annotations
                ))
                """
            )

            # Snapshot item rows hold restrictive Issue FKs. Drop the active
            # pointers and the full-restore facts before pruning Issues.
            connection.execute("DELETE FROM gt_snapshot_active")
            connection.execute("DELETE FROM gt_snapshot_items")
            connection.execute("DELETE FROM gt_snapshots")

            connection.execute(
                f"DELETE FROM issues WHERE issue_id NOT IN ({placeholders})",
                selected_params,
            )
            connection.execute(
                """
                DELETE FROM model_runs run WHERE NOT EXISTS (
                    SELECT 1 FROM model_predictions prediction WHERE prediction.model_run_id = run.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM annotations annotation WHERE annotation.model_run_id = run.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM review_comments comment WHERE comment.model_run_id = run.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM issue_work_splits split WHERE split.model_run_id = run.id
                       OR split.selection_source_run_id = run.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM model_review_revisions review WHERE review.model_run_id = run.id
                )
                """
            )
            connection.execute("DELETE FROM access_users")
            connection.execute("DELETE FROM mention_users")
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO access_users (
                    username, role, created_by, created_at, updated_at
                ) VALUES ('manual_s3_smoke_admin', 'admin', 'smoke-builder', ?, ?)
                """,
                (now, now),
            )

            # Existing full-data snapshots/export references cannot claim subset coverage.
            for _baseline_id, scope, _mode in SCOPES:
                scoped = sorted(set(scope_rows[scope]).intersection(selected))
                valid_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM issues WHERE baseline_scope = ? AND COALESCE(gt_label, '') != ''",
                    (scope,),
                ).fetchone()["count"]
                smoke_source_sha = hashlib.sha256(
                    f"{args.seed}\0{scope}\0{_snapshot_membership_sha(scoped)}".encode()
                ).hexdigest()
                connection.execute(
                    """
                    UPDATE gt_sync_state SET status = 'ready', source_sha256 = ?,
                        source_row_count = ?, message = 'manual_s3 smoke subset',
                        error_text = '' WHERE baseline_scope = ?
                    """,
                    (smoke_source_sha, int(valid_count or 0), scope),
                )

        for synthetic_state in manifest.get("synthetic_label_states", []):
            seeded = seed_synthetic_stale_label_state(
                database, str(synthetic_state["issue_id"])
            )
            synthetic_state.update(seeded)

        # Create content-addressed smoke GT snapshots after the prune transaction commits.
        for _baseline_id, scope, mode in SCOPES:
            scoped = sorted(set(scope_rows[scope]).intersection(selected))
            snapshot = database.create_gt_snapshot_from_current(
                scope=scope,
                gt_mode=mode,
                created_by="manual_s3_smoke_builder",
                created_by_source="smoke",
                created_by_verified=False,
                activation_reason="manual_s3_smoke_subset",
                expected_member_count=len(scoped),
                expected_membership_sha256=_snapshot_membership_sha(scoped),
            )
            manifest_scope = next(item for item in manifest["scopes"] if item["scope"] == scope)
            manifest_scope["smoke_snapshot_id"] = snapshot["id"]
            manifest_scope["smoke_snapshot_content_sha256"] = snapshot["content_sha256"]

        with database.connect() as connection:
            failures = orphan_checks(connection)
            unselected_refs: dict[str, int] = {}
            tables = connection.execute(
                """
                SELECT table_name FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'issue_id'
                ORDER BY table_name
                """
            ).fetchall()
            for row in tables:
                table = str(row["table_name"])
                count = connection.execute(
                    f'SELECT COUNT(*) AS count FROM "{table}" WHERE issue_id NOT IN ({placeholders})',
                    selected_params,
                ).fetchone()["count"]
                if int(count or 0):
                    unselected_refs[table] = int(count)
            if failures or unselected_refs:
                raise RuntimeError(
                    f"smoke integrity failed: orphans={failures} unselected={unselected_refs}"
                )
            manifest["foreign_key_orphans"] = failures
            manifest["unselected_issue_references"] = unselected_refs
            manifest["final_table_counts"] = {
                table: int(connection.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()["count"])
                for table in ("issues", "model_runs", "model_predictions", "annotations", "review_comments", "label_cases", "label_revisions", "gt_snapshots", "gt_snapshot_items")
                if table_exists(connection, table)
            }

        manifest_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, manifest_path)
        os.chmod(manifest_path, 0o600)
        print(json.dumps({
            "status": "applied", "database": db_name,
            "selected_issue_count": len(selected),
            "manifest": str(manifest_path),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        }, ensure_ascii=False))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
