"""A metric refresh must bind complete, read-only sources to one version receipt."""
import copy
from types import SimpleNamespace

import pytest

from ra_triage_dashboard.app import version_metric_source as module
from ra_triage_dashboard.app import rd_results
from ra_triage_dashboard.app.version_metrics import is_trail_snapshot


def sources(monkeypatch):
    rows = [dict(issue_id=f"cn{i}", state="published", is_sample=True, is_low=i == 1,
                 model_label="正确触发", model_confidence=.8) for i in range(1, 23)]
    dataset = dict(id="release-20261030-odd2", revision=1, run_id="run")
    monkeypatch.setattr(module, "inventory_rows", lambda *args: (dataset, rows))
    db = SimpleNamespace(project_issue_exclusions=lambda ids: {})
    calls = []
    def fetch(ids):
        calls.append(ids)
        return [dict(issue_id=iid, ra_stuck_auto_result="正确触发", ra_review_result_new="成功",
                     ra_rd_review_result="误触发", ra_stuck_auto_result_info=dict(daily_auto_triage=dict(
                         model_result="正确触发", model_confidence=.8, prediction_source="model"))) for iid in ids]
    return db, SimpleNamespace(fetch=fetch), calls, rows, dataset


def test_complete_read_keeps_lane_observation_and_recorded_routing(monkeypatch):
    db, client, calls, rows, dataset = sources(monkeypatch)
    result = module.source(db, "20261030", client)
    assert [len(ids) for ids in calls] == [20, 2]
    assert result["registry_revision"] == dataset["revision"]
    assert is_trail_snapshot(result)
    assert result["provenance"]["requested_total"] == result["provenance"]["returned_total"] == 22
    first = result["rows"][0]
    assert first["references"]["te"] == dict(observed=True, value="成功")
    assert first["references"]["te_prime"] == dict(observed=False, value=None)
    assert first["routed_to_human"] is True
    assert result["rows"][1]["routed_to_human"] is False
    assert first["human_reference"] == "rd" and first["human_label"] == "误触发"


@pytest.mark.parametrize("failure", ["partial", "duplicate", "prediction", "rule", "metadata"])
def test_incomplete_or_conflicting_source_cannot_be_published(monkeypatch, failure):
    db, client, _, _, _ = sources(monkeypatch)
    original = client.fetch
    def fetch(ids):
        rows = original(ids)
        if failure == "partial": return rows[:-1]
        if failure == "duplicate": return [rows[0]] * len(ids)
        if failure == "prediction": rows[0]["ra_stuck_auto_result"] = "误触发"
        daily = rows[0]["ra_stuck_auto_result_info"]["daily_auto_triage"]
        if failure == "rule": daily["prediction_source"] = "pre_rule"
        if failure == "metadata": daily["model_result"] = "误触发"
        return rows
    client.fetch = fetch
    with pytest.raises(ValueError): module.source(db, "20261030", client)


def test_membership_change_during_read_rejects_receipt(monkeypatch):
    db, client, _, rows, dataset = sources(monkeypatch)
    before = copy.deepcopy(rows)
    count = [0]
    def inventory(*args):
        count[0] += 1
        return dataset, before if count[0] == 1 else rows[:-1]
    monkeypatch.setattr(module, "inventory_rows", inventory)
    with pytest.raises(ValueError, match="membership changed"):
        module.source(db, "20261030", client)


def test_query_wrapper_projects_every_lane_and_spaces_reads(monkeypatch):
    calls = []
    row = dict(issue_id="cn1", ra_stuck_auto_result="成功", ra_stuck_auto_result_info={},
               **dict.fromkeys(module.FIELDS.values()))

    def send(url, body, timeout):
        calls.append((url, body))
        return SimpleNamespace(json=lambda: {"code": 0, "msg": "success", "data": {"cn1": row}})

    delegate = SimpleNamespace(client=SimpleNamespace(send_request=send))
    monkeypatch.setattr(rd_results, "adapter", lambda root: delegate)
    clock = [20.]
    monkeypatch.setattr(module, "_last_query", 0.)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    client = module.read_only_client("unused")
    assert client.fetch(["cn1"]) == [row]
    assert client.fetch(["cn1"]) == [row]
    assert clock[0] == 21.
    assert all(url.endswith("/query_by_issue_id_list/") and set(body["select_field_list"]) == set(row)
               for url, body in calls)
    del row["ra_review_result_arbitrated"]
    with pytest.raises(ValueError, match="Incomplete metric fields"):
        client.fetch(["cn1"])
