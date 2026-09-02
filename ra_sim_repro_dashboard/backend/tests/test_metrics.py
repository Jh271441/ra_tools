from app.metrics import classify_result, summarize_rows


class Row:
    def __init__(
        self,
        *,
        road_triggered: bool,
        sim_triggered: bool,
        precision_label: str,
        source_groups: list[str],
    ):
        self.road_triggered = road_triggered
        self.sim_triggered = sim_triggered
        self.reproduced = road_triggered and sim_triggered
        self.precision_label = precision_label
        self.trigger_type = "MODEL" if sim_triggered else "NONE"
        self.root_cause = "REPRODUCED" if self.reproduced else "UNKNOWN"
        self.raw_metrics = {"source_groups": source_groups}


def test_model_fp_with_model_evidence_keeps_model_type_and_fp_root_cause():
    result = classify_result(
        {
            "road_triggered": True,
            "sim_triggered": False,
            "unstuck_status": "MODEL_FP",
            "max_scen_dnn": 0.8,
            "threshold": 0.5,
            "fp_reasons": ["FP_LANE_CHANGE_FORBID"],
            "fn_reasons": [],
        }
    )
    assert result.trigger_type == "MODEL"
    assert result.root_cause == "FP_RULE_SUPPRESS"
    assert result.precision_label == "FN"


def test_model_fp_without_model_evidence_is_fp_suppressed():
    result = classify_result(
        {
            "road_triggered": True,
            "sim_triggered": False,
            "unstuck_status": "MODEL_FP",
            "max_scen_dnn": -1,
            "threshold": 0.5,
        }
    )
    assert result.trigger_type == "FP_SUPPRESSED"
    assert result.root_cause == "FP_RULE_SUPPRESS"


def test_negative_dataset_labels_have_clear_roots():
    tn = classify_result({"road_triggered": False, "sim_triggered": False})
    fp = classify_result({"road_triggered": False, "sim_triggered": True})

    assert tn.precision_label == "TN"
    assert tn.root_cause == "TRUE_NEGATIVE"
    assert fp.precision_label == "FP"
    assert fp.root_cause == "FALSE_POSITIVE"


def test_summary_rates():
    rows = [
        classify_result({"road_triggered": True, "sim_triggered": True, "fn_reasons": ["ASSIST_STUCK_MODEL"]}),
        classify_result({"road_triggered": True, "sim_triggered": False, "max_scen_dnn": 0.1, "threshold": 0.5}),
        classify_result({"road_triggered": False, "sim_triggered": True}),
    ]
    summary = summarize_rows(rows)
    assert summary["total_cases"] == 3
    assert summary["sim_repro_rate"] == 0.5
    assert summary["precision"] == 0.5
    assert summary["recall"] == 0.5


def test_summary_repro_rate_uses_all_three_road_behavior_cohorts():
    rows = [
        Row(road_triggered=True, sim_triggered=True, precision_label="TP", source_groups=["positive_auto"]),
        Row(road_triggered=True, sim_triggered=False, precision_label="FN", source_groups=["positive_auto"]),
        Row(road_triggered=True, sim_triggered=True, precision_label="TP", source_groups=["positive_manual"]),
        Row(road_triggered=True, sim_triggered=False, precision_label="FN", source_groups=["positive_manual"]),
        Row(road_triggered=False, sim_triggered=True, precision_label="FP", source_groups=["negative_auto"]),
        Row(road_triggered=False, sim_triggered=False, precision_label="TN", source_groups=["negative_auto"]),
    ]

    summary = summarize_rows(rows)

    assert summary["road_positive_cases"] == 4
    assert summary["road_behavior_cases"] == 6
    assert summary["reproduced_cases"] == 3
    assert summary["sim_repro_rate"] == 0.5
    assert summary["precision"] == 0.6667
    assert summary["recall"] == 0.5
    assert summary["positive_auto_repro_rate"] == 0.5
    assert summary["negative_auto_repro_rate"] == 0.5
    assert summary["positive_manual_repro_rate"] == 0.5
    assert summary["specificity"] == 0.5
