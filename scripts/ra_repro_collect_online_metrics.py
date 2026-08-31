#!/usr/bin/env python3
"""Collect Shuyi-aligned online RA precision/recall populations from Trail."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ra_api.issue_api import TrailInterface
from scripts.ra_repro_launch_binary_backtest import TEMPLATE_JOBS


DEFAULT_ABNORMAL_BEHAVIOR_IDS = (292, 297, 299, 393, 391)
GOOD_RESULTS = frozenset(("成功", "失败", "无需协助", "限制使用"))
PRECISION_EXCLUDED_RESULTS = frozenset(("out_of_scope", "未接起", "未填写"))
RECALL_EXCLUDED_RESULTS = frozenset(
    ("误触发", "out_of_scope", "未接起", "未填写"))


def build_query_attrs(
    release: str,
    abnormal_behavior_ids: Sequence[int] = DEFAULT_ABNORMAL_BEHAVIOR_IDS,
) -> list[dict[str, Any]]:
  return [{
      "attr_id": "version",
      "operator": "like",
      "val": [release],
  }, {
      "attr_id": "trip_category",
      "operator": "in",
      "val": [0],
  }, {
      "attr_id": "abnormal_behavior",
      "operator": "in",
      "val": [int(value) for value in abnormal_behavior_ids],
  }, {
      "attr_id": "ra_type",
      "operator": "in",
      "val": [2, 3],
  }, {
      "attr_id": "trip_odd",
      "operator": "in",
      "val": ["ODD2"],
  }, {
      "attr_id": "is_deleted",
      "operator": "in",
      "val": [0],
  }, {
      "attr_id": "platform",
      "operator": "in",
      "val": [7, 8],
  }]


def _ratio(numerator: int, denominator: int) -> float | None:
  return numerator / denominator if denominator else None


def summarize_release(issues: pd.DataFrame, release: str) -> dict[str, Any]:
  required = {"issue_id", "ra_type", "ra_merge_result"}
  missing = required - set(issues.columns)
  if missing:
    raise ValueError(
        f"Trail response for {release} is missing columns: {sorted(missing)}")
  raw_rows = len(issues)
  work = issues.drop_duplicates(subset=["issue_id"], keep="first").copy()
  work["ra_type"] = pd.to_numeric(work["ra_type"], errors="coerce")
  result = work["ra_merge_result"].astype("string")
  auto = work["ra_type"].eq(2)
  manual = work["ra_type"].eq(3)
  has_result = result.notna()
  precision_eligible = has_result & ~result.isin(PRECISION_EXCLUDED_RESULTS)
  recall_eligible = has_result & ~result.isin(RECALL_EXCLUDED_RESULTS)

  precision_auto_tp = int((auto & result.isin(GOOD_RESULTS)).sum())
  precision_denominator = int((auto & precision_eligible).sum())
  precision_auto_fp = precision_denominator - precision_auto_tp
  recall_auto_tp = int((auto & recall_eligible).sum())
  recall_denominator = int(((auto | manual) & recall_eligible).sum())
  recall_manual_fn = recall_denominator - recall_auto_tp
  result_counts = {
      str(trigger_type): {
          ("<null>" if pd.isna(value) else str(value)): int(count)
          for value, count in group["ra_merge_result"].value_counts(
              dropna=False).items()
      }
      for trigger_type, group in work.groupby("ra_type", dropna=False)
  }
  return {
      "release": release,
      "raw_rows": raw_rows,
      "unique_issue_ids": int(work["issue_id"].nunique()),
      "duplicate_issue_rows": raw_rows - len(work),
      "auto_trigger_total": int(auto.sum()),
      "manual_trigger_total": int(manual.sum()),
      "precision_auto_tp": precision_auto_tp,
      "precision_auto_fp": precision_auto_fp,
      "precision_numerator": precision_auto_tp,
      "precision_denominator": precision_denominator,
      "online_precision": _ratio(
          precision_auto_tp, precision_denominator),
      "recall_auto_tp": recall_auto_tp,
      "recall_manual_fn": recall_manual_fn,
      "recall_numerator": recall_auto_tp,
      "recall_denominator": recall_denominator,
      "online_recall": _ratio(recall_auto_tp, recall_denominator),
      # Backward-compatible population aliases used by the dashboard.  The
      # explicit precision/recall fields above remain authoritative when the
      # two Shuyi numerators differ (for example 待确认/其它).
      "auto_trigger_tp": precision_auto_tp,
      "auto_trigger_fp": precision_auto_fp,
      "manual_trigger_fn": recall_manual_fn,
      "auto_recall_only_count": recall_auto_tp - precision_auto_tp,
      "result_counts_by_ra_type": result_counts,
      "data_source": "trail_view_2410_shuyi_contract",
  }


def collect(
    releases: Sequence[str],
    output_path: Path,
    csv_output_path: Path | None,
    view_id: int,
    page_size: int,
    abnormal_behavior_ids: Sequence[int],
    base_url: str | None,
) -> dict[str, Any]:
  trail = TrailInterface(base_url=base_url)
  per_release = {}
  for index, release in enumerate(releases, start=1):
    print(
        f"[{index}/{len(releases)}] querying {release}",
        file=sys.stderr,
        flush=True,
    )
    attrs = build_query_attrs(release, abnormal_behavior_ids)
    issues = trail.query_issue_poll(view_id, attrs, size=page_size)
    if issues.empty:
      raise RuntimeError(
          f"Trail returned no rows for {release}; refusing to publish a "
          "possibly empty result")
    summary = summarize_release(issues, release)
    per_release[release] = summary
    print(
        f"  issues={summary['unique_issue_ids']} "
        f"P={summary['online_precision']:.4%} "
        f"R={summary['online_recall']:.4%}",
        file=sys.stderr,
        flush=True,
    )

  payload = {
      "generated_at": datetime.now(timezone.utc).isoformat(),
      "view_id": int(view_id),
      "query_contract": {
          "trip_category": [0],
          "abnormal_behavior": [int(value) for value in abnormal_behavior_ids],
          "ra_type": [2, 3],
          "trip_odd": ["ODD2"],
          "is_deleted": [0],
          "platform": [7, 8],
          "distinct_key": "issue_id",
      },
      "formulas": {
          "precision_good_results": sorted(GOOD_RESULTS),
          "precision_excluded_results": sorted(PRECISION_EXCLUDED_RESULTS),
          "recall_excluded_results": sorted(RECALL_EXCLUDED_RESULTS),
      },
      "releases": per_release,
  }
  output_path.parent.mkdir(parents=True, exist_ok=True)
  temporary = output_path.with_suffix(output_path.suffix + ".tmp")
  temporary.write_text(
      json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )
  temporary.replace(output_path)
  if csv_output_path is not None:
    csv_output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_tmp = csv_output_path.with_suffix(csv_output_path.suffix + ".tmp")
    pd.DataFrame(per_release.values()).drop(
        columns=["result_counts_by_ra_type"]).to_csv(csv_tmp, index=False)
    csv_tmp.replace(csv_output_path)
  return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("--release", action="append", dest="releases")
  parser.add_argument("--view-id", type=int, default=2410)
  parser.add_argument("--page-size", type=int, default=500)
  parser.add_argument(
      "--abnormal-behavior-id", action="append", type=int,
      dest="abnormal_behavior_ids")
  parser.add_argument("--base-url")
  parser.add_argument(
      "--output", type=Path,
      default=Path("reports/ra_online_metrics_20260831.json"))
  parser.add_argument(
      "--csv-output", type=Path,
      default=Path("reports/ra_online_metrics_20260831.csv"))
  return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
  args = _parse_args(argv)
  releases = args.releases or list(TEMPLATE_JOBS)
  abnormal_behavior_ids = (
      args.abnormal_behavior_ids or list(DEFAULT_ABNORMAL_BEHAVIOR_IDS))
  payload = collect(
      releases=releases,
      output_path=args.output,
      csv_output_path=args.csv_output,
      view_id=args.view_id,
      page_size=args.page_size,
      abnormal_behavior_ids=abnormal_behavior_ids,
      base_url=args.base_url,
  )
  print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
