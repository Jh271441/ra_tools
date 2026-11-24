from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ra_triage_dashboard.app import cron_source, cron_timing, cron_version_source
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.version_review_tasks import version_tasks
from ra_triage_dashboard.scripts import deploy_cloud


class Phase15PerfTests(unittest.TestCase):
    def test_063_perf_indexes_passes_additive_migration_validator_and_sqlite_parity(self) -> None:
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations/postgres/063_perf_indexes.sql"
        )
        self.assertTrue(migration_path.is_file())
        content = migration_path.read_text(encoding="utf-8")
        deploy_cloud.validate_additive_migration_sql(
            "ra_triage_dashboard/migrations/postgres/063_perf_indexes.sql",
            content,
        )

        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "perf_idx.sqlite")
            db.init()
            with db.connect() as conn:
                sqlite_indexes = {
                    str(row["name"])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    ).fetchall()
                }
            expected_indexes = {
                "idx_model_review_revisions_issue_id",
                "idx_model_review_revisions_campaign_id",
                "idx_model_review_heads_campaign",
                "idx_combined_review_progress_lookup",
                "idx_review_work_assignments_split_lower_assignee",
                "idx_version_dataset_items_target",
                "idx_version_dataset_items_issue",
                "idx_dataset_ingestion_batches_dataset_created",
                "idx_label_revisions_case_lower_author",
                "idx_issues_scope_issue",
            }
            self.assertTrue(
                expected_indexes.issubset(sqlite_indexes),
                f"Missing SQLite indexes: {expected_indexes - sqlite_indexes}",
            )

    def test_postgres_pool_disables_jit_for_oltp_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "jit.sqlite")
            db.backend = "postgresql"
            db.database_url = "postgresql://localhost/unused"
            captured: dict = {}

            def _fake_pool(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(close=lambda: None)

            with patch.object(
                db, "_postgres_dependencies", return_value=(None, object(), _fake_pool)
            ):
                db._ensure_postgres_pool()
            self.assertEqual(
                captured.get("kwargs", {}).get("options"), "-c jit=off"
            )
            db.close()

    def test_version_datasets_batched_listing_and_targets_only_gallery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "vds.sqlite")
            db.init()
            policy = {"sampling_policy": "version_probability_v3", "seed": "a" * 64}
            db.ingest_version_dataset(
                family="20261113",
                policy=policy,
                batch_key="b1",
                actor="tester",
                items=[
                    {
                        "issue_id": "cn1001",
                        "software_version": "1.gen4-release-20261113",
                        "state": "published",
                        "is_target": True,
                        "is_sample": True,
                        "is_low": True,
                    },
                    {
                        "issue_id": "cn1002",
                        "software_version": "1.gen4-release-20261113",
                        "state": "published",
                        "is_target": True,
                        "is_sample": False,
                        "is_low": True,
                    },
                    {
                        "issue_id": "cn1003",
                        "software_version": "1.gen4-release-20261113",
                        "state": "inferred",
                        "is_target": False,
                        "is_sample": False,
                        "is_low": False,
                    },
                ],
            )
            datasets = db.list_version_datasets()
            self.assertEqual(len(datasets), 1)
            ds = datasets[0]
            self.assertEqual(ds["total"], 3)
            self.assertEqual(ds["targets"], 2)
            self.assertEqual(ds["samples"], 1)
            self.assertEqual(ds["sampled_targets"], 1)
            self.assertEqual(ds["low"], 2)
            self.assertEqual(ds["low_only"], 1)
            self.assertEqual(ds["states"], {"inferred": 1, "published": 2})

            all_rows = db.version_dataset_gallery_rows("release-20261113-odd2")
            target_rows = db.version_dataset_gallery_rows(
                "release-20261113-odd2", targets_only=True
            )
            self.assertEqual(len(all_rows), 3)
            self.assertEqual({r["issue_id"] for r in target_rows}, {"cn1001", "cn1002"})
            self.assertEqual(db.version_dataset_gallery_rows("release-20990101-odd2"), [])

    def test_version_tasks_preloads_gallery_and_batches_once_per_dataset(self) -> None:
        calls = {"gallery": 0, "batches": 0, "targets_only": []}
        dataset = {
            "id": "release-20261113-odd2",
            "release_family": "20261113",
            "run_id": "run-1",
            "created_at": "2026-11-13T00:00:00Z",
            "updated_at": "2026-11-13T01:00:00Z",
        }
        rows = [
            {
                "issue_id": "cn1",
                "is_target": True,
                "binding": {"campaign_id": "c-samp", "assignee": "alice"},
                "review_submitted": True,
                "review_submitted_at": "2026-11-13T02:00:00Z",
            },
            {
                "issue_id": "cn2",
                "is_target": True,
                "binding": {"campaign_id": "c-low", "assignee": "bob"},
                "review_submitted": False,
                "review_submitted_at": "",
            },
        ]

        def _gallery(did, *, targets_only=False):
            calls["gallery"] += 1
            calls["targets_only"].append(targets_only)
            return rows

        def _batches(did):
            calls["batches"] += 1
            return [{"target_added": 2, "created_at": "2026-11-13T01:00:00Z"}]

        from contextlib import contextmanager

        @contextmanager
        def _fake_connect():
            yield SimpleNamespace(execute=lambda *a, **kw: SimpleNamespace(fetchone=lambda: None))

        db = SimpleNamespace(
            list_version_datasets=lambda: [dataset],
            role_version_campaigns=lambda did: [
                {"campaign_id": "c-samp", "cohort": "sampling"},
                {"campaign_id": "c-low", "cohort": "low"},
            ],
            version_dataset_gallery_rows=_gallery,
            version_dataset_batches=_batches,
            connect=_fake_connect,
        )
        items = version_tasks(db, lifecycle="current")
        self.assertEqual(len(items), 2)
        self.assertEqual(calls["gallery"], 1)
        self.assertEqual(calls["batches"], 1)
        self.assertEqual(calls["targets_only"], [True])

    def test_cron_cached_document_invalidates_on_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "receipt.json"
            p.write_text(json.dumps({"state": "verified", "issue_id": "cn1"}), encoding="utf-8")
            with cron_version_source._doc_cache_lock:
                cron_version_source._doc_cache.clear()
            first = cron_version_source._cached_document(p)
            self.assertEqual(first["issue_id"], "cn1")
            second = cron_version_source._cached_document(p)
            self.assertIs(first, second)
            p.write_text(json.dumps({"state": "verified", "issue_id": "cn2222"}), encoding="utf-8")
            third = cron_version_source._cached_document(p)
            self.assertEqual(third["issue_id"], "cn2222")

    def test_cron_snapshot_force_refresh_bypasses_ttl_cache(self) -> None:
        cron_source._cache.clear()
        calls = {"n": 0}

        def _fake_snapshot(ra_root, data_dir):
            calls["n"] += 1
            return {"seq": calls["n"]}

        with patch.object(cron_source, "_snapshot", side_effect=_fake_snapshot):
            a = cron_source.cron_snapshot(Path("/r"), Path("/d"))
            b = cron_source.cron_snapshot(Path("/r"), Path("/d"))
            c = cron_source.cron_snapshot(Path("/r"), Path("/d"), force_refresh=True)
        self.assertEqual(a["seq"], 1)
        self.assertEqual(b["seq"], 1)
        self.assertEqual(c["seq"], 2)
        cron_source._cache.clear()


if __name__ == "__main__":
    unittest.main()
