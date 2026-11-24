"""Read the report's exact population, literal labels and SQL memberships.

No report configuration, dataset, platform labels or simulation is changed.
An expired/missing SSO session fails closed instead of substituting Trail rows.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import time

import httpx

REPORT_ID = 288969
SLICE_ID = 13096015
REVIEW_SLICE_ID = 11214491
SOURCE = "table_1726127226310"
PROJECT_ID = 22760
ENDPOINT = "https://bigdata.xiaojukeji.com/newReport/report/v2/display/viewReportData"
GOOD = {"成功", "失败", "无需协助", "限制使用"}
EXCLUDED = {"out_of_scope", "未接起", "未填写"}
FIELDS = {
    "issue_id": ("datae_column_cdf8654c9e", 2),
    "big_version": ("datae_column_3aa42d9e30", 2),
    "create_date": ("datae_column_135ffc9af2", 3),
    "ra_trigger_type": ("datae_column_9fb276f760", 2),
    "merged_ra_result": ("datae_column_ddfbf7ac5c", 2),
    "merged_ra_auto_result": ("datae_column_263be8f49e", 2),
    "trip_odd": ("datae_column_a48e91a041", 2),
    "trip_category_name": ("datae_column_7d8eb1b28b", 2),
    "version_category": ("datae_column_bdd6873ef3", 2),
    "is_deleted": ("datae_column_67a0822312", 1),
}
REVIEW_FIELDS = {
    "platform_gen": ("datae_column_3da008e2eb", 2),
    "merged_ra_rd_result": ("datae_column_948aead35f", 2),
}
RAW_FIELDS = {
    "ra_review_result_new": ("datae_column_b7fec7c307", 2),  # dataset te_ra_result
    "ra_rd_review_result": ("datae_column_9ffadb0441", 2),
    "ra_stuck_auto_result": ("datae_column_a608bfc321", 2),
    "ra_original_result": ("datae_column_b66ccf16a3", 2),  # dataset ops_ra_result
}
COLUMN_FIELDS = {**FIELDS, **REVIEW_FIELDS, **RAW_FIELDS}
LABEL_PAIRS = (("auto", "merged_ra_auto_result"), ("baseline", "merged_ra_result"))


def label_pairs(receipt):
    version = receipt.get("schema_version", 1)
    if version == 3 and type(version) is int:
        if receipt.get("provider") != "trail" or receipt.get("baseline_available") is not False:
            raise ValueError("sample_schema_invalid")
        return (("auto", "merged_ra_auto_result"), ("review", "merged_ra_rd_result"))
    if type(version) is not int or version not in (1, 2):
        raise ValueError("sample_schema_invalid")
    return LABEL_PAIRS + ((("review", "merged_ra_rd_result"),) if version == 2 else ())


def membership(trigger, label):
    """The provided SQL's four independent COUNT(DISTINCT IF(...)) sets."""
    return {
        "precision_numerator": int(trigger == "自触发" and label in GOOD),
        "precision_denominator": int(
            trigger == "自触发" and label is not None and label not in EXCLUDED
        ),
        "recall_numerator": int(
            trigger == "自触发" and label is not None and label not in EXCLUDED | {"误触发"}
        ),
        "recall_denominator": int(
            trigger in ("自触发", "人工触发")
            and label is not None
            and label not in EXCLUDED | {"误触发"}
        ),
    }


def scope_for(period, date_start=None, date_end=None):
    if bool(date_start) != bool(date_end):
        raise ValueError("dashboard_dates_required")
    start = (
        date.fromisoformat(date_start)
        if date_start
        else datetime.fromisoformat(period["case_start"]).date()
    )
    end = (
        date.fromisoformat(date_end)
        if date_end
        else (
            datetime.fromisoformat(period["case_end_exclusive"]) - timedelta(microseconds=1)
        ).date()
    )
    if end < start or (end - start).days > 366:
        raise ValueError("dashboard_dates_invalid")
    return {
        "release": period["release"],
        "date_start": start.isoformat(),
        "date_end": end.isoformat(),
    }


