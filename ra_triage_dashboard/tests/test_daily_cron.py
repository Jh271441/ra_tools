from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app import cron_source


class DailyCronSourceTest(unittest.TestCase):
    def test_local_sources_overlap_monitor_wait_and_share_closeup_snapshot(self):
        cohort = object()
        media_started = threading.Event()
        version_started = threading.Event()

        def fetch(key):
            if key == "overview":
                self.assertTrue(media_started.wait(3))
                self.assertTrue(version_started.wait(3))
                return {"daily": {"runs": []}}
            return [] if key == "history" else {"state": "idle"}

        def media(root, *, closeup):
            self.assertIs(closeup, cohort)
            media_started.set()
            return {"runs": []}

        def version(root, data, *, closeup):
            self.assertIs(closeup, cohort)
            version_started.set()
            self.assertTrue(media_started.wait(3))
            return {"versions": []}

        with patch.object(cron_source, "_fetch", side_effect=fetch), \
             patch.object(cron_source, "CloseupCohort", return_value=cohort) as factory, \
             patch.object(cron_source, "media_snapshot", side_effect=media), \
             patch.object(cron_source, "version_status", side_effect=version), \
             patch.object(cron_source, "closeup_status", return_value={"state": "idle"}), \
             patch.object(cron_source, "add_main_timings"):
            result = cron_source._snapshot(Path("/source"), Path("/data"))
        factory.assert_called_once_with(Path("/source"))
        self.assertEqual(result["sources"], {"overview": "ready", "history": "ready", "sidecar": "ready", "media_daily": "ready"})
        self.assertEqual(result["incremental"], {"versions": []})

    def test_failed_local_projection_does_not_hide_independent_sources(self):
        with patch.object(cron_source, "_fetch", side_effect=lambda key: {"daily": {}} if key == "overview" else [] if key == "history" else {"state": "idle"}), \
             patch.object(cron_source, "CloseupCohort", return_value=object()), \
             patch.object(cron_source, "media_snapshot", side_effect=OSError("private")), \
             patch.object(cron_source, "version_status", return_value={"versions": ["kept"]}), \
             patch.object(cron_source, "closeup_status", side_effect=ValueError("private")), \
             patch.object(cron_source, "add_main_timings"):
            result = cron_source._snapshot(Path("/source"), Path("/data"))
        self.assertEqual(result["sources"]["overview"], "ready")
        self.assertEqual(result["sources"]["media_daily"], "unavailable")
        self.assertIsNone(result["media_daily"])
        self.assertEqual(result["incremental"], {"versions": ["kept"]})
        self.assertEqual(result["closeup"], {"state": "unavailable", "stale": True})
        self.assertNotIn("private", json.dumps(result))

    def test_unavailable_shared_queue_retains_monitor_progress_and_disabled_version(self):
        with patch.object(cron_source, "_fetch", side_effect=lambda key: {"daily": {}} if key == "overview" else [] if key == "history" else {"state": "idle"}), \
             patch.object(cron_source, "CloseupCohort", side_effect=ValueError("private")), \
             patch.object(cron_source, "closeup_status", return_value={"state": "idle"}), \
             patch.object(cron_source, "add_main_timings"):
            result = cron_source._snapshot(Path("/source"), Path("/data"))
        self.assertEqual(result["sources"]["overview"], "ready")
        self.assertEqual(result["sources"]["media_daily"], "unavailable")
        self.assertIsNone(result["incremental"])
        self.assertEqual(result["closeup"], {"state": "idle"})

    def test_independent_sources_and_private_fields(self):
        payload = {
            "collected_at": 123, "command": "private command", "daily": {
                "health": "partial", "runs": [{
                    "id": "daily-2026-10-18", "selected": 210, "inferred": 206,
                    "skipped_cases": [{"issue_id": "cn36963093", "code": "missing_event", "error": "/private/path secret"}],
                    "failure_details": [{"issue_id": "../escape", "error": "private"}],
                }], "alerts": [{"kind": "source", "message": "/private/path"}],
            }, "jobs": [{"name": "daily", "schedule": "* * * * *", "command": "private"}],
        }
        def fetch(key):
            if key == "history":
                raise OSError("private connection error")
            return payload if key == "overview" else {"state": "complete", "media_verified": 517, "main_pipeline_affected": True}
        with patch.object(cron_source, "_fetch", side_effect=fetch):
            snapshot = cron_source._snapshot()
        self.assertEqual(snapshot["sources"], {"overview": "ready", "history": "unavailable", "sidecar": "ready"})
        self.assertIsNone(snapshot["history"])
        run = snapshot["overview"]["daily"]["runs"][0]
        self.assertEqual(run["selected"], 210)
        self.assertEqual(run["skipped_cases"], [{"issue_id": "cn36963093", "code": "missing_event"}])
        self.assertEqual(run["failure_details"], [])
        self.assertFalse(snapshot["sidecar"]["main_pipeline_affected"])
        self.assertNotIn("private", json.dumps(snapshot))
        self.assertIsNone(snapshot["sidecar"]["camera"]["completed"])

    def test_invalid_or_absent_sources_are_unavailable_not_zero(self):
        with patch.object(cron_source, "_fetch", return_value=None):
            result = cron_source._snapshot()
        self.assertTrue(all(value == "unavailable" for value in result["sources"].values()))
        self.assertIsNone(result["overview"])
        self.assertIsNone(cron_source._number(float("nan")))
        self.assertIsNone(cron_source._number(True))

    def test_fixed_loopback_get_is_bounded(self):
        response = io.BytesIO(b'{"daily": {}}')
        response.headers = {}
        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return response
        opener = Opener()
        with patch.object(cron_source, "build_opener", return_value=opener):
            self.assertEqual(cron_source._fetch("overview"), {"daily": {}})
        self.assertEqual(opener.request.full_url, "http://127.0.0.1:8791/api/overview")
        self.assertEqual(opener.request.method, "GET")
        self.assertEqual(opener.timeout, 2)
        response = io.BytesIO(b" " * (cron_source.MAX_RESPONSE_BYTES + 1))
        response.headers = {}
        with patch.object(cron_source, "build_opener", return_value=opener):
            with self.assertRaises(ValueError):
                cron_source._fetch("overview")
        with self.assertRaises(KeyError):
            cron_source._fetch("http://external.example/")


