from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import os
from uuid import uuid4
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.trail_audit import audited_write, owned, snapshots, restore_changes
from ra_triage_dashboard.app.routers import trail_history as routes

FIELD = "ra_stuck_auto_result_info"
ACTOR = SimpleNamespace(username="alice", source="sso", verified=True)


def item(issue="cn00000001", before=None):
    return {"issue_id":issue,"field":FIELD,"before":{} if before is None else before,
            "after":{"should_exclude":True,"should_exclude_comment":"new","operation_id":"original"}}


def request(body=None):
    return SimpleNamespace(headers={"x-ra-triage-request":"browser-v1"},json=AsyncMock(return_value=body or {}))


class TrailHistoryDatabaseTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.db=Database(Path(temporary.name)/"history.sqlite3");self.db.init()

    def begin(self, **kwargs):
        self.db.begin_trail_operation(operation_id="original",actor="alice",actor_source="sso",
            actor_verified=True,source="exclusion_summary",items=[item()],**kwargs)

    def test_immutable_intent_append_events_and_filters(self):
        self.begin();self.begin()
        self.db.append_trail_event("original","unknown",{"cn00000001":"unknown"})
        self.db.append_trail_event("original","succeeded",{"cn00000001":"succeeded"})
        record=self.db.trail_operation("original")
        self.assertEqual(len(record["events"]),3)
        self.assertEqual(record["items"][0]["before"],{})
        self.assertEqual(record["status"],"succeeded")
        self.assertEqual(self.db.list_trail_operations(actor="alice",issue_id="cn00000001",status="succeeded")["total"],1)
        self.assertEqual(self.db.list_trail_operations(actor="bob")["total"],0)
        for table in ("trail_operations","trail_operation_items","trail_operation_events"):
            with self.assertRaises(sqlite3.IntegrityError),self.db.connect() as conn:
                conn.execute(f"DELETE FROM {table}")

    def test_retry_cannot_replace_before_or_actor(self):
        self.begin()
        with self.assertRaises(ValueError):
            self.db.begin_trail_operation(operation_id="original",actor="bob",actor_source="sso",actor_verified=True,source="exclusion_summary",items=[item()])
        with self.assertRaises(ValueError):
            self.db.begin_trail_operation(operation_id="original",actor="alice",actor_source="sso",actor_verified=True,source="exclusion_summary",items=[item(before={"should_exclude":False})])
        self.assertEqual(self.db.trail_operation("original")["items"][0]["before"],{})

    def test_legacy_import_is_idempotent_and_cannot_claim_snapshots(self):
        self.db.upsert_trail_issue_exclusion_history(operation_id="old",actor="bob",entries=[{"issue_id":"cn00000002","comment":"old note","status":"synced"}])
        self.db.import_legacy_trail_history();self.db.import_legacy_trail_history()
        record=self.db.trail_operation("old")
        self.assertEqual(record["source"],"legacy")
        self.assertEqual(len(record["events"]),1)
        self.assertIsNone(self.db.list_trail_operations()["started_at"])

    def test_restoration_keeps_unowned_fields_and_exact_absence(self):
        for before in ({},{"should_exclude":False,"should_exclude_comment":""},{"should_exclude":None}):
            target=item(before=before)
            row={"issue_id":target["issue_id"],FIELD:{"model_result":{"label":"keep"},"ra_triage_dashboard":{**target["after"],"future_key":7}}}
            changes,conflicts=restore_changes({"items":[target]},[row],"restore-id")
            self.assertFalse(conflicts)
            self.assertEqual(owned(changes[0][FIELD]),{**before,"operation_id":"restore-id"})
            self.assertEqual(changes[0][FIELD]["model_result"],{"label":"keep"})
            self.assertEqual(changes[0][FIELD]["ra_triage_dashboard"]["future_key"],7)
            self.assertTrue(snapshots(changes,[row],FIELD))

    def test_conflict_compares_types_and_marker(self):
        target=item()
        for change in ({"should_exclude":1},{"operation_id":"someone-else"},{"should_exclude_comment":"newer"}):
            row={"issue_id":target["issue_id"],FIELD:{"ra_triage_dashboard":{**target["after"],**change}}}
            changes,conflicts=restore_changes({"items":[target]},[row],"restore")
            self.assertEqual(changes,[]);self.assertEqual(conflicts,[target["issue_id"]])

    def test_audit_refuses_changes_to_model_fields(self):
        with self.assertRaises(ValueError):
            snapshots([{"issue_id":"cn00000001",FIELD:{"model_result":42}}],[{"issue_id":"cn00000001",FIELD:{}}],FIELD)


class TrailHistoryRoutesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.db=Database(Path(temporary.name)/"history.sqlite3");self.db.init()
        self.db.begin_trail_operation(operation_id="original",actor="alice",actor_source="sso",actor_verified=True,source="exclusion_summary",items=[item()])
        self.db.append_trail_event("original","succeeded",{"cn00000001":"succeeded"})
        self.rows=[{"issue_id":"cn00000001",FIELD:{"other":17,"ra_triage_dashboard":item()["after"]}}]
        self.writes=[]
        self.settings=SimpleNamespace(trail_attribute_write_enabled=True,trail_rollback_enabled=True,sso_write_users=(),trail_attribute_info_field=FIELD,
            ra_auto_triage_root="/tmp",trail_view_id=2410,trail_sync_chunk_size=10,trail_attribute_write_chunk_size=10)
        def read(**kwargs):
            return SimpleNamespace(complete=True,rows=deepcopy(self.rows),fields_visible=[FIELD],returned_issues=1,queried_issues=1,view_id=2410,message="")
        def write(changes,**kwargs):
            self.writes.extend(deepcopy(changes))
            for change in changes:self.rows[0].update(deepcopy(change))
            return {"failed_issue_ids":[],"failed_count":0}
        for obj,name,value in ((routes,"database",self.db),(routes,"settings",self.settings),
            (routes,"request_identity",lambda *a:ACTOR),(routes,"read_trail_model_fields",read),
            (routes,"write_trail_model_results",write),(self.db,"access_role",lambda _:"admin")):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        routes._previews.clear()

    async def preview(self):
        return await routes.restore_preview("original",request({"reason":"mistake"}))

    async def commit(self,preview):
        return await routes.restore_commit("original",request({"preview_id":preview["preview_id"],"confirm":True}))

    async def test_restore_and_idempotent_retry_do_not_write_local_reviews(self):
        preview=await self.preview();self.assertTrue(preview["ready"]);self.assertEqual(self.writes,[])
        result=await self.commit(preview);again=await self.commit(preview)
        self.assertEqual(result,again);self.assertTrue(result["ok"]);self.assertEqual(len(self.writes),1)
        self.assertEqual(self.rows[0][FIELD]["other"],17)
        self.assertNotIn("should_exclude",owned(self.rows[0][FIELD]))
        self.assertEqual(self.db.trail_operation(result["operation_id"])["parent_id"],"original")

    async def test_stale_preview_including_unowned_change_refuses_write(self):
        preview=await self.preview();self.rows[0][FIELD]["other"]=18
        with self.assertRaises(HTTPException) as error:await self.commit(preview)
        self.assertEqual(error.exception.status_code,409);self.assertEqual(self.writes,[])

    async def test_conflict_preview_never_returns_commit_token(self):
        self.rows[0][FIELD]["ra_triage_dashboard"]["operation_id"]="newer"
        preview=await self.preview();self.assertFalse(preview["ready"]);self.assertEqual(preview["preview_id"],"")

    async def test_actor_expiry_confirmation_and_admin_gates(self):
        preview=await self.preview()
        with patch.object(routes,"request_identity",return_value=SimpleNamespace(username="bob",source="sso",verified=True)):
            with self.assertRaises(HTTPException) as error:await self.commit(preview)
            self.assertEqual(error.exception.status_code,403)
        with patch.object(self.db,"access_role",return_value="writer"):
            with self.assertRaises(HTTPException):await self.preview()
        self.settings.trail_rollback_enabled=False
        with self.assertRaises(HTTPException):await self.preview()
        self.settings.trail_rollback_enabled=True
        routes._previews[preview["preview_id"]]["expires_at"]=0
        with self.assertRaises(HTTPException):await self.commit(preview)
        self.assertEqual(self.writes,[])

    async def test_audit_failure_prevents_external_write(self):
        preview=await self.preview()
        with patch.object(self.db,"begin_trail_operation",side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):await self.commit(preview)
        self.assertEqual(self.writes,[])

    async def test_uncertain_write_can_be_verified_after_restart(self):
        preview=await self.preview()
        original_writer=routes.write_trail_model_results
        def timeout(changes,**kwargs):
            original_writer(changes,**kwargs)
            raise TimeoutError()
        with patch.object(routes,"write_trail_model_results",timeout):
            with self.assertRaises(TimeoutError):await self.commit(preview)
        restore_id=routes._previews[preview["preview_id"]]["operation_id"]
        self.assertEqual(self.db.trail_operation(restore_id)["status"],"unknown")
        routes._previews.clear()
        result=await routes.verify(restore_id,request())
        self.assertEqual(result["status"],"succeeded");self.assertEqual(len(self.writes),1)

    async def test_timeout_retry_reconciles_without_duplicate_write(self):
        preview=await self.preview();original=routes.write_trail_model_results
        def timeout(changes,**kwargs):original(changes,**kwargs);raise TimeoutError()
        with patch.object(routes,"write_trail_model_results",timeout):
            with self.assertRaises(TimeoutError):await self.commit(preview)
        result=await self.commit(preview)
        self.assertTrue(result["ok"]);self.assertEqual(len(self.writes),1)

    async def test_read_history_does_not_query_trail(self):
        with patch.object(routes,"read_trail_model_fields",side_effect=AssertionError("unexpected remote read")):
            result=await routes.history(request(),issue_id="",actor="",source="",status="",since="",until="",page=1,page_size=20)
            self.assertEqual(result["total"],1)
            self.assertEqual(result["coverage"]["historical_values_complete"],False)

    async def test_legacy_cannot_restore(self):
        self.db.upsert_trail_issue_exclusion_history(operation_id="old",entries=[{"issue_id":"cn00000001","status":"synced"}])
        self.db.import_legacy_trail_history()
        with self.assertRaises(HTTPException):await routes.restore_preview("old",request({"reason":"test"}))

    async def test_partial_batch_explicit_subset_and_out_of_scope_guard(self):
        self.db.begin_trail_operation(operation_id="partial",actor="alice",actor_source="sso",actor_verified=True,
            source="exclusion_direct",items=[item(),item("cn00000002")])
        self.db.append_trail_event("partial","partial",{"cn00000001":"succeeded","cn00000002":"unknown"})
        preview=await routes.restore_preview("partial",request({"reason":"subset","issue_ids":["cn00000001"]}))
        self.assertTrue(preview["ready"])
        self.assertEqual([i["issue_id"] for i in preview["items"]],["cn00000001"])
        for ids in (["cn00000002"],["cn99999999"],[],["cn00000001","cn00000001"]):
            with self.assertRaises(HTTPException):await routes.restore_preview("partial",request({"reason":"subset","issue_ids":ids}))

    async def test_later_observation_does_not_erase_original_success(self):
        self.rows[0][FIELD]["ra_triage_dashboard"]["operation_id"]="someone-else"
        result=await routes.verify("original",request())
        self.assertEqual(result["status"],"succeeded")
        self.assertEqual(result["current_conflicts"],["cn00000001"])


