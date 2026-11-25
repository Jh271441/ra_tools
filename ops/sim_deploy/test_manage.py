import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

s = importlib.util.spec_from_file_location("manage", Path(__file__).with_name("manage.py"))
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)


class ConfigTests(unittest.TestCase):
    def test_ports_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "target.json"
            base = {
                "root": d,
                "source": d + "/source",
                "pg_bin": "/usr/lib/postgresql/14/bin",
                "port": 8787,
                "api_port": 8788,
            }
            p.write_text(json.dumps(base))
            self.assertEqual(m.load(p)["port"], 8787)
            for changes in (
                {"port": 80},
                {"api_port": 8787},
                {"root": "/tmp/a b"},
                {"root": "/tmp/$(bad)"},
                {"root": "/"},
                {"root": "relative"},
                {"root": "/srv/../etc"},
            ):
                p.write_text(json.dumps(dict(base, **changes)))
                with self.assertRaises(ValueError):
                    m.load(p)

    def test_parse_non_infra_programs_includes_all_workers_and_excludes_data_stores(self):
        sample = (
            "postgres                         RUNNING   pid 100, uptime 1:00:00\n"
            "redis                            RUNNING   pid 101, uptime 1:00:00\n"
            "api                              RUNNING   pid 102, uptime 1:00:00\n"
            "release-worker                   RUNNING   pid 103, uptime 1:00:00\n"
            "label-worker                     RUNNING   pid 104, uptime 1:00:00\n"
            "evaluation-worker                STOPPED   Not started\n"
            "web                              RUNNING   pid 105, uptime 1:00:00\n"
        )
        self.assertEqual(
            m.parse_non_infra_programs(sample),
            ["api", "release-worker", "label-worker", "evaluation-worker", "web"],
        )

    def test_resolve_config_path_prefers_persistent_private_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "root"
            src = Path(d) / "release"
            (src / "ra_sim_repro_dashboard/config").mkdir(parents=True)
            fallback = src / "ra_sim_repro_dashboard/config/release-cycles.default"
            fallback.write_text("{}")
            self.assertEqual(
                m.resolve_config_path(root, src, "release-cycles.default"),
                str(fallback),
            )
            (root / "private/config").mkdir(parents=True)
            persistent = root / "private/config/release-cycles.default"
            persistent.write_text('{"release_monitor": {"enabled": true}}')
            self.assertEqual(
                m.resolve_config_path(root, src, "release-cycles.default"),
                str(persistent),
            )


if __name__ == "__main__":
    unittest.main()