def column(name):
    code, kind = COLUMN_FIELDS[name]
    return {
        "clientId": "at-" + name,
        "columnName": name,
        "columnCode": code,
        "dataSourceCode": SOURCE,
        "dataSourceVersion": 2,
        "dataSourceType": "hive",
        "columnDataType": kind,
        "columnType": "dim",
        "displayName": name,
        "finalName": name,
        "authType": 0,
        "configId": "dim",
        "columnFormat": "yyyy-MM-dd" if kind == 3 else "",
        "express": None,
        "oriExpress": None,
        "columnOriType": 0,
    }


def count_metric(name, expression):
    return {
        "clientId": name,
        "columnName": name,
        "columnCode": "cal_" + hashlib.md5(expression.encode()).hexdigest(),
        "dataSourceCode": SOURCE,
        "dataSourceVersion": 2,
        "dataSourceType": "hive",
        "columnDataType": 1,
        "columnType": "metric",
        "displayName": name,
        "finalName": name,
        "authType": 0,
        "displayType": 10,
        "aggregateType": "",
        "express": expression,
        "oriExpress": expression,
    }


def query(scope, *, rows=False, page=1, population_filters=None, include_review=False):
    from app.services.metric_profiles import DEFAULT_FILTERS, REVIEW_CONFIG

    selected = population_filters or (
        REVIEW_CONFIG["population"]["filters"] if include_review else DEFAULT_FILTERS
    )
    filters = []
    for name, values, operator in (
        ("ra_trigger_type", ["人工触发", "自触发"], "in"),
        ("is_deleted", selected["is_deleted"], "in"),
        ("create_date", [scope["date_start"], scope["date_end"]], "between"),
        ("trip_odd", selected["trip_odd"], "in"),
        ("trip_category_name", selected["trip_category_name"], "in"),
        ("version_category", selected["version_category"], "in"),
        ("big_version", ["1." + scope["release"]], "in"),
    ):
        filters.append(
            {
                **column(name),
                "values": values,
                "valuesType": operator,
                "groupValues": [],
                "isCalculated": False,
                "conditionType": 1,
                "isReportFilter": True,
            }
        )
    if "platform_gen" in selected:
        filters.append(
            {
                **column("platform_gen"),
                "values": selected["platform_gen"],
                "valuesType": "in",
                "groupValues": [],
                "isCalculated": False,
                "conditionType": 1,
                "isReportFilter": True,
            }
        )
    metrics = []
    iid = "[" + FIELDS["issue_id"][0] + "]"
    trigger = "[" + FIELDS["ra_trigger_type"][0] + "]"
    pairs = label_pairs({"schema_version": 2 if include_review else 1})
    for prefix, field in pairs:
        label = "[" + COLUMN_FIELDS[field][0] + "]"
        conditions = {
            "precision_numerator": f"{trigger}='自触发' AND {label} IN ('成功','失败','无需协助','限制使用')",
            "precision_denominator": f"{trigger}='自触发' AND {label} NOT IN ('out_of_scope','未接起','未填写')",
            "recall_numerator": f"{trigger}='自触发' AND {label} NOT IN ('误触发','out_of_scope','未接起','未填写')",
            "recall_denominator": f"{trigger} IN ('自触发','人工触发') AND {label} NOT IN ('误触发','out_of_scope','未接起','未填写')",
        }
        metrics.extend(
            count_metric(prefix + "_" + name, f"count(distinct if({condition}, {iid}, null))")
            for name, condition in conditions.items()
        )
        if rows:
            metrics.append(
                count_metric(
                    prefix + "_is_null", f"count(distinct if({label} is null, {iid}, null))"
                )
            )
    if rows and include_review:
        for name, (code, _) in RAW_FIELDS.items():
            metrics.append(
                count_metric(
                    name + "_is_null", f"count(distinct if([{code}] is null, {iid}, null))"
                )
            )
    metrics.append(count_metric("population_count", f"count(distinct {iid})"))
    dimension_names = [*FIELDS, *REVIEW_FIELDS, *RAW_FIELDS] if include_review else list(FIELDS)
    dims = [column(name) for name in dimension_names] if rows else [column("big_version")]
    return {
        "reportId": REPORT_ID,
        "productId": 101000,
        "source": "market",
        "slices": [
            {
                "id": REVIEW_SLICE_ID if include_review else SLICE_ID,
                "clientId": "auto-triage-reconciliation",
                "type": "simpleTable",
                "projectId": PROJECT_ID,
                "reportId": REPORT_ID,
                "pageIndex": page,
                "pageSize": 2000,
                "dims": dims,
                "metrics": metrics,
                "filters": filters,
                "orderColumns": [{**d, "orderType": "asc"} for d in dims],
                "userSets": {"filters": [], "displays": [], "categories": []},
                "hideRuleIds": None,
                "hideColumnCodes": [],
                "total": {"isShowTotal": False, "items": []},
                "advancedSetting": {"autoClassify": False},
            }
        ],
    }


