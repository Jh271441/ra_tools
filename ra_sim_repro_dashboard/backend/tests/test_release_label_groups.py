from types import SimpleNamespace
from urllib.parse import unquote
import json

from app.services import release_label_groups as groups
from app.services import ordinary_evaluation, auto_triage_metrics
from app.services.release_metrics import GOOD_RESULTS


def decode_filters(url):
    path, query = url.split("?", 1)
    assert path.endswith("/#/issue/pool")
    params = dict(pair.split("=", 1) for pair in query.split("&"))
    assert params["view_id~d"] == "2410"
    attrs = {}
    for key, raw in params.items():
        if key.startswith("query_attrs.$"):
            field, op, wire, kind = unquote(raw).split("|")
            wire = unquote(wire)
            attrs[field] = (op, json.loads(wire) if kind == "o" else [
                int(item) if kind == "a_d" else unquote(item) for item in wire.split(",")])
    return attrs, json.loads(unquote(params.get("query_filters~o", "[]")))


def test_native_trail_queries_cover_all_platform_members(monkeypatch):
    base = "ra_repro_full_20261109_20261106"
    release = "gen4-release-20261106"
    definitions = {
        "1": ("release", "positive_auto", "AutoTrigger"),
        "2": ("release", "negative_auto", "AutoTrigger"),
        "3": ("release", "positive_manual", "ManualTrigger"),
    }
    scenes = [{"scenario_id": sid, "scenario_labels": [base, *[
        base + "_" + (release if suffix == "release" else suffix) for suffix in labels]]}
        for sid, labels in definitions.items()]
    common = [{"attr_id": "version", "operator": "like", "val": [release]},
              {"attr_id": "issue_time", "operator": "range", "val": {"min": 100, "max": 219}}]
    monkeypatch.setattr(groups, "fetch_scenarios", lambda _: scenes + scenes[:1])
    monkeypatch.setattr(ordinary_evaluation, "read", lambda *_: None)
    monkeypatch.setattr(auto_triage_metrics, "_snapshot", lambda *_: SimpleNamespace(payload={
        "period": {"release": release, "scenario_creation_label": base}, "population_complete": True,
        "query_attrs": common, "scenarios": scenes[:1]}))
    result = groups.for_release(None, release)
    assert result["total_scenarios"] == 3
    assert [r["count"] for r in result["rows"]] == [3, 3, 1, 1, 1, 2, 1]
    positive = sorted(GOOD_RESULTS)
    for row, triggers, results in zip(result["rows"], [[2, 3], [2, 3], [2], [2], [3], [2], [3]],
                                      [positive + ["误触发"]] * 2 + [positive, ["误触发"], positive, positive + ["误触发"], positive]):
        attrs, nested = decode_filters(row["trail_url"])
        assert attrs == {"version": ("like", [release]), "issue_time": ("range", {"min": 100, "max": 219}),
                         "ra_type": ("in", triggers), "ra_merge_result": ("in", results)}
        assert nested == ([{"filter_operator": "OR", "query_attrs": [
            {"attr_id":"ra_type", "operator":"in", "val":[2]},
            {"attr_id":"ra_merge_result", "operator":"in", "val":positive}]}] if len(triggers) == 2 else [])


def test_ordinary_revision_takes_priority_and_uses_physical_groups(monkeypatch):
    release = "gen4-release-20261030"
    root = "ra_repro_physical_20261030"
    tag = root + "_" + release
    auto = {"scenario_id":"1", "labels":[root, tag, root + "_source_auto", "other_gen4-release-20261016"]}
    manual = {"scenario_id":"2", "labels":[root, tag, root + "_source_manual"]}
    def platform(query):
        assert query == {"scenario_query_labels":[tag]}
        return [auto, manual]
    monkeypatch.setattr(groups, "fetch_scenarios", platform)
    monkeypatch.setattr(ordinary_evaluation, "read", lambda *_: {"payload":{"scenarios":[auto, auto]}})
    data = groups.for_release(None, release)
    assert (data["total_scenarios"], data["frozen_count"]) == (2, 1)
    assert [row["group"] for row in data["rows"]] == ["full", "release", "source_auto", "source_manual"]
    assert decode_filters(data["rows"][-1]["trail_url"]) == ({"version":("like",[release]), "ra_type":("in",[3])}, [])


def test_historical_release_unions_batches_and_excludes_other_release(tmp_path, monkeypatch):
    release = "gen4-release-20260821"
    source = tmp_path / "manifest.csv"
    import csv
    with source.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["release", "upload_status", "scenario_labels"])
        for root, status, version in [("a", "uploaded", release), ("b", "existing", release),
                                      ("c", "failed", release), ("d", "uploaded", "gen4-release-20260828")]:
            writer.writerow([version, status, json.dumps([root+"_"+version])])
    db = SimpleNamespace(get=lambda *_: SimpleNamespace(metadata_json={"source_manifest":str(source)}))
    monkeypatch.setattr(ordinary_evaluation, "read", lambda *_: None)
    monkeypatch.setattr(auto_triage_metrics, "_snapshot", lambda *_: None)
    def platform(query):
        tag, = query["scenario_query_labels"]
        assert tag in {"a_"+release, "b_"+release}
        return [{"scenario_id":"1", "labels":[tag, tag[0]]}]
    monkeypatch.setattr(groups, "fetch_scenarios", platform)
    value = groups.for_release(db, release)
    assert value["total_scenarios"] == 1
    assert {r["label"] for r in value["rows"]} == {"a","b","a_"+release,"b_"+release}
    assert groups.for_release(SimpleNamespace(get=lambda *_: None), release)["rows"] == []


def test_historical_manifest_without_tags_uses_selected_release_ids(tmp_path, monkeypatch):
    release = "gen4-release-20260612"
    path = tmp_path / "shared_manifest.csv"
    path.write_text("release,upload_status,scenario_id\n" + release + ",uploaded,17.0\n" +
                    release + ",existing,21\nother,uploaded,29\n")
    monkeypatch.setattr(groups, "trail_credentials", lambda **_: ("app", "token"))
    def by_id(url, body, *args):
        assert body == {"id":"17,21"}
        return [{"id":17, "labels":["renamed_"+release]}, {"id":21, "labels":["second_"+release]}]
    monkeypatch.setattr(groups, "complete_query", by_id)
    assert groups.historical_namespaces({"source_manifest":str(path)}, release) == {"renamed","second"}