class DailyCronFrontendTest(unittest.TestCase):
    def test_route_lifecycle_stale_response_and_missing_counts(self):
        js = Path(__file__).resolve().parents[1] / "static/js/daily-cron.js"
        script = r'''
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const nodes = new Map();
const window = { setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {}, RACronGraph: { render: () => {} } };
let request;
const context = vm.createContext({
  window, document: { hidden: false, addEventListener: () => {} }, AbortController, Date,
  enhanceNativeUiSelect: () => null,
  state: { uiLanguage: "zh" },
  $: (selector) => { if (!nodes.has(selector)) nodes.set(selector, { disabled: false, dataset: {}, textContent: "", setAttribute() {}, hasAttribute: () => false, querySelectorAll: () => [], querySelector: () => null, insertAdjacentHTML(_position, html) { this.innerHTML += html; } }); return nodes.get(selector); },
  uiText: (zh) => zh, escapeHtml: (value) => String(value).replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
  api: () => new Promise((resolve, reject) => { request = { resolve, reject }; }),
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
assert.equal(vm.runInContext("cronFraction(null, 10)", context), "— / 10");
assert.equal(vm.runInContext("cronTime(null)", context), "—");
assert.equal(vm.runInContext('cronLatestRun({overview:{daily:{runs:[{id:"smoke"},{id:"daily-2026-10-18"}]}}}).id', context), "daily-2026-10-18");
vm.runInContext('dailyCronState.data = {overview:{jobs:[{name:"<img>",schedule:"* * * * *",evidence:"unknown"}]}}; renderDailyCronJobs()', context);
assert(nodes.get("#dailyCronJobs").innerHTML.includes("&lt;img>"));
vm.runInContext("dailyCronState.data = null; setDailyCronActive(true); loadDailyCron()", context);
const old = request;
vm.runInContext("setDailyCronActive(false); setDailyCronActive(true); loadDailyCron()", context);
const current = request;
assert.notEqual(old, current);
old.reject(Error("old request cancelled"));
setImmediate(() => {
  assert.equal(vm.runInContext("dailyCronState.error", context), false);
  assert.equal(nodes.get("#dailyCronRefresh").disabled, true);
  current.resolve({ sources: {overview:"unavailable"}, observed_at:1 });
  setImmediate(() => {
    assert.equal(vm.runInContext("dailyCronState.data.observed_at", context), 1);
    assert.equal(nodes.get("#dailyCronRefresh").disabled, false);
    vm.runInContext("setDailyCronActive(false)", context);
  });
});
'''
        result = subprocess.run(["node", "-e", script, str(js), str(js.with_name("daily-cron-graph.js"))], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