class Client:
    def __init__(self):
        state_path = Path(
            os.getenv("AUTO_TRIAGE_SHUYI_STORAGE_STATE", "/tmp/ares_storage_state.json")
        )
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            raise ValueError("dashboard_login_required") from None
        cookies = httpx.Cookies()
        for row in state.get("cookies", []):
            if row["domain"].lstrip(".") in ("bigdata.xiaojukeji.com", "xiaojukeji.com"):
                cookies.set(
                    row["name"], row["value"], domain=row["domain"], path=row.get("path", "/")
                )
        if not cookies:
            raise ValueError("dashboard_login_required")
        self.http = httpx.Client(
            cookies=cookies,
            trust_env=False,
            follow_redirects=False,
            timeout=180,
            headers={
                "Referer": "https://bigdata.xiaojukeji.com/analysis_platform_static/board.html"
            },
        )

    def close(self):
        self.http.close()

    def _post(self, payload):
        response = self.http.post(ENDPOINT, json=payload)
        if response.status_code in (301, 302, 303, 401, 403):
            raise ValueError("dashboard_login_required")
        response.raise_for_status()
        value = response.json()
        if value.get("meta", {}).get("code") == 401:
            raise ValueError("dashboard_login_required")
        if not value.get("success") or value.get("meta", {}).get("code") != 0:
            raise ValueError("dashboard_query_failed")
        return value["data"]

    def read(self, payload):
        data = self._post(payload)
        original_slice = (payload.get("slices") or [{}])[0]
        slice_id = (
            original_slice.get("id", SLICE_ID) if isinstance(original_slice, dict) else SLICE_ID
        )
        for _ in range(30):
            if data.get("searchStatus") != "continue":
                if "dsDatas" not in data:
                    raise ValueError("dashboard_query_incomplete")
                return data
            time.sleep(1)
            data = self._post(
                {
                    "queryId": data["queryId"],
                    "sliceId": slice_id,
                    "reportId": REPORT_ID,
                    "productId": 101000,
                    "source": "market",
                }
            )
        raise ValueError("dashboard_query_incomplete")


def decode(data, payload):
    sl = payload["slices"][0]
    names = {
        c["dataSourceCode"] + "." + c["columnCode"]: c["columnName"]
        for c in sl["dims"] + sl["metrics"]
    }
    return [
        {name: node.get(code) for code, name in names.items()} for node in data["dsDatas"]["nodes"]
    ]


