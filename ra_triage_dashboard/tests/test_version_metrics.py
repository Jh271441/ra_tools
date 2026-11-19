"""Metric contracts: exact populations, independent lanes, rule-only coverage and history."""
import copy
import fcntl
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from ra_triage_dashboard.app.version_metrics import FIELDS, POLICY, evaluate, case_page, digest
from ra_triage_dashboard.app.version_metric_store import VersionMetricStore


def fixture():
    rows = []
    cases = [
        ("正确触发", .7, "model", "成功", "误触发", False, True),
        ("正确触发", .98, "model", "误触发", "误触发", False, True),
        ("正确触发", .95, "pre_rule", "失败", "成功", True, True),
        ("误触发", .82, "model", "out_of_scope", "误触发", False, True),
        ("无需协助", .99, "model", None, "无需协助", False, True),
        ("误触发", .88, "model", "无需协助", "无需协助", False, True),
        ("正确触发", .6, "model", None, None, False, False),
    ]
    for i, (label, confidence, source, te, rd, excluded, sample) in enumerate(cases, 1):
        refs = {key: dict(observed=key in ("te", "rd"), value=te if key == "te" else rd if key == "rd" else None) for key in FIELDS}
        rows.append(dict(issue_id="cn"+str(i), label=label, confidence=confidence, source=source,
                         sample=sample, published=True, excluded=excluded, references=refs,
                         routed_to_human=source == "model" and confidence < .9))
    return dict(id="a"*64, schema_version=1, policy=POLICY, family="20261030", observed_at="2026-11-15T13:47:45+00:00",
                run_id="frozen-run", registry_revision=1, rows=rows)


def trail_fixture():
    receipt = fixture()
    receipt["started_at"] = "2026-11-15T13:47:00+00:00"
    receipt["provenance"] = dict(reference_source="Trail", prediction_source="published_run_and_trail",
        requested_total=len(receipt["rows"]), returned_total=len(receipt["rows"]), source_sha256=digest(receipt["rows"]))
    return receipt


class VersionMetricsTests(unittest.TestCase):
    def test_rule_only_counts_in_chain_but_not_pure_model(self):
        result = evaluate(fixture())
        self.assertEqual(result["sample_total"], 6)
        self.assertEqual(result["valid_total"], 4)
        self.assertEqual((result["metrics"]["model"]["correct"], result["metrics"]["model"]["total"]), (1, 3))
        self.assertEqual((result["metrics"]["chain"]["correct"], result["metrics"]["chain"]["total"]), (2, 4))
        self.assertEqual(result["metrics"]["model"]["coverage"], .75)
        self.assertEqual(result["metrics"]["chain_human_sim"]["correct"], 3)
        self.assertEqual(result["metrics"]["model_human_sim"]["total"], 3)
        self.assertEqual(result["metrics"]["chain_human_sim"]["confusion_matrix"], result["metrics"]["chain_post_human_sim"]["confusion_matrix"])
        self.assertTrue(result["metrics"]["chain_human_sim"]["simulated"])

    def test_reference_lanes_never_fill_each_other_and_unknown_is_not_zero(self):
        result = evaluate(fixture(), reference="rd")
        self.assertEqual(result["valid_total"], 6)
        self.assertEqual(result["reference_field"], "ra_rd_review_result")
        absent = evaluate(fixture(), reference="te_prime")
        self.assertEqual(absent["valid_total"], 0)
        self.assertEqual(absent["invalid"], {"unknown": 6})
        self.assertIsNone(absent["metrics"]["chain"]["accuracy"])
        self.assertIsNone(absent["metrics"]["chain"]["macro_f1"])
        self.assertEqual(evaluate(fixture())["invalid"], {"oos": 1, "missing": 1})

    def test_exclusion_is_opt_in_and_deduplicates_with_invalid(self):
        f = fixture()
        f["rows"][3]["excluded"] = True
        result = evaluate(f, exclusion="exclude")
        self.assertEqual(result["valid_total"], 3)
        self.assertEqual(result["excluded"], 2)
        self.assertEqual(result["metrics"]["chain"]["total"], 3)
        self.assertEqual(result["metrics"]["model"]["total"], 3)
        self.assertEqual(result["coverage"]["te"]["filled"], 5)

    def test_threshold_workload_uses_published_population_not_sample(self):
        result = evaluate(fixture())
        first = result["thresholds"][0]
        self.assertEqual((first["full_low"], first["full_total"], first["human_count"]), (4, 7, 2))
        lower = evaluate(fixture(), threshold=.8)
        self.assertEqual(lower["metrics"]["chain_human_sim"]["human_count"], 1)
        with self.assertRaises(ValueError):
            evaluate(fixture(), threshold=.89)

    def test_real_review_does_not_reuse_reference_or_sensitivity_threshold(self):
        f = fixture()
        f["rows"][0].update(human_label="误触发", human_reference="rd")
        result = evaluate(f, threshold=.65)
        actual = result["metrics"]["observed_human"]
        self.assertFalse(actual["simulated"])
        self.assertEqual(actual["human_count"], 1)
        self.assertEqual(actual["missing"], 1)  # low case cn6 has no observed human result
        self.assertEqual(actual["same_reference_count"], 0)

    def test_cases_are_exact_and_pagination_clamps_and_validates(self):
        cases = case_page(fixture(), page=999)
        self.assertEqual(cases["page"], 1)
        self.assertEqual([r["issue_id"] for r in cases["items"]], ["cn2", "cn6"])
        matrix = case_page(fixture(), status="all", truth="误触发", predicted="正确触发")
        self.assertEqual([r["issue_id"] for r in matrix["items"]], ["cn2"])
        invalid = case_page(fixture(), status="invalid")
        self.assertEqual([r["issue_id"] for r in invalid["items"]], ["cn4", "cn5"])
        for bad in (0, -1, 1.2):
            with self.assertRaises(ValueError): case_page(fixture(), page=bad)
        with self.assertRaises(ValueError): case_page(fixture(), page_size=1000)

    def test_duplicate_ids_bad_flags_and_nonfinite_confidence_rejected(self):
        for change in (lambda f: f["rows"].append(copy.deepcopy(f["rows"][0])),
                       lambda f: f["rows"][0].update(sample="false"),
                       lambda f: f["rows"][0].update(confidence=float("nan"))):
            f=fixture();change(f)
            with self.assertRaises(ValueError): evaluate(f)


class VersionMetricStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=VersionMetricStore(Path(self.tmp.name))

    def test_job_rechecks_terminal_state_after_acquiring_worker_lock(self):
        state_path = self.store.root / "refresh.json"
        real_flock = fcntl.flock
        for status in ("ready", "failed"):
            with self.subTest(status=status):
                running = dict(status="running", completed=0, total=1)
                terminal = dict(running, status=status, finished_at="2026-11-19T02:00:00+00:00")
                self.store._save(state_path, running)

                def finish_before_lock_observation(lock, operation):
                    real_flock(lock, operation)
                    self.store._save(state_path, terminal)

                with mock.patch(
                    "ra_triage_dashboard.app.version_metric_store.fcntl.flock",
                    side_effect=finish_before_lock_observation,
                ):
                    self.assertEqual(self.store.job(), terminal)
                self.assertEqual(self.store._read(state_path), terminal)

    def test_history_is_immutable_and_changes_counted(self):
        first=self.store.publish("20261030",fixture())
        changed=fixture();changed["rows"][1]["references"]["te"]["value"]="成功"
        second=self.store.publish("20261030",changed)
        self.assertNotEqual(first["id"],second["id"])
        self.assertEqual(second["changes"]["references"],1)
        self.assertEqual(self.store.latest("20261030",first["id"]),first)
        self.assertEqual(self.store.latest("20261030"),second)
        self.assertEqual(len(self.store.history("20261030")),2)
        path=self.store.root/"20261030"/(first["id"]+".json")
        data=json.loads(path.read_text());data["rows"][0]["label"]="误触发";path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.store.latest("20261030",first["id"])
        with self.assertRaises(ValueError): self.store.latest("../../etc")

    def test_failed_refresh_retains_complete_snapshot(self):
        first=self.store.publish("20261030",fixture())
        def fail(_): raise RuntimeError("secret must never appear")
        self.store.refresh(["20261030"],fail)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            job=self.store.job()
            if job["status"]!="running":break
            time.sleep(.01)
        self.assertEqual(job["status"],"failed")
        self.assertNotIn("secret",json.dumps(job))
        self.assertEqual(self.store.latest("20261030")["id"],first["id"])

    def test_current_metrics_require_a_complete_trail_receipt(self):
        report = self.store.publish("20261030", fixture())
        self.assertIsNone(self.store.latest_trail("20261030"))
        actual = self.store.publish("20261030", trail_fixture())
        self.assertEqual(self.store.latest_trail("20261030")["id"], actual["id"])
        self.assertIsNone(self.store.latest_trail("20261030", report["id"]))
        self.assertEqual(self.store.latest("20261030", report["id"])["id"], report["id"])

    def test_report_refresh_cannot_replace_a_real_trail_snapshot(self):
        actual = self.store.publish("20261030", trail_fixture())
        self.store.refresh(["20261030"], lambda family: fixture())
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            job = self.store.job()
            if job["status"] != "running": break
            time.sleep(.01)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.store.latest_trail("20261030")["id"], actual["id"])
