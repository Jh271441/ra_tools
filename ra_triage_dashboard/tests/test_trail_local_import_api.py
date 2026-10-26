"""All external reads are mocked; no Trail mutation is performed."""
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from ra_triage_dashboard.app.routers.trail_update import local_import as api


def request(body):
    return SimpleNamespace(json=AsyncMock(return_value=body))


class LocalImportApiTest(IsolatedAsyncioTestCase):
    def setUp(self):
        api._previews.clear()
        self.db = Mock()
        self.db.access_role.return_value = "writer"
        self.db.trail_local_import_result.return_value = None
        self.db.preview_trail_local_import.return_value = [{"issue_id": "cn12345678"}]
        self.db.commit_trail_local_import.return_value = {"ok": True, "imported_count": 1}
        self.identity = SimpleNamespace(username="alice", verified=True)
        self.remote = {"cn12345678": {"should_exclude": True, "should_exclude_comment": "reason"}}
        for name, value in (("database", self.db), ("request_identity", Mock(return_value=self.identity)),
                            ("identity_can_write", Mock(return_value=True)),
                            ("has_same_origin_mutation_marker", Mock(return_value=True)),
                            ("resolve_request_baseline_scopes", Mock(return_value=["scope"])),
                            ("_remote", AsyncMock(return_value=self.remote))):
            p = patch.object(api, name, value)
            p.start()
            self.addCleanup(p.stop)

    async def preview(self):
        return await api.local_import_preview(request({"issue_ids": ["cn12345678"], "baselines": ["scope"]}))

    async def test_preview_never_saves_and_commit_rechecks_remote(self):
        result = await self.preview()
        self.db.commit_trail_local_import.assert_not_called()
        token = result["preview_id"]
        api._remote.return_value = {"cn12345678": {"should_exclude": False}}
        with self.assertRaises(HTTPException) as error:
            await api.local_import_commit(request({"preview_id": token, "confirm": True}))
        self.assertEqual(error.exception.status_code, 409)
        self.db.commit_trail_local_import.assert_not_called()
        api._remote.return_value = self.remote
        self.assertTrue((await api.local_import_commit(request({"preview_id": token, "confirm": True})))["ok"])

    async def test_confirmation_expiry_actor_and_durable_replay(self):
        token = (await self.preview())["preview_id"]
        with self.assertRaises(HTTPException):
            await api.local_import_commit(request({"preview_id": token}))
        api._previews[token]["actor"] = "bob"
        with self.assertRaises(HTTPException) as error:
            await api.local_import_commit(request({"preview_id": token, "confirm": True}))
        self.assertEqual(error.exception.status_code, 403)
        api._previews[token]["expires_at"] = time.time() - 1
        with self.assertRaises(HTTPException) as error:
            await api.local_import_commit(request({"preview_id": token, "confirm": True}))
        self.assertEqual(error.exception.status_code, 409)
        api._previews.clear()
        self.db.trail_local_import_result.return_value = {"ok": True, "imported_count": 1}
        api._remote.reset_mock()
        self.assertTrue((await api.local_import_commit(request({"preview_id": token, "confirm": True})))["ok"])
        api._remote.assert_not_called()
        self.db.commit_trail_local_import.assert_not_called()

    async def test_unverified_readonly_and_missing_origin_rejected(self):
        for changed, value in ((api.has_same_origin_mutation_marker, False), (api.identity_can_write, False), (self.db.access_role, "reader")):
            old = changed.return_value
            changed.return_value = value
            with self.assertRaises(HTTPException) as error:
                await self.preview()
            self.assertEqual(error.exception.status_code, 403)
            changed.return_value = old
        self.identity.verified = False
        with self.assertRaises(HTTPException):
            await self.preview()
        api._remote.assert_not_called()

    async def test_remote_snapshot_completeness_and_format(self):
        # Exercise the actual remote parser independently of the mocked preview flow.
        original = self._original_remote
        with patch.object(api, "_field_names", return_value=("label", "info")), patch.object(api, "read_trail_model_fields") as read:
            for complete, rows in ((False, []), (True, []),
                                   (True, [{"issue_id": "cn12345678", "info": "invalid"}])):
                read.return_value = SimpleNamespace(complete=complete, rows=rows)
                with self.assertRaises(HTTPException):
                    await original(["cn12345678"])
            read.return_value = SimpleNamespace(complete=True, rows=[{"issue_id": "cn12345678", "info": {"ra_triage_dashboard": self.remote["cn12345678"]}}])
            self.assertEqual(await original(["cn12345678"]), self.remote)
            read.return_value = SimpleNamespace(complete=True, rows=[{"issue_id":"cn12345678"}])
            self.assertEqual(await original(["cn12345678"]), {"cn12345678":{}})

    async def test_discovery_only_queries_not_locally_excluded_and_preserves_blocked_rows(self):
        self.db.trail_local_import_members.return_value = {"items": [
            {"issue_id":"cn12345678","local_excluded":False},
            {"issue_id":"cn23456789","local_excluded":True},
            {"issue_id":"cn34567890","local_excluded":None}],"total":101,"scanned":100,"next_cursor":"cn99999999"}
        api._remote.return_value = {"cn12345678":{"should_exclude":True,"should_exclude_comment":"remote"},"cn34567890":{"should_exclude":1}}
        self.db.preview_trail_local_import.side_effect = ValueError("Existing adjudication")
        result = await api.local_import_candidates(request({"baselines":"scope"}))
        api._remote.assert_awaited_once_with(["cn12345678","cn34567890"])
        self.assertEqual(len(result["items"]),1)
        self.assertFalse(result["items"][0]["can_import"])
        self.assertEqual(result["next_cursor"],"cn99999999")
        self.db.commit_trail_local_import.assert_not_called()

    async def test_discovery_empty_page_does_not_query_remote(self):
        self.db.trail_local_import_members.return_value = {"items":[],"total":0,"scanned":0,"next_cursor":None}
        result = await api.local_import_candidates(request({"baselines":"scope"}))
        self.assertEqual(result["items"],[])
        api._remote.assert_not_called()

    _original_remote = staticmethod(api._remote)
