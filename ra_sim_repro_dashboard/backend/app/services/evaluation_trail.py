"""Offline Trail acquisition, internal receipt validation and optional parity diagnosis.

The general view 1000 is required: view 2410 hides known report samples.
Unknown platform records are quarantined; valid records retain their own snapshot.
The original warehouse RA merge is never reconstructed from Trail ra_merge_result.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from zoneinfo import ZoneInfo

from app.domain.hashing import digest
from app.domain.labels import QUERY_FIELDS
from app.domain import labels as evaluation_labels, metrics as domain_metrics
from app.services import auto_triage_warehouse as warehouse, release_source

profiles = domain_metrics

VIEW_ID = 1000
PLATFORMS = {7: "GEN4_PT", 8: "GEN4_SOP"}
RA_ENUM = {
    0: "未填写",
    1: "成功",
    2: "失败",
    3: "限制使用",
    4: "无需协助",
    5: "误触发",
    6: "未接起",
}
RAW_FIELDS = ("ra_review_result_new", "ra_rd_review_result", "ra_stuck_auto_result", "ra_result")
TZ = ZoneInfo("Asia/Shanghai")


def query(scope, population_filters):
    import re

    filters = profiles.validate(
        {
            **deepcopy(profiles.REVIEW_CONFIG),
            "population": {"date_field": "create_date", "filters": deepcopy(population_filters)},
        }
    )["population"]["filters"]
    if (
        not re.fullmatch(r"gen4-release-\d{8}", scope["release"])
        or filters["trip_category_name"] != ["Daily Cruise/稳定版本测试"]
        or filters["version_category"] != ["release版本"]
        or not set(filters["platform_gen"]) <= set(PLATFORMS.values())
    ):
        raise ValueError("trail_filter_mapping_unverified")
    checked = warehouse.scope_for(
        {"release": scope["release"]}, scope["date_start"], scope["date_end"]
    )
    start = datetime.fromisoformat(checked["date_start"]).replace(tzinfo=TZ)
    end = datetime.fromisoformat(checked["date_end"]).replace(tzinfo=TZ) + timedelta(days=1)
    return {
        "view_id": VIEW_ID,
        "user_location": "cn",
        "filter_operator": "AND",
        "query_attrs": [
            {"attr_id": "version", "operator": "like", "val": [scope["release"]]},
            {"attr_id": "ra_type", "operator": "in", "val": [2, 3]},
            {"attr_id": "is_deleted", "operator": "in", "val": [0]},
            {"attr_id": "trip_odd", "operator": "in", "val": filters["trip_odd"]},
            {"attr_id": "trip_category", "operator": "in", "val": [0]},
            {
                "attr_id": "create_time",
                "operator": "range",
                "val": {
                    "min": int(start.timestamp() * 1000),
                    "max": int(end.timestamp() * 1000) - 1,
                },
            },
        ],
    }


def project(raw, scope, population_filters):
    if not all(
        k in raw
        for k in (
            *RAW_FIELDS,
            "issue_id",
            "create_time",
            "version",
            "ra_type",
            "is_deleted",
            "platform",
            "trip_category",
            "trip_odd",
            "last_modify_time",
        )
    ):
        raise ValueError("trail_projection_incomplete")
    if type(raw["create_time"]) is not int or type(raw["last_modify_time"]) is not int:
        raise ValueError("trail_projection_incomplete")
    day = datetime.fromtimestamp(raw["create_time"] / 1000, TZ).date().isoformat()
    if (
        raw["ra_type"] not in (2, 3)
        or raw["is_deleted"] != 0
        or raw["trip_category"] != 0
        or raw["trip_odd"] not in population_filters["trip_odd"]
        or not scope["date_start"] <= day <= scope["date_end"]
        or not str(raw["version"]).startswith("1." + scope["release"] + ".")
    ):
        raise ValueError("trail_scope_changed")
    original = raw["ra_result"]
    if original is not None and (type(original) is not int or original not in RA_ENUM):
        raise ValueError("trail_ra_enum_unverified")
    values = {k: raw[k] for k in RAW_FIELDS if k != "ra_result"}
    values["ra_original_result"] = RA_ENUM.get(original)
    if any(v is not None and not isinstance(v, str) for v in values.values()):
        raise ValueError("trail_label_projection_invalid")
    receipts = {
        name: {
            "state": "observed",
            "value": values[evaluation_labels.SOURCE_FIELDS[name]],
            "revision": "issue:" + str(raw["last_modify_time"]),
        }
        for name in evaluation_labels.CURRENT_PRIORITY
    }
    normalized = {
        "issue_id": str(raw["issue_id"]),
        "big_version": "1." + scope["release"],
        "create_date": day,
        "ra_trigger_type": "自触发" if raw["ra_type"] == 2 else "人工触发",
        "is_deleted": 0,
        "platform_gen": PLATFORMS.get(raw["platform"]),
        "trip_odd": raw["trip_odd"],
        "trip_category_name": "Daily Cruise/稳定版本测试",
        "version_category": "release版本",
        **values,
        "label_sources": receipts,
    }
    resolved = profiles.resolution(profiles.REVIEW_CONFIG, normalized)
    normalized["merged_ra_rd_result"] = resolved["raw_label"]
    normalized["merged_ra_auto_result"] = (
        values["ra_stuck_auto_result"]
        if values["ra_stuck_auto_result"] is not None
        else values["ra_original_result"]
    )
    return normalized


def collect(scope, population_filters):
    body = query(scope, population_filters)  # Validate before accessing credentials or network.
    appid, token = release_source.trail_credentials()
    base = os.getenv("TRAIL_ISSUE_BASE_URL", "http://10.88.128.83").rstrip("/")
    started = datetime.now(timezone.utc).isoformat()
    listed = release_source.complete_query(
        base + "/paladin/issue/pool/query/", body, appid, token, "issue_id"
    )
    ids = sorted(str(r["issue_id"]) for r in listed)
    fields = sorted(
        set(QUERY_FIELDS)
        | set(RAW_FIELDS)
        | {"create_time", "platform", "trip_category", "trip_odd", "last_modify_time"}
    )
    physical, rows, pending = {}, [], []
    excluded_platform_count = 0
    for offset in range(0, len(ids), 200):
        batch = ids[offset : offset + 200]
        fetched = release_source.signed_query(
            base + "/paladin/issue/pool/query_by_issue_id_list/",
            {"source_id": 1, "issue_id_list": batch, "select_field_list": fields},
            appid,
            token,
        )
        if not isinstance(fetched, dict) or set(fetched) != set(batch):
            raise ValueError("trail_projection_incomplete")
        for iid, raw in fetched.items():
            row = project(raw, scope, population_filters)
            if row["issue_id"] != iid:
                raise ValueError("trail_projection_incomplete")
            if row["platform_gen"] is None:
                pending.append(
                    {
                        "issue_id": iid,
                        "field": "platform_gen",
                        "reason": "unavailable",
                        "row": row,
                        "raw": deepcopy(raw),
                    }
                )
                continue
            elif row["platform_gen"] not in population_filters["platform_gen"]:
                excluded_platform_count += 1
                continue
            rows.append(row)
            physical[iid] = raw
    return {
        "provider": "trail",
        "view_id": VIEW_ID,
        "scope": deepcopy(scope),
        "population_filters": deepcopy(population_filters),
        "started_at": started,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "query": body,
        "rows": sorted(rows, key=lambda r: r["issue_id"]),
        "labels": physical,
        "pending": pending,
        "queried_count": len(ids),
        "excluded_platform_count": excluded_platform_count,
    }


def receipt(candidate):
    """Build a Trail-native receipt, without inventing a warehouse baseline column."""
    scope, selected = candidate["scope"], candidate["population_filters"]
    if candidate.get("provider") != "trail" or candidate.get("view_id") != VIEW_ID:
        raise ValueError("trail_source_invalid")
    query(scope, selected)
    if (
        candidate["queried_count"]
        != len(candidate["rows"]) + len(candidate["pending"]) + candidate["excluded_platform_count"]
    ):
        raise ValueError("trail_projection_incomplete")
    ids = [row["issue_id"] for row in candidate["rows"]]
    pending_ids = [row["issue_id"] for row in candidate["pending"]]
    if (
        len(set(ids)) != len(ids)
        or len(set(pending_ids)) != len(pending_ids)
        or set(ids) & set(pending_ids)
        or set(candidate["labels"]) != set(ids)
    ):
        raise ValueError("trail_projection_incomplete")
    for item in candidate["pending"]:
        expected = project(item["raw"], scope, selected)
        if (
            item.get("field") != "platform_gen"
            or item.get("reason") != "unavailable"
            or expected["platform_gen"] is not None
            or item["row"] != expected
            or item["issue_id"] != expected["issue_id"]
        ):
            raise ValueError("trail_projection_incomplete")
    rows = []
    for row in candidate["rows"]:
        raw = candidate["labels"][row["issue_id"]]
        expected = project(raw, scope, selected)
        if (
            row != expected
            or row["platform_gen"] not in selected["platform_gen"]
            or "merged_ra_result" in row
        ):
            raise ValueError("trail_projection_incomplete")
        item = deepcopy(row)
        for prefix, field in (("auto", "merged_ra_auto_result"), ("review", "merged_ra_rd_result")):
            item.update(
                {
                    prefix + "_" + k: v
                    for k, v in warehouse.membership(item["ra_trigger_type"], item[field]).items()
                }
            )
            item[prefix + "_is_null"] = int(item[field] is None)
        item.update(
            {field + "_is_null": int(item[field] is None) for field in warehouse.RAW_FIELDS}
        )
        rows.append(item)
    result = {
        "schema_version": 3,
        "provider": "trail",
        "baseline_available": False,
        "scope": deepcopy(scope),
        "population_filters": deepcopy(selected),
        "rows": rows,
        "observed_at": candidate["observed_at"],
        "started_at": candidate["started_at"],
        "pending": deepcopy(candidate["pending"]),
        "query": deepcopy(candidate["query"]),
        "queried_count": candidate["queried_count"],
        "excluded_platform_count": candidate["excluded_platform_count"],
        "references": [
            {
                "kind": "trail_signed_snapshot",
                "view_id": VIEW_ID,
                "content_hash": digest({"rows": rows, "pending": candidate["pending"]}),
            }
        ],
    }
    keys = [
        prefix + "_" + k
        for prefix, _ in warehouse.label_pairs(result)
        for k in profiles.DEFAULT_CONFIG["memberships"]
    ]
    result["counts"] = {key: sum(row[key] for row in rows) for key in keys}
    result["counts"].update(population_count=len(rows), big_version="1." + scope["release"])
    return warehouse.validate_receipt(result)


def validate_native(dashboard, physical):
    """Validate the offline import against the actual Trail raw projections."""
    if dashboard.get("provider") != "trail" or dashboard.get("baseline_available") is not False:
        raise ValueError("trail_source_invalid")
    scope, selected = dashboard["scope"], dashboard["population_filters"]
    if dashboard.get("query") != query(scope, selected):
        raise ValueError("trail_source_invalid")
    for row in dashboard["rows"]:
        expected = project(physical[row["issue_id"]], scope, selected)
        if (
            any(row.get(key) != value for key, value in expected.items())
            or "merged_ra_result" in row
        ):
            raise ValueError("trail_projection_incomplete")
    candidate = {
        "provider": "trail",
        "view_id": VIEW_ID,
        "scope": scope,
        "population_filters": selected,
        "rows": [project(physical[row["issue_id"]], scope, selected) for row in dashboard["rows"]],
        "labels": physical,
        "pending": dashboard["pending"],
        "query": dashboard["query"],
        "started_at": dashboard["started_at"],
        "observed_at": dashboard["observed_at"],
        "queried_count": dashboard["queried_count"],
        "excluded_platform_count": dashboard["excluded_platform_count"],
    }
    if any(
        type(candidate[k]) is not int or candidate[k] < 0
        for k in ("queried_count", "excluded_platform_count")
    ):
        raise ValueError("trail_projection_incomplete")
    expected = receipt(candidate)
    if dashboard["counts"] != expected["counts"]:
        raise ValueError("dashboard_count_mismatch")


def validate_reference(reference):
    try:
        if reference.get("schema_version") != 2:
            raise ValueError("trail_review_reference_required")
        profiles.validate(
            {
                **deepcopy(profiles.REVIEW_CONFIG),
                "population": {
                    "date_field": "create_date",
                    "filters": reference["population_filters"],
                },
            }
        )
        warehouse.validate_receipt(reference)
        for row in reference["rows"]:
            for field in warehouse.RAW_FIELDS:
                if field not in row or row[field] is not None and not isinstance(row[field], str):
                    raise ValueError("trail_review_reference_required")
                if field + "_is_null" in row and (
                    type(row[field + "_is_null"]) is not int
                    or row[field + "_is_null"] != int(row[field] is None)
                ):
                    raise ValueError("trail_review_reference_required")
            resolved = profiles.resolution(profiles.REVIEW_CONFIG, row)
            if (
                resolved["status"] not in evaluation_labels.READY
                or resolved["raw_label"] != row["merged_ra_rd_result"]
            ):
                raise ValueError("trail_review_reference_required")
        return reference
    except (KeyError, TypeError, AttributeError):
        raise ValueError("trail_review_reference_required") from None


def verify(reference, candidate):
    validate_reference(reference)
    if (
        reference["scope"] != candidate["scope"]
        or reference["population_filters"] != candidate["population_filters"]
    ):
        raise ValueError("trail_reference_scope_mismatch")
    expected = {r["issue_id"]: r for r in reference["rows"]}
    actual = {r["issue_id"]: r for r in candidate["rows"]}
    if len(expected) != len(reference["rows"]) or len(actual) != len(candidate["rows"]):
        raise ValueError("trail_projection_incomplete")
    fields = (
        "big_version",
        "create_date",
        "ra_trigger_type",
        "platform_gen",
        "trip_odd",
        "trip_category_name",
        "version_category",
        "is_deleted",
        "merged_ra_auto_result",
        "merged_ra_rd_result",
        *warehouse.RAW_FIELDS,
    )
    diffs = [
        {
            "issue_id": iid,
            "fields": {
                k: {"reference": expected[iid].get(k), "trail": actual[iid].get(k)}
                for k in fields
                if expected[iid].get(k) != actual[iid].get(k)
            },
        }
        for iid in sorted(expected.keys() & actual.keys())
    ]
    diffs = [d for d in diffs if d["fields"]]
    flags = {
        key: sum(
            warehouse.membership(r["ra_trigger_type"], r["merged_ra_rd_result"])[key]
            for r in candidate["rows"]
        )
        for key in profiles.DEFAULT_CONFIG["memberships"]
    }
    counts = {key: reference["counts"]["review_" + key] for key in flags}
    matched = (
        not diffs and set(expected) == set(actual) and flags == counts and not candidate["pending"]
    )
    return {
        "status": "matched" if matched else "pending",
        "reference_observed_at": reference["observed_at"],
        "trail_observed_at": candidate["observed_at"],
        "reference_count": len(expected),
        "trail_count": len(actual),
        "added_ids": sorted(actual.keys() - expected.keys()),
        "missing_ids": sorted(expected.keys() - actual.keys()),
        "differences": diffs,
        "unresolved": deepcopy(candidate["pending"]),
        "reference_counts": counts,
        "trail_counts": flags,
        "simulation_submitted": False,
    }
