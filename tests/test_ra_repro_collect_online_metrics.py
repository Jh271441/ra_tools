from pathlib import Path
import sys

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ra_repro_collect_online_metrics import (
    build_query_attrs,
    summarize_release,
)


def test_build_query_attrs_matches_final_trail_contract():
  attrs = build_query_attrs("gen4-release-20260821")
  by_id = {item["attr_id"]: item for item in attrs}

  assert by_id["trip_category"]["val"] == [0]
  assert by_id["abnormal_behavior"]["val"] == [292, 297, 299, 393, 391]
  assert by_id["ra_type"]["val"] == [2, 3]
  assert by_id["trip_odd"]["val"] == ["ODD2"]
  assert by_id["is_deleted"]["val"] == [0]
  assert by_id["platform"]["val"] == [7, 8]


def test_summarize_release_reproduces_shuyi_precision_recall_semantics():
  issues = pd.DataFrame([
      {"issue_id": "a", "ra_type": 2, "ra_merge_result": "成功"},
      {"issue_id": "b", "ra_type": 2, "ra_merge_result": "失败"},
      {"issue_id": "c", "ra_type": 2, "ra_merge_result": "无需协助"},
      {"issue_id": "d", "ra_type": 2, "ra_merge_result": "限制使用"},
      {"issue_id": "e", "ra_type": 2, "ra_merge_result": "误触发"},
      {"issue_id": "f", "ra_type": 2, "ra_merge_result": "待确认"},
      {"issue_id": "g", "ra_type": 2, "ra_merge_result": "out_of_scope"},
      {"issue_id": "h", "ra_type": 2, "ra_merge_result": None},
      {"issue_id": "i", "ra_type": 3, "ra_merge_result": "成功"},
      {"issue_id": "j", "ra_type": 3, "ra_merge_result": "误触发"},
      # Duplicate rows must follow Shuyi COUNT(DISTINCT issue_id).
      {"issue_id": "a", "ra_type": 2, "ra_merge_result": "成功"},
  ])

  result = summarize_release(issues, "release")

  assert result["raw_rows"] == 11
  assert result["unique_issue_ids"] == 10
  assert result["precision_numerator"] == 4
  assert result["precision_denominator"] == 6
  assert result["precision_auto_fp"] == 2
  assert result["online_precision"] == pytest.approx(4 / 6)
  assert result["recall_numerator"] == 5
  assert result["recall_denominator"] == 6
  assert result["recall_manual_fn"] == 1
  assert result["online_recall"] == pytest.approx(5 / 6)
  assert result["auto_recall_only_count"] == 1


def test_summarize_release_rejects_missing_authoritative_columns():
  with pytest.raises(ValueError, match="missing columns"):
    summarize_release(pd.DataFrame({"issue_id": ["a"]}), "release")
