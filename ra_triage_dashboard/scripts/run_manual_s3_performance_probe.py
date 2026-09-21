#!/usr/bin/env python3
"""Measure five-scope 5000+ Review queries on a disposable logical clone."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database


SCOPES = (
    "release0508_1071_20260729",
    "release0206_1326_20260729",
    "release0626_300_spotcheck",
    "release0522_100_20260908",
    "release0821_1242_20260908",
)
EXPECTED_SCOPE_COUNTS = {
    "release0508_1071_20260729": 1071,
    "release0206_1326_20260729": 1326,
    "release0626_300_spotcheck": 300,
    "release0522_100_20260908": 100,
    "release0821_1242_20260908": 1242,
}
SAFE_DATABASE_RE = re.compile(r"^manual_s3_perf(?:_[a-z0-9][a-z0-9_-]*)?$", re.IGNORECASE)
SAFE_HOSTS = {"", "127.0.0.1", "::1", "localhost"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--probe-count", type=int, default=5001)
    return parser.parse_args()


def read_url_file(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("performance database URL file must be an owned regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("performance database URL file must be 0600")
        raw = os.read(descriptor, 16 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(raw) > 16 * 1024:
        raise RuntimeError("performance database URL file is too large")
    return raw.decode("utf-8").strip()


def _walk_plan(node: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    nodes.append(
        {
            key: node[key]
            for key in (
                "Node Type",
                "Relation Name",
                "Index Name",
                "Plan Rows",
                "Actual Rows",
                "Actual Total Time",
                "Rows Removed by Filter",
            )
            if key in node
        }
    )
    for child in node.get("Plans") or []:
        _walk_plan(child, nodes)


def main() -> int:
    args = parse_args()
    if args.probe_count <= 5000:
        raise ValueError("probe-count must exceed 5000")
    database = Database(
        read_url_file(Path(args.database_url_file)),
        postgres_migrations_dir=Path(__file__).resolve().parents[1] / "migrations" / "postgres",
        pool_size=4,
    )
    temp_scope = "manual_s3_perf_probe"
    try:
        with database.connect() as connection:
            identity = connection.execute(
                "SELECT current_database() AS name, COALESCE(inet_server_addr()::text, '') AS host"
            ).fetchone()
        db_name = str(identity["name"] or "")
        host = str(identity["host"] or "")
        if not SAFE_DATABASE_RE.fullmatch(db_name) or host not in SAFE_HOSTS:
            raise RuntimeError("refusing a non-performance-copy database target")

        # Refuse a sampled smoke database: this probe requires all five full
        # immutable source scopes from the verified logical backup.
        with database.connect() as connection:
            source_migration_count = int(
                connection.execute("SELECT COUNT(*) AS n FROM dashboard_schema_migrations").fetchone()["n"]
            )
            before_scope_counts = {
                scope: int(connection.execute(
                    "SELECT COUNT(*) AS n FROM issues WHERE baseline_scope=?", (scope,)
                ).fetchone()["n"])
                for scope in SCOPES
            }
        if source_migration_count != 43 or before_scope_counts != EXPECTED_SCOPE_COUNTS:
            raise RuntimeError("performance target is not the full migration-043 five-scope restore")

        # The full logical restore starts at S2 (migration 043); the disposable
        # copy receives the candidate S3 migration before planning the S3 view.
        database.init()
        run = ""
        with database.connect() as connection:
            migration_count = int(
                connection.execute("SELECT COUNT(*) AS n FROM dashboard_schema_migrations").fetchone()["n"]
            )
            if migration_count != 44:
                raise RuntimeError("performance clone did not apply exactly through candidate migration 044")
            run_row = connection.execute(
                "SELECT model_run_id AS id FROM issue_work_splits WHERE TRIM(model_run_id) != '' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if run_row:
                run = str(run_row["id"] or "")
            if not run:
                run_row = connection.execute("SELECT id FROM model_runs ORDER BY created_at DESC LIMIT 1").fetchone()
                run = str(run_row["id"] or "") if run_row else ""
        if not run:
            raise RuntimeError("full logical performance clone contains no Model Run")

        probe_ids = [f"cn990{index:08d}" for index in range(int(args.probe_count))]
        with database.connect() as connection:
            for offset in range(0, len(probe_ids), 400):
                batch = probe_ids[offset : offset + 400]
                count = int(connection.execute(
                    f"SELECT COUNT(*) AS n FROM issues WHERE issue_id IN ({', '.join('?' for _ in batch)})",
                    batch,
                ).fetchone()["n"])
                if count:
                    raise RuntimeError("synthetic performance IDs collide with the restored source")

        probe_rows_by_scope = {scope: [] for scope in SCOPES}
        for index, issue_id in enumerate(probe_ids):
            scope = SCOPES[index % len(SCOPES)]
            probe_rows_by_scope[scope].append(
                {"issue_id": issue_id, "gt_label": "误触发", "gt_source": "s3_perf_probe"}
            )

        try:
            insert_started = time.perf_counter()
            for scope, rows in probe_rows_by_scope.items():
                for offset in range(0, len(rows), 400):
                    batch = rows[offset : offset + 400]
                    result = database.upsert_issues(
                        batch,
                        source="manual_s3_perf_probe",
                        replace_gt=False,
                        baseline_scope=scope,
                    )
                    if int(result.get("inserted") or 0) != len(batch):
                        raise AssertionError("not all synthetic performance rows were inserted")
            insert_seconds = time.perf_counter() - insert_started

            with database.connect() as connection:
                for table in ("issues", "model_predictions", "annotations", "model_review_revisions", "model_review_heads"):
                    connection.execute(f"ANALYZE {table}")

            page_started = time.perf_counter()
            page = database.list_cases(
                baseline_scopes=SCOPES, model_run_id=run, page=1, page_size=100
            )
            page_seconds = time.perf_counter() - page_started
            stream_started = time.perf_counter()
            batch_count = max_batch = streamed = 0
            for batch in database.iter_case_review_candidate_batches(
                batch_size=400, baseline_scopes=SCOPES, model_run_id=run
            ):
                batch_count += 1
                max_batch = max(max_batch, len(batch))
                streamed += len(batch)
            stream_seconds = time.perf_counter() - stream_started

            condition, params, model_args, common = database._case_list_filters(
                baseline_scopes=SCOPES,
                model_run_id=run,
            )
            explain_sql = (
                f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                f"SELECT i.issue_id {common} {condition} ORDER BY i.issue_id ASC LIMIT ?"
            )
            with database.connect() as connection:
                explain_value = connection.execute(
                    explain_sql, (*model_args, *params, 100)
                ).fetchone()[0]
            if isinstance(explain_value, str):
                explain_value = json.loads(explain_value)
            explain_root = explain_value[0]
            plan_nodes: list[dict[str, Any]] = []
            _walk_plan(explain_root["Plan"], plan_nodes)
            status_filtered = database.list_cases(
                baseline_scopes=SCOPES,
                model_run_id=run,
                model_review_status="completed",
                page=1,
                page_size=100,
            )
            expected_candidates = sum(before_scope_counts.values()) + len(probe_ids)
            if int(page["total"]) != expected_candidates or streamed != expected_candidates:
                raise AssertionError("five-scope query did not return the full 5000+ candidate set")
            if len(page["items"]) != 100 or max_batch > 400:
                raise AssertionError("page/keyset bounds or status filter failed")
        finally:
            for offset in range(0, len(probe_ids), 400):
                batch = probe_ids[offset : offset + 400]
                with database.connect() as connection:
                    connection.execute(
                        f"DELETE FROM issues WHERE issue_id IN ({', '.join('?' for _ in batch)})",
                        batch,
                    )

        with database.connect() as connection:
            remaining = int(connection.execute(
                "SELECT COUNT(*) AS n FROM issues WHERE LEFT(issue_id, 5) = 'cn990' AND source='manual_s3_perf_probe'"
            ).fetchone()["n"])
            after_scope_counts = {
                scope: int(connection.execute(
                    "SELECT COUNT(*) AS n FROM issues WHERE baseline_scope=?", (scope,)
                ).fetchone()["n"])
                for scope in SCOPES
            }
        if remaining or after_scope_counts != before_scope_counts:
            raise AssertionError("performance probe rows were not fully cleaned")
        report = {
            "schema": "manual-s3-performance-probe-v1",
            "database": db_name,
            "host": host or "local_socket",
            "migration_count": migration_count,
            "scope_candidate_counts_before": before_scope_counts,
            "five_scope_source_candidates": sum(before_scope_counts.values()),
            "synthetic_candidate_count": len(probe_ids),
            "candidate_count": int(page["total"]),
            "page_items": len(page["items"]),
            "batch_count": batch_count,
            "max_batch": max_batch,
            "keyset_candidate_count": streamed,
            "insert_seconds": round(insert_seconds, 3),
            "page_seconds": round(page_seconds, 3),
            "keyset_scan_seconds": round(stream_seconds, 3),
            "status_filtered_candidate_count": int(status_filtered["total"]),
            "explain": {
                "query_shape": "five-scope selected-Run candidate page without a Review-status predicate",
                "planning_ms": float(explain_root.get("Planning Time") or 0),
                "execution_ms": float(explain_root.get("Execution Time") or 0),
                "index_names": sorted({str(node.get("Index Name")) for node in plan_nodes if node.get("Index Name")}),
                "node_types": sorted({str(node.get("Node Type")) for node in plan_nodes}),
                "nodes": plan_nodes,
            },
            "probe_rows_after_cleanup": remaining,
            "scope_counts_restored": after_scope_counts == before_scope_counts,
        }
        output = Path(args.output).expanduser().absolute()
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
        os.chmod(output, 0o600)
        print(json.dumps({"status": "passed", "output": str(output), "candidate_count": report["candidate_count"], "page_seconds": report["page_seconds"], "keyset_scan_seconds": report["keyset_scan_seconds"], "explain_execution_ms": report["explain"]["execution_ms"], "index_names": report["explain"]["index_names"], "max_batch": max_batch}, ensure_ascii=False))
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
