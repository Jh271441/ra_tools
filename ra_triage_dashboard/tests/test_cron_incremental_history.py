from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from ra_triage_dashboard.app.cron_incremental_history import incremental_history, window_start


def at(s):
    return datetime.fromisoformat(s + "+08:00").timestamp()


class IncrementHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "ledger.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE scans(at REAL); CREATE TABLE events(id INTEGER PRIMARY KEY,at REAL,family TEXT,issue_id TEXT,action TEXT,detail_json TEXT);")
        self.control = {"updated_at": at("2026-10-24T01:30:00"), "discovery_schedule": {"hours": [7,19]}}
        self.datasets = [{"id": "d1009", "release_family": "20261009"}, {"id": "d1016", "release_family": "20261016"}]
        self.pg = sqlite3.connect(":memory:")
        self.pg.row_factory = sqlite3.Row
        self.addCleanup(self.pg.close)
        self.pg.execute("CREATE TABLE dataset_ingestion_batches(dataset_id TEXT,batch_key TEXT,receipt_json TEXT,created_at TEXT)")
        self.database = Mock()
        @contextmanager
        def connect():
            yield self.pg
        self.database.connect = connect

    def event(self, hour, action, iid, family="20261016", detail=None):
        self.db.execute("INSERT INTO events(at,family,issue_id,action,detail_json) VALUES(?,?,?,?,?)", (at("2026-10-24T"+hour), family, iid, action, json.dumps(detail or {})))

    def history(self):
        self.db.commit()
        return incremental_history(self.root, self.control, self.datasets, self.database)

    def test_new_filled_published_are_distinct_and_import_receipts_deduplicate(self):
        self.db.executemany("INSERT INTO scans VALUES(?)", [(at("2026-10-24T07:00:19"),), (at("2026-10-24T19:00:18"),)])
        self.event("07:00:18", "discovered", "cnNew")
        self.event("07:00:18", "source_transition", "cnOld", detail={"from":"waiting_metadata","to":"ready"})
        self.event("07:00:18", "source_transition", "cnExcluded", detail={"from":"waiting_metadata","to":"excluded"})
        self.event("07:20:00", "published", "cnOld")
        self.event("07:25:00", "published", "cnOld")
        self.event("07:26:00", "source_enriched", "cnNew")
        self.event("19:00:00", "published", "cnCrossRound")
        receipt=json.dumps({"target_added":1,"target_retired":0})
        self.pg.executemany("INSERT INTO dataset_ingestion_batches VALUES(?,?,?,?)", [("d1016","one",receipt,"2026-10-24T00:30:00+00:00")]*2)
        result=self.history()
        self.assertEqual(result["status"],"ready")
        rows=[r for r in result["items"] if r["family"]=="20261016"]
        self.assertEqual([r["published"] for r in rows],[1,1])
        self.assertEqual((rows[1]["new"],rows[1]["filled"],rows[1]["target_added"]),(1,1,1))
        self.assertTrue(all(r["new"]==0 and r["published"]==0 for r in result["items"] if r["family"]=="20261009"))

    def test_failed_scan_has_unknown_discovery_counts_and_no_database_writes(self):
        (self.root/"discovery-schedule.json").write_text(json.dumps({"last_attempt_slot":at("2026-10-24T19:00:00"),"state":"failed"}))
        self.db.commit()
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        result=self.history()
        self.assertEqual(result["items"][0]["scan_state"],"failed")
        self.assertIsNone(result["items"][0]["new"])
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_missing_source_never_creates_a_ledger_or_invents_zero(self):
        missing=self.root/"absent"
        result=incremental_history(missing,self.control,self.datasets,self.database)
        self.assertEqual(result["status"],"unavailable")
        self.assertFalse(missing.exists())

    def test_no_scheduled_scans_is_empty(self):
        self.assertEqual(self.history(),{"status":"empty","items":[]})

    def test_later_configuration_edit_does_not_erase_anchored_history(self):
        self.db.execute("INSERT INTO scans VALUES(?)",(at("2026-10-24T07:00:19"),))
        self.control["discovery_history_started_at"]=self.control["updated_at"]
        self.control["updated_at"]=at("2026-10-24T20:00:00")
        self.assertEqual(len(self.history()["items"]),2)

    def test_bad_receipt_or_pool_failure_is_isolated(self):
        self.db.execute("INSERT INTO scans VALUES(?)",(at("2026-10-24T07:00:19"),))
        self.pg.execute("INSERT INTO dataset_ingestion_batches VALUES(?,?,?,?)",("d1016","bad","{}","2026-10-24T00:30:00+00:00"))
        self.assertEqual(self.history()["status"],"unavailable")
        self.database.connect=Mock(side_effect=RuntimeError("private pool path"))
        result=self.history()
        self.assertEqual(result["status"],"unavailable")
        self.assertNotIn("private",json.dumps(result))

    def test_cst_boundary_and_old_five_minute_history_not_misrepresented(self):
        self.assertEqual(window_start(at("2026-10-24T06:59:59")),at("2026-10-23T19:00:00"))
        self.control["discovery_schedule"]={}
        self.assertEqual(self.history()["status"],"unsupported")
