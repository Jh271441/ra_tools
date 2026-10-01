"""Issue-level metrics: multiple scenarios never multiply the source population."""

from __future__ import annotations

GOOD_RESULTS = {"成功", "失败", "无需协助", "限制使用"}
EXCLUDED_RESULTS = {"out_of_scope", "未接起", "未填写"}


def cohort_for_issue(issue):
    ra_type = int(issue["ra_type"])
    result = issue.get("ra_merge_result")
    if result in GOOD_RESULTS:
        return (
            "positive_auto"
            if ra_type == 2
            else "positive_manual"
            if ra_type == 3
            else None
        )
    if result == "误触发" and ra_type == 2:
        return "negative_auto"
    return None


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def excluded_issue(issue):
    return issue.get("ra_merge_result") in EXCLUDED_RESULTS or (
        int(issue["ra_type"]) == 3 and issue.get("ra_merge_result") == "误触发"
    )


def summarize_population(issues, scenarios, results):
    """Publish only a complete eligible population; unknown GT remains explicit."""
    groups = {}
    for scenario in scenarios:
        groups.setdefault(str(scenario["issue_id"]), []).append(
            str(scenario["scenario_id"])
        )
    counts = {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "tn": 0,
        "road_matches": 0,
        "eligible": 0,
        "missing_results": 0,
        "unclassified": 0,
        "excluded": 0,
    }
    source_auto_tp = source_auto_fp = source_manual_fn = 0
    cohort_counts = {
        k: {"count": 0, "matches": 0}
        for k in ("positive_auto", "negative_auto", "positive_manual")
    }
    for issue in issues:
        cohort = cohort_for_issue(issue)
        if cohort is None:
            counts["excluded" if excluded_issue(issue) else "unclassified"] += 1
            continue
        if cohort == "positive_auto":
            source_auto_tp += 1
        elif cohort == "negative_auto":
            source_auto_fp += 1
        else:
            source_manual_fn += 1
        counts["eligible"] += 1
        cohort_counts[cohort]["count"] += 1
        ids = groups.get(str(issue["issue_id"]), [])
        if not ids or any(
            sid not in results
            or not isinstance(results[sid].get("sim_triggered"), bool)
            for sid in ids
        ):
            counts["missing_results"] += 1
            continue
        triggered = any(results[sid]["sim_triggered"] for sid in ids)
        if cohort == "negative_auto":
            counts["fp" if triggered else "tn"] += 1
        else:
            counts["tp" if triggered else "fn"] += 1
        matches = int(not triggered if cohort == "positive_manual" else triggered)
        counts["road_matches"] += matches
        cohort_counts[cohort]["matches"] += matches
    precision_tp = sum(
        int(i["ra_type"]) == 2 and i.get("ra_merge_result") in GOOD_RESULTS
        for i in issues
    )
    precision_den = sum(
        int(i["ra_type"]) == 2
        and i.get("ra_merge_result") is not None
        and i.get("ra_merge_result") not in EXCLUDED_RESULTS
        for i in issues
    )
    recall_tp = sum(
        int(i["ra_type"]) == 2
        and i.get("ra_merge_result") is not None
        and i.get("ra_merge_result") not in EXCLUDED_RESULTS | {"误触发"}
        for i in issues
    )
    recall_den = sum(
        int(i["ra_type"]) in (2, 3)
        and i.get("ra_merge_result") is not None
        and i.get("ra_merge_result") not in EXCLUDED_RESULTS | {"误触发"}
        for i in issues
    )
    complete = (
        counts["eligible"] > 0
        and not counts["missing_results"]
        and not counts["unclassified"]
    )
    return {
        "available": complete,
        **counts,
        **{
            k + "_repro_rate": ratio(v["matches"], v["count"]) if complete else None
            for k, v in cohort_counts.items()
        },
        "precision": ratio(counts["tp"], counts["tp"] + counts["fp"])
        if complete
        else None,
        "recall": ratio(counts["tp"], counts["tp"] + counts["fn"])
        if complete
        else None,
        "sim_repro_rate": ratio(counts["road_matches"], counts["eligible"])
        if complete
        else None,
        "online_precision": ratio(precision_tp, precision_den),
        "online_recall": ratio(recall_tp, recall_den),
        "precision_auto_tp": precision_tp,
        "precision_denominator": precision_den,
        "recall_auto_tp": recall_tp,
        "recall_denominator": recall_den,
        "aggregation": "one_issue_any_scenario_triggered",
    }
