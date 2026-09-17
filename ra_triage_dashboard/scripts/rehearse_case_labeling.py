#!/usr/bin/env python3
"""Restore a verified cloud backup and rehearse Case-labeling end to end.

Backfill, reconciliation and the M6 activation cutover all run inside one
disposable database restored from the backup; production is never written.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import uuid4


APP_ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = Path("/volume/home/workspace/ra_triage_dashboard_data/postgres_backups")
REPORT_ROOT = Path("/volume/home/workspace/ra_triage_dashboard_deploy/labeling-rehearsals")
PRESERVED_TABLES = (
    "issues", "annotations", "review_attachments", "review_comments",
    "comment_attachments", "model_runs", "model_predictions",
    "review_work_assignments", "review_work_assignment_changes",
    "review_notifications", "comment_notifications",
)


def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(arg) for arg in args], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_digest(connection: object) -> dict[str, dict[str, object]]:
    """Hash original rows without emitting their content into reports."""
    from psycopg import sql

    result = {}
    for table in (*PRESERVED_TABLES, "issue_work_splits"):
        # The legacy Split remains the task identity; only the three additive
        # binding columns may change during backfill.
        projection = "to_jsonb(source)"
        if table == "issue_work_splits":
            projection += " - 'task_kind' - 'workset_id' - 'selection_source_run_id'"
        query = sql.SQL("SELECT ({projection})::text FROM {table} source ORDER BY 1").format(
            projection=sql.SQL(projection), table=sql.Identifier(table)
        )
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(query):
            digest.update(row[0].encode("utf-8"))
            digest.update(b"\n")
            count += 1
        result[table] = {"count": count, "sha256": digest.hexdigest()}
    return result


def verify_attachment_files(connection: object, scopes: list[str], data_dir: Path) -> dict:
    checked, errors = 0, []
    for attachment_table, owner_table, owner_key in (
        ("review_attachments", "annotations", "annotation_id"),
        ("comment_attachments", "review_comments", "comment_id"),
    ):
        # Table names are fixed above; user input is always parameterized.
        rows = connection.execute(
            f"""SELECT attachment.id, attachment.stored_name,
                       attachment.size_bytes, attachment.sha256
                FROM {attachment_table} attachment
                JOIN {owner_table} owner ON owner.id = attachment.{owner_key}
                JOIN issues issue ON issue.issue_id = owner.issue_id
                WHERE issue.baseline_scope = ANY(%s) ORDER BY attachment.id""",
            (scopes,),
        )
        root = (data_dir / attachment_table).resolve()
        for attachment_id, stored_name, size_bytes, sha256 in rows:
            path = (root / stored_name).resolve()
            valid = (
                path.is_relative_to(root) and path.is_file()
                and path.stat().st_size == size_bytes
                and sha256_file(path) == sha256
            )
            checked += 1
            if not valid:
                errors.append({"table": attachment_table, "id": str(attachment_id)})
    return {"checked": checked, "passed": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--datasets", default="0522")
    parser.add_argument("--policy-version", default="case-labeling-v1")
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    if backup.parent != BACKUP_ROOT or not re.fullmatch(
        r"ra_triage_dashboard-\d{8}T\d{6}Z\.dump", backup.name
    ):
        parser.error("backup must be an exact Dashboard dump under the cloud backup root")
    config_path = args.runtime_config.resolve(strict=True)
    metadata = config_path.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        parser.error("runtime config must belong to this user and have mode 0600")
    if set(args.datasets.split(",")) - {"0522", "0626", "0821"}:
        parser.error("only confirmed labeling datasets 0522,0626,0821 may be rehearsed")
    if run("git", "status", "--porcelain", cwd=APP_ROOT.parent).stdout.strip():
        parser.error("rehearsal requires a clean committed checkout")
    code_sha = run("git", "rev-parse", "HEAD", cwd=APP_ROOT.parent).stdout.strip()
    checksum = Path(str(backup) + ".sha256").read_text().split()[0]
    if sha256_file(backup) != checksum:
        parser.error("backup checksum mismatch")
    run("pg_restore", "--list", backup)

    runtime = json.loads(config_path.read_text())
    original_env = runtime["env"]
    production_data_dir = Path(original_env["DASHBOARD_DATA_DIR"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:8]
    database_name = f"ra_label_rehearsal_{stamp.lower()}_{suffix}"
    REPORT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    report_dir = Path(tempfile.mkdtemp(prefix=f"{stamp}-{suffix}-", dir=REPORT_ROOT))
    report: dict = {
        "code_sha": code_sha, "backup": str(backup), "backup_sha256": checksum,
        "datasets": args.datasets.split(","), "policy_version": args.policy_version,
        "disposable_database": database_name, "passed": False,
        "production_backfill": False, "production_activation": False,
    }
    created = False
    try:
        run("sudo", "-n", "-u", "postgres", "createdb", "--template", "template0",
            "--owner", getpass.getuser(), database_name)
        created = True
        run("pg_restore", "--dbname", database_name, "--no-owner",
            "--no-privileges", "--exit-on-error", backup)
        import psycopg

        database_url = f"postgresql:///{database_name}"
        with psycopg.connect(database_url) as connection:
            report["source_before"] = source_digest(connection)
            scope_table_exists = connection.execute(
                "SELECT to_regclass('public.labeling_scope_state') IS NOT NULL"
            ).fetchone()[0]
            scope_states_before = (
                dict(connection.execute(
                    "SELECT baseline_scope, to_jsonb(state) FROM labeling_scope_state state"
                ).fetchall()) if scope_table_exists else {}
            )

        env = dict(original_env)
        env.update(
            DASHBOARD_DATABASE_URL=database_url, DASHBOARD_DATABASE_URL_FILE="",
            DASHBOARD_DATA_DIR=str(report_dir / "data"),
            DASHBOARD_POSTGRES_PERSISTENT_DATA="false",
            DASHBOARD_BUILD_COMMIT=code_sha,
            DASHBOARD_DCHAT_CREDENTIALS_FILE="", DASHBOARD_BOOTSTRAP_MODEL_JSON="",
        )
        for key in (
            "DASHBOARD_SYNC_TRAIL_ON_START", "DASHBOARD_BATCH_PREDICTION_ENABLED",
            "DASHBOARD_AUTOTRIAGE_PUSH_ENABLED", "DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED",
            "DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED",
            "DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED",
        ):
            env[key] = "false"
        script = APP_ROOT / "scripts/migrate_case_labeling.py"
        backfill_counts = []
        for mode in ("plan", "backfill", "reconcile", "backfill", "reconcile"):
            command = [sys.executable, script, mode, "--datasets", args.datasets,
                       "--policy-version", args.policy_version]
            if mode == "backfill":
                command.extend(["--apply", "--actor", "rehearsal"])
            output = run(*command, cwd=APP_ROOT, env=env)
            key = mode if mode not in report else mode + "_repeat"
            report[key] = json.loads(output.stdout)
            if mode == "backfill":
                with psycopg.connect(database_url) as connection:
                    backfill_counts.append({
                        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                        for table in (
                            "label_cases", "label_revisions", "label_attachments",
                            "label_comment_links", "label_migration_map", "review_worksets",
                            "review_workset_items", "label_resolutions",
                        )
                    })
        scopes = report["plan"]["baseline_scopes"]
        # M6 rehearsal: flip every rehearsed scope to active inside the
        # disposable database, proving the atomic epoch/fingerprint cutover
        # on a real restored copy before any production activation.
        activation_results = []
        states_by_scope = {
            str(state["baseline_scope"]): state
            for state in report["reconcile"]["reconciliation"]["scope_states"]
        }
        for dataset_id, scope in zip(report["plan"]["dataset_ids"], scopes):
            state = states_by_scope.get(scope)
            if state is None:
                activation_results.append({
                    "dataset": dataset_id, "baseline_scope": scope, "passed": False,
                    "errors": ["缺少回填状态。"],
                })
                continue
            output = run(
                sys.executable, script, "activate", "--datasets", dataset_id,
                "--policy-version", args.policy_version, "--apply",
                "--actor", "rehearsal", "--expected-epoch", str(state["epoch"]),
                cwd=APP_ROOT, env=env,
            )
            activation = json.loads(output.stdout)["activation"]
            activation_results.append(activation)
        report["activation_rehearsal"] = activation_results
        with psycopg.connect(database_url) as connection:
            report["source_after"] = source_digest(connection)
            report["attachments"] = verify_attachment_files(
                connection, scopes, production_data_dir
            )
            report["label_revision_count"] = connection.execute(
                "SELECT count(*) FROM label_revisions"
            ).fetchone()[0]
            report["active_scope_count"] = connection.execute(
                "SELECT count(*) FROM labeling_scope_state WHERE status = 'active' "
                "AND baseline_scope = ANY(%s)", (scopes,),
            ).fetchone()[0]
            scope_states_after = dict(connection.execute(
                "SELECT baseline_scope, to_jsonb(state) FROM labeling_scope_state state"
            ).fetchall())
        report["unrelated_scope_states_unchanged"] = (
            {key: value for key, value in scope_states_before.items() if key not in scopes}
            == {key: value for key, value in scope_states_after.items() if key not in scopes}
        )
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        report["backfill_counts"] = backfill_counts
        report["idempotent_counts"] = backfill_counts[0] == backfill_counts[1]
        report["passed"] = all((
            report["source_unchanged"], report["attachments"]["passed"],
            report["idempotent_counts"],
            report["unrelated_scope_states_unchanged"],
            report["reconcile"]["reconciliation"]["passed"],
            report["reconcile_repeat"]["reconciliation"]["passed"],
            all(item["passed"] for item in activation_results),
            report["active_scope_count"] == len(scopes),
        ))
    except Exception as exc:
        # stderr may contain raw imported values or settings; retain only the
        # error category and failed executable, never credentials or row text.
        report["error_type"] = type(exc).__name__
        if isinstance(exc, subprocess.CalledProcessError):
            report["failed_executable"] = str(exc.cmd[0])
            report["exit_code"] = exc.returncode
            # Full diagnostic content stays on the cloud in a private file.
            diagnostic = report_dir / "step-error.log"
            with diagnostic.open("x") as stream:
                os.chmod(diagnostic, 0o600)
                stream.write(exc.stderr or "")
                stream.write(exc.stdout or "")
    finally:
        if created:
            try:
                run("sudo", "-n", "-u", "postgres", "dropdb", database_name)
                report["disposable_database_removed"] = True
            except Exception as cleanup_error:
                report["disposable_database_removed"] = False
                report["cleanup_error_type"] = type(cleanup_error).__name__
                report["passed"] = False
        report_path = report_dir / "report.json"
        with report_path.open("x") as stream:
            os.chmod(report_path, 0o600)
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({
            "passed": report["passed"], "report": str(report_path),
            "code_sha": code_sha, "production_backfill": False,
            "production_activation": False,
        }, ensure_ascii=False))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
