from types import SimpleNamespace

from ra_triage_dashboard.app import version_metric_cron as cron
from ra_triage_dashboard.app.version_metric_store import VersionMetricStore
from ra_triage_dashboard.app.version_metrics import digest
from ra_triage_dashboard.tests.test_version_metrics import trail_fixture


def test_cron_follows_new_versions_and_external_changes_without_duplicate_snapshots(tmp_path, monkeypatch):
    store = VersionMetricStore(tmp_path)
    family = "20260102"
    catalog = [dict(release_family=family, revision=1)]
    db = SimpleNamespace(list_version_datasets=lambda: catalog)
    receipt = trail_fixture()
    monkeypatch.setattr(cron, "read_only_client", lambda root: object())
    calls = []

    def source(db, release, client):
        calls.append(release)
        return receipt

    monkeypatch.setattr(cron, "source", source)
    cron.reconcile(store, db, "")
    assert not calls
    store.root.mkdir()
    tick = store.root / "cron.tick"
    tick.touch()
    cron.reconcile(store, db, "")
    cron.reconcile(store, db, "")
    assert calls == [family]
    tick.touch()
    cron.reconcile(store, db, "")
    assert calls == [family, family] and len(store.history(family)) == 1
    receipt["rows"][0]["references"]["te"]["value"] = "无需协助"
    receipt["provenance"]["source_sha256"] = digest(receipt["rows"])
    second = "20260109"
    catalog.append(dict(release_family=second, revision=1))
    tick.touch()
    cron.reconcile(store, db, "")
    assert calls[-2:] == [second, family]
    assert len(store.history(family)) == 2 and len(store.history(second)) == 1
    receipt["provenance"]["source_sha256"] = "incomplete"
    tick.touch()
    cron.reconcile(store, db, "")
    assert len(store.history(second)) == 1
    assert store.job()["status"] == "failed"
