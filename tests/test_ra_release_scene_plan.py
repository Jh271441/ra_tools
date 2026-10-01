import json
import pytest
from scripts.ra_release_scene_plan import read_source, read_plan


def test_numeric_looking_trip_id_retains_underscores(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            [
                {
                    "issue_id": "cn1",
                    "trip_id": "10336_20260923_230336",
                    "issue_time": 1790175830910,
                }
            ]
        )
    )
    original = read_source(source)
    assert original.iloc[0]["trip_id"] == "10336_20260923_230336"
    original["validation_error"] = ""
    path = tmp_path / "plan.csv"
    original.to_csv(path, index=False)
    assert read_plan(path, original).iloc[0]["trip_id"] == "10336_20260923_230336"


def test_coerced_numeric_trip_id_never_uploaded(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps([{"issue_id": "cn1", "trip_id": "10336_20260923_230336"}])
    )
    original = read_source(source)
    changed = original.copy()
    changed["trip_id"] = "1033620260923230336"
    changed["validation_error"] = ""
    path = tmp_path / "plan.csv"
    changed.to_csv(path, index=False)
    with pytest.raises(ValueError, match="identity"):
        read_plan(path, original)


def test_nonstring_source_trip_id_rejected(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps([{"issue_id": "cn1", "trip_id": 1033620260923230336}]))
    with pytest.raises(ValueError, match="original string"):
        read_source(source)
