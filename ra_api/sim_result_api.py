"""Simulation result query API for RA scenario analysis.

Queries scenario-level DPE metrics from the Trail ClickHouse backend.
API endpoint: /simulation/sim_test/result/query_report/
Auth: JSON sign backend (app_id=21, testing_engineer)

Usage example:
    client = SimResultClient()
    df = client.query_report(
        job_id_base=40390125,
        job_id_feature=40390703,
        filter_expr="Base.dpe_assist_channel_triggered.value > -900 AND Base.dpe_assist_channel_triggered.value < 1",
        order_by="group1__dpe_assist_channel_triggered",
        order_type="desc",
    )
    ids = client.get_scenario_ids(job_id_base=40390125, job_id_feature=40390703,
                                   filter_expr="Base.dpe_assist_channel_triggered.value < 1")
"""

import hashlib
import json
import logging
import os
import re
import time
from typing import Dict, Any, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_VIP = "http://100.69.238.11:8000/voyager/trail"
_HOST = "https://voyager.intra.xiaojukeji.com"
_DEFAULT_APP_ID = "21"
_DEFAULT_APP_TOKEN = "d2570c086ea9c64219c81ab95dd1e31f"
_DEFAULT_METRICS = [
    "dpe_collision",
    "dpe_stuck_detect",
    "dpe_assist_channel_triggered",
]

_OP_MAP = {">": "gt", "<": "lt", ">=": "gte", "<=": "lte", "==": "eq", "=": "eq", "!=": "ne"}


def _sign_payload(payload: Dict[str, Any], token: str) -> str:
    """Trail API 签名：MD5(json.dumps(payload) + '&token=' + token)。

    必须与 requests.post(json=payload) 使用相同的序列化格式（默认分隔符含空格），
    否则服务端签名验证失败。与 check_sim_reproduction/08_batch_job_diff_analysis.py 一致。
    """
    text = json.dumps(payload) + "&token=" + token
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _make_filters_protocol_sql(n: int) -> str:
    """生成 n 个 filter 的 protocol SQL 模板。

    服务端 FilterAnalysis._analysis_sql_protocol_filters 需要这个模板来拼接 WHERE 子句。
    例：n=2 → "(filter AND filter)"
    """
    if n == 0:
        return ""
    if n == 1:
        return "filter"
    return "(" + " AND ".join(["filter"] * n) + ")"


def _parse_filter_expr(expr: str) -> List[Dict[str, Any]]:
    """将页面 filterQuery 字符串解析为 Trail API 所需的 filters 列表。

    Trail API filter 格式（DPE 指标值过滤）：
        {name, group, suffix, comparison_operator, comparison_val}

    支持输入格式：
        Base.dpe_assist_channel_triggered.value > -900 AND Base.dpe_assist_channel_triggered.value < 1
        group2__dpe_stuck_detect > 0
        Base.dpe_collision < 0
    """
    filters = []
    for clause in re.split(r"\bAND\b", expr, flags=re.IGNORECASE):
        clause = clause.strip().strip("()")
        m = re.match(r"([\w.__]+)\s*(>=|<=|!=|==|>|<|=)\s*(-?[\d.]+)", clause)
        if not m:
            logger.warning("无法解析过滤条件: %s", clause)
            continue
        field_raw, op_raw, val_str = m.group(1), m.group(2), m.group(3)

        suffix = "value"
        if field_raw.endswith(".value"):
            field_raw = field_raw[:-len(".value")]
        elif field_raw.endswith(".status"):
            field_raw = field_raw[:-len(".status")]
            suffix = "status"

        field_raw = field_raw.replace("Base.", "group1__").replace(".", "__")
        group, metric = field_raw.split("__", 1) if "__" in field_raw else ("group1", field_raw)

        val = float(val_str) if "." in val_str else int(val_str)
        filters.append({
            "name": metric,
            "group": group,
            "suffix": suffix,
            "comparison_operator": _OP_MAP[op_raw],
            "comparison_val": val,
        })
    return filters


