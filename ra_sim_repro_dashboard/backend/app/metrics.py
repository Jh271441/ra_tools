from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MODEL_REASONS = {"ASSIST_STUCK_MODEL", "MODEL_REQUEST", "MODEL_DETECT"}
FN_PREFIXES = ("FN_",)
FP_PREFIXES = ("FP_",)
FP_STATUSES = {"MODEL_FP", "kAbort", "ABORT", "3"}
ROAD_BEHAVIOR_SOURCE_GROUPS = {
    "positive_auto",
    "negative_auto",
    "positive_manual",
}


@dataclass(frozen=True)
class ClassifiedResult:
    road_triggered: bool
    sim_triggered: bool
    reproduced: bool
    precision_label: str
    trigger_type: str
    root_cause: str


def normalize_reasons(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        return [part.strip() for part in value.replace("|", ",").split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def boolish(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "opened", "triggered"}
    return default


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return None


def classify_result(raw: dict[str, Any]) -> ClassifiedResult:
    road_triggered = boolish(raw.get("road_triggered"), default=True)
    sim_triggered = boolish(
        raw.get("sim_triggered", raw.get("dpe_assist_channel_triggered")),
        default=False,
    )
    fp_reasons = normalize_reasons(raw.get("fp_reasons") or raw.get("fp_process_reasons"))
    fn_reasons = normalize_reasons(raw.get("fn_reasons") or raw.get("fn_process_reasons"))
    unstuck_status = str(raw.get("unstuck_status") or "")
    model_score = as_float(first_present(raw, "model_score_max", "max_scen_dnn"))
    threshold = as_float(first_present(raw, "threshold", "stuck_threshold"))
    by_model = boolish(raw.get("is_stuck_detected_by_model"), default=False)
    route_unstuck = boolish(raw.get("route_unstuck"), default=False)
    received_fix_point = boolish(raw.get("receive_fix_point_from_cloud"), default=False)

    if any(reason in MODEL_REASONS or "ASSIST_STUCK_MODEL" in reason for reason in fn_reasons):
        trigger_type = "MODEL"
    elif by_model or (model_score is not None and threshold is not None and model_score >= threshold):
        trigger_type = "MODEL"
    elif any(reason.startswith(FN_PREFIXES) for reason in fn_reasons):
        trigger_type = "FN"
    elif fp_reasons or unstuck_status in FP_STATUSES:
        trigger_type = "FP_SUPPRESSED"
    elif sim_triggered:
        trigger_type = "OTHER"
    else:
        trigger_type = "NONE"

    if road_triggered and sim_triggered:
        precision_label = "TP"
    elif not road_triggered and sim_triggered:
        precision_label = "FP"
    elif road_triggered and not sim_triggered:
        precision_label = "FN"
    else:
        precision_label = "TN"

    if precision_label == "TP":
        root_cause = "REPRODUCED"
    elif precision_label == "TN":
        root_cause = "TRUE_NEGATIVE"
    elif precision_label == "FP":
        root_cause = "FALSE_POSITIVE"
    elif fp_reasons or unstuck_status in FP_STATUSES:
        root_cause = "FP_RULE_SUPPRESS"
    elif route_unstuck or received_fix_point:
        root_cause = "SIM_DIVERGENCE"
    elif not sim_triggered and (
        model_score is None
        or model_score < 0
        or (threshold is not None and model_score < threshold)
        or boolish(raw.get("counter_insufficient"), default=False)
    ):
        root_cause = "MODEL_OR_COUNTER_INSUFFICIENT"
    elif sim_triggered:
        root_cause = "REPRODUCED"
    else:
        root_cause = "UNKNOWN"

    return ClassifiedResult(
        road_triggered=road_triggered,
        sim_triggered=sim_triggered,
        reproduced=road_triggered and sim_triggered,
        precision_label=precision_label,
        trigger_type=trigger_type,
        root_cause=root_cause,
    )


def rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def source_groups(row: Any) -> set[str]:
    raw_metrics = getattr(row, "raw_metrics", None)
    if not isinstance(raw_metrics, dict):
        return set()
    value = raw_metrics.get("source_groups")
    if isinstance(value, list):
        return {str(item) for item in value if str(item).strip()}
    if isinstance(value, str):
        return {part.strip() for part in value.replace("|", ",").split(",") if part.strip()}
    return set()


def summarize_rows(rows: list[Any]) -> dict[str, Any]:
    total = len(rows)
    sim_positive = sum(1 for row in rows if row.sim_triggered)
    tp = sum(1 for row in rows if row.precision_label == "TP")
    fp = sum(1 for row in rows if row.precision_label == "FP")
    fn = sum(1 for row in rows if row.precision_label == "FN")
    tn = sum(1 for row in rows if row.precision_label == "TN")
    model_count = sum(1 for row in rows if row.trigger_type == "MODEL" and row.sim_triggered)
    fn_count = sum(1 for row in rows if row.trigger_type == "FN" and row.sim_triggered)
    fp_suppress_count = sum(1 for row in rows if row.root_cause == "FP_RULE_SUPPRESS")
    rows_have_source_groups = any(source_groups(row) for row in rows)
    if rows_have_source_groups:
        repro_rows = [
            row
            for row in rows
            if source_groups(row) & ROAD_BEHAVIOR_SOURCE_GROUPS
        ]
        reproduced = sum(
            1
            for row in repro_rows
            if (
                not row.sim_triggered
                if "positive_manual" in source_groups(row)
                else row.sim_triggered
            )
        )
    else:
        repro_rows = [row for row in rows if row.road_triggered]
        reproduced = sum(1 for row in repro_rows if row.sim_triggered)
    repro_source_cases = len(repro_rows)
    auto_trigger_source_cases = sum(
        1
        for row in rows
        if source_groups(row) & {"positive_auto", "negative_auto"}
    ) if rows_have_source_groups else repro_source_cases

    cohort_rows = {
        group: [row for row in rows if group in source_groups(row)]
        for group in ("positive_auto", "negative_auto", "positive_manual")
    }
    positive_auto_repro = rate(
        sum(1 for row in cohort_rows["positive_auto"] if row.sim_triggered),
        len(cohort_rows["positive_auto"]),
    )
    negative_auto_repro = rate(
        sum(1 for row in cohort_rows["negative_auto"] if row.sim_triggered),
        len(cohort_rows["negative_auto"]),
    )
    positive_manual_repro = rate(
        sum(1 for row in cohort_rows["positive_manual"] if not row.sim_triggered),
        len(cohort_rows["positive_manual"]),
    )

    precision = rate(tp, tp + fp)
    recall = rate(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0

    root_causes: dict[str, int] = {}
    for row in rows:
        root_causes[row.root_cause] = root_causes.get(row.root_cause, 0) + 1

    return {
        "total_cases": total,
        # Kept for API compatibility: this is the historical auto-trigger
        # population, while road_behavior_cases is the denominator of the
        # first-chart road->sim behavior reproduction rate.
        "road_positive_cases": auto_trigger_source_cases,
        "road_behavior_cases": repro_source_cases,
        "sim_positive_cases": sim_positive,
        "reproduced_cases": reproduced,
        "sim_repro_rate": rate(reproduced, repro_source_cases),
        "model_repro_rate": rate(model_count, repro_source_cases),
        "fn_fallback_rate": rate(fn_count, max(sim_positive, 1)),
        "fp_suppress_rate": rate(fp_suppress_count, total),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": rate(tn, tn + fp),
        "accuracy": rate(tp + tn, total),
        "positive_auto_repro_rate": positive_auto_repro,
        "negative_auto_repro_rate": negative_auto_repro,
        "positive_manual_repro_rate": positive_manual_repro,
        "evaluated_cases": total,
        "dpe_coverage": 1.0 if total else 0.0,
        "quality_gate_passed": True,
        "root_causes": root_causes,
    }
