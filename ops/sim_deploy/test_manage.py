import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

s = importlib.util.spec_from_file_location(
    "manage", Path(__file__).with_name("manage.py")
)
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


if __name__ == "__main__":
    unittest.main()
