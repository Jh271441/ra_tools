from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from ra_triage_dashboard.app.cron_timing import add_main_timings, read_receipt, timing


class CronTimingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.ra = self.parent / "ra_auto_triage"
        self.root = self.parent / "ra_auto_triage_deploy"
        self.work = self.root / "state/pipeline_v1/daily-2026-10-19"
        self.overview = {"collected_at": 2000, "daily": {"runs": [{"id": "daily-2026-10-19", "target_date_cst": "2026-10-19", "started_at": 1000, "elapsed_seconds": 350, "health": "partial", "state": "complete_with_gaps"}], "launches": [{"target_date_cst": "2026-10-19", "started_at": "1970-01-01T00:16:30+00:00"}]}}
        self.write(self.work / "registration.json", {"run_id": "daily-2026-10-19", "started_at": 1000, "selection_sha256": "a" * 64, "scope": {"date_cst": "2026-10-19"}})
        self.write(self.work / "selection.json", [{"issue_id": "cn123"}, {"issue_id": "cn456"}])

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def finish(self):
        self.write(self.work / "publication_cohort.json", {"run_id": "daily-2026-10-19", "included_ids": ["cn123", "cn456"], "selection_sha256": "a" * 64})
        self.write(self.work / "review_plan.json", {"sampled_ids": ["cn456"]})
        for iid, start, end in (("cn123", 1200, 1250), ("cn456", 1220, 1280)):
            self.write(self.work / f"cases/{iid}/publication/attempt_{start * 10**9:019d}/intent.json", {})
            self.write(self.work / f"cases/{iid}/publication/verified.json", {"verified_at": end})
        self.write(self.work / "cases/cn456/sample_hook/attempt_0000001290000000000/intent.json", {})
        self.write(self.work / "cases/cn456/sample_hook/verified.json", {"verified_at": 1310})

    def run_row(self):
        add_main_timings(self.overview, self.ra)
        return self.overview["daily"]["runs"][0]

    def test_exported_total_and_parallel_receipt_spans(self):
        self.finish()
        # Full Trail selection snapshots can be large/private; use only the
        # hash-bound publication cohort, not those documents or filesystem mtimes.
        (self.work / "selection.json").write_text("x" * 2_000_001)
        row = self.run_row()
        self.assertEqual(row["timing"]["elapsed_seconds"], 350)
        self.assertEqual(row["timing"]["finished_at"], 1350)
        stages = row["stage_timings"]
        self.assertEqual(stages["main-query"]["elapsed_seconds"], 10)
        self.assertEqual(stages["main-infer"]["elapsed_seconds"], 200)
        self.assertEqual(stages["main-publish"]["elapsed_seconds"], 80)  # Wall-clock span, not 50+60.
        self.assertEqual(stages["main-publish"]["observed"], 2)
        self.assertEqual(stages["main-verify"]["elapsed_seconds"], 20)

    def test_running_uses_observation_and_partial_span_stays_explicit(self):
        self.overview["daily"]["runs"][0].update(health="running", stage="inference")
        row = self.run_row()
        self.assertEqual(row["timing"]["mode"], "running")
        self.assertEqual(row["timing"]["elapsed_seconds"], 1000)
        self.assertEqual(row["stage_timings"]["main-infer"]["mode"], "running")
        self.finish()
        (self.work / "cases/cn456/publication/verified.json").unlink()
        row = self.run_row()
        self.assertEqual(row["stage_timings"]["main-publish"]["mode"], "observed")
        self.assertEqual(row["stage_timings"]["main-publish"]["observed"], 1)

    def test_wrong_scope_and_broken_optional_receipt_preserve_run(self):
        self.finish()
        self.write(self.work / "registration.json", {"run_id": "wrong-run", "started_at": 1000, "selection_sha256": "a" * 64, "scope": {"date_cst": "2026-10-19"}})
        self.assertEqual(self.run_row()["stage_timings"], {})
        self.write(self.work / "registration.json", {"run_id": "daily-2026-10-19", "started_at": 1000, "selection_sha256": "a" * 64, "scope": {"date_cst": "2026-10-19"}})
        (self.work / "cases/cn123/publication/verified.json").write_text("not-json")
        row = self.run_row()
        self.assertTrue(row["timing_error"])
        self.assertEqual(row["state"], "complete_with_gaps")
        self.assertEqual(row["timing"]["elapsed_seconds"], 350)

    def test_invalid_times_escape_and_future_receipts(self):
        for seconds in (-1, True, float("nan"), float("inf")):
            self.assertEqual(timing(seconds=seconds)["mode"], "unavailable")
        self.assertEqual(timing(100, 99)["mode"], "unavailable")
        self.assertEqual(timing(100, 201, observed_at=150)["mode"], "unavailable")
        self.assertEqual(timing(100, seconds=100, observed_at=150)["mode"], "unavailable")
        self.assertEqual(timing(running=True, observed_at=150)["mode"], "unavailable")
        self.assertEqual(timing(100, 100)["elapsed_seconds"], 0)
        outside = self.parent / "outside.json"
        self.write(outside, {"started_at": 1})
        with self.assertRaises(ValueError):
            read_receipt(self.root, outside)
        link = self.root / "link.json"
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            read_receipt(self.root, link)

    def test_duration_text_and_stale_running_view(self):
        js = Path(__file__).resolve().parents[1] / "static/js/daily-cron.js"
        script = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
let language='zh';const ctx=vm.createContext({window:{},document:{addEventListener(){}},uiText:(zh,en)=>language==='zh'?zh:en});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
assert.equal(vm.runInContext('cronDuration(null)',ctx),'—');
assert.equal(vm.runInContext('cronDuration(-1)',ctx),'—');
assert.equal(vm.runInContext('cronDuration(0)',ctx),'0秒');
assert.equal(vm.runInContext('cronDuration(0.1)',ctx),'<1秒');
assert.equal(vm.runInContext('cronDuration(155)',ctx),'2分35秒');
assert.equal(vm.runInContext('cronDuration(6137.5)',ctx),'1小时42分17秒');
assert.equal(vm.runInContext('cronDuration(6137.5,{compact:true})',ctx),'1时42分');
assert.equal(vm.runInContext('cronTimingText({mode:"running",elapsed_seconds:30},{stale:true})',ctx),'上次已运行 30秒');
assert.equal(vm.runInContext('cronTimingText({mode:"observed",kind:"span",elapsed_seconds:12})',ctx),'已观测跨度 12秒');
assert.equal(vm.runInContext('cronTimingText({mode:"finished",kind:"p50",elapsed_seconds:12})',ctx),'任务 P50 12秒');
language='en';assert.equal(vm.runInContext('cronDuration(155)',ctx),'2m 35s');
assert.equal(vm.runInContext('cronTimingText({mode:"running",elapsed_seconds:155})',ctx),'Elapsed 2m 35s');
'''
        result = subprocess.run(["node", "-e", script, str(js)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
