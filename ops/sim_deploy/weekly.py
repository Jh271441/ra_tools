#!/usr/bin/env python3
"""Read-only weekly release audit. Never submits simulations or guesses periods.
Unverified contracts and incomplete cohorts produce a status, not a published rate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def last_cycle_end(day):
    monday = day - dt.timedelta(days=day.weekday())
    return monday - dt.timedelta(days=4)


def choose_period(config, day):
    end = last_cycle_end(day).isoformat()
    matches = [p for p in config["periods"] if p["cycle_end"] == end]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one authoritative period ending {end}; found {len(matches)}"
        )
    period = matches[0]
    start = dt.datetime.fromisoformat(period["case_start"])
    stop = dt.datetime.fromisoformat(period["case_end_exclusive"])
    if start.tzinfo is None or stop.tzinfo is None or start >= stop:
        raise ValueError("Case boundaries must be timezone-aware and increasing")
    return period


def atomic(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    temp.replace(path)


def evaluate(config, day, output):
    result = {
        "checked_at": dt.datetime.now(TZ).isoformat(),
        "scheduled_week": (day - dt.timedelta(days=day.weekday())).isoformat(),
        "status": "pending_configuration",
        "published": False,
    }
    try:
        period = choose_period(config, day)
    except ValueError:
        result.update(
            status="pending_period",
            reason=f"缺少唯一且有效的 {last_cycle_end(day)} 结束周期记录；不根据版本名称猜测。",
        )
        return result
    result["period"] = period
    result["contract_hash"] = hashlib.sha256(
        json.dumps(config["contract"], sort_keys=True).encode()
    ).hexdigest()
    if not config["contract"].get("verified") or not period.get("verified"):
        result["reason"] = (
            "数易筛选、日期边界和 release 周期尚未核实，禁止发布推测指标。"
        )
        return result
    contract = config["contract"]
    if not contract.get("reference") or not period.get("evidence"):
        raise ValueError(
            "Verified configuration requires contract reference and period evidence"
        )
    if not period.get("job_ids") or not period.get("manifest"):
        result.update(
            status="pending_simulation",
            reason="缺少已核实的仿真 job 或场景映射；不会自动创建仿真。",
        )
        return result
    if not os.environ.get("ORION_TOKEN"):
        result.update(status="authentication_required", reason="ORION_TOKEN 未配置。")
        return result
    import pandas as pd

    from ra_api.issue_api import TrailInterface
    from scripts.ra_repro_validate_orion import validate

    start = int(dt.datetime.fromisoformat(period["case_start"]).timestamp() * 1000)
    stop = int(
        dt.datetime.fromisoformat(period["case_end_exclusive"]).timestamp() * 1000
    )
    attrs = list(contract["query_attrs"]) + [
        {
            "attr_id": "version",
            "operator": contract["version_operator"],
            "val": [period["release"]],
        },
        {
            "attr_id": contract["time_field"],
            "operator": "range",
            "val": {"min": start, "max": stop - 1},
        },
    ]
    result["query_attrs"] = attrs
    issues = TrailInterface(base_url=contract.get("base_url")).query_issue_poll(
        contract["view_id"], attrs, size=500, require_complete=True
    )
    if issues.empty:
        result.update(status="no_cases", reason="上游返回空 case 集合，未发布指标。")
        return result
    required = {"issue_id", contract["time_field"]}
    if not required.issubset(issues.columns):
        raise ValueError("Missing identity or timestamp in case response")
    timestamps = pd.to_numeric(issues[contract["time_field"]], errors="raise")
    if not ((timestamps >= start) & (timestamps < stop)).all():
        raise ValueError("Upstream returned out-of-period cases")
    issues = issues.drop_duplicates("issue_id")
    issue_ids = set(issues.issue_id.astype(str))
    manifest_path = Path(period["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = Path(os.environ["SIM_SOURCE_ROOT"]) / manifest_path
    manifest = pd.read_csv(manifest_path, low_memory=False)
    manifest = manifest[manifest["release"].eq(period["release"])].copy()
    manifest_ids = set(manifest.issue_id.astype(str))
    selected = manifest[manifest.issue_id.astype(str).isin(issue_ids)].copy()
    if selected.issue_id.duplicated().any():
        raise ValueError("Duplicate issue-to-scenario mappings")
    missing = sorted(issue_ids - manifest_ids)
    result["case_count"] = len(issue_ids)
    result["case_ids"] = sorted(issue_ids)
    result["missing_scenario_issue_ids"] = missing
    result["excluded_manifest_rows"] = len(manifest) - len(selected)
    if missing:
        result.update(
            status="incomplete_coverage",
            reason=f"{len(missing)} 个数易 case 没有场景映射。",
        )
        return result
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manifest.csv"
        selected.to_csv(path, index=False)
        metrics = validate(
            period["job_ids"], path, period["release"], os.environ["ORION_TOKEN"]
        )
    result["metrics"] = metrics
    cohorts = metrics["cohorts"]
    numerator = sum(int(v["road_behavior_matches"]) for v in cohorts.values())
    denominator = sum(int(v["evaluated"]) for v in cohorts.values())
    result.update(
        numerator=numerator,
        denominator=denominator,
        observed_rate=numerator / denominator if denominator else None,
    )
    complete = (
        metrics.get("is_terminal_and_complete") is True
        and metrics.get("quality", {}).get("gate_passed_so_far") is True
        and not metrics.get("cross_job_result_conflict_count")
        and denominator == len(issue_ids)
    )
    result.update(
        status="complete" if complete else "incomplete_simulation", published=complete
    )
    result["reason"] = (
        "复现率为有效仿真与路测触发行为一致的比例；自动场景应触发，人工场景应不触发。"
        if complete
        else "任务、场景覆盖或质量门禁未通过，保留已有正式报告。"
    )
    return result


def render(output, current):
    latest = output / "latest.json"
    good = json.loads(latest.read_text()) if latest.exists() else None
    rate = f"{good['observed_rate']:.2%}" if good else "暂无通过验收的周报"
    period = current.get("period", {})
    labels = {
        "pending_period": "待补充运行周期",
        "pending_configuration": "待核实统计口径",
        "pending_simulation": "等待仿真任务",
        "authentication_required": "需要更新数据访问凭据",
        "no_cases": "未查到符合条件的 case",
        "incomplete_coverage": "场景覆盖不完整",
        "incomplete_simulation": "仿真结果尚未通过校验",
        "complete": "检查完成",
        "check_failed": "检查失败",
    }
    period_text = (
        f"{period.get('release', '')} · {period.get('case_start', '')} 至 {period.get('case_end_exclusive', '')}（右端不含）"
        if period
        else "尚未确定本次检查的 release 及 case 范围"
    )
    body = f"""<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Release 每周复现检查</title>
