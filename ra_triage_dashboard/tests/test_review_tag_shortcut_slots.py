from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from ra_triage_dashboard.app.review_tag_shortcuts import ReviewTagShortcutStore


def items(count, group="true_trigger"):
    return [{"key": f"tag-{i}", "label": f"Label {i}", "group": group} for i in range(count)]


def bindings(store, namespace, catalog):
    return {item["key"]: item["shortcut_slot"] for item in store.apply(namespace, lambda: catalog)
            if item["shortcut_slot"] is not None}


class ReviewTagShortcutSlotsTest(unittest.TestCase):
    def test_existing_keys_survive_rename_delete_reorder_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shortcuts.json"
            catalog = items(13)
            catalog.insert(8, {"key": "retired", "deleted": True, "group": "true_trigger"})
            initial = bindings(ReviewTagShortcutStore(path), "tags", catalog)
            self.assertEqual(initial, {f"tag-{i}": i for i in range(13)})
            catalog.reverse()
            for item in catalog:
                item["label"] = "Renamed"
            self.assertEqual(bindings(ReviewTagShortcutStore(path), "tags", catalog), initial)
            for item in catalog:
                if item["key"] == "tag-2":
                    item["deleted"] = True
            catalog.append({"key": "new-tag", "label": "New", "group": "true_trigger"})
            changed = bindings(ReviewTagShortcutStore(path), "tags", catalog)
            self.assertEqual(changed["new-tag"], 2)
            self.assertEqual({key:value for key,value in changed.items() if key != "new-tag"},
                             {key:value for key,value in initial.items() if key != "tag-2"})
            self.assertNotIn("Renamed", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_overflow_and_group_moves_keep_other_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewTagShortcutStore(Path(directory) / "shortcuts.json")
            catalog = items(25)
            initial = bindings(store, "tags", catalog)
            self.assertEqual(len(initial), 24)
            self.assertNotIn("tag-24", initial)
            catalog[0]["group"] = "environment"
            changed = bindings(store, "tags", catalog)
            self.assertEqual(changed["tag-0"], 0)
            self.assertEqual(changed["tag-24"], 0)
            self.assertEqual({key:changed[key] for key in initial if key != "tag-0"},
                             {key:value for key,value in initial.items() if key != "tag-0"})

    def test_concurrent_namespaces_preserve_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shortcuts.json"
            def resolve(namespace):
                return bindings(ReviewTagShortcutStore(path), namespace, items(24))
            names = ["tags", "evidence"] * 8
            with ThreadPoolExecutor(max_workers=4) as workers:
                for result in workers.map(resolve, names):
                    self.assertEqual(len(set(result.values())), 24)
            self.assertEqual(set(json.loads(path.read_text())["groups"]),
                             {"tags:true_trigger", "evidence:true_trigger"})

    def test_corrupt_metadata_is_never_silently_reassigned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shortcuts.json"
            broken = {"schema":1,"groups":{"tags:true_trigger":{"a":0,"b":0}}}
            path.write_text(json.dumps(broken))
            with self.assertRaises(ValueError):
                bindings(ReviewTagShortcutStore(path), "tags", items(2))
            self.assertEqual(json.loads(path.read_text()), broken)

    def test_keyboard_normalization_and_scope(self):
        subprocess.run(["node", str(Path(__file__).with_name("extended_tag_shortcuts.cjs"))],
                       check=True, capture_output=True, text=True)
