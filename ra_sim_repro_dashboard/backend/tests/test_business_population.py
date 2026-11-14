"""Native publication scope: disposable SQLite, no upstream or operational writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ReleaseIssueSnapshot, ReleaseSimulationBatch, ReleaseWorkflowState
from app.services import release_workflow as workflow
from app.services.business_population import scope_for_batch, historical_scope


class BusinessPopulationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.now = datetime.now(timezone.utc)
        self.release = "gen4-release-20261106"
        self.period = {"release": self.release, "verified": True, "status": "completed", "binary_id": 123,
                       "case_start": (self.now-timedelta(days=3)).isoformat(),
                       "case_end_exclusive": (self.now-timedelta(days=1)).isoformat(),
                       "evidence": "synthetic full observation", "completion_rule": "issue_last_time_24h",
                       "cycle_end": (self.now-timedelta(days=2)).date().isoformat(),
                       "observed_at": self.now.isoformat(), "last_issue_at": (self.now-timedelta(days=2)).isoformat()}
        self.rows = [{"issue_id": "cn1", "ra_type": 2, "version": "1."+self.release+".600",
                      "issue_time": int((self.now-timedelta(days=2)).timestamp()*1000), "ra_merge_result": "成功"},
                     {"issue_id": "cn2", "ra_type": 3, "version": "1."+self.release+".600",
                      "issue_time": int((self.now-timedelta(days=2, hours=1)).timestamp()*1000), "ra_merge_result": "成功"}]
        self.payload = {"release": self.release, "period": self.period, "issues": self.rows,
                        "scenarios": [{"scenario_id": "1", "issue_id": "cn1"}, {"scenario_id": "2", "issue_id": "cn2"}],
                        "population_complete": True, "source_scope": "full_period"}
        self.config = {"contract": {"verified": True, "reference": "fixture", "time_field": "issue_time"},
                       "periods": [self.period], "simulation": {}}
        self.payload["population_hash"] = workflow.population_identity(self.payload)
        self.batch = ReleaseSimulationBatch(fingerprint="frozen", release=self.release, status="complete",
            payload={**deepcopy(self.payload), "summary": {"eligible": 2},
                     "issues": [{key: row[key] for key in ("issue_id", "ra_type", "ra_merge_result")} for row in self.rows]})
        self.snapshot = ReleaseIssueSnapshot(release=self.release,
            period_hash=workflow.period_key(self.config, self.period), payload=deepcopy(self.payload))
        self.db.add_all([self.batch, self.snapshot]); self.db.commit()
        self.config_patch = patch.object(workflow, "effective_config", return_value=self.config)
        self.config_patch.start(); self.addCleanup(self.config_patch.stop)

    def observe(self, rows=None, *, completed=True, stale=False, changed=True):
        rows = deepcopy(self.rows if rows is None else rows)
        activity = "current-activity"
        workflow.put_state(self.db, "release_observation:"+self.release, {
            "release": self.release, "issues": rows, "activity_hash": activity, "observed_at": self.now.isoformat()})
        workflow.put_state(self.db, "release_monitor:"+self.release, {
            "release": self.release, "activity_hash": activity, "quiet_seconds": 86400 if completed else 3600,
            "last_success_at": (self.now-timedelta(hours=4) if stale else self.now).isoformat(),
            "population_changed_after_submission": changed, "status": "already_submitted"})

    def test_historical_full_population_needs_no_observation(self):
        result = scope_for_batch(self.db, self.batch)
        self.assertTrue(result["available"])
        self.assertEqual((result["collected_issue_count"], result["auto_count"], result["manual_count"]), (2, 1, 1))
        self.assertEqual(result["evaluated_issue_count"], 2)

    def test_real_make_plan_shape_uses_frozen_source_version_and_time(self):
        self.assertEqual(set(self.batch.payload["issues"][0]), {"issue_id", "ra_type", "ra_merge_result"})
        self.observe()
        self.assertTrue(scope_for_batch(self.db, self.batch)["available"])

    def test_batch_identity_must_match_original_source_even_when_plan_is_compact(self):
        original = deepcopy(self.batch.payload)
        for changed in ({"issue_id": "different"}, {"ra_type": 3},
                        {"version": "1."+self.release+".601"}, {"issue_time": self.rows[0]["issue_time"]+1}):
            with self.subTest(changed=changed):
                value = deepcopy(original); value["issues"][0].update(changed)
                self.batch.payload = value; self.db.commit()
                self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "invalid_population")

    def test_duplicate_batch_ids_cannot_match_original_source(self):
        value = deepcopy(self.batch.payload); value["issues"][1] = deepcopy(value["issues"][0])
        self.batch.payload = value; self.db.commit()
        self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "invalid_population")

    def test_expanding_population_does_not_publish_old_small_execution(self):
        rows = self.rows + [{**self.rows[0], "issue_id": "cn3", "issue_time": int(self.now.timestamp()*1000)}]
        self.observe(rows, completed=False)
        result = scope_for_batch(self.db, self.batch)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason_code"], "population_changed")
        self.assertEqual((result["collected_issue_count"], result["evaluated_issue_count"]), (3, 2))

    def test_same_count_replacement_is_population_changed(self):
        self.observe([{**self.rows[0], "issue_id": "cn3"}, self.rows[1]])
        self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "population_changed")

    def test_only_closed_history_can_retain_original_frozen_scope(self):
        self.observe([{**self.rows[0], 'issue_id':'late'}, self.rows[1]])
        scope = scope_for_batch(self.db, self.batch)
        self.assertFalse(scope['available'])
        self.assertTrue(historical_scope(scope, is_current=False)['historical_frozen'])
        self.assertNotIn('historical_frozen', historical_scope(scope, is_current=True))
        for patch_scope in ({'collection_status':'collecting'}, {'collection_completed':False},
                            {'stale':True}, {'reason_code':'invalid_population'}, {'frozen_issue_count':None}):
            self.assertNotIn('historical_frozen', historical_scope({**scope, **patch_scope}, is_current=False))

    def test_collecting_same_population_does_not_publish(self):
        self.observe(completed=False)
        result = scope_for_batch(self.db, self.batch)
        self.assertFalse(result["available"])
        self.assertEqual((result["reason_code"], result["collection_status"]), ("collecting", "collecting"))

    def test_gt_only_change_and_any_old_batch_flag_do_not_change_population(self):
        self.observe([{**row, "ra_merge_result": "误触发"} for row in self.rows])
        self.assertTrue(scope_for_batch(self.db, self.batch)["available"])

    def test_stale_observation_is_not_current_coverage(self):
        self.observe(stale=True)
        result = scope_for_batch(self.db, self.batch)
        self.assertTrue(result["collection_completed"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["reason_code"], "collecting")

    def test_duplicate_observation_identity_fails_closed(self):
        self.observe(self.rows + [self.rows[0]])
        self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "invalid_population")

    def test_identity_field_changes_are_not_gt_changes(self):
        for key, replacement in (("ra_type", 3), ("version", "1."+self.release+".601"),
                                 ("issue_time", self.rows[0]["issue_time"]+1)):
            with self.subTest(key=key):
                self.observe([{**self.rows[0], key: replacement}, self.rows[1]])
                self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "population_changed")

    def test_partial_or_unverified_original_source_cannot_publish(self):
        for change in ({"population_complete": False}, {"source_scope": "acceptance_subset"},
                       {"period": {**self.period, "verified": False}}):
            with self.subTest(change=change):
                self.snapshot.payload = {**deepcopy(self.payload), **change}; self.db.commit()
                self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "invalid_population")

    def test_missing_complete_evidence_and_source_record_fail_closed(self):
        self.snapshot.payload = {k: v for k, v in self.payload.items() if k != "population_complete"}; self.db.commit()
        self.assertFalse(scope_for_batch(self.db, self.batch)["available"])
        self.db.delete(self.snapshot); self.db.commit()
        self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "invalid_population")

    def test_new_full_snapshot_without_observer_also_checks_membership(self):
        latest = {**deepcopy(self.payload), "issues": self.rows + [{**self.rows[0], "issue_id": "cn3"}]}
        self.db.add(ReleaseIssueSnapshot(release=self.release, period_hash="newer", payload=latest)); self.db.commit()
        self.assertEqual(scope_for_batch(self.db, self.batch)["reason_code"], "population_changed")

    def test_complete_source_marker_without_legacy_scope_is_compatible(self):
        self.snapshot.payload = {k: v for k, v in self.payload.items() if k != "source_scope"}; self.db.commit()
        self.assertTrue(scope_for_batch(self.db, self.batch)["available"])

    def test_read_does_not_modify_snapshots_or_approvals(self):
        self.observe()
        before = deepcopy(self.batch.payload), deepcopy(self.snapshot.payload)
        state_count = len(list(self.db.scalars(select(ReleaseWorkflowState))))
        self.assertTrue(scope_for_batch(self.db, self.batch)["available"])
        self.assertFalse(self.db.dirty)
        self.assertEqual((self.batch.payload, self.snapshot.payload), before)
        self.assertEqual(len(list(self.db.scalars(select(ReleaseWorkflowState)))), state_count)


if __name__ == "__main__":
    unittest.main()