@unittest.skipUnless(os.getenv("DASHBOARD_TEST_POSTGRES_URL", "").startswith("postgresql://"), "Disposable PostgreSQL URL required")
class TrailHistoryPostgresTest(unittest.TestCase):
    def test_migration_audit_retry_and_immutable_triggers(self):
        database=Database(os.environ["DASHBOARD_TEST_POSTGRES_URL"],postgres_migrations_dir=Path(__file__).resolve().parents[1]/"migrations"/"postgres")
        self.addCleanup(database.close)
        database.init()
        operation_id="pg-trail-"+uuid4().hex
        args=dict(operation_id=operation_id,actor="pg-trail-test",actor_source="test",actor_verified=True,source="exclusion_summary",items=[item()])
        revision=database.change_revision()
        database.begin_trail_operation(**args);database.begin_trail_operation(**args)
        database.append_trail_event(operation_id,"succeeded",{"cn00000001":"succeeded"})
        self.assertEqual(database.trail_operation(operation_id)["status"],"succeeded")
        self.assertGreater(database.change_revision(),revision)
        import psycopg
        with self.assertRaises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute("DELETE FROM trail_operations WHERE id = ?",(operation_id,))
        self.assertIsNotNone(database.trail_operation(operation_id))


if __name__ == "__main__":
    unittest.main()
