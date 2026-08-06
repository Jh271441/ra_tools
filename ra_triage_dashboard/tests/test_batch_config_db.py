from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.db import AnnotationConflictError, Database


class BatchConfigDatabaseTest(unittest.TestCase):
    @staticmethod
    def _create_job(database: Database, issue_id: str = "cn12345") -> dict:
        return database.create_batch_prediction_job(
            name="queued experiment",
            issue_ids=[issue_id],
            requested_by="jasper",
            requested_model_id="auto",
            resolved_model_id="Qwen3.5/base",
            model_source="ra_model_gateway",
            catalog_sha256="a" * 64,
            model_validation_status="validated",
            prompt_version="stuck_triage_auto_opt_api",
            prompt_template="三分类：误触发、正确触发、无需协助。",
            prompt_template_sha256="b" * 64,
            prompt_mode="custom",
            input_profile="camera_ra_event",
            input_config={"profile_id": "camera_ra_event"},
        )

    def test_change_revision_tracks_committed_shared_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            initial = database.change_revision()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            after_issue = database.change_revision()
            self.assertGreater(after_issue, initial)
            database.create_annotation(
                issue_id="cn12345",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="shared update",
                author="jasper",
            )
            self.assertGreater(database.change_revision(), after_issue)

    def test_missing_evidence_catalog_is_shared_and_descriptive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            initial = database.change_revision()
            item = database.create_missing_evidence(
                label="绕行空间缺失",
                hint="未确认相邻车道是否存在可行绕行空间",
                created_by="jasperchen",
            )
            self.assertTrue(item["key"].startswith("custom:"))
            self.assertEqual(item["label"], "绕行空间缺失")
            self.assertEqual(
                database.list_missing_evidence_catalog(),
                [item],
            )
            self.assertGreater(database.change_revision(), initial)
            updated = database.update_missing_evidence(
                key=item["key"],
                label="绕行空间与时序缺失",
                hint="未确认可行绕行空间或关键时序证据",
                updated_by="other",
            )
            self.assertEqual(updated["key"], item["key"])
            self.assertEqual(updated["label"], "绕行空间与时序缺失")
            self.assertEqual(updated["active"], 1)
            deleted = database.delete_missing_evidence(
                key=item["key"],
                deleted_by="other",
            )
            self.assertEqual(deleted["key"], item["key"])
            self.assertEqual(deleted["active"], 0)
            self.assertEqual(
                database.list_missing_evidence_catalog(include_inactive=False),
                [],
            )
            with self.assertRaisesRegex(ValueError, "已经存在"):
                database.create_missing_evidence(
                    label="绕行空间与时序缺失",
                    hint="另一个说明",
                    created_by="other",
                )

    def test_review_tag_catalog_is_shared_and_soft_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            item = database.create_review_tag(
                label="施工围挡",
                hint="施工区域边界发生变化",
                section="scene",
                group_key="environment",
                created_by="jasperchen",
            )
            self.assertTrue(item["key"].startswith("custom:tag:"))
            self.assertEqual(item["group_key"], "environment")
            updated = database.update_review_tag(
                key=item["key"],
                label="施工围挡与变更区域",
                hint="施工区域边界发生变化或临时调整",
                section="scene",
                group_key="environment",
                updated_by="other",
            )
            self.assertEqual(updated["key"], item["key"])
            self.assertEqual(updated["active"], 1)
            deleted = database.delete_review_tag(key=item["key"], deleted_by="other")
            self.assertEqual(deleted["active"], 0)
            self.assertEqual(
                database.list_review_tag_catalog(include_inactive=False),
                [],
            )

    def test_review_tag_catalog_accepts_trigger_and_egress_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            false_trigger = database.create_review_tag(
                label="临时施工误报",
                hint="施工区误判为卡住",
                section="interaction_decision",
                group_key="false_trigger",
                created_by="jasperchen",
            )
            true_trigger = database.create_review_tag(
                label="近距未脱困",
                hint="",
                section="interaction_decision",
                group_key="true_trigger",
                created_by="jasperchen",
            )
            egress_ra = database.create_review_tag(
                label="自定义绕障",
                hint="需要人工路径",
                section="egress",
                group_key="ra",
                created_by="jasperchen",
            )
            egress_none = database.create_review_tag(
                label="等待条件恢复",
                hint="",
                section="egress",
                group_key="no_assist",
                created_by="jasperchen",
            )
            self.assertEqual(false_trigger["section"], "interaction_decision")
            self.assertEqual(false_trigger["group_key"], "false_trigger")
            self.assertEqual(true_trigger["group_key"], "true_trigger")
            self.assertEqual(egress_ra["section"], "egress")
            self.assertEqual(egress_ra["group_key"], "ra")
            self.assertEqual(egress_none["group_key"], "no_assist")
            with self.assertRaisesRegex(ValueError, "场景标签分组不合法"):
                database.create_review_tag(
                    label="非法分组",
                    hint="",
                    section="scene",
                    group_key="false_trigger",
                    created_by="jasperchen",
                )
            with self.assertRaisesRegex(ValueError, "场景标签分组不合法"):
                database.create_review_tag(
                    label="非法分组2",
                    hint="",
                    section="legacy",
                    group_key="legacy",
                    created_by="jasperchen",
                )

    def test_annotation_requires_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            with self.assertRaisesRegex(ValueError, "复核人不能为空"):
                database.create_annotation(
                    issue_id="cn12345",
                    label="误触发",
                    review_status="reviewed",
                    tags=[],
                    missing_evidence=[],
                    note="missing reviewer",
                    author=" ",
                )

    def test_annotation_persists_issue_exclusion_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            annotation = database.create_annotation(
                issue_id="cn12345",
                label="误触发",
                review_status="needs_gt_review",
                tags=["queue"],
                missing_evidence=[],
                note="not a model-scope case",
                author="jasper",
                is_excluded=True,
            )
            self.assertTrue(annotation["is_excluded"])
            self.assertTrue(database.get_case("cn12345")["annotations"][0]["is_excluded"])

    def test_annotations_are_bound_to_runs_and_reject_stale_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            run_a, _ = database.import_model_run(
                name="run-a",
                source_name="run-a.json",
                source_sha256="a" * 64,
                metadata={},
                rows=[{"issue_id": "cn12345", "model_label": "正确触发"}],
            )
            run_b, _ = database.import_model_run(
                name="run-b",
                source_name="run-b.json",
                source_sha256="b" * 64,
                metadata={},
                rows=[{"issue_id": "cn12345", "model_label": "无需协助"}],
            )
            first_a = database.create_annotation(
                issue_id="cn12345",
                model_run_id=run_a["id"],
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="run A first",
                author="jasper",
                expected_previous_annotation_id=None,
            )
            first_b = database.create_annotation(
                issue_id="cn12345",
                model_run_id=run_b["id"],
                label="无需协助",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="run B first",
                author="liang",
                expected_previous_annotation_id=None,
            )
            self.assertEqual(first_a["model_run_id"], run_a["id"])
            self.assertEqual(first_b["model_run_id"], run_b["id"])
            self.assertIsNone(first_a["supersedes_id"])
            self.assertIsNone(first_b["supersedes_id"])

            second_a = database.create_annotation(
                issue_id="cn12345",
                model_run_id=run_a["id"],
                label="正确触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="run A second",
                author="jasper",
                expected_previous_annotation_id=first_a["id"],
            )
            self.assertEqual(second_a["supersedes_id"], first_a["id"])
            with self.assertRaises(AnnotationConflictError):
                database.create_annotation(
                    issue_id="cn12345",
                    model_run_id=run_a["id"],
                    label="无需协助",
                    review_status="reviewed",
                    tags=[],
                    missing_evidence=[],
                    note="stale edit",
                    author="other",
                    expected_previous_annotation_id=first_a["id"],
                )

            case = database.get_case("cn12345")
            self.assertEqual(
                [item["model_run_id"] for item in case["annotations"][:3]],
                [run_a["id"], run_b["id"], run_a["id"]],
            )
            run_a_case = database.list_cases(
                model_run_id=run_a["id"], page=1, page_size=10
            )["items"][0]
            run_b_case = database.list_cases(
                model_run_id=run_b["id"], page=1, page_size=10
            )["items"][0]
            self.assertEqual(run_a_case["annotation"]["model_run_id"], run_a["id"])
            self.assertEqual(run_b_case["annotation"]["model_run_id"], run_b["id"])
            overview_a = database.overview(baseline_scope="", model_run_id=run_a["id"])
            overview_b = database.overview(baseline_scope="", model_run_id=run_b["id"])
            self.assertEqual(overview_a["labelled"], 1)
            self.assertEqual(overview_b["labelled"], 1)

    def test_annotation_delete_reconnects_history_and_removes_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            first = database.create_annotation(
                issue_id="cn12345",
                label="误触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="first",
                author="jasper",
            )
            second = database.create_annotation(
                issue_id="cn12345",
                label="正确触发",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="second",
                author="jasper",
                attachments=[
                    {
                        "id": "attachment-1",
                        "original_name": "review.png",
                        "stored_name": "stored-review.png",
                        "media_type": "image/png",
                        "size_bytes": 12,
                        "width": 2,
                        "height": 2,
                        "sha256": "a" * 64,
                    }
                ],
            )
            third = database.create_annotation(
                issue_id="cn12345",
                label="无需协助",
                review_status="reviewed",
                tags=[],
                missing_evidence=[],
                note="third",
                author="jasper",
            )
            revision = database.change_revision()

            deleted = database.delete_annotation(
                issue_id="cn12345",
                annotation_id=second["id"],
            )

            self.assertEqual(deleted["id"], second["id"])
            self.assertEqual(deleted["attachments"][0]["id"], "attachment-1")
            case = database.get_case("cn12345")
            self.assertEqual(
                [item["id"] for item in case["annotations"]],
                [third["id"], first["id"]],
            )
            self.assertEqual(case["annotations"][0]["supersedes_id"], first["id"])
            self.assertIsNone(database.get_review_attachment("attachment-1"))
            self.assertGreater(database.change_revision(), revision)
            self.assertIsNone(
                database.delete_annotation(
                    issue_id="cn12345",
                    annotation_id=second["id"],
                )
            )

    def test_queued_batch_survives_restart_and_remains_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "triage.sqlite3"
            database = Database(path)
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345"}, {"issue_id": "cn12346"}],
                source="test",
                replace_gt=False,
            )
            first = self._create_job(database)
            second = self._create_job(database, "cn12346")
            with database.connect() as conn:
                conn.execute(
                    "UPDATE batch_prediction_jobs SET created_at = ? WHERE id IN (?, ?)",
                    ("2026-08-02T00:00:00+00:00", first["id"], second["id"]),
                )
            restarted = Database(path)
            restarted.init()
            restored = restarted.get_batch_prediction_job(first["id"])
            self.assertEqual(restored["status"], "queued")
            self.assertEqual(
                restarted.next_queued_batch_prediction_job()["id"],
                first["id"],
            )

    def test_job_keeps_exact_prompt_and_input_and_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345"}],
                source="test",
                replace_gt=False,
            )
            prompt = "三分类：误触发、正确触发、无需协助。" * 4
            job = database.create_batch_prediction_job(
                name="prompt experiment",
                issue_ids=["cn12345"],
                requested_by="jasper",
                requested_model_id="auto",
                resolved_model_id="Qwen3.5/base",
                model_source="ra_model_gateway",
                catalog_sha256="a" * 64,
                model_validation_status="validated",
                prompt_version="stuck_triage_auto_opt_api",
                prompt_template=prompt,
                prompt_template_sha256="b" * 64,
                prompt_mode="custom",
                input_profile="camera_ra_event",
                input_config={
                    "profile_id": "camera_ra_event",
                    "frame_offsets_ms": [-1000, 0, 1000],
                    "use_ra_event": True,
                    "use_ra_options": False,
                },
            )
            self.assertEqual(job["prompt_template"], prompt)
            self.assertEqual(job["input_config"]["frame_offsets_ms"], [-1000, 0, 1000])
            filtered = database.list_batch_prediction_jobs(
                model_id="auto",
                prompt_version="stuck_triage_auto_opt_api",
                prompt_mode="custom",
                prompt_sha256="b" * 64,
                input_profile="camera_ra_event",
            )
            self.assertEqual(filtered["total"], 1)
            self.assertEqual(
                {item["id"] for item in filtered["facets"]["models"]},
                {"auto", "Qwen3.5/base"},
            )
            self.assertEqual(
                filtered["facets"]["prompts"],
                [
                    {
                        "version": "stuck_triage_auto_opt_api",
                        "mode": "custom",
                        "sha256": "b" * 64,
                        "job_count": 1,
                    }
                ],
            )
            self.assertEqual(
                filtered["facets"]["input_profiles"],
                [{"id": "camera_ra_event", "job_count": 1}],
            )

    def test_model_run_delete_cascades_predictions_but_keeps_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "triage.sqlite3")
            database.init()
            database.upsert_issues(
                [{"issue_id": "cn12345", "gt_label": "误触发"}],
                source="test",
                replace_gt=False,
            )
            run, duplicate = database.import_model_run(
                name="delete me",
                source_name="results.csv",
                source_sha256="c" * 64,
                metadata={},
                rows=[
                    {
                        "issue_id": "cn12345",
                        "model_label": "正确触发",
                        "model_reason": "test",
                        "raw": {"issue_id": "cn12345", "model_label": "正确触发"},
                    }
                ],
            )
            self.assertFalse(duplicate)
            self.assertIsNotNone(database.get_case("cn12345"))
            deleted = database.delete_model_run(run["id"])
            self.assertEqual(deleted["id"], run["id"])
            self.assertIsNone(database.get_model_run(run["id"]))
            case = database.get_case("cn12345")
            self.assertIsNotNone(case)
            self.assertEqual(case["predictions"], [])
