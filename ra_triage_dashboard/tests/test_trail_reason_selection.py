from __future__ import annotations
import asyncio
from copy import deepcopy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from ra_triage_dashboard.app.routers.trail_update import selection as selected
from ra_triage_dashboard.app.routers.trail_update import commit
from ra_triage_dashboard.app.trail_exclusion_contracts import exclusion_comparison, trail_update_details
from ra_triage_dashboard.app.trail_writer import build_trail_changes, verify_trail_readback

INFO = "ra_stuck_auto_result_info"

def request(body):
    return SimpleNamespace(json=AsyncMock(return_value=body))

def item(issue="cn00000001", reason="new", revision=1):
    return {"issue_id": issue, "comment": reason, "review": {"note": reason},
            "reason_source": {"kind": "case_label", "revision_id": revision, "author": "alice"},
            "case_label_source": {"revision_ids": [revision]},
            "target": {"patch": {"ra_triage_dashboard": {"should_exclude": True,
                **({"should_exclude_comment": reason} if reason else {})}}}}

class ReasonComparisonTest(unittest.TestCase):
    def test_readback_requires_boolean_not_numeric_equivalence(self):
        for expected, numeric in ((False, 0), (True, 1)):
            changes = [{"issue_id": "cn00000001", INFO: {"ra_triage_dashboard": {"should_exclude": expected}}}]
            rows = [{"issue_id": "cn00000001", INFO: {"ra_triage_dashboard": {"should_exclude": numeric}}}]
            self.assertFalse(verify_trail_readback(changes, rows)["ok"])
            self.assertTrue(verify_trail_readback(changes, changes)["ok"])

    def test_matrix_and_empty_reason_preserves_exact_remote(self):
        for marker, remote, local, expected in [
            (True,"same","same","synced"), (True,"","","excluded_no_reason"),
            (True,"old","new","reason_changed"), (True,"","new","reason_missing"),
            (True,"old","","excluded_keep_reason"), (False,"old","new","needs_exclusion"),
            (None,"","","needs_exclusion"),
        ]:
            with self.subTest(expected=expected):
                self.assertEqual(exclusion_comparison(marker,remote,local)["state"],expected)
        remote = {"ra_triage_dashboard":{"should_exclude":False,"should_exclude_comment":"  original\n text  "},"model_result":{"label":"keep"},"other":42}
        changes=build_trail_changes([item(reason="")], current_rows=[{"issue_id":"cn00000001",INFO:remote}],write_result_field=False)
        self.assertEqual(changes[0][INFO]["ra_triage_dashboard"]["should_exclude_comment"],"  original\n text  ")
        self.assertEqual(changes[0][INFO]["other"],42)
        self.assertEqual(changes[0][INFO]["model_result"],{"label":"keep"})
        self.assertNotIn("ra_stuck_auto_result",changes[0])

    def test_45_candidates_keep_exclusion_counts_after_four_reasons(self):
        ids=[f"cn{i:08}" for i in range(45)]
        rows=[{"issue_id":issue,INFO:{"ra_triage_dashboard":{"should_exclude":i<15,"should_exclude_comment":"old" if i<4 else "new"}}} for i,issue in enumerate(ids)]
        snapshot=SimpleNamespace(complete=True,rows=rows)
        def counts():
            details=trail_update_details(snapshot,ids,info_field=INFO,expected_comments=dict.fromkeys(ids,"new"))
            return [sum(d["trail_should_exclude"] is True for d in details.values()),sum(d["needs_exclusion_update"] for d in details.values()),sum(d["state"]=="reason_changed" for d in details.values())]
        self.assertEqual(counts(),[15,30,4])
        for row in rows[:4]:row[INFO]["ra_triage_dashboard"]["should_exclude_comment"]="new"
        self.assertEqual(counts(),[15,30,0])
        snapshot.complete=False
        self.assertTrue(all(d["state"]=="query_failed" for d in trail_update_details(snapshot,ids,info_field=INFO).values()))

    def test_dataframe_empty_info_is_unset_but_malformed_values_fail_closed(self):
        issue = "cn00000001"
        for value in (None, "", float("nan")):
            snapshot = SimpleNamespace(complete=True, rows=[{"issue_id":issue, INFO:value}])
            detail = trail_update_details(snapshot, [issue], info_field=INFO, expected_comments={issue:"new"})[issue]
            self.assertEqual(detail["state"], "needs_exclusion")
            self.assertIsNone(detail["trail_should_exclude"])
            self.assertEqual(selected._owned_fields(snapshot.rows[0], INFO), {})
        for value in (float("inf"), 0, 7.5, "NaN", [], "broken JSON"):
            snapshot = SimpleNamespace(complete=True, rows=[{"issue_id":issue, INFO:value}])
            detail = trail_update_details(snapshot, [issue], info_field=INFO)[issue]
            self.assertEqual(detail["state"], "query_failed")
            self.assertFalse(detail["needs_exclusion_update"])
            with self.assertRaises(HTTPException):selected._owned_fields(snapshot.rows[0], INFO)

    def test_canonical_exclusion_skips_synthetic_review_and_notifications(self):
        with patch.object(commit.database,"get_case",return_value={"annotations":[{"id":4000000000000614}]}), patch.object(commit.database,"project_issue_exclusions",return_value={"cn00000001":{"is_excluded":True}}), patch.object(commit.database,"create_annotation") as create:
            result=commit._mark_local_review_exclusions(["cn00000001"],actor=SimpleNamespace(username="alice",source="sso",verified=True),notification_recipients_by_issue={"cn00000001":["bob"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["already_excluded_count"],1)
        self.assertEqual(result["notification_queued_count"],0)
        create.assert_not_called()

class SelectedUpdateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path
        from ra_triage_dashboard.app.db import Database
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        audit_database = Database(Path(temporary.name) / "audit.sqlite3")
        audit_database.init()
        audit_patch = patch.object(selected, "database", audit_database)
        audit_patch.start(); self.addCleanup(audit_patch.stop)
        selected._selection_previews.clear()
        self.items=[item(),item("cn00000002")]
        self.rows=[{"issue_id":it["issue_id"],INFO:{"other":17,"model_result":{"label":"keep"},"ra_triage_dashboard":{"should_exclude":True,"should_exclude_comment":"old"}}} for it in self.items]
        self.actor=SimpleNamespace(username="alice",source="sso",verified=True)
        self.writes=[]
        def read(**kwargs):
            rows=[deepcopy(row) for row in self.rows if row["issue_id"] in kwargs["issue_ids"]]
            return SimpleNamespace(complete=True,rows=rows,fields_visible=[INFO],returned_issues=len(rows),queried_issues=len(kwargs["issue_ids"]),view_id="2410",message="model field missing")
        async def candidates(*args,**kwargs):return {"items":deepcopy(self.items)}
        def write(changes,**kwargs):
            self.writes.extend(deepcopy(changes))
            for change in changes:
                for row in self.rows:
                    if row["issue_id"]==change["issue_id"]:row.update(deepcopy(change))
            return {"total":len(changes),"success_count":len(changes),"failed_count":0,"failed_issue_ids":[]}
        self.audit=AsyncMock()
        for obj,name,value in [
            (selected,"settings",SimpleNamespace(trail_attribute_write_enabled=True,trail_attribute_review_write_enabled=True,ra_auto_triage_root="/tmp",trail_view_id="2410",trail_sync_chunk_size=10,trail_attribute_write_chunk_size=10)),
            (selected,"has_same_origin_mutation_marker",lambda r:True),
            (selected,"request_identity",lambda *a:self.actor),(selected,"identity_can_write",lambda *a:True),
            (selected,"_build_preview",candidates),(selected,"read_trail_model_fields",read),
            (commit,"read_trail_model_fields",read),(selected,"write_trail_model_results",write),
            (selected,"_audit",self.audit),
            (selected,"resolve_request_baseline_scopes",lambda *a, **k:["scope"]),
        ]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    async def preview(self,**extra):
        return await selected.selection_preview(request({"issue_ids":["cn00000001"],"intent":"reason_only",**extra}))
    async def submit(self,preview,**extra):
        return await selected.selection_commit(request({"confirm":True,"payload_sha256":preview["payload_sha256"],**extra}))

    def false_vote(self, author="alice", excluded=False, previous=None):
        selected.database.upsert_issues(
            [{"issue_id": "cn00000001", "gt_label": "正确触发"}],
            source="test", replace_gt=True, baseline_scope="scope")
        return selected.database.create_label_revision(issue_id="cn00000001",
            expected_output="正确触发", tags=[], evidence_gaps=[], rationale="local rationale",
            is_excluded=excluded, author=author, author_source="test", author_verified=True,
            expected_previous_revision_id=previous)

    async def non_preview(self, **extra):
        return await selected.non_exclusion_preview(request({"issue_ids": ["cn00000001"], **extra}))

    async def test_non_exclusion_preserves_reason_and_audits_boolean_false(self):
        vote = self.false_vote()
        self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude_comment"] = "  original\n text  "
        preview = await self.non_preview()
        self.assertEqual(preview["intent"], "unexclude")
        change = preview["items"][0]
        self.assertEqual(change["target"]["patch"], {"ra_triage_dashboard": {"should_exclude": False}})
        self.assertEqual(change["case_label_source"]["revision_ids"], [vote["id"]])
        self.assertEqual(change["reason_source"]["rationale"], "local rationale")
        self.assertEqual(change["after"]["should_exclude_comment"], "  original\n text  ")
        self.assertFalse(self.writes)
        result = await selected.non_exclusion_commit(request({"confirm": True, "payload_sha256": preview["payload_sha256"]}))
        self.assertTrue(result["ok"])
        self.assertIs(self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"], False)
        self.assertEqual(self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude_comment"], "  original\n text  ")
        self.assertEqual(self.rows[0][INFO]["other"], 17)
        self.assertEqual(self.rows[0][INFO]["model_result"], {"label": "keep"})
        self.assertEqual(set(self.writes[0]), {"issue_id", INFO})
        operation = selected.database.trail_operation(preview["payload_sha256"])
        self.assertIs(operation["items"][0]["before"]["should_exclude"], True)
        self.assertIs(operation["items"][0]["after"]["should_exclude"], False)
        self.assertEqual((await self.submit(preview))["submitted_count"], 0)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(selected.database.project_issue_exclusions(["cn00000001"])["cn00000001"]["revision_ids"], [vote["id"]])

    async def test_non_exclusion_rejects_unknown_true_other_author_and_stale_local(self):
        with self.assertRaises(HTTPException): await self.non_preview()
        first = self.false_vote()
        preview = await self.non_preview()
        self.false_vote("bob", excluded=True)
        with self.assertRaises(HTTPException): await self.submit(preview)
        with self.assertRaises(HTTPException): await self.non_preview()
        self.assertFalse(self.writes)

    async def test_non_exclusion_revision_scope_run_and_remote_guards(self):
        first = self.false_vote()
        with self.assertRaises(HTTPException): await self.non_preview(model_run_id="missing-run")
        with patch.object(selected, "resolve_request_baseline_scopes", return_value=["other"]):
            with self.assertRaises(HTTPException): await self.non_preview()
        preview = await self.non_preview()
        self.false_vote(previous=first["id"])
        with self.assertRaises(HTTPException): await self.submit(preview)
        preview = await self.non_preview()
        self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude_comment"] = "changed remotely"
        with self.assertRaises(HTTPException): await self.submit(preview)
        for marker in (False, "false", 0, 1, "true", []):
            self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"] = marker
            with self.assertRaises(HTTPException): await self.non_preview()
        self.assertFalse(self.writes)

    async def test_non_exclusion_missing_marker_and_strict_route_intent(self):
        self.false_vote()
        with self.assertRaises(HTTPException): await self.non_preview(intent="exclude")
        reason_preview = await self.preview()
        with self.assertRaises(HTTPException):
            await selected.non_exclusion_commit(request({"confirm": True, "payload_sha256": reason_preview["payload_sha256"]}))
        self.rows[0][INFO] = {"other": 17}
        preview = await self.non_preview()
        self.assertEqual(preview["items"][0]["after"], {"should_exclude": False})
        self.assertTrue((await self.submit(preview))["ok"])
        self.assertNotIn("should_exclude_comment", self.rows[0][INFO]["ra_triage_dashboard"])

    async def test_non_exclusion_remote_numeric_change_is_not_idempotent_success(self):
        self.false_vote()
        preview = await self.non_preview()
        self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"] = 1
        with self.assertRaises(HTTPException): await self.submit(preview)
        self.assertFalse(self.writes)
        self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"] = True
        self.assertTrue((await self.submit(preview))["ok"])
        self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"] = 0
        with self.assertRaises(HTTPException): await self.submit(preview)
        self.assertEqual(len(self.writes), 1)

    async def test_non_exclusion_shared_auth_confirmation_audit_and_retry_guards(self):
        self.false_vote()
        with patch.object(selected, "has_same_origin_mutation_marker", return_value=False):
            with self.assertRaises(HTTPException): await self.non_preview()
        with patch.object(selected, "identity_can_write", return_value=False):
            with self.assertRaises(HTTPException): await self.non_preview()
        selected.settings.trail_attribute_review_write_enabled = False
        with self.assertRaises(HTTPException): await self.non_preview()
        selected.settings.trail_attribute_review_write_enabled = True
        preview = await self.non_preview()
        with self.assertRaises(HTTPException): await self.submit(preview, confirm=False)
        self.actor.username = "bob"
        with self.assertRaises(HTTPException): await self.submit(preview)
        self.actor.username = "alice"
        self.audit.side_effect = RuntimeError("audit unavailable")
        with self.assertRaises(RuntimeError): await self.submit(preview)
        self.assertFalse(self.writes)
        self.audit.side_effect = None
        original = selected.write_trail_model_results
        def timeout(changes, **kwargs):
            original(changes, **kwargs)
            raise TimeoutError("lost response")
        with patch.object(selected, "write_trail_model_results", timeout):
            with self.assertRaises(TimeoutError): await self.submit(preview)
        self.assertTrue((await self.submit(preview))["ok"])
        self.assertEqual(len(self.writes), 1)

    async def test_selected_subset_tampering_idempotence_readback_and_other_keys(self):
        preview=await self.preview()
        result=await self.submit(preview,issue_ids=["cn00000002"],target={"patch":{"evil":True}})
        self.assertTrue(result["ok"])
        self.assertEqual([w["issue_id"] for w in self.writes],["cn00000001"])
        self.assertEqual(self.rows[0][INFO]["other"],17)
        self.assertEqual(self.rows[0][INFO]["model_result"],{"label":"keep"})
        self.assertEqual(self.rows[1][INFO]["ra_triage_dashboard"]["should_exclude_comment"],"old")
        self.assertNotIn("模型字段",result["readback"]["message"])
        result2=await self.submit(preview)
        self.assertTrue(result2["ok"]);self.assertEqual(result2["submitted_count"],0)
        self.assertEqual(len(self.writes),1)
        self.assertEqual(self.audit.await_count,2)
        self.assertEqual(self.audit.call_args.args[3],"synced")

    async def test_dataframe_empty_info_selected_exclusion_is_idempotent(self):
        self.rows[0][INFO] = float("nan")
        preview = await self.preview(intent="exclude")
        self.assertEqual(preview["items"][0]["before"], {})
        result = await self.submit(preview)
        self.assertTrue(result["ok"])
        self.assertTrue(self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"])
        self.assertNotIn("ra_stuck_auto_result", self.writes[0])
        repeated = await self.submit(preview)
        self.assertTrue(repeated["ok"])
        self.assertEqual(len(self.writes), 1)

    async def test_local_revision_change_rejected_even_same_text(self):
        preview=await self.preview();self.items[0]["reason_source"]["revision_id"]=2
        with self.assertRaises(HTTPException) as cm:await self.submit(preview)
        self.assertEqual(cm.exception.status_code,409);self.assertFalse(self.writes)

    async def test_remote_reason_change_rejected(self):
        preview=await self.preview();self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude_comment"]="someone else"
        with self.assertRaises(HTTPException) as cm:await self.submit(preview)
        self.assertEqual(cm.exception.status_code,409);self.assertFalse(self.writes)

    async def test_actor_expiry_and_confirmation(self):
        preview=await self.preview();self.actor.username="bob"
        with self.assertRaises(HTTPException) as cm:await self.submit(preview)
        self.assertEqual(cm.exception.status_code,403)
        self.actor.username="alice"
        with self.assertRaises(HTTPException):await self.submit(preview,confirm=False)
        selected._selection_previews[preview["payload_sha256"]]["expires_at"]=0
        with self.assertRaises(HTTPException):await self.submit(preview)
        self.assertFalse(self.writes)

    async def test_authorization_and_write_switches(self):
        for target,value in [("has_same_origin_mutation_marker",lambda r:False),("identity_can_write",lambda *a:False)]:
            with patch.object(selected,target,value),self.assertRaises(HTTPException) as cm:await self.preview()
            self.assertEqual(cm.exception.status_code,403)
        selected.settings.trail_attribute_review_write_enabled=False
        with self.assertRaises(HTTPException):await self.preview()
        self.assertFalse(self.writes)

    async def test_only_reason_requires_excluded_and_nonempty_changed_reason(self):
        self.rows[0][INFO]["ra_triage_dashboard"]["should_exclude"]=False
        with self.assertRaises(HTTPException):await self.preview()
        preview=await self.preview(intent="exclude")
        self.assertTrue((await self.submit(preview))["ok"])
        self.items[0]=item(reason="")
        with self.assertRaises(HTTPException):await self.preview()

    async def test_missing_remote_or_candidate_fails_closed(self):
        self.rows=[]
        with self.assertRaises(HTTPException):await self.preview()
        self.items=[]
        with self.assertRaises(HTTPException):await self.preview()
        self.assertFalse(self.writes)

    async def test_audit_failure_blocks_external_write(self):
        preview=await self.preview();self.audit.side_effect=RuntimeError("audit unavailable")
        with self.assertRaises(RuntimeError):await self.submit(preview)
        self.assertFalse(self.writes)

    async def test_readonly_history_and_ambiguous_baselines_rejected(self):
        with self.assertRaises(HTTPException):await self.preview(issue_ids=["cn32171803"])
        self.items[0]["readonly"]=True
        with self.assertRaises(HTTPException):await self.preview()
        self.items[0]["readonly"]=False
        self.items.append(deepcopy(self.items[0]))
        with self.assertRaises(HTTPException):await self.preview()
        self.assertFalse(self.writes)

    async def test_partial_write_retry_submits_only_unapplied_issue(self):
        preview=await self.preview(issue_ids=["cn00000001","cn00000002"])
        original=selected.write_trail_model_results
        def partial(changes,**kwargs):
            original(changes[:1],**kwargs)
            return {"failed_count":1,"failed_issue_ids":["cn00000002"]}
        with patch.object(selected,"write_trail_model_results",partial):
            first=await self.submit(preview)
        self.assertFalse(first["ok"])
        self.assertEqual(first["failed_issue_ids"],["cn00000002"])
        second=await self.submit(preview)
        self.assertTrue(second["ok"])
        self.assertEqual(second["submitted_count"],1)
        self.assertEqual(second["skipped_synced_issue_ids"],["cn00000001"])
        self.assertEqual([row["issue_id"] for row in self.writes],["cn00000001","cn00000002"])

    async def test_timeout_after_write_retry_does_not_duplicate(self):
        preview=await self.preview()
        original=selected.write_trail_model_results
        def timeout(changes,**kwargs):
            original(changes,**kwargs)
            raise TimeoutError("response lost")
        with patch.object(selected,"write_trail_model_results",timeout),self.assertRaises(TimeoutError):
            await self.submit(preview)
        result=await self.submit(preview)
        self.assertTrue(result["ok"]);self.assertEqual(result["submitted_count"],0)
        self.assertEqual(len(self.writes),1)

    async def test_concurrent_commits_are_serialized(self):
        preview=await self.preview()
        results=await asyncio.gather(self.submit(preview),self.submit(preview))
        self.assertTrue(all(result["ok"] for result in results))
        self.assertEqual(sum(result["submitted_count"] for result in results),1)
        self.assertEqual(len(self.writes),1)

    async def test_corrupt_info_duplicate_snapshot_and_failed_readback_fail_closed(self):
        self.rows[0][INFO]="invalid JSON"
        with self.assertRaises(HTTPException):await self.preview()
        self.assertFalse(self.writes)
        self.rows[0][INFO]={"ra_triage_dashboard":{"should_exclude":True,"should_exclude_comment":"old"}}
        self.rows.append(deepcopy(self.rows[0]))
        with self.assertRaises(HTTPException):await self.preview()
        self.rows.pop()
        preview=await self.preview()
        with patch.object(selected,"_readback_changes",AsyncMock(return_value={"complete":False,"ok":False})):
            result=await self.submit(preview)
        self.assertFalse(result["ok"]);self.assertEqual(result["failed_issue_ids"],["cn00000001"])

if __name__ == "__main__":unittest.main()
