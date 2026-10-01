"""Read-only signed Trail queries. Partial responses fail closed."""

from __future__ import annotations
import hashlib
import json
import os
import time
import httpx
import ast
from pathlib import Path
from app.config import settings
from app.services.release_cycle import query_contract, real_labels


def trail_credentials(scenario=False):
    app_id = (
        settings.scenario_app_id if scenario else os.getenv("TRAIL_ISSUE_APP_ID", "21")
    )
    token = (
        settings.scenario_app_token if scenario else os.getenv("TRAIL_API_TOKEN", "")
    )
    if token:
        return app_id, token
    # Same Trail app-21 signer already used by the repository result client.
    from ra_api.sim_result_api import SimResultClient

    client = SimResultClient()
    return client._app_id, client._app_token


def scenario_issue_id(row):
    labels = real_labels(row)
    label_ids = {f"cn{v[1:]}" for v in labels if v.startswith("#") and v[1:].isdigit()}
    if len(label_ids) > 1:
        raise ValueError("Scenario 包含多个 Issue 来源标签")
    explicit = row.get("issue_id") or row.get("disengage_info_id")
    if explicit:
        value = str(explicit)
        if value.isdigit():
            value = "cn" + value
        if label_ids and value not in label_ids:
            raise ValueError("Scenario 的 Issue 字段与来源标签冲突")
        return value
    return next(iter(label_ids), "")


def signed_query(url, body, app_id, token):
    if not token or not app_id:
        raise RuntimeError("上游查询凭据未配置")
    text = json.dumps(body)
    headers = {
        "content-type": "application/json",
        "appid": str(app_id),
        "time": str(int(time.time())),
        "sign": hashlib.md5((text + "&token=" + token).encode()).hexdigest(),
    }
    with httpx.Client(timeout=60, trust_env=False) as client:
        response = client.post(url, content=text, headers=headers)
        response.raise_for_status()
        value = response.json()
    if value.get("msg") != "success":
        raise RuntimeError("上游查询返回失败，保留旧快照")
    return value["data"]


def complete_query(url, body, app_id, token, identity):
    all_rows = []
    total = None
    page = 1
    while total is None or len(all_rows) < total:
        data = signed_query(url, {**body, "page": page, "size": 500}, app_id, token)
        reported = data.get("total", data.get("count"))
        if reported is None or int(reported) < 0:
            raise RuntimeError("上游缺少有效总数，无法确认分页完整性")
        if total is not None and total != int(reported):
            raise RuntimeError("分页期间总数变化，请重新同步")
        total = int(reported)
        rows = data.get("res", data.get("data", data.get("items", [])))
        if not isinstance(rows, list) or (not rows and len(all_rows) < total):
            raise RuntimeError("上游分页不完整")
        all_rows.extend(rows)
        page += 1
        if page > 1000:
            raise RuntimeError("上游分页超过安全上限")
    ids = [str(row.get(identity, "")) for row in all_rows]
    if len(all_rows) != total or len(set(ids)) != total or any(not v for v in ids):
        raise RuntimeError("上游 ID 重复、缺失或分页数量不一致")
    return all_rows


def artifact_source(period):
    path = period.get("source_artifact")
    if not path:
        return None
    value = json.loads(Path(path).read_text())
    if (
        not isinstance(value.get("complete"), bool)
        or not isinstance(value.get("issues"), list)
        or not isinstance(value.get("scenarios"), list)
    ):
        raise ValueError("历史快照缺少完整性声明或必要数据")
    return value


def fetch_population(config, period):
    contract = config["contract"]
    base = os.getenv("TRAIL_ISSUE_BASE_URL", "http://10.88.128.83").rstrip("/")
    artifact = artifact_source(period)
    app_id, token = trail_credentials()
    rows = (
        artifact["issues"]
        if artifact is not None
        else complete_query(
            base + "/paladin/issue/pool/query/",
            {
                "view_id": contract.get("view_id", 2410),
                "user_location": "cn",
                "query_attrs": query_contract(config, period, include_manual=True),
            },
            app_id,
            token,
            "issue_id",
        )
    )
    # Validate the returned population, not only the requested filter.
    from datetime import datetime

    lo = int(datetime.fromisoformat(period["case_start"]).timestamp() * 1000)
    hi = int(datetime.fromisoformat(period["case_end_exclusive"]).timestamp() * 1000)
    for row in rows:
        if not lo <= int(row[contract["time_field"]]) < hi:
            raise RuntimeError("返回 Issue 超出已核实周期")
        if period["release"] not in str(row.get("version", "")):
            raise RuntimeError("返回 Issue 的版本与查询不一致")
        if int(row.get("ra_type", -1)) not in (2, 3):
            raise RuntimeError("返回 Issue 不属于准召人口")
        for key, allowed in [
            ("trip_category", {0}),
            ("platform", {7, 8}),
            ("is_deleted", {0}),
        ]:
            if int(row.get(key, -1)) not in allowed:
                raise RuntimeError("返回 Issue 的业务筛选字段不匹配")
        if row.get("trip_odd") != "ODD2":
            raise RuntimeError("返回 Issue 的 ODD 不匹配")
        behavior = row.get("abnormal_behavior", [])
        if isinstance(behavior, str):
            try:
                behavior = ast.literal_eval(behavior)
            except (ValueError, SyntaxError):
                behavior = []
        if not isinstance(behavior, list) or not {int(v) for v in behavior} & {
            292,
            297,
            299,
            393,
            391,
        }:
            raise RuntimeError("返回 Issue 的 abnormal_behavior 不匹配")
    fields = (
        "issue_id",
        "issue_time",
        "version",
        "ra_type",
        "ra_merge_result",
        "issue_topic",
        "status",
        "priority",
        "poi",
        "trip_category",
        "abnormal_behavior",
        "trip_odd",
        "is_deleted",
        "platform",
        "trip_id",
        "ra_start_timestamp",
        "trip_start_time",
        "trip_end_time",
    )
    return [{k: row.get(k) for k in fields} for row in rows]


def fetch_scenarios(period):
    artifact = artifact_source(period)
    if artifact is not None:
        return artifact["scenarios"]
    label_sets = period.get("scenario_query_label_sets") or [
        period.get("scenario_query_labels") or [cycle_scene_label(period)]
    ]
    if not label_sets or any(
        not labels or not all(isinstance(v, str) and v.strip() for v in labels)
        for labels in label_sets
    ):
        raise RuntimeError("该周期未配置可核对的场景查询标签")
    app_id, token = trail_credentials(scenario=True)
    rows_by_id = {}
    for labels in label_sets:
        rows = complete_query(
            settings.scenario_base_url.rstrip("/") + "/simulation/scenario/query/",
            {"labels": ",".join(labels)},
            app_id,
            token,
            "id",
        )
        for row in rows:
            key = str(row["id"])
            if key in rows_by_id and rows_by_id[key] != row:
                raise RuntimeError("场景在多个标签查询期间发生变化，请重新同步")
            rows_by_id[key] = row
    return [
        {
            "scenario_id": str(row["id"]),
            "scenario_name": row.get("name", ""),
            "issue_id": scenario_issue_id(row),
            "scenario_labels": real_labels(row),
            "scenario_revision": row.get("version"),
            "start_timestamp": row.get("start_timestamp"),
            "end_timestamp": row.get("end_timestamp"),
        }
        for row in rows_by_id.values()
    ]


def cycle_scene_label(period):
    return (
        "ra_repro_cycle_"
        + period["cycle_end"].replace("-", "")
        + "_"
        + period["release"][-4:]
    )
