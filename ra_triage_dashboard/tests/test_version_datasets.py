import hashlib, json, tempfile, unittest
from pathlib import Path
from ra_triage_dashboard.app.db import Database


class VersionDatasetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "db.sqlite")
        self.db.init()

    def packet(self, i="cn1", family="20261009"):
        return dict(
            issue_id=i,
            software_version="1.gen4-release-" + family + ".594",
            state="ready",
            is_target=False,
            is_sample=False,
            is_low=False,
        )

    def ingest(self, items, key="a", family="20261009"):
        return self.db.ingest_version_dataset(
            family=family,
            policy={"sampling_policy": "version_probability_v3", "seed": "a" * 64},
            items=items,
            batch_key=key,
            actor="test",
        )

    def test_idempotent_append_and_separate_versions(self):
        first = self.ingest([self.packet()])
        self.assertTrue(self.ingest([self.packet()])["replayed"])
        self.ingest([self.packet("cn2")], "b")
        self.ingest([self.packet("cn3", "20261023")], family="20261023")
        datasets = self.db.list_version_datasets()
        self.assertEqual(len(datasets), 2)
        self.assertEqual(sum(x["total"] for x in datasets), 3)
        self.assertEqual(
            self.db.version_dataset_items(first["dataset_id"], mode="all")["total"], 2
        )
        self.assertEqual(len(self.db.version_dataset_batches(first["dataset_id"])), 2)

    def test_reused_key_different_source_and_cross_version_are_rejected(self):
        self.ingest([self.packet()])
        with self.assertRaises(ValueError):
            self.ingest([self.packet("cn2")])
        with self.assertRaises(ValueError):
            self.ingest([self.packet("cn3", "20261023")], "b")

    def test_published_non_target_media_lookup_does_not_admit_review_case(self):
        self.ingest([
            dict(self.packet("cn1"), state="published"),
            dict(self.packet("cn2"), state="inferred"),
            self.packet("cn3"),
            dict(self.packet("cn4"), state="excluded"),
        ])
        before = self.db.version_dataset_items("release-20261009-odd2", mode="all")
        for iid in ("cn1", "cn2"):
            reference = self.db.get_media_issue(iid)
            self.assertTrue(reference["reference_media"])
            self.assertEqual(reference["gt_label"], "")
            self.assertNotIn("trip_id", reference)
            self.assertIsNone(self.db.get_issue(iid))
            self.assertIsNone(self.db.get_case(iid))
        for iid in ("cn3", "cn4", "cn9999"):
            self.assertIsNone(self.db.get_media_issue(iid))
        self.assertEqual(self.db.version_dataset_items("release-20261009-odd2", mode="all"), before)
        self.assertEqual(self.db.version_dataset_items("release-20261009-odd2")["total"], 0)
        self.assertEqual(self.db.list_model_runs(), [])

    def test_media_reference_keeps_existing_issue_scope_and_gt(self):
        self.ingest([dict(self.packet(), state="published")])
        self.db.upsert_issues([dict(issue_id="cn1", gt_label="误触发", trip_id="original_trip")],
                              source="existing", replace_gt=False, baseline_scope="original_scope")
        original = self.db.get_issue("cn1")
        self.assertEqual(self.db.get_media_issue("cn1"), original)
        self.assertEqual(self.db.get_issue("cn1"), original)

    def test_current_membership_filter_preserves_frozen_campaign_scope(self):
        from unittest.mock import patch
        from ra_triage_dashboard.app.support import baselines,filter_parsing
        self.ingest([dict(self.packet(),state="published",is_target=True,is_low=True),self.packet("cn2")])
        with patch.object(baselines,"database",self.db),patch.object(filter_parsing,"resolve_request_baseline_scopes",return_value=["scope"]),patch.object(baselines,"resolve_request_baseline_ids",return_value=["version-20261009"]):
            current=filter_parsing._case_filter_kwargs(baselines="version-20261009")
            frozen=filter_parsing._case_filter_kwargs(baselines="version-20261009",work_split_id="original-campaign")
        self.assertEqual(current["issue_ids"],("cn1",))
        self.assertFalse(frozen["issue_ids"])
        self.assertEqual(frozen["work_split_id"],"original-campaign")

    def test_failed_ingest_rolls_back_whole_batch(self):
        with self.assertRaises(ValueError):
            self.ingest(
                [self.packet(), dict(self.packet("cn2"), binding={"run_id": "missing"})]
            )
        self.assertEqual(self.db.list_version_datasets(), [])

    def test_direct_consolidation_preserves_human_row_ids(self):
        ids = []
        for n in [1, 2]:
            run, _ = self.db.import_model_run(
                name="old" + str(n),
                source_name="old.json",
                source_sha256=hashlib.sha256(str(n).encode()).hexdigest(),
                metadata={},
                rows=[
                    dict(
                        issue_id="cn" + str(n),
                        model_label="误触发",
                        model_confidence=0.5,
                        model_extra={"software_version": "1.gen4-release-20261009.594"},
                    )
                ],
            )
            ids.append(run["id"])
        with self.db.connect() as conn:
            old = conn.execute(
                "INSERT INTO model_review_revisions(model_run_id,issue_id,status,reviewer,created_at) VALUES(?,?,'completed','jasperchen','2026-10-20') RETURNING id",
                (ids[0], "cn1"),
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO model_review_heads(model_run_id,issue_id,campaign_id,reference_id,reviewer,revision_id,updated_at) VALUES(?,?,'','','jasperchen',?,'2026-10-20')",
                (ids[0], "cn1", old),
            )
        result = self.db.consolidate_version_runs(
            family="20261009", run_ids=ids, backup_sha256="a" * 64, actor="migration"
        )
        self.assertEqual(len(self.db.list_model_runs()), 1)
        self.ingest([dict(self.packet(), state="published", is_target=True, is_low=True,
                         binding={"run_id": result["run_id"]})], key="projection")
        page = self.db.version_dataset_items("release-20261009-odd2")
        self.assertEqual(page["items"][0]["prediction"]["model_label"], "误触发")
        self.assertEqual(page["items"][0]["prediction"]["model_confidence"], 0.5)
        bulk=self.db.version_dataset_gallery_rows("release-20261009-odd2")
        self.assertEqual(bulk[0]["prediction"]["model_confidence"],0.5)
        self.assertNotIn("raw_json",bulk[0])
        self.assertEqual(len(self.db.model_run_source_rows(result["run_id"],include_history=True)), 2)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_review_revisions WHERE id=?", (old,)
            ).fetchone()
            self.assertEqual(row["model_run_id"], result["run_id"])
            self.assertEqual(row["reviewer"], "jasperchen")
            self.assertEqual(row["created_at"], "2026-10-20")
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM version_run_archives"
                ).fetchone()["n"],
                2,
            )
        self.assertTrue(
            self.db.consolidate_version_runs(
                family="20261009",
                run_ids=ids,
                backup_sha256="a" * 64,
                actor="migration",
            )["replayed"]
        )

    def test_late_old_case_is_newest_arrival_and_can_be_searched(self):
        self.ingest([dict(self.packet('cn200'), is_target=True, is_low=True, issue_time=2000)])
        self.ingest([dict(self.packet('cn100'), is_target=True, is_low=True, is_sample=True, issue_time=1000)], key='late')
        with self.db.connect() as conn:
            conn.execute("UPDATE version_dataset_items SET first_seen='2026-10-20',updated_at='2026-10-23' WHERE issue_id='cn200'")
            conn.execute("UPDATE version_dataset_items SET first_seen='2026-10-22',updated_at='2026-10-22' WHERE issue_id='cn100'")
        did='release-20261009-odd2'
        newest=self.db.version_dataset_items(did, page_size=1)
        self.assertEqual(newest['items'][0]['issue_id'],'cn100')
        self.assertEqual(newest['total'],2)
        self.assertEqual(newest['items'][0]['first_seen'],'2026-10-22')
        updated=self.db.version_dataset_items(did, sort='updated')
        self.assertEqual(updated['items'][0]['issue_id'],'cn200')
        self.assertEqual(self.db.version_dataset_items(did,query='cn100')['total'],1)
        counts=self.db.list_version_datasets()[0]
        self.assertEqual((counts['targets'],counts['sampled_targets'],counts['low_only']),(2,1,1))
        with self.assertRaises(ValueError):self.db.version_dataset_items(did,sort='first_seen; DROP TABLE issues')


if __name__ == "__main__":
    unittest.main()
