import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


weekly = module("weekly")
scheduler = module("scheduler")


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((HERE / "weekly.example.json").read_text())

    def test_variable_periods(self):
        a = weekly.choose_period(self.config, dt.date(2026, 9, 14))
        b = weekly.choose_period(self.config, dt.date(2026, 9, 28))
        self.assertEqual(a["release"], "gen4-release-20260828")
        self.assertEqual(b["release"], "gen4-release-20260904")
        self.assertEqual(b["case_start"][:10], "2026-09-10")

    def test_unknown_period_does_not_guess(self):
        with self.assertRaises(ValueError):
            weekly.choose_period(self.config, dt.date(2026, 10, 5))

    def test_ambiguous_period_rejected(self):
        self.config["periods"].append(self.config["periods"][0])
        with self.assertRaises(ValueError):
            weekly.choose_period(self.config, dt.date(2026, 9, 14))

    def test_unverified_preserves_latest(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            conf = root / "config.json"
            conf.write_text(json.dumps(self.config))
            good = {"observed_rate": 0.9, "period": {"release": "older"}}
            (root / "latest.json").write_text(json.dumps(good))
            result = weekly.execute(conf, root, dt.date(2026, 9, 28))
            self.assertFalse(result["published"])
            self.assertEqual(json.loads((root / "latest.json").read_text()), good)
            self.assertIn("待核实统计口径", (root / "index.html").read_text())

    def test_schedule_timezone_and_catchup(self):
        tz = ZoneInfo("Asia/Shanghai")
        self.assertFalse(scheduler.due(dt.datetime(2026, 9, 28, 8, 59, tzinfo=tz), {}))
        now = dt.datetime(2026, 9, 29, 10, tzinfo=tz)
        self.assertTrue(scheduler.due(now, {}))
        self.assertFalse(scheduler.due(now, {"week": "2026-09-28", "attempts": 3}))
        self.assertFalse(
            scheduler.due(now, {"week": "2026-09-28", "status": "complete"})
        )
        self.assertFalse(
            scheduler.due(
                now,
                {"week": "2026-09-28", "attempts": 1, "attempted_at": now.timestamp()},
            )
        )


if __name__ == "__main__":
    unittest.main()
