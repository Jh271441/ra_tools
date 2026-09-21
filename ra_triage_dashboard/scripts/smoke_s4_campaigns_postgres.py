#!/usr/bin/env python3
"""Run S4 Campaign smoke fixtures against a disposable PostgreSQL S4 clone.

This runner refuses the primary S4 smoke DB, S3, production, SQLite, and remote
PostgreSQL hosts. Its fixture rows are intended to be discarded by dropping the
short-lived database created by run_s4_campaign_smoke_postgres.sh.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
import hashlib
import json
import os
import re
import stat
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException
from starlette.requests import Request

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

FIXTURE_DATABASE_RE = re.compile(r"^manual_s4_smoke_campaign_fixture_[0-9]{8}_[a-f0-9]{8}$")
BASELINES_RE = re.compile(r"^[A-Za-z0-9._/-]{1,256}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", required=True)
    parser.add_argument("--baselines-file", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--receipt", required=True)
    return parser.parse_args()


def read_private_url(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("Smoke DB URL must be an owned regular file.")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError("Smoke DB URL must have mode 0600.")
        raw = os.read(descriptor, 16 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(raw) > 16 * 1024:
        raise RuntimeError("Smoke DB URL file is too large.")
    value = raw.decode("utf-8").strip()
    if not value:
        raise RuntimeError("Smoke DB URL file is empty.")
    return value


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    output = path.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = os.stat(output.parent, follow_symlinks=False)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise RuntimeError("Smoke receipt parent must be owned and private (0700 or stricter).")
    temporary = output.with_suffix(output.suffix + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, output)
    os.chmod(output, 0o600)


def timed(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = call()
    return value, round((time.perf_counter() - started) * 1000, 2)


def _row_count(connection: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = connection.execute(sql, params).fetchone()
    return int(row["n"] if row else 0)


def _explain(connection: Any, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    row = connection.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
        params,
    ).fetchone()
    value = row[next(iter(row.keys()))]
    if isinstance(value, str):
        value = json.loads(value)
    root = value[0]
    plan = root.get("Plan") or {}
    return {
        "planning_ms": round(float(root.get("Planning Time") or 0), 2),
        "execution_ms": round(float(root.get("Execution Time") or 0), 2),
        "plan_rows": int(plan.get("Plan Rows") or 0),
        "node_type": str(plan.get("Node Type") or ""),
        "shared_hit_blocks": int(plan.get("Shared Hit Blocks") or 0),
        "shared_read_blocks": int(plan.get("Shared Read Blocks") or 0),
    }


class SmokeRollback(Exception):
    pass


def main() -> int:
    args = parse_args()
    db_url_path = Path(args.database_url_file).expanduser().absolute()
    baselines_path = Path(args.baselines_file).expanduser().absolute()
    data_dir = Path(args.data_dir).expanduser().absolute()
    receipt_path = Path(args.receipt).expanduser().absolute()
    database_url = read_private_url(db_url_path)
    if not BASELINES_RE.fullmatch(str(baselines_path)):
        raise RuntimeError("Baselines file path is invalid.")
    if not baselines_path.is_file():
        raise RuntimeError("S4 baselines file is missing.")

    # The router's baseline registry must describe the copied S4 configuration.
    os.environ.pop("DASHBOARD_DATABASE_URL", None)
    os.environ["DASHBOARD_DATABASE_URL_FILE"] = str(db_url_path)
    os.environ["DASHBOARD_BASELINES_FILE"] = str(baselines_path)
    os.environ["DASHBOARD_DATA_DIR"] = str(data_dir)
    os.environ["DASHBOARD_POSTGRES_PERSISTENT_DATA"] = "false"
    os.environ["DASHBOARD_DEPLOYMENT_MODE"] = "development"
    os.environ["DASHBOARD_KYLIN_SSO_ENABLED"] = "false"
    os.environ["DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS"] = "false"
    os.environ["DASHBOARD_SYNC_TRAIL_ON_START"] = "false"
    os.environ["DASHBOARD_GT_SYNC_ENABLED"] = "false"
    os.environ["DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED"] = "false"
    os.environ["DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED"] = "false"
    os.environ["DASHBOARD_BATCH_PREDICTION_ENABLED"] = "false"
    os.environ["DASHBOARD_AUTOTRIAGE_PUSH_ENABLED"] = "false"
    os.environ["DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED"] = "false"

    from app.db import Database
    from app.db_parts.campaigns import CampaignConflictError
    from app.runtime import baseline_registry
    from app.routers import campaigns as campaigns_router
    from app.routers import case_comments as case_comments_router
    from app.routers import cases as cases_router
    from types import SimpleNamespace
    from unittest.mock import patch

    db = Database(database_url, postgres_migrations_dir=APP_ROOT / "migrations" / "postgres", pool_size=8)
    db.init()
    result: dict[str, Any] = {
        "schema": "s4-postgres-campaign-smoke-v1",
        "fixture_kind": "disposable-postgres-clone",
        "assertions": {},
        "performance_ms": {},
        "explain": {},
    }
    try:
        if db.backend != "postgresql":
            raise RuntimeError("Smoke runner requires PostgreSQL.")
        with db.connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            identity = connection.execute(
                "SELECT current_database() AS name, COALESCE(inet_server_addr()::text, '') AS host, "
                "current_user AS user"
            ).fetchone()
            database_name = str(identity["name"] or "")
            if not FIXTURE_DATABASE_RE.fullmatch(database_name):
                raise RuntimeError("Refusing to write fixtures outside a disposable S4 smoke database.")
            if str(identity["host"] or "") not in {"", "127.0.0.1", "::1"}:
                raise RuntimeError("Smoke runner only permits a local PostgreSQL fixture.")
            migration_count = _row_count(connection, "SELECT COUNT(*) AS n FROM dashboard_schema_migrations")
            if migration_count < 46:
                raise RuntimeError(f"Fixture schema is behind S4 migration 046 (found {migration_count}).")
            scope_row = connection.execute(
                """
                SELECT active.baseline_scope
                FROM gt_snapshot_active active
                JOIN gt_snapshots snapshot ON snapshot.id = active.snapshot_id
                ORDER BY snapshot.member_count DESC, active.baseline_scope
                LIMIT 1
                """
            ).fetchone()
            if scope_row is None:
                raise RuntimeError("Fixture DB has no active GT snapshot.")
            scope = str(scope_row["baseline_scope"] or "")
            base_rows = connection.execute(
                "SELECT issue_id FROM issues WHERE baseline_scope = ? ORDER BY issue_id LIMIT 8",
                (scope,),
            ).fetchall()
            base_issue_ids = [str(row["issue_id"]) for row in base_rows]
        if len(base_issue_ids) < 5:
            raise RuntimeError("Fixture baseline must contain at least five Issues.")

        token = uuid4().hex[:10]
        smoke_users = {
            name: f"s4smoke_{token}_{name}"
            for name in (
                "agent", "alice", "bob", "carol", "dave", "erin",
                "group_a", "group_b", "before", "after", "after2", "draft",
                "draft_cancel", "supersede", "scale", "race_from",
                "race_a", "race_b", "work_split",
            )
        }
        actor = smoke_users["agent"]
        db.set_access_user(username=actor, role="admin", actor=actor, intent_permission="manage")
        for name, username in smoke_users.items():
            if name == "agent":
                continue
            db.set_access_user(username=username, role="writer", actor=actor, intent_permission="view")

        def verified_smoke_request(
            method: str,
            path: str,
            payload: dict[str, Any] | None = None,
            *,
            campaign_admin: bool = False,
            cases_admin: bool = False,
            case_writer: bool = False,
        ) -> Any:
            request_headers = {
                "x-ra-triage-request": "comment-v1" if "/comments" in path else "review-v1",
            }
            if payload and payload.get("idempotency_key"):
                request_headers["idempotency-key"] = str(payload["idempotency_key"])
            body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(
                {
                    "type": "http",
                    "method": method.upper(),
                    "path": path,
                    "headers": [(str(name).lower().encode("ascii"), str(value).encode("utf-8")) for name, value in request_headers.items()],
                },
                receive,
            )

            async def dispatch() -> Any:
                parts = [part for part in path.split("/") if part]
                if path == "/api/campaigns":
                    return await campaigns_router.create_campaign(request)
                if path == "/api/review-task-groups":
                    return await campaigns_router.create_campaign_group(request)
                if path == "/api/cases/work-split":
                    return await cases_router.split_case_work(request)
                if len(parts) >= 3 and parts[0:2] == ["api", "campaigns"]:
                    campaign_id = parts[2]
                    if len(parts) == 4 and parts[3] in {"close", "reopen", "activate", "cancel", "supersede"}:
                        return await getattr(campaigns_router, f"{parts[3]}_campaign")(campaign_id, request)
                    if len(parts) == 6 and parts[3] == "issues" and parts[5] == "assignments":
                        return await campaigns_router.update_campaign_assignment(campaign_id, parts[4], request)
                    if len(parts) == 6 and parts[3] == "issues" and parts[5] == "comments":
                        return await campaigns_router.create_campaign_comment(campaign_id, parts[4], request)
                if len(parts) == 4 and parts[0:2] == ["api", "cases"] and parts[3] == "case-comments":
                    return await case_comments_router.create_case_discussion(parts[2], request)
                raise RuntimeError(f"smoke router path not supported: {path}")

            class SmokeResponse:
                def __init__(self, status_code: int, value: Any = None, detail: Any = None):
                    self.status_code = status_code
                    self._value = value
                    self._detail = detail
                    self.text = json.dumps(value if value is not None else {"detail": detail}, ensure_ascii=False)

                def json(self) -> Any:
                    return self._value if self._value is not None else {"detail": self._detail}
            with patch.object(campaigns_router, "database", db), \
                 patch.object(case_comments_router, "database", db), \
                 patch.object(cases_router, "database", db):
                admin_patch = patch.object(
                    campaigns_router,
                    "_campaign_admin",
                    return_value=(actor, "verified_smoke_client", True),
                )
                cases_patch = patch.object(
                    cases_router,
                    "_admin_identity",
                    return_value=SimpleNamespace(
                        username=actor, source="verified_smoke_client", verified=True
                    ),
                )
                case_writer_patch = patch.object(
                    case_comments_router,
                    "_action_actor",
                    return_value=(actor, "verified_smoke_client", True),
                )
                with (admin_patch if campaign_admin else nullcontext()), \
                     (cases_patch if cases_admin else nullcontext()), \
                     (case_writer_patch if case_writer else nullcontext()):
                    try:
                        return SmokeResponse(200, asyncio.run(dispatch()))
                    except HTTPException as exc:
                        return SmokeResponse(int(exc.status_code), detail=exc.detail)

        def create_campaign_via_api(spec: dict[str, Any]) -> dict[str, Any]:
            response = verified_smoke_request(
                "post", "/api/campaigns", spec, campaign_admin=True
            )
            assert response.status_code == 200, response.text
            return response.json()["campaign"]

        def create_group_via_api(payload: dict[str, Any]) -> dict[str, Any]:
            response = verified_smoke_request(
                "post", "/api/review-task-groups", payload, campaign_admin=True
            )
            assert response.status_code == 200, response.text
            return response.json()["group"]

        run_rows = [
            {"issue_id": issue_id, "model_label": "正确触发", "model_reason": "S4 smoke model reason"}
            for issue_id in base_issue_ids[:5]
        ]
        run_a, _ = db.import_model_run(
            name=f"S4 smoke Run A {token}",
            source_name=f"s4-smoke-run-a-{token}.json",
            source_sha256=hashlib.sha256(f"s4-smoke-run-a:{token}".encode()).hexdigest(),
            metadata={"purpose": "disposable S4 PostgreSQL smoke"},
            rows=run_rows,
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        run_b, _ = db.import_model_run(
            name=f"S4 smoke Run B {token}",
            source_name=f"s4-smoke-run-b-{token}.json",
            source_sha256=hashlib.sha256(f"s4-smoke-run-b:{token}".encode()).hexdigest(),
            metadata={"purpose": "disposable S4 PostgreSQL smoke"},
            rows=run_rows,
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )

        issue_a, issue_b, issue_c, issue_d, issue_e = base_issue_ids[:5]
        workset_a = db.create_review_workset(
            baseline_scope=scope,
            issue_ids=[issue_a, issue_b],
            name=f"Smoke Label A {token}",
            selection_source_run_id=run_a["id"],
            source_filter={"smoke": token, "fixture": "overlap-a"},
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        workset_b = db.create_review_workset(
            baseline_scope=scope,
            issue_ids=[issue_b, issue_c],
            name=f"Smoke Label B {token}",
            selection_source_run_id=run_a["id"],
            source_filter={"smoke": token, "fixture": "overlap-b"},
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        label_a = create_campaign_via_api({
            "purpose": "labeling",
            "workset_id": workset_a["id"],
            "name": f"Smoke overlapping Label A {token}",
            "members": [
                {"issue_id": issue_a, "assignees": [smoke_users["alice"]]},
                {"issue_id": issue_b, "assignees": [smoke_users["alice"], smoke_users["bob"]]},
            ],
            "idempotency_key": f"{token}:label-a",
        })
        label_b = create_campaign_via_api({
            "purpose": "labeling",
            "workset_id": workset_b["id"],
            "name": f"Smoke overlapping Label B {token}",
            "members": [
                {"issue_id": issue_b, "assignees": [smoke_users["carol"]]},
                {"issue_id": issue_c, "assignees": [smoke_users["dave"], smoke_users["erin"]]},
            ],
            "idempotency_key": f"{token}:label-b",
        })
        label_a_id = label_a["campaign"]["id"]
        label_b_id = label_b["campaign"]["id"]
        for issue_id, reviewer, rationale in (
            (issue_a, smoke_users["alice"], "queueing: red light wait is normal"),
            (issue_b, smoke_users["alice"], "planning route did not consider the target lane"),
            (issue_b, smoke_users["bob"], "planning route did not consider the target lane"),
        ):
            db.create_label_revision(
                issue_id=issue_id,
                expected_output="正确触发",
                tags=["construction_change", "queue", "egress_swag"] if issue_id == issue_a else [],
                evidence_gaps=[],
                rationale=rationale,
                is_excluded=False,
                author=reviewer,
                author_source="verified_smoke_client",
                author_verified=True,
                task_id=label_a_id,
                source_run_id=run_a["id"],
                expected_previous_revision_id=None,
            )
        label_a_progress = db.get_campaign(label_a_id)["progress"]
        label_b_progress = db.get_campaign(label_b_id)["progress"]
        assert label_a_progress["required_submitter_count"] == 3
        assert label_a_progress["completed_issue_count"] == 2
        assert label_b_progress["required_submitter_count"] == 3
        assert label_b_progress["completed_issue_count"] == 0
        assert label_a_progress["tag_counts"] == {
            "construction_change": 1,
            "queue": 1,
            "egress_swag": 1,
        }
        assert label_a_progress["rationale_theme_counts"]["normal_traffic"] == 1
        assert label_a_progress["rationale_theme_counts"]["routing_intent"] == 1
        result["assertions"]["overlapping_label_campaigns_no_credit_bleed"] = True
        result["assertions"]["per_issue_requirements_1_of_1_and_1_of_2"] = True
        result["assertions"]["label_analysis_tag_axes_and_rationale_themes"] = True

        group_workset = db.create_review_workset(
            baseline_scope=scope,
            issue_ids=[issue_a, issue_b],
            name=f"Smoke shared Run group {token}",
            selection_source_run_id=run_b["id"],
            source_filter={"smoke": token, "fixture": "two-run-group"},
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        group = create_group_via_api({
            "name": f"S4 smoke two-Run group {token}",
            "purpose": "model_review",
            "campaigns": [
                {
                    "purpose": "model_review", "evaluation_run_id": run_a["id"],
                    "workset_id": group_workset["id"], "name": "Smoke Run A",
                    "members": [{"issue_id": issue_a, "assignees": [smoke_users["group_a"]]},
                                {"issue_id": issue_b, "assignees": [smoke_users["group_a"]]}],
                },
                {
                    "purpose": "model_review", "evaluation_run_id": run_b["id"],
                    "workset_id": group_workset["id"], "name": "Smoke Run B",
                    "members": [{"issue_id": issue_a, "assignees": [smoke_users["group_b"]]},
                                {"issue_id": issue_b, "assignees": [smoke_users["group_b"]]}],
                },
            ],
            "idempotency_key": f"{token}:group",
        })
        child_a, child_b = [item["campaign"] for item in group["campaigns"]]
        db.create_model_review(
            issue_id=issue_a,
            model_run_id=run_a["id"],
            status="completed",
            reason="S4 smoke completed child only",
            missing_evidence=[],
            reviewer=smoke_users["group_a"],
            campaign_id=child_a["id"],
            reference_id=child_a["reference_id"],
            work_split_id=child_a["id"],
        )
        group_detail = db.get_campaign_group(group["id"])
        progress_by_run = {
            item["campaign"]["evaluation_run_id"]: item["progress"]
            for item in group_detail["campaigns"]
        }
        assert group_detail["group"]["workset_id"] == group_workset["id"]
        assert progress_by_run[run_a["id"]]["completed_issue_count"] == 1
        assert progress_by_run[run_b["id"]]["completed_issue_count"] == 0
        result["assertions"]["two_run_group_has_independent_child_progress"] = True

        lifecycle_workset = db.create_review_workset(
            baseline_scope=scope,
            issue_ids=[issue_d],
            name=f"Smoke lifecycle Workset {token}",
            selection_source_run_id=run_a["id"],
            source_filter={"smoke": token, "fixture": "lifecycle"},
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        lifecycle_campaign = create_campaign_via_api({
            "purpose": "model_review", "evaluation_run_id": run_a["id"],
            "workset_id": lifecycle_workset["id"], "name": f"Smoke lifecycle {token}",
            "members": [{"issue_id": issue_d, "assignees": [smoke_users["before"]]}],
            "idempotency_key": f"{token}:lifecycle",
        })
        lifecycle_id = lifecycle_campaign["campaign"]["id"]
        reassign_args = {
            "campaign_id": lifecycle_id, "issue_id": issue_d, "action": "reassign",
            "actor": actor, "actor_source": "verified_smoke_client", "actor_verified": True,
            "expected_revision": 1, "idempotency_key": f"{token}:reassign",
            "from_assignee": smoke_users["before"], "assignee": smoke_users["after"], "reason": "S4 smoke rotation",
        }
        reassign_body = {
            "action": "reassign",
            "from_assignee": reassign_args["from_assignee"],
            "assignee": reassign_args["assignee"],
            "expected_revision": 1,
            "idempotency_key": reassign_args["idempotency_key"],
            "reason": reassign_args["reason"],
        }
        reassign_path = f"/api/campaigns/{quote(lifecycle_id)}/issues/{quote(issue_d)}/assignments"
        reassigned_response = verified_smoke_request(
            "patch", reassign_path, reassign_body, campaign_admin=True
        )
        assert reassigned_response.status_code == 200, reassigned_response.text
        reassigned = reassigned_response.json()
        replay_response = verified_smoke_request(
            "patch", reassign_path, reassign_body, campaign_admin=True
        )
        assert replay_response.status_code == 200, replay_response.text
        replay = replay_response.json()
        detail_after_reassign = db.get_campaign(lifecycle_id)
        assert reassigned["config_revision"] == 2 and replay["replayed"]
        assert [item["assignee"] for item in detail_after_reassign["issues"][0]["assignments"]] == [smoke_users["after"]]
        assert detail_after_reassign["assignment_audit"][0]["action"] == "reassigned"
        assert detail_after_reassign["assignment_audit"][0]["reason"] == "S4 smoke rotation"
        assert detail_after_reassign["assignment_audit"][0]["action"] == "reassigned"
        close_body = {
            "expected_revision": 2,
            "idempotency_key": f"{token}:close",
            "reason": "S4 smoke snapshot",
        }
        close_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(lifecycle_id)}/close", close_body,
            campaign_admin=True,
        )
        assert close_response.status_code == 200, close_response.text
        closed = close_response.json()
        assert closed["campaign"]["close_snapshot"]["config_revision"] == 2
        closed_write_response = verified_smoke_request(
            "patch", reassign_path,
            {
                "action": "reassign",
                "from_assignee": smoke_users["after"],
                "assignee": smoke_users["after2"],
                "expected_revision": 2,
                "idempotency_key": f"{token}:closed-write",
                "reason": "should be rejected",
            },
            campaign_admin=True,
        )
        assert closed_write_response.status_code == 409
        reopen_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(lifecycle_id)}/reopen",
            {"expected_revision": 2, "idempotency_key": f"{token}:reopen", "reason": "S4 smoke reopen"},
            campaign_admin=True,
        )
        assert reopen_response.status_code == 200, reopen_response.text
        reopened = reopen_response.json()
        assert reopened["campaign"]["campaign"]["config_revision"] == 3
        assert reopened["campaign"]["campaign"]["lifecycle"] == "active"
        assert reopened["campaign"]["close_snapshot"]["id"] == closed["snapshot_id"]
        result["assertions"]["atomic_reassign_audit_idempotency_close_snapshot_write_guard_reopen"] = True

        draft = create_campaign_via_api({
            "purpose": "model_review", "evaluation_run_id": run_a["id"],
            "workset_id": lifecycle_workset["id"], "lifecycle": "draft",
            "name": f"Smoke draft {token}",
            "members": [{"issue_id": issue_d, "assignees": [smoke_users["draft"]]}],
            "idempotency_key": f"{token}:draft",
        })
        activated_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(draft['campaign']['id'])}/activate",
            {"expected_revision": 1, "idempotency_key": f"{token}:activate", "reason": "S4 smoke activation"},
            campaign_admin=True,
        )
        assert activated_response.status_code == 200, activated_response.text
        activated = activated_response.json()
        cancelled_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(draft['campaign']['id'])}/cancel",
            {"expected_revision": 2, "idempotency_key": f"{token}:cancel", "reason": "S4 smoke cancellation"},
            campaign_admin=True,
        )
        assert cancelled_response.status_code == 200, cancelled_response.text
        cancelled = cancelled_response.json()
        draft_cancel = create_campaign_via_api({
            "purpose": "model_review", "evaluation_run_id": run_a["id"],
            "workset_id": lifecycle_workset["id"], "lifecycle": "draft",
            "name": f"S4 smoke draft cancellation {token}",
            "members": [{"issue_id": issue_d, "assignees": [smoke_users["draft_cancel"]]}],
            "idempotency_key": f"{token}:draft-cancel",
        })
        cancelled_draft_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(draft_cancel['campaign']['id'])}/cancel",
            {"expected_revision": 1, "idempotency_key": f"{token}:cancel-draft", "reason": "S4 smoke cancel before activation"},
            campaign_admin=True,
        )
        assert cancelled_draft_response.status_code == 200, cancelled_draft_response.text
        cancelled_draft = cancelled_draft_response.json()
        supersede_target = create_campaign_via_api({
            "purpose": "model_review", "evaluation_run_id": run_b["id"],
            "workset_id": lifecycle_workset["id"], "name": f"Smoke supersede {token}",
            "members": [{"issue_id": issue_d, "assignees": [smoke_users["supersede"]]}],
            "idempotency_key": f"{token}:supersede-target",
        })
        superseded_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(supersede_target['campaign']['id'])}/supersede",
            {"expected_revision": 1, "idempotency_key": f"{token}:supersede", "reason": "S4 smoke replacement"},
            campaign_admin=True,
        )
        assert superseded_response.status_code == 200, superseded_response.text
        superseded = superseded_response.json()
        assert activated["campaign"]["campaign"]["lifecycle"] == "active"
        assert cancelled["campaign"]["campaign"]["lifecycle"] == "cancelled"
        assert cancelled_draft["campaign"]["campaign"]["lifecycle"] == "cancelled"
        assert superseded["campaign"]["campaign"]["lifecycle"] == "superseded"
        terminal_transition_rejections = 0
        for terminal_id in (draft["campaign"]["id"], supersede_target["campaign"]["id"]):
            try:
                with db.connect() as connection:
                    connection.execute(
                        "UPDATE issue_work_splits SET lifecycle = 'active', "
                        "config_revision = config_revision + 1 WHERE id = ?",
                        (terminal_id,),
                    )
            except Exception:
                terminal_transition_rejections += 1
        assert terminal_transition_rejections == 2
        result["assertions"]["draft_activate_cancel_supersede"] = True
        result["assertions"]["postgres_lifecycle_trigger_rejects_terminal_reactivation"] = True

        case_comment_response = verified_smoke_request(
            "post", f"/api/cases/{quote(issue_b)}/case-comments",
            {"body": "S4 smoke Case channel"}, case_writer=True,
        )
        assert case_comment_response.status_code == 200, case_comment_response.text
        case_comment = case_comment_response.json()["comment"]
        campaign_comment_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(label_a_id)}/issues/{quote(issue_b)}/comments",
            {"body": "S4 smoke Campaign channel"}, campaign_admin=True,
        )
        assert campaign_comment_response.status_code == 200, campaign_comment_response.text
        campaign_comment = campaign_comment_response.json()["comment"]
        other_campaign_comment_response = verified_smoke_request(
            "post", f"/api/campaigns/{quote(label_b_id)}/issues/{quote(issue_b)}/comments",
            {"body": "S4 smoke read-only other Campaign"}, campaign_admin=True,
        )
        assert other_campaign_comment_response.status_code == 200, other_campaign_comment_response.text
        other_campaign_comment = other_campaign_comment_response.json()["comment"]
        run_comment = db.create_review_comment(
            issue_id=issue_b, model_run_id=run_a["id"], body="S4 smoke Run channel",
            author=actor, author_source="verified_smoke_client", author_verified=True,
        )
        cross_channel_replies = 0
        for channel, campaign_id, model_run_id, parent in (
            ("campaign", label_a_id, "", case_comment),
            ("case", "", "", campaign_comment),
            ("model_review", "", run_a["id"], case_comment),
        ):
            try:
                db.create_review_comment(
                    issue_id=issue_b, model_run_id=model_run_id, body="Invalid cross-channel reply",
                    author=actor, author_source="verified_smoke_client", author_verified=True,
                    discussion_channel=channel, campaign_id=campaign_id,
                    baseline_scope=scope if channel == "case" else "",
                    reply_to_id=parent["id"], require_existing_model_run=False,
                )
            except ValueError:
                cross_channel_replies += 1
        related_groups = db.list_related_campaign_comment_groups(
            issue_id=issue_b, exclude_campaign_id=label_a_id
        )
        assert run_comment["discussion_channel"] == "model_review"
        assert cross_channel_replies == 3
        assert any(
            group["campaign_id"] == label_b_id
            and any(comment["id"] == other_campaign_comment["id"] for comment in group["comments"])
            for group in related_groups
        )
        result["assertions"]["case_campaign_run_channels_and_cross_reply_rejection"] = True

        synthetic_issue_ids = [f"s4smoke-{token}-{index:04d}" for index in range(5000)]
        _, seed_issue_ms = timed(lambda: db.upsert_issues(
            ({"issue_id": issue_id, "title": "S4 smoke scale fixture", "scenario": "smoke-scale"}
             for issue_id in synthetic_issue_ids),
            source="s4_campaign_postgres_smoke",
            replace_gt=False,
            baseline_scope=scope,
        ))
        scale_workset = db.create_review_workset(
            baseline_scope=scope,
            issue_ids=synthetic_issue_ids,
            name=f"Smoke 5000 Workset {token}",
            selection_source_run_id=run_a["id"],
            source_filter={"smoke": token, "fixture": "5000-member-performance"},
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        scale_members = [
            {"issue_id": issue_id, "assignees": [smoke_users["scale"]]}
            for issue_id in synthetic_issue_ids
        ]
        scale_campaign, create_ms = timed(lambda: db.create_campaign(
            spec={
                "purpose": "labeling",
                "workset_id": scale_workset["id"],
                "name": f"Smoke 5000 member Campaign {token}",
                "members": scale_members,
                "idempotency_key": f"{token}:scale-campaign",
            },
            actor=actor,
            actor_source="verified_smoke_client",
            actor_verified=True,
            idempotency_key=f"{token}:scale-campaign",
        ))
        scale_id = scale_campaign["campaign"]["id"]
        result["performance_ms"]["seed_5000_issues"] = seed_issue_ms
        result["performance_ms"]["create_5000_member_campaign"] = create_ms

        from app.routers import campaigns as campaigns_router
        from app.routers import case_comments as case_comments_router
        from app.routers import cases as cases_router
        baseline_id = baseline_registry.scope_to_id(scope) or baseline_registry.default_ids()[0]

        work_split_body = {
            "filters": {"baselines": str(baseline_id), "model_run_id": run_a["id"], "issue_ids": issue_c},
            "assignees": [{"name": smoke_users["work_split"]}], "seed": 42,
            "reviewers_per_issue": 1, "overlap_ratio": 0.0,
            "name": f"S4 smoke Run Work Split {token}",
            "idempotency_key": f"{token}:run-work-split",
        }
        work_split_response = verified_smoke_request(
            "post", "/api/cases/work-split", work_split_body, cases_admin=True
        )
        assert work_split_response.status_code == 200, work_split_response.text
        work_split_campaign = db.get_campaign(work_split_response.json()["split_id"])
        assert work_split_campaign["campaign"]["workset_id"]
        assert work_split_campaign["campaign"]["evaluation_run_id"] == run_a["id"]
        result["assertions"]["run_based_work_split_creates_frozen_workset"] = True

        def list_campaigns_api() -> dict[str, Any]:
            with patch.object(campaigns_router, "database", db):
                return asyncio.run(campaigns_router.list_campaigns(
                    Request({"type": "http", "method": "GET", "path": "/api/campaigns", "headers": []}),
                    baselines=str(baseline_id), purpose="labeling", lifecycle="all",
                    include_legacy=False, q=scale_id, page=1, page_size=100,
                ))

        def get_campaign_api(campaign_id: str) -> dict[str, Any]:
            with patch.object(campaigns_router, "database", db):
                return asyncio.run(campaigns_router.get_campaign(campaign_id, page=1, page_size=50))

        def get_analysis_api(campaign_id: str) -> dict[str, Any]:
            with patch.object(campaigns_router, "database", db):
                return asyncio.run(campaigns_router.campaign_analysis(campaign_id, page=1, page_size=100))

        def get_group_api(group_id: str) -> dict[str, Any]:
            with patch.object(campaigns_router, "database", db):
                return asyncio.run(campaigns_router.get_campaign_group(group_id))

        def get_discussion_api(campaign_id: str, issue_id: str) -> dict[str, Any]:
            with patch.object(campaigns_router, "database", db):
                return asyncio.run(campaigns_router.get_campaign_discussion(campaign_id, issue_id))

        listed, result["performance_ms"]["campaign_list_5000_member"] = timed(list_campaigns_api)
        assert listed["total"] == 1
        detail_json, result["performance_ms"]["campaign_detail_5000_member"] = timed(lambda: get_campaign_api(scale_id))
        assert detail_json["progress"]["member_count"] == 5000
        assert detail_json["progress"]["required_submitter_count"] == 5000
        analysis_json, result["performance_ms"]["label_analysis_5000_member"] = timed(lambda: get_analysis_api(scale_id))
        assert analysis_json["total"] == 5000
        assert get_group_api(group["id"])["group"]["id"] == group["id"]
        discussion = get_discussion_api(label_a_id, issue_b)
        assert any(item["id"] == case_comment["id"] for item in discussion["case_comments"])
        assert any(item["id"] == campaign_comment["id"] for item in discussion["campaign_comments"])
        assert any(item["campaign_id"] == label_b_id for item in discussion["other_campaigns"])
        result["assertions"]["api_read_routes_discussion_group_and_5000_member_queries"] = True

        with db.connect() as connection:
            scale_row = connection.execute(
                "SELECT * FROM issue_work_splits WHERE id = ?", (scale_id,)
            ).fetchone()
            progress, result["performance_ms"]["campaign_progress_5000_member"] = timed(
                lambda: db._campaign_progress_batch(connection, [scale_row])
            )
            assert progress[scale_id]["member_count"] == 5000
        with db.connect() as connection:
            result["explain"]["campaign_list"] = _explain(
                connection,
                """
                SELECT split.id
                FROM issue_work_splits split
                LEFT JOIN review_worksets workset ON workset.id = split.workset_id
                WHERE split.purpose = 'labeling' AND split.lifecycle = 'active'
                  AND split.id LIKE ?
                ORDER BY split.created_at DESC, split.id DESC
                LIMIT ?
                """,
                (f"%{scale_id}%", 100),
            )
            result["explain"]["campaign_detail_members"] = _explain(
                connection,
                """
                SELECT member.issue_id, issue.title, issue.scenario,
                       member.required_submitter_count, member.ordinal
                FROM campaign_issue_members member
                JOIN issues issue ON issue.issue_id = member.issue_id
                WHERE member.campaign_id = ?
                ORDER BY member.ordinal, member.issue_id
                LIMIT ?
                """,
                (scale_id, 50),
            )
            result["explain"]["campaign_assignments"] = _explain(
                connection,
                "SELECT issue_id, assignee, assignment_kind, ordinal "
                "FROM review_work_assignments WHERE split_id = ? "
                "ORDER BY issue_id, lower(assignee), ordinal LIMIT ?",
                (scale_id, 100),
            )
            result["explain"]["label_analysis_heads"] = _explain(
                connection,
                """
                WITH ranked AS (
                    SELECT label_case.issue_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY label_case.id, lower(revision.author)
                               ORDER BY revision.id DESC
                           ) AS row_number
                    FROM label_cases label_case
                    JOIN label_revisions revision ON revision.label_case_id = label_case.id
                    WHERE label_case.task_id = ?
                      AND revision.revision_kind IN ('submission', 'legacy')
                )
                SELECT issue_id FROM ranked WHERE row_number = 1 LIMIT ?
                """,
                (scale_id, 100),
            )
        result["assertions"]["5000_member_list_detail_progress_analysis_and_explain"] = True

        rollback_marker = f"s4-smoke-rollback-{token}"
        try:
            with db.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO review_comments (
                        issue_id, model_run_id, body, author, author_source,
                        author_verified, mentions_json, reply_to_id, created_at,
                        discussion_channel, campaign_id, baseline_scope, evaluation_run_id
                    ) VALUES (?, '', ?, ?, 'verified_smoke_client', true, '[]', NULL,
                              CURRENT_TIMESTAMP, 'case', '', ?, '')
                    """,
                    (issue_a, rollback_marker, actor, scope),
                )
                raise SmokeRollback()
        except SmokeRollback:
            pass
        with db.connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            rollback_count = _row_count(
                connection,
                "SELECT COUNT(*) AS n FROM review_comments WHERE body = ?",
                (rollback_marker,),
            )
        assert rollback_count == 0
        result["assertions"]["transaction_rollback"] = True

        race_workset = db.create_review_workset(
            baseline_scope=scope,
            issue_ids=[issue_e],
            name=f"Smoke concurrency Workset {token}",
            selection_source_run_id=run_a["id"],
            source_filter={"smoke": token, "fixture": "two-connection-race"},
            created_by=actor,
            created_by_source="verified_smoke_client",
            created_by_verified=True,
        )
        race_campaign = db.create_campaign(
            spec={
                "purpose": "model_review", "evaluation_run_id": run_a["id"],
                "workset_id": race_workset["id"], "name": f"Smoke two-connection race {token}",
                "members": [{"issue_id": issue_e, "assignees": [smoke_users["race_from"]]}],
                "idempotency_key": f"{token}:race-campaign",
            },
            actor=actor,
            actor_source="verified_smoke_client",
            actor_verified=True,
            idempotency_key=f"{token}:race-campaign",
        )
        race_campaign_id = race_campaign["campaign"]["id"]
        db_a = Database(database_url, postgres_migrations_dir=APP_ROOT / "migrations" / "postgres", pool_size=2)
        db_b = Database(database_url, postgres_migrations_dir=APP_ROOT / "migrations" / "postgres", pool_size=2)
        barrier = threading.Barrier(2)
        outcomes: list[dict[str, Any]] = []
        outcome_lock = threading.Lock()

        def concurrent_reassign(db_for_thread: Database, new_assignee: str) -> None:
            args = {
                "campaign_id": race_campaign_id,
                "issue_id": issue_e,
                "action": "reassign",
                "actor": actor,
                "actor_source": "verified_smoke_client",
                "actor_verified": True,
                "expected_revision": 1,
                "idempotency_key": f"{token}:race:{new_assignee}",
                "from_assignee": smoke_users["race_from"],
                "assignee": new_assignee,
                "reason": "S4 two-connection race",
            }
            barrier.wait(timeout=10)
            try:
                response = db_for_thread.update_campaign_assignment(**args)
                item = {"outcome": "success", "assignee": new_assignee, "args": args, "response": response}
            except CampaignConflictError as exc:
                item = {"outcome": "revision_conflict", "assignee": new_assignee, "detail": str(exc)}
            except Exception as exc:
                if type(exc).__name__ in {"SerializationFailure", "DeadlockDetected"}:
                    item = {"outcome": "serialization_conflict", "assignee": new_assignee, "detail": type(exc).__name__}
                else:
                    item = {"outcome": "unexpected_error", "assignee": new_assignee, "detail": type(exc).__name__}
            with outcome_lock:
                outcomes.append(item)

        threads = [
            threading.Thread(target=concurrent_reassign, args=(db_a, smoke_users["race_a"])),
            threading.Thread(target=concurrent_reassign, args=(db_b, smoke_users["race_b"])),
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            if any(thread.is_alive() for thread in threads):
                raise RuntimeError("PostgreSQL two-connection race did not finish.")
        finally:
            db_a.close()
            db_b.close()
        successes = [item for item in outcomes if item["outcome"] == "success"]
        conflicts = [item for item in outcomes if item["outcome"] in {"revision_conflict", "serialization_conflict"}]
        if len(successes) != 1 or len(conflicts) != 1:
            raise AssertionError({"race_outcomes": [item["outcome"] for item in outcomes]})
        replay = db.update_campaign_assignment(**successes[0]["args"])
        assert replay["replayed"] is True
        result["assertions"]["two_postgres_connections_revision_conflict_and_idempotent_retry"] = True
        result["postgres_concurrency"] = {
            "connection_count": 2,
            "successful_updates": len(successes),
            "conflicts": len(conflicts),
            "idempotent_retry_replayed": bool(replay["replayed"]),
        }
        result["database"] = database_name
        result["schema_migration_count"] = migration_count
        result["synthetic_scale_members"] = 5000
        result["all_checks_passed"] = all(result["assertions"].values())
        if not result["all_checks_passed"]:
            raise AssertionError("A PostgreSQL S4 smoke assertion failed.")
        write_private_json(receipt_path, result)
        print(json.dumps({
            "status": "passed",
            "database": database_name,
            "schema_migration_count": migration_count,
            "checks": result["assertions"],
            "performance_ms": result["performance_ms"],
            "explain": result["explain"],
            "receipt": str(receipt_path),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
