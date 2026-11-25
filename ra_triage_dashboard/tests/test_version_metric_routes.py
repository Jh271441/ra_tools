"""HTTP reads never call Trail; explicit refresh requires the existing write role."""
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException

from ra_triage_dashboard.app.routers import version_metrics as routes
from ra_triage_dashboard.app.version_metric_store import VersionMetricStore
from ra_triage_dashboard.tests.test_rd_results import AsgiClient
from ra_triage_dashboard.tests.test_version_metrics import fixture, trail_fixture


def client_for(monkeypatch, tmp_path):
    store = VersionMetricStore(tmp_path)
    store.publish("20261030", trail_fixture())
    monkeypatch.setattr(routes, "store", lambda: store)
    monkeypatch.setattr(routes, "catalog", lambda: [dict(id="release-20261030-odd2", release_family="20261030", revision=1, published_samples=7)])
    monkeypatch.setattr(routes, "read_only_client", lambda *args: (_ for _ in ()).throw(AssertionError("Unexpected remote read")))
    app = FastAPI()
    app.include_router(routes.router)
    return AsgiClient(app), store


def test_read_is_snapshot_only_and_validates_scope(monkeypatch, tmp_path):
    client, _ = client_for(monkeypatch, tmp_path)
    response = client.get("/api/version-metrics?families=20261030")
    assert response.status_code == 200
    assert response.json()["items"][0]["metrics"]["chain"]["total"] == 4
    assert response.json()["items"][0]["current_sample_total"] == 7
    for query in ("reference=merge", "families=20261023", "families=20261030,20261030", "threshold=0.89", "page_size=200"):
        assert client.get("/api/version-metrics?"+query).status_code == 400
    assert client.get("/api/version-metrics?page=0").status_code == 422


def test_old_report_is_not_served_as_current_trail_metrics(monkeypatch, tmp_path):
    client, store = client_for(monkeypatch, tmp_path)
    report = store.publish("20261030", fixture())
    row = client.get("/api/version-metrics?families=20261030").json()["items"][0]
    assert row == dict(family="20261030", status="unavailable", reason="trail_snapshot_required", current_sample_total=7)
    assert client.get("/api/version-metrics/20261030?snapshot="+report["id"]).status_code == 400


def test_refresh_role_marker_and_unknown_body_cannot_start_job(monkeypatch, tmp_path):
    client, store = client_for(monkeypatch, tmp_path)
    monkeypatch.setattr(routes, "has_same_origin_mutation_marker", lambda req: req.headers.get("X-RA-Triage-Request") == "dashboard")
    def denied(request): raise HTTPException(403, "Writer required")
    monkeypatch.setattr(routes, "_writer_identity", denied)
    body = dict(families=["20261030"])
    assert client.post("/api/version-metrics/refresh", json=body).status_code == 403
    monkeypatch.setattr(routes, "_writer_identity", lambda req: SimpleNamespace(username="writer"))
    assert client.post("/api/version-metrics/refresh", json=body).status_code == 403
    headers = {"X-RA-Triage-Request": "dashboard"}
    assert client.post("/api/version-metrics/refresh", json=dict(body, rows=[]), headers=headers).status_code == 422
    assert store.job()["status"] == "idle"
    started = []
    monkeypatch.setattr(store, "refresh", lambda families, factory: started.append(families) or dict(status="running"))
    assert client.post("/api/version-metrics/refresh", json=body, headers=headers).status_code == 202
    assert started == [["20261030"]]
