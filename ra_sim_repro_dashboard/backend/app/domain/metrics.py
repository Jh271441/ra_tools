"""Unified pure metric, cohort, profile validation, and SQL three-value membership engine."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.domain.hashing import digest
from app.domain import labels as label_domain

GOOD = ["成功", "失败", "无需协助", "限制使用"]
EXCLUDED = ["out_of_scope", "未接起", "未填写"]
GOOD_RESULTS = set(GOOD)
EXCLUDED_RESULTS = set(EXCLUDED)

DEFAULT_FILTERS = {
    "trip_odd": ["ODD2"],
    "trip_category_name": ["Daily Cruise/稳定版本测试"],
    "version_category": ["release版本"],
    "is_deleted": [0],
}
DEFAULT_CONFIG = {
    "schema_version": 1,
    "population": {"date_field": "create_date", "filters": DEFAULT_FILTERS},
    "label": {"source": "merged_ra_auto_result", "mapping": {}},
    "memberships": {
        "precision_numerator": {"triggers": [2], "include": GOOD},
        "precision_denominator": {"triggers": [2], "exclude": EXCLUDED},
        "recall_numerator": {"triggers": [2], "exclude": ["误触发", *EXCLUDED]},
        "recall_denominator": {"triggers": [2, 3], "exclude": ["误触发", *EXCLUDED]},
    },
}
BUILTIN = {
    "id": "auto_triage_sql_v2",
    "name": "SQL v2",
    "status": "published",
    "config": DEFAULT_CONFIG,
    "config_hash": digest(DEFAULT_CONFIG),
    "created_at": None,
    "parent": None,
    "description": "Verified literal-label SQL, 2026-11-04",
}

REVIEW_CONFIG = deepcopy(DEFAULT_CONFIG)
REVIEW_CONFIG.update(schema_version=2)
REVIEW_CONFIG["population"]["filters"]["platform_gen"] = ["GEN4_PT", "GEN4_SOP"]
REVIEW_CONFIG["label"] = {
    "source": "coalesce",
    "priority": list(label_domain.CURRENT_PRIORITY),
    "mapping": {},
}
REVIEW = {
    "id": "auto_triage_review_v1",
    "name": "人工复核",
    "status": "published",
    "config": REVIEW_CONFIG,
    "config_hash": digest(REVIEW_CONFIG),
    "created_at": None,
    "parent": BUILTIN["id"],
    "description": "Shuyi verified review basis, PT + SOP, 2026-11-09",
}
BUILTINS = {p["id"]: p for p in (BUILTIN, REVIEW)}


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def membership(config: dict[str, Any], trigger: int, label: str | None) -> dict[str, int]:
    """SQL three-value logic: NULL never matches IN or NOT IN."""
    return {
        name: int(
            label is not None
            and trigger in rule["triggers"]
            and (label in rule["include"] if "include" in rule else label not in rule["exclude"])
        )
        for name, rule in config["memberships"].items()
    }


def validate_profile(config: Any) -> dict[str, Any]:
    if (
        not isinstance(config, dict)
        or set(config) != set(DEFAULT_CONFIG)
        or config["schema_version"] not in (1, 2)
    ):
        raise ValueError("profile_schema_invalid")
    population = config["population"]
    if set(population) != {"date_field", "filters"} or population["date_field"] != "create_date":
        raise ValueError("profile_date_field_invalid")
    filters = population["filters"]
    expected_filters = set(DEFAULT_FILTERS) | (
        {"platform_gen"} if config["schema_version"] == 2 else set()
    )
    if set(filters) != expected_filters:
        raise ValueError("profile_filters_invalid")
    for name, values in filters.items():
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 30
            or any(type(v) not in (str, int) for v in values)
        ):
            raise ValueError("profile_filters_invalid")
        if name == "is_deleted" and values != [0]:
            raise ValueError("profile_deleted_population_invalid")
    label = config["label"]
    if config["schema_version"] == 1:
        if set(label) != {"source", "mapping"} or label["source"] not in (
            "merged_ra_auto_result",
            "merged_ra_result",
        ):
            raise ValueError("profile_label_invalid")
    else:
        if set(label) != {"source", "priority", "mapping"} or label["source"] != "coalesce":
            raise ValueError("profile_label_invalid")
        label_domain.validate_policy(label)
    if (
        not isinstance(label["mapping"], dict)
        or len(label["mapping"]) > 100
        or any(
            not isinstance(k, str)
            or len(k) > 100
            or v is not None
            and (not isinstance(v, str) or len(v) > 100)
            for k, v in label["mapping"].items()
        )
    ):
        raise ValueError("profile_mapping_invalid")
    rules = config["memberships"]
    if set(rules) != set(DEFAULT_CONFIG["memberships"]):
        raise ValueError("profile_memberships_invalid")
    for rule in rules.values():
        if not isinstance(rule, dict) or set(rule) not in (
            {"triggers", "include"},
            {"triggers", "exclude"},
        ):
            raise ValueError("profile_condition_invalid")
        if (
            not isinstance(rule["triggers"], list)
            or not rule["triggers"]
            or any(type(v) is not int or v not in (2, 3) for v in rule["triggers"])
        ):
            raise ValueError("profile_trigger_invalid")
        values = rule.get("include", rule.get("exclude"))
        if (
            not isinstance(values, list)
            or len(values) > 100
            or any(not isinstance(v, str) or len(v) > 100 for v in values)
        ):
            raise ValueError("profile_condition_invalid")
    label_domain_values = {
        None,
        "",
        "__unlisted__",
        *[v for rule in rules.values() for v in rule.get("include", rule.get("exclude"))],
    }
    for trigger in (2, 3):
        for value in label_domain_values:
            flags = membership(config, trigger, value)
            if any(
                flags[m + "_numerator"] > flags[m + "_denominator"] for m in ("precision", "recall")
            ):
                raise ValueError("profile_numerator_outside_denominator")
    return deepcopy(config)


def resolution_for_config(config: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    if config["label"]["source"] == "coalesce":
        return label_domain.resolve_label(row, config["label"])
    value = row[config["label"]["source"]]
    return {
        "label": config["label"]["mapping"].get(value, value) if value is not None else None,
        "raw_label": value,
        "source": "warehouse",
        "status": "resolved" if value is not None else "all_null",
        "policy_version": digest(config["label"]),
        "source_revision": None,
        "trace": [],
    }


def resolve_label_for_config(config: dict[str, Any], row: dict[str, Any]) -> str | None:
    if config["label"]["source"] == "coalesce":
        result = resolution_for_config(config, row)
        if result["status"] not in label_domain.READY:
            raise ValueError("label_source_" + result["status"])
        return result["label"]
    value = row[config["label"]["source"]]
    return config["label"]["mapping"].get(value, value) if value is not None else None


validate = validate_profile
resolution = resolution_for_config
resolve = resolve_label_for_config


def cohort_for_issue(issue: dict[str, Any]) -> str | None:
    if issue.get("evaluation_exclusion"):
        return None
    ra_type = int(issue["ra_type"])
    result = issue.get("ra_merge_result")
    if result in GOOD_RESULTS:
        return "positive_auto" if ra_type == 2 else "positive_manual" if ra_type == 3 else None
    if result == "误触发" and ra_type == 2:
        return "negative_auto"
    return None


def excluded_issue(issue: dict[str, Any]) -> bool:
    return (
        bool(issue.get("evaluation_exclusion"))
        or issue.get("ra_merge_result") in EXCLUDED_RESULTS
        or (int(issue["ra_type"]) == 3 and issue.get("ra_merge_result") == "误触发")
    )


def summarize_population(issues, scenarios, results) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for scenario in scenarios:
        groups.setdefault(str(scenario["issue_id"]), []).append(str(scenario["scenario_id"]))
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
    cohort_counts = {
        k: {"count": 0, "matches": 0} for k in ("positive_auto", "negative_auto", "positive_manual")
    }
    for issue in issues:
        cohort = cohort_for_issue(issue)
        if cohort is None:
            counts["excluded" if excluded_issue(issue) else "unclassified"] += 1
            continue
        counts["eligible"] += 1
        cohort_counts[cohort]["count"] += 1
        ids = groups.get(str(issue["issue_id"]), [])
        if not ids or any(
            sid not in results or not isinstance(results[sid].get("sim_triggered"), bool)
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
    metric_issues = [i for i in issues if not i.get("evaluation_exclusion")]
    precision_tp = sum(
        int(i["ra_type"]) == 2 and i.get("ra_merge_result") in GOOD_RESULTS for i in metric_issues
    )
    precision_den = sum(
        int(i["ra_type"]) == 2
        and i.get("ra_merge_result") is not None
        and i.get("ra_merge_result") not in EXCLUDED_RESULTS
        for i in metric_issues
    )
    recall_tp = sum(
        int(i["ra_type"]) == 2
        and i.get("ra_merge_result") is not None
        and i.get("ra_merge_result") not in EXCLUDED_RESULTS | {"误触发"}
        for i in metric_issues
    )
    recall_den = sum(
        int(i["ra_type"]) in (2, 3)
        and i.get("ra_merge_result") is not None
        and i.get("ra_merge_result") not in EXCLUDED_RESULTS | {"误触发"}
        for i in metric_issues
    )
    complete = (
        counts["eligible"] > 0 and not counts["missing_results"] and not counts["unclassified"]
    )
    return {
        "available": complete,
        **counts,
        **{
            k + "_repro_rate": ratio(v["matches"], v["count"]) if complete else None
            for k, v in cohort_counts.items()
        },
        "precision": ratio(counts["tp"], counts["tp"] + counts["fp"]) if complete else None,
        "recall": ratio(counts["tp"], counts["tp"] + counts["fn"]) if complete else None,
        "sim_repro_rate": ratio(counts["road_matches"], counts["eligible"]) if complete else None,
        "online_precision": ratio(precision_tp, precision_den),
        "online_recall": ratio(recall_tp, recall_den),
        "precision_auto_tp": precision_tp,
        "precision_denominator": precision_den,
        "recall_auto_tp": recall_tp,
        "recall_denominator": recall_den,
        "aggregation": "one_issue_any_scenario_triggered",
    }
