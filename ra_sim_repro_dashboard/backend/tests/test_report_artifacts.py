import csv
import json

from app.services.refresh import _summary_from_release_metrics
from app.services.report_artifacts import (
    build_manifest_scenario_index,
    canonical_scenario_id,
    load_binary_backtest_sources,
    load_release_metrics,
)


def _complete_cohorts(expected=10, trigger_rate=0.5):
    return {
        cohort: {
            "expected": expected,
            "evaluated": expected,
            "trigger_rate": trigger_rate,
        }
        for cohort in ("positive_auto", "negative_auto", "positive_manual")
    }


def test_manifest_index_preserves_cohort_truth_and_canonicalizes_id(tmp_path):
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["release", "cohort", "issue_id", "scenario_id", "upload_status"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "release": "v1",
                "cohort": "negative_auto",
                "issue_id": "cn1",
                "scenario_id": "123.0",
                "upload_status": "uploaded",
            }
        )
        writer.writerow(
            {
                "release": "v1",
                "cohort": "positive_auto",
                "issue_id": "cn2",
                "scenario_id": "",
                "upload_status": "failed:no bag",
            }
        )

    index = build_manifest_scenario_index({"source_manifest": str(path)}, "v1")

    assert canonical_scenario_id("123.0") == "123"
    assert list(index) == ["123"]
    assert index["123"]["source_groups"] == ["negative_auto"]
    assert index["123"]["truth_positive"] is False
    assert index["123"]["issue_id"] == "cn1"


def test_release_metrics_summary_uses_three_cohort_semantics(tmp_path):
    path = tmp_path / "metrics.json"
    payload = {
        "per_release": {
            "v1": {
                "job_id": [101],
                "completed": 6,
                "completed_dpe_covered": 6,
                "terminal_failed": 0,
                "quality": {"gate_passed_so_far": True},
                "manifest_audit": {
                    "source_rows": 7,
                    "submitted_rows": 6,
                    "excluded_rows": 1,
                },
                "cohorts": {
                    "positive_auto": {
                        "evaluated": 2,
                        "triggered": 1,
                        "road_behavior_reproduction": 0.5,
                    },
                    "negative_auto": {
                        "evaluated": 2,
                        "triggered": 2,
                        "road_behavior_reproduction": 1.0,
                    },
                    "positive_manual": {
                        "evaluated": 2,
                        "triggered": 1,
                        "road_behavior_reproduction": 0.5,
                    },
                },
                "truth": {
                    "tp": 2,
                    "fn": 2,
                    "fp": 2,
                    "tn": 0,
                    "precision": 0.5,
                    "recall": 0.5,
                    "specificity": 0.0,
                    "accuracy": 1 / 3,
                },
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    metrics = load_release_metrics({"result_metrics": str(path)}, "v1")
    summary = _summary_from_release_metrics(metrics, {})

    assert summary["sim_repro_rate"] == 0.75
    assert summary["positive_auto_repro_rate"] == 0.5
    assert summary["negative_auto_repro_rate"] == 1.0
    assert summary["positive_manual_repro_rate"] == 0.5
    assert summary["precision"] == 0.5
    assert summary["recall"] == 0.5
    assert summary["source_gt"]["excluded_scenarios"] == 1
    assert summary["sim_estimate"]["job_id"] == 101


def test_load_binary_backtest_sources_by_target_release(tmp_path):
    path = tmp_path / "backtest.json"
    path.write_text(json.dumps({
        "targets": {
            "v2": {
                "quality_gate_passed": True,
                "source_releases": ["v1", "v2"],
                "window_size": 2,
                "sources": {
                    "v1": {
                        "expected": 30,
                        "evaluated": 30,
                        "dpe_coverage": 1.0,
                        "cohorts": _complete_cohorts(),
                        "estimated_tp": 8,
                        "estimated_fp": 2,
                        "estimated_fn": 1,
                    },
                    "v2": {
                        "expected": 30,
                        "evaluated": 30,
                        "dpe_coverage": 1.0,
                        "cohorts": _complete_cohorts(),
                        "estimated_tp": 9,
                        "estimated_fp": 1,
                        "estimated_fn": 0,
                    },
                }
            }
        }
    }), encoding="utf-8")

    sources = load_binary_backtest_sources({
        "binary_backtest": {"result_metrics": str(path)}
    }, "v2")

    assert sources["v1"]["estimated_tp"] == 8
    assert sources["v2"]["estimated_fp"] == 1


def test_binary_backtest_reader_invalidates_cache_when_artifact_changes(tmp_path):
    path = tmp_path / "backtest.json"
    config = {"binary_backtest": {"result_metrics": str(path)}}
    path.write_text(json.dumps({
        "targets": {
            "v2": {
                "quality_gate_passed": True,
                "source_releases": ["v1"],
                "window_size": 1,
                "sources": {
                    "v1": {
                        "expected": 1,
                        "evaluated": 1,
                        "dpe_coverage": 1.0,
                        "cohorts": _complete_cohorts(expected=1),
                        "estimated_tp": 1,
                    }
                },
            }
        }
    }), encoding="utf-8")

    first = load_binary_backtest_sources(config, "v2")
    assert first["v1"]["estimated_tp"] == 1

    path.write_text(json.dumps({
        "targets": {
            "v2": {
                "quality_gate_passed": True,
                "source_releases": ["v1", "v2"],
                "window_size": 2,
                "sources": {
                    "v1": {
                        "expected": 1,
                        "evaluated": 1,
                        "dpe_coverage": 1.0,
                        "cohorts": _complete_cohorts(expected=1),
                        "estimated_tp": 123,
                    },
                    "v2": {
                        "expected": 1,
                        "evaluated": 1,
                        "dpe_coverage": 1.0,
                        "cohorts": _complete_cohorts(expected=1),
                        "estimated_tp": 456,
                    },
                }
            }
        }
    }), encoding="utf-8")

    second = load_binary_backtest_sources(config, "v2")
    assert second["v1"]["estimated_tp"] == 123
    assert second["v2"]["estimated_tp"] == 456


def test_binary_backtest_reader_rejects_partial_or_failed_target(tmp_path):
    path = tmp_path / "backtest.json"
    config = {"binary_backtest": {"result_metrics": str(path)}}
    target = {
        "quality_gate_passed": False,
        "source_releases": ["v1"],
        "window_size": 1,
        "sources": {
            "v1": {
                "expected": 30,
                "evaluated": 20,
                "dpe_coverage": 2 / 3,
                "estimated_tp": 10,
            }
        },
    }
    path.write_text(json.dumps({"targets": {"v2": target}}), encoding="utf-8")

    assert load_binary_backtest_sources(config, "v2") == {}

    target["quality_gate_passed"] = True
    path.write_text(json.dumps({"targets": {"v2": target}}), encoding="utf-8")

    assert load_binary_backtest_sources(config, "v2") == {}