class SimResultClient:
    """Trail 仿真结果查询客户端。

    与 check_sim_reproduction/08_batch_job_diff_analysis.py 保持一致：
    - app_id=21 (testing_engineer)
    - 签名对 dict 直接序列化（json.dumps 默认格式），与 requests.post(json=) 一致
    - 必须同时传 filters 和 filters_protocol_sql，过滤才能生效
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_token: Optional[str] = None,
        use_vip: bool = True,
    ):
        self._app_id = app_id or os.environ.get("SIM_RESULT_APP_ID", _DEFAULT_APP_ID)
        self._app_token = app_token or os.environ.get("SIM_RESULT_APP_TOKEN", _DEFAULT_APP_TOKEN)
        base = _VIP if use_vip else _HOST
        self._url = f"{base}/simulation/sim_test/result/query_report/"
        self._last_count: int = 0

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        # 签名必须与 requests.post(json=body) 使用相同的序列化（含空格的默认格式）
        headers = {
            "content-type": "application/json",
            "appid": self._app_id,
            "time": str(int(time.time())),
            "sign": _sign_payload(body, self._app_token),
        }
        resp = requests.post(self._url, json=body, headers=headers, verify=False, timeout=60)
        resp.raise_for_status()
        result = resp.json()
        if result.get("msg") != "success":
            raise RuntimeError(f"API 返回错误: {result}")
        return result

    def query_report(
        self,
        job_id_base: int,
        job_id_feature: Optional[int] = None,
        metrics: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
        filters: Optional[List[Dict]] = None,
        order_by: Optional[str] = None,
        order_type: str = "desc",
        page: int = 1,
        size: int = 100,
    ) -> pd.DataFrame:
        """查询场景级指标结果，返回 DataFrame。

        Args:
            job_id_base: Base Job ID（必填）。
            job_id_feature: Feature Job ID，不填则单 job 查询。
            metrics: 指标名列表，默认三个 RA 核心指标。
            filter_expr: 从页面 URL 复制的 filterQuery 字符串，例如：
                "Base.dpe_assist_channel_triggered.value > -900 AND Base.dpe_assist_channel_triggered.value < 1"
            filters: 直接传结构化 filters 列表，与 filter_expr 二选一。
            order_by: 排序字段，如 "group1__dpe_assist_channel_triggered"。
            order_type: "asc" 或 "desc"。
            page: 页码（从 1 开始）。
            size: 每页条数，最大 1000。

        Returns:
            DataFrame，每行一个 scenario，列含 scenario_id、scenario_name、
            issue_id、signature 以及各指标的 group1/group2 值和 diff。
        """
        job_ids = [job_id_base] + ([job_id_feature] if job_id_feature else [])
        resolved_filters = filters or (_parse_filter_expr(filter_expr) if filter_expr else [])

        body: Dict[str, Any] = {
            "orion_job_ids": job_ids,
            "selected_metrics": metrics or _DEFAULT_METRICS,
            "filters": resolved_filters,
            # filters_protocol_sql 是服务端 FilterAnalysis 必需的模板，缺少时过滤不生效
            "filters_protocol_sql": _make_filters_protocol_sql(len(resolved_filters)),
            "page": page,
            "size": size,
            "extra_fields": [],
        }
        if order_by:
            body["order_by"] = order_by
            body["order_type"] = order_type

        data = self._post(body)
        details = data.get("data", {}).get("details", {})
        items = details.get("results", []) if isinstance(details, dict) else []
        self._last_count = details.get("count", len(items)) if isinstance(details, dict) else len(items)

        rows = []
        for item in items:
            info = item.get("scenario_info", {})
            row: Dict[str, Any] = {
                "scenario_id": info.get("scenario_id"),
                "scenario_name": info.get("scenario_name", ""),
                "issue_id": info.get("issue_id", ""),
                "signature": info.get("signature", ""),
            }
            for metric, groups in item.get("metric_results", {}).items():
                for group, result in groups.items():
                    val = result.get("value", {})
                    row[f"{metric}__{group}"] = val.get("value") if isinstance(val, dict) else val
                    if "diff" in result:
                        row[f"{metric}__diff"] = result["diff"].get("value")
            rows.append(row)
        return pd.DataFrame(rows)

    def get_scenario_ids(
        self,
        job_id_base: int,
        job_id_feature: Optional[int] = None,
        filter_expr: Optional[str] = None,
        filters: Optional[List[Dict]] = None,
        metrics: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        order_type: str = "desc",
        size: int = 500,
    ) -> List[int]:
        """快捷方法：返回满足条件的 scenario_id 列表。"""
        df = self.query_report(
            job_id_base=job_id_base,
            job_id_feature=job_id_feature,
            metrics=metrics or ["dpe_assist_channel_triggered"],
            filter_expr=filter_expr,
            filters=filters,
            order_by=order_by,
            order_type=order_type,
            size=size,
        )
        return df["scenario_id"].dropna().astype(int).tolist()

    def query_all_pages(
        self,
        job_id_base: int,
        job_id_feature: Optional[int] = None,
        metrics: Optional[List[str]] = None,
        filter_expr: Optional[str] = None,
        filters: Optional[List[Dict]] = None,
        order_by: Optional[str] = None,
        order_type: str = "desc",
        page_size: int = 100,
    ) -> pd.DataFrame:
        """自动翻页拉取所有满足条件的结果。"""
        frames, page = [], 1
        while True:
            df = self.query_report(
                job_id_base=job_id_base, job_id_feature=job_id_feature,
                metrics=metrics, filter_expr=filter_expr, filters=filters,
                order_by=order_by, order_type=order_type, page=page, size=page_size,
            )
            if df.empty:
                break
            frames.append(df)
            if len(df) < page_size:
                break
            page += 1
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