<style>body{{font:16px system-ui;max-width:960px;margin:48px auto;padding:0 24px;color:#172b4d;background:#f6f8fc}}article{{background:white;border-radius:16px;padding:28px;margin:20px 0}}h1{{font-size:28px}}.rate{{font-size:36px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#1762bb}}</style>
<a href="/sim/overview">返回仿真看板</a><h1>Release 每周复现检查</h1>
<article><h2>最近有效结果</h2><div class="rate">{html.escape(rate)}</div><p>{html.escape(str((good or {}).get("period", {}).get("release", "")))}</p></article>
<article><h2>本次检查：{html.escape(labels.get(current["status"], current["status"]))}</h2><p>{html.escape(current.get("reason", ""))}</p><p>{html.escape(period_text)}</p><p>检查时间：{html.escape(current["checked_at"])}</p><p>北京时间每周一 09:00；未通过校验不会覆盖有效结果。</p><a href="status.json">查看本次记录</a></article></html>"""
    temp = output / "index.html.tmp"
    temp.write_text(body)
    temp.replace(output / "index.html")


def execute(config_path, output, day):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        config = json.loads(config_path.read_text())
        try:
            result = evaluate(config, day, output)
        except Exception as exc:
            # Exceptions may include remote URLs; keep credentials out of public output.
            result = {
                "checked_at": dt.datetime.now(TZ).isoformat(),
                "status": "check_failed",
                "published": False,
                "reason": f"检查失败（{type(exc).__name__}），请查看私有任务日志。",
            }
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        key = hashlib.sha256(
            json.dumps(
                {
                    "week": str(last_cycle_end(day)),
                    "period": result.get("period"),
                    "contract": config["contract"],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:16]
        atomic(output / (key + ".json"), result)
        atomic(output / "status.json", result)
        if result["published"]:
            atomic(output / "latest.json", result)
        render(output, result)
        return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument(
        "--as-of", type=dt.date.fromisoformat, default=dt.datetime.now(TZ).date()
    )
    a = p.parse_args()
    r = execute(a.config, a.output, a.as_of)
    print(
        json.dumps(
            {k: r.get(k) for k in ("status", "published", "reason")}, ensure_ascii=False
        )
        if r
        else "Another check is running"
    )
