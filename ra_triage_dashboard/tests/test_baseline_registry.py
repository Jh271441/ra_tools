"""Unit tests for multi-baseline registry parse and id/scope helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ra_triage_dashboard.app.baseline import load_spotcheck_zh_baseline, normalize_gt_label
from ra_triage_dashboard.app.baseline_registry import (
    detect_issue_scope_overlaps,
    expand_path_template,
    ids_to_scopes,
    load_baseline_registry,
    normalize_baseline_ids,
)
from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.media_registry import BagsAresAnimationProvider


class BaselineRegistryTests(unittest.TestCase):
    def test_expand_path_template_and_parse_registry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = root / "baselines.json"
            cfg.write_text(
                json.dumps(
                    [
                        {
                            "id": "0508",
                            "label": "0508",
                            "scope": "release0508_1071_20260729",
                            "loader": "trail_label_baseline",
                            "xlsx": "${RA_ROOT}/data/a.xlsx",
                            "dataset": "0508",
                            "default_selected": True,
                            "media": {"provider": "product_layout", "layout_id": "x"},
                        },
                        {
                            "id": "0626",
                            "label": "0626 抽检",
                            "scope": "release0626_300_spotcheck",
                            "loader": "spotcheck_zh",
                            "xlsx": "${RA_ROOT}/data/b.xlsx",
                            "default_selected": False,
                            "media": {
                                "provider": "bags_ares_animation",
                                "bev_frames_root": "${RA_ROOT}/bags/frames",
                                "animation_root": "${RA_ROOT}/bags/anim",
                                "animation_job_ids": [1, 2],
                            },
                        },
                    ]
                ),
                encoding="utf-8",
            )
            registry = load_baseline_registry(
                cfg, env={"RA_ROOT": str(root), "RA_AUTO_TRIAGE_ROOT": str(root)}
            )
            self.assertEqual([entry.id for entry in registry.entries], ["0508", "0626"])
            self.assertEqual(registry.default_ids(), ["0508"])
            self.assertEqual(registry.id_to_scope("0626"), "release0626_300_spotcheck")
            self.assertEqual(
                expand_path_template("${RA_ROOT}/data/a.xlsx", env={"RA_ROOT": "/tmp"}),
                "/tmp/data/a.xlsx",
            )
            self.assertEqual(
                ids_to_scopes(["0508", "0626", "0508"], registry),
                ["release0508_1071_20260729", "release0626_300_spotcheck"],
            )

    def test_normalize_baseline_ids_defaults_and_filters(self) -> None:
        allowed = {"0508", "0626"}
        self.assertEqual(
            normalize_baseline_ids("", allowed=allowed, default=["0508"]),
            ["0508"],
        )
        self.assertEqual(
            normalize_baseline_ids("0626,0508,nope", allowed=allowed, default=["0508"]),
            ["0626", "0508"],
        )
        self.assertEqual(
            normalize_baseline_ids(["0626", "0626"], allowed=allowed, default=["0508"]),
            ["0626"],
        )

    def test_overlap_detection(self) -> None:
        overlaps = detect_issue_scope_overlaps(
            [
                ("cn1", "s1"),
                ("cn2", "s1"),
                ("cn1", "s2"),
            ]
        )
        self.assertEqual(overlaps, {"cn1": ["s1", "s2"]})

    def test_spotcheck_loader_and_db_union_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Minimal xlsx via openpyxl
            import openpyxl

            xlsx = root / "spot.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["问题 ID", "合并标注", "最终Comment"])
            ws.append(["cn_a", "误触发", "a"])
            ws.append(["cn_b", "正确触发", "b"])
            ws.append(["cn_c", "无需协助", "c"])
            ws.append(["cn_bad", "未知", "x"])
            wb.save(xlsx)
            loaded = load_spotcheck_zh_baseline(xlsx)
            self.assertEqual(loaded.source_rows, 4)
            self.assertEqual(len(loaded.rows), 3)
            self.assertEqual(normalize_gt_label("正确触发"), "正确触发")

            db = Database(root / "t.sqlite3")
            db.init()
            db.replace_baseline_scope(
                scope="scope_a",
                rows=[
                    {"issue_id": "cn_a", "gt_label": "误触发"},
                    {"issue_id": "cn_b", "gt_label": "正确触发"},
                ],
                source="test",
            )
            db.replace_baseline_scope(
                scope="scope_b",
                rows=[{"issue_id": "cn_c", "gt_label": "无需协助"}],
                source="test",
            )
            overview_a = db.overview(baseline_scopes=["scope_a"])
            overview_b = db.overview(baseline_scopes=["scope_b"])
            overview_u = db.overview(baseline_scopes=["scope_a", "scope_b"])
            self.assertEqual(overview_a["issues"], 2)
            self.assertEqual(overview_b["issues"], 1)
            self.assertEqual(overview_u["issues"], 3)
            ids = db.baseline_issue_ids(baseline_scopes=["scope_a", "scope_b"])
            self.assertEqual(ids, ["cn_a", "cn_b", "cn_c"])
            cases = db.list_cases(baseline_scopes=["scope_b"], page=1, page_size=20)
            self.assertEqual(cases["total"], 1)
            self.assertEqual(cases["items"][0]["issue_id"], "cn_c")

    def test_bags_provider_frames_and_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames_v2_0626" / "cn_demo_0"
            frames.mkdir(parents=True)
            (frames / "bev_+0ms.jpg").write_bytes(b"fakejpg0")
            (frames / "bev_-10000ms.jpg").write_bytes(b"fakejpg1")
            anim = root / "ares"
            job = anim / "job_1"
            job.mkdir(parents=True)
            video = job / "cn_demo.mp4"
            video.write_bytes(b"fakevideo")
            (anim / "registry.jsonl").write_text(
                json.dumps(
                    {
                        "issue_id": "cn_demo",
                        "animation_path": "job_1/cn_demo.mp4",
                        "duration_sec": 12.5,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            provider = BagsAresAnimationProvider(
                bev_frames_root=root / "frames_v2_0626",
                animation_root=anim,
                animation_job_ids=(1,),
                base_path="",
            )
            self.assertTrue(provider.has_issue("cn_demo"))
            assets = provider.get_assets("cn_demo")
            self.assertTrue(assets["available"])
            self.assertEqual(len(assets["frames"]), 2)
            offsets = [frame["offset_ms"] for frame in assets["frames"]]
            self.assertIn(0, offsets)
            self.assertIn(-10000, offsets)
            thumb = provider.get_thumbnail_source("cn_demo")
            self.assertIsNotNone(thumb)
            video_meta = provider.get_video("cn_demo")
            self.assertIsNotNone(video_meta)
            self.assertEqual(video_meta["source"], "ares_animation")
            path = provider.get_asset_path("cn_demo", video_meta["id"])
            self.assertEqual(path, video.resolve())


if __name__ == "__main__":
    unittest.main()