def validate_receipt(receipt):
    from app.services.metric_profiles import DEFAULT_FILTERS

    selected = receipt.get("population_filters") or DEFAULT_FILTERS
    scope, rows, counts = receipt["scope"], receipt["rows"], receipt["counts"]
    pairs = label_pairs(receipt)
    if len({r["issue_id"] for r in rows}) != len(rows) or len(rows) != counts["population_count"]:
        raise ValueError("dashboard_population_mismatch")
    for row in rows:
        if (
            not row["issue_id"]
            or row["big_version"] != "1." + scope["release"]
            or not scope["date_start"] <= row["create_date"] <= scope["date_end"]
            or row["ra_trigger_type"] not in ("自触发", "人工触发")
            or row["is_deleted"] != 0
            or any(row[name] not in allowed for name, allowed in selected.items())
        ):
            raise ValueError("dashboard_scope_mismatch")
        for prefix, key in pairs:
            for name, value in membership(row["ra_trigger_type"], row[key]).items():
                if row.get(prefix + "_" + name) != value:
                    raise ValueError("dashboard_membership_mismatch")
    for name, value in counts.items():
        if (
            name != "big_version"
            and (len(rows) if name == "population_count" else sum(r[name] for r in rows)) != value
        ):
            raise ValueError("dashboard_count_mismatch")
    return receipt


def fetch(scope, client=None, *, population_filters=None, include_review=False):
    if include_review and population_filters is None:
        from app.services.metric_profiles import REVIEW_CONFIG

        population_filters = deepcopy(REVIEW_CONFIG["population"]["filters"])
    owned = client is None
    client = client or Client()
    started = datetime.now(timezone.utc).isoformat()
    try:
        count_query = query(
            scope, population_filters=population_filters, include_review=include_review
        )
        count_data = client.read(count_query)
        count_rows = decode(count_data, count_query)
        if len(count_rows) > 1:
            raise ValueError("dashboard_scope_mismatch")
        counts = (
            count_rows[0]
            if count_rows
            else {m["columnName"]: 0 for m in count_query["slices"][0]["metrics"]}
        )
        rows, references, total = [], [], None
        for page in range(1, 31):
            payload = query(
                scope,
                rows=True,
                page=page,
                population_filters=population_filters,
                include_review=include_review,
            )
            data = client.read(payload)
            reported = data.get("pagination", {}).get("totalItems")
            if type(reported) is not int or total is not None and reported != total:
                raise ValueError("dashboard_query_incomplete")
            total = reported
            nodes = decode(data, payload)
            for row in nodes:
                # The display API replaces SQL NULL with '-'. Use backend SQL flags.
                for prefix, key in label_pairs({"schema_version": 2 if include_review else 1}):
                    if row.get(prefix + "_is_null") not in (0, 1):
                        raise ValueError("dashboard_null_projection_missing")
                    if row[prefix + "_is_null"] == 1:
                        row[key] = None
                if include_review:
                    for key in RAW_FIELDS:
                        if row.get(key + "_is_null") not in (0, 1):
                            raise ValueError("dashboard_null_projection_missing")
                        if row[key + "_is_null"] == 1:
                            row[key] = None
                        elif row[key] is None:
                            raise ValueError("dashboard_null_projection_missing")
            rows.extend(nodes)
            references.append({"page": page, "query_id": data.get("queryMeta", {}).get("queryId")})
            if len(rows) == total:
                break
            if not nodes or len(rows) > total:
                raise ValueError("dashboard_query_incomplete")
        else:
            raise ValueError("dashboard_query_incomplete")
        return validate_receipt(
            {
                "scope": deepcopy(scope),
                "rows": rows,
                "counts": counts,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "started_at": started,
                "report_id": REPORT_ID,
                "slice_id": REVIEW_SLICE_ID if include_review else SLICE_ID,
                "data_source_code": SOURCE,
                "references": references,
                "count_query_id": count_data.get("queryMeta", {}).get("queryId"),
                **({"schema_version": 2} if include_review else {}),
                **(
                    {"population_filters": deepcopy(population_filters)}
                    if population_filters
                    else {}
                ),
            }
        )
    finally:
        if owned:
            client.close()
