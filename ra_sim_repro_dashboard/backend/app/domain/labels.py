"""Pure label resolution, canonical scenario label validation, and physical input comparison.

Internalizes `ra_api.release_labels` and `evaluation_labels` with zero DB/HTTP dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import hashlib
import json
import re
from typing import Any

from app.domain.hashing import digest

COHORTS = ("positive_auto", "positive_manual", "negative_auto")

INPUT_FIELDS = (
    "version",
    "issue_time",
    "ra_type",
    "trip_id",
    "ra_start_timestamp",
    "trip_start_time",
    "trip_end_time",
)
SCENE_FIELDS = ("issue_id", "scenario_revision", "start_timestamp", "end_timestamp")
LABEL_FIELDS = ("ra_stuck_auto_result", "ra_result")
QUERY_FIELDS = (
    "issue_id",
    *INPUT_FIELDS,
    "issue_topic",
    "ra_merge_result",
    *LABEL_FIELDS,
    "is_deleted",
)

QUIET_SECONDS = 24 * 3600
MAX_OBSERVATION_GAP_SECONDS = 3 * 3600
WATCH_RULE = "issue_last_time_24h"
AUTOMATIC_RULES = {WATCH_RULE, "issue_inactivity_24h"}

SOURCE_FIELDS = {
    "review": None,
    "te_prime": None,
    "te": "ra_review_result_new",
    "rd": "ra_rd_review_result",
    "auto": "ra_stuck_auto_result",
    "to": "ra_original_result",
}
CURRENT_PRIORITY = ["te", "rd", "auto", "to"]
FUTURE_PRIORITY = ["review", "te_prime", *CURRENT_PRIORITY]
READY = ("resolved", "all_null")


def scene_labels(row: Mapping[str, Any]) -> set[str]:
    labels = row.get("labels", row.get("scenario_labels", []))
    if isinstance(labels, str):
        labels = json.loads(labels) if labels.startswith("[") else labels.split(",")
    return {str(v).strip() for v in labels}


def real_labels(raw: Mapping[str, Any]) -> list[str]:
    """Only platform labels; source_labels are query provenance, not actual tags."""
    value = raw.get("labels", raw.get("scenario_labels", []))
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.lstrip().startswith("[") else value.split(",")
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return sorted({str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip()})


def full_scene_label(period: Mapping[str, Any]) -> str:
    release = period["release"]
    if not re.fullmatch(r"gen4-release-\d{8}", release):
        raise ValueError("A dated gen4 release is required for Scenario labels")
    pattern = rf"ra_repro_full_\d{{8}}_{release[-8:]}"
    explicit = period.get("scenario_creation_label")
    if explicit:
        if not re.fullmatch(pattern, explicit):
            raise ValueError("Scenario namespace does not match release")
        return explicit
    labels = set(period.get("scenario_query_labels", []))
    for group in period.get("scenario_query_label_sets", []):
        labels.update(group)
    existing = {label for label in labels if re.fullmatch(pattern, label)}
    if len(existing) > 1:
        raise ValueError("Multiple full namespaces require an explicit canonical label")
    if existing:
        return existing.pop()
    end = period["cycle_end"].replace("-", "")
    if not re.fullmatch(r"\d{8}", end):
        raise ValueError("A closed cycle is required for Scenario labels")
    return f"ra_repro_full_{end}_{release[-8:]}"


def validate_scene_labels(row: Mapping[str, Any], label: str, release: str, cohort: str) -> None:
    labels = scene_labels(row)
    trigger = "ManualTrigger" if cohort == "positive_manual" else "AutoTrigger"
    required = {label, f"{label}_{release}", f"{label}_{cohort}", f"{label}_{trigger}"}
    if cohort not in COHORTS or not required <= labels:
        raise ValueError("Scenario is missing canonical full/cohort/trigger labels")
    if any(v.startswith("ra_repro_cycle_") for v in labels):
        raise ValueError("Legacy cycle labels must be consolidated before submission")
    for value in labels:
        namespace = re.match(r"(ra_repro_full_\d{8}_\d{8})(?:_|$)", value)
        if namespace and namespace[1] != label:
            raise ValueError("Scenario has multiple full namespaces")
    if labels & {f"{label}_{c}" for c in COHORTS} != {f"{label}_{cohort}"}:
        raise ValueError("Scenario cohort labels disagree with frozen GT")
    if labels & {f"{label}_AutoTrigger", f"{label}_ManualTrigger"} != {f"{label}_{trigger}"}:
        raise ValueError("Scenario trigger group is ambiguous")


def validate_physical_scene_labels(
    row: Mapping[str, Any], label: str, release: str, cohort: str
) -> None:
    labels = scene_labels(row)
    original = [value for value in COHORTS if f"{label}_{value}" in labels]
    if len(original) != 1 or cohort not in ("source_auto", "source_manual"):
        raise ValueError("Scenario cohort labels are ambiguous")
    validate_scene_labels(row, label, release, original[0])
    if (original[0] == "positive_manual") != (cohort == "source_manual"):
        raise ValueError("Scenario trigger group is ambiguous")


def cohort_label_update(
    row: Mapping[str, Any], label: str, release: str, cohort: str
) -> list[str] | None:
    labels = scene_labels(row)
    present = [c for c in COHORTS if f"{label}_{c}" in labels]
    if len(present) != 1 or cohort not in COHORTS:
        raise ValueError("Scenario cohort labels are ambiguous")
    previous = present[0]
    validate_scene_labels(row, label, release, previous)
    if (previous == "positive_manual") != (cohort == "positive_manual"):
        raise ValueError("Scenario trigger change requires review")
    if previous == cohort:
        return None
    updated = labels - {f"{label}_{previous}"} | {f"{label}_{cohort}"}
    validate_scene_labels({"labels": sorted(updated)}, label, release, cohort)
    return sorted(updated)


RAW_RESULTS = {
    0: "未填写",
    1: "成功",
    2: "失败",
    3: "限制使用",
    4: "无需协助",
    5: "误触发",
    6: "未接起",
}
KNOWN_RESULTS = {
    "成功",
    "失败",
    "无需协助",
    "限制使用",
    "out_of_scope",
    "未接起",
    "未填写",
    "误触发",
    "正确触发",
}


def business_label(value: Any) -> Any:
    """Map only the original RA enum, without rewriting model/warehouse labels."""
    if value is None or isinstance(value, str) and value in KNOWN_RESULTS:
        return value
    if type(value) is int or isinstance(value, str) and value.isdecimal():
        return RAW_RESULTS.get(int(value), str(value))
    return str(value)


def physical_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: row.get(key) for key in INPUT_FIELDS}
    for key in ("ra_type", "issue_time", "ra_start_timestamp", "trip_start_time", "trip_end_time"):
        value = result[key]
        if isinstance(value, str) and value.isdecimal():
            result[key] = int(value)
    return result


def same_inputs(before, after, fields=INPUT_FIELDS) -> bool:
    old = {str(i["issue_id"]): i for i in before}
    new = {str(i["issue_id"]): i for i in after}
    return (
        len(old) == len(before)
        and len(new) == len(after)
        and old.keys() == new.keys()
        and all(old[i].get(k) == new[i].get(k) for i in old for k in fields)
    )


def activity_identity(rows, time_field: str) -> str:
    values = [
        {k: row.get(k) for k in ("issue_id", time_field, "version", "ra_type", "ra_merge_result")}
        for row in rows
    ]
    ids = [str(row.get("issue_id") or "") for row in rows]
    if not rows or any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("观察人口为空、重复或缺少Issue ID")
    return digest(sorted(values, key=lambda row: str(row["issue_id"])))


def validate_monitor_config(config: Mapping[str, Any]) -> None:
    contract = config.get("contract", {})
    if not all(contract.get(k) for k in ("verified", "reference", "time_field")):
        raise ValueError("自动观察要求已核实的数易查询口径")
    if config.get("simulation", {}).get("acceptance_only"):
        raise ValueError("验收子集禁止开启自动仿真")


def validate_policy(policy: Any) -> Mapping[str, Any]:
    if not isinstance(policy, Mapping):
        raise ValueError("profile_priority_invalid")
    priority = policy.get("priority")
    if (
        not isinstance(priority, list)
        or not 1 <= len(priority) <= len(SOURCE_FIELDS)
        or any(not isinstance(name, str) or name not in SOURCE_FIELDS for name in priority)
        or len(set(priority)) != len(priority)
    ):
        raise ValueError("profile_priority_invalid")
    return policy


@lru_cache(maxsize=128)
def _policy_version(serialized: str) -> str:
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def source_value(sample: Mapping[str, Any], name: str) -> dict[str, Any]:
    projected = sample.get("label_sources", {})
    if isinstance(projected, Mapping) and name in projected:
        item = projected[name]
        if not isinstance(item, Mapping):
            return {"state": "unavailable"}
        if item.get("state") in ("unavailable", "conflict"):
            return {"state": item["state"], "revision": item.get("revision")}
        if item.get("state") != "observed" or "value" not in item:
            return {"state": "unavailable"}
        value = item["value"]
        revision = item.get("revision")
    else:
        field = SOURCE_FIELDS[name]
        if field is None or field not in sample:
            return {"state": "unavailable"}
        value, revision = sample[field], None
    if value is not None and not isinstance(value, str):
        return {"state": "unavailable", "revision": revision}
    return {"state": "null" if value is None else "value", "value": value, "revision": revision}


def resolve_label(
    sample: Mapping[str, Any], policy: Mapping[str, Any], *, policy_version: str | None = None
) -> dict[str, Any]:
    validate_policy(policy)
    version = policy_version or _policy_version(
        json.dumps(policy, sort_keys=True, ensure_ascii=True)
    )
    trace = []
    for name in policy["priority"]:
        item = source_value(sample, name)
        trace.append({"source": name, "state": item["state"]})
        if item["state"] in ("unavailable", "conflict"):
            return {
                "label": None,
                "raw_label": None,
                "source": None,
                "policy_version": version,
                "source_revision": item.get("revision"),
                "status": item["state"],
                "trace": trace,
            }
        if item["state"] == "value":
            raw = item["value"]
            return {
                "label": policy.get("mapping", {}).get(raw, raw),
                "raw_label": raw,
                "source": name,
                "policy_version": version,
                "source_revision": item.get("revision"),
                "status": "resolved",
                "trace": trace,
            }
    return {
        "label": None,
        "raw_label": None,
        "source": None,
        "policy_version": version,
        "source_revision": None,
        "status": "all_null",
        "trace": trace,
    }
