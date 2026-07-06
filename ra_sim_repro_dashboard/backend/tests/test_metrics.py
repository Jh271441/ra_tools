from app.metrics import classify_result, summarize_rows


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
