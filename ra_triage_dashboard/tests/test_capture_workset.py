import json
import pytest
from ra_triage_dashboard.app.baseline import load_baseline_entry


def test_workset_retains_unlabeled_members(tmp_path):
    path = tmp_path / "workset.json"
    path.write_text(json.dumps({"schema_version": "capture-workset-v1", "expected_count": 2, "rows": [{"issue_id": "cn1", "source": {"ra_result": "成功"}}, {"issue_id": "cn2", "gt_label": "误触发"}]}))
    result = load_baseline_entry(loader="capture_workset", path=path)
    assert len(result.rows) == 2
    assert result.rows[0]["gt_label"] == ""
    assert result.rows[1]["gt_label"] == "误触发"


@pytest.mark.parametrize("rows,count", [([{"issue_id": "cn1"}], 2), ([{"issue_id": "cn1"}, {"issue_id": "cn1"}], 2), ([{"issue_id": "cn1", "gt_label": "成功"}], 1)])
def test_workset_rejects_invalid_membership_or_gt(tmp_path, rows, count):
    path = tmp_path / "workset.json"
    path.write_text(json.dumps({"schema_version": "capture-workset-v1", "expected_count": count, "rows": rows}))
    with pytest.raises(ValueError):
        load_baseline_entry(loader="capture_workset", path=path)


@pytest.mark.parametrize("baseline_id,versions,expected", [
    ("review-2026-10-19", ["1.gen4-release-20261009.594"] * 2, "1009 2026-10-19"),
    ("review-2026-11-01", ["1.gen4-release-20261030.1"], "1030 2026-11-01"),
    ("review-2026-10-19", ["1.gen4-release-20261009.594", "1.gen4-release-20260821.2"], "0821 / 1009 2026-10-19"),
    ("review-2026-10-19", ["1.gen4-release-20261009.594", ""], "Original label"),
    ("0821-review-extra", ["1.gen4-release-20261009.594"], "Original label"),
    ("review-2026-10-19", [], "Original label"),
])
def test_daily_names_follow_all_member_versions(baseline_id, versions, expected):
    from ra_triage_dashboard.app.baseline import daily_baseline_display_label
    rows = [{"extra": {"baseline": {"version": version}}} for version in versions]
    before = json.dumps(rows)
    assert daily_baseline_display_label(baseline_id, "Original label", rows) == expected
    assert json.dumps(rows) == before
