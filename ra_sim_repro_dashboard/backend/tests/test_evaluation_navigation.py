from copy import deepcopy
import pytest
from app.api import evaluation_routes as routes
from app.models import ReleaseIssueSnapshot, Version
from app.services import evaluation_pipeline as p
from test_auto_triage_metrics import db, prepared, RELEASE
from test_evaluation_pipeline import seed


def test_navigation_empty_and_new_snapshot_invalidates(db, monkeypatch):
    monkeypatch.setattr(routes, "load_versions_config", lambda: {"versions": {}})
    assert routes.versions(db)["versions"] == []
    db.add(ReleaseIssueSnapshot(release=RELEASE, period_hash="one", payload={}))
    db.commit()
    result = routes.versions(db)
    assert result["current_version"] == RELEASE
    assert result["versions"][0]["metadata_json"]["release_date"] == "2026-10-16"
    assert result["versions"][0]["metadata_json"]["platform_gen"] == "GEN4_PT"


def test_navigation_deduplicates_without_loading_snapshots_or_computing_kpis(db, monkeypatch):
    other = "gen4-release-20261106"
    for release, period in [(RELEASE, "one"), (RELEASE, "two"), (other, "three")]:
        db.add(
            ReleaseIssueSnapshot(
                release=release, period_hash=period, payload={"not": "a metric snapshot"}
            )
        )
    db.add(
        Version(
            version_key=RELEASE,
            label="saved label",
            metadata_json={
                "version_category": "release版本",
                "big_version": "1.0",
                "test_version": "stable",
                "_private_blob": "hidden",
            },
        )
    )
    db.commit()
    monkeypatch.setattr(
        routes, "load_versions_config", lambda: {"versions": {RELEASE: {"platform_gen": "GEN4_PT"}}}
    )
    monkeypatch.setattr(p.at, "_base", lambda *a: pytest.fail("navigation audited a batch"))
    monkeypatch.setattr(
        p.at, "_snapshot", lambda *a: pytest.fail("navigation loaded snapshot JSON")
    )
    result = routes.versions(db)
    assert [v["version_key"] for v in result["versions"]] == [RELEASE, other]
    assert [v["is_current"] for v in result["versions"]] == [False, True]
    assert result["versions"][0]["label"] == "saved label"
    metadata = result["versions"][0]["metadata_json"]
    assert metadata["version_category"] == "release版本" and metadata["test_version"] == "stable"
    assert "_private_blob" not in metadata
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("stale", [False, True])
def test_comparison_keeps_identical_audited_revision_without_board_details(
    prepared, monkeypatch, stale
):
    db, snapshot, _, _, revision = seed(prepared, monkeypatch)
    if stale:
        changed = deepcopy(snapshot.payload)
        changed["issues"][0]["issue_topic"] = "changed source"
        snapshot.payload = changed
        db.commit()
    full = p.board(db, RELEASE)
    monkeypatch.setattr(
        p, "public_executions", lambda *a: pytest.fail("comparison loaded execution histories")
    )
    original_rows = p.rows

    def rows(db, prefix):
        assert prefix != "evstart:"
        return original_rows(db, prefix)

    monkeypatch.setattr(p, "rows", rows)
    compact = p.board(db, RELEASE, comparison_only=True)
    assert compact == {k: full[k] for k in ("revision", "stale")}
    monkeypatch.setattr(
        p.at, "versions", lambda *a: pytest.fail("comparison audited unused navigation jobs")
    )
    compared = p.comparison(db)["versions"]
    assert compared == [{"release": RELEASE, **compact}]


def test_metrics_board_keeps_audits_and_navigation_without_ordinary_catalogue(
    prepared, monkeypatch
):
    db, snapshot, _, _, revision = seed(prepared, monkeypatch)
    ctx = routes.Context(**revision["context"])
    full = routes.board(ctx=ctx, view="full", db=db)
    monkeypatch.setattr(
        p.at, "versions", lambda *_: pytest.fail("metric page audited ordinary navigation jobs")
    )
    metrics = routes.board(ctx=ctx, view="metrics", db=db)
    assert metrics["versions"] == [
        {"release": RELEASE, "source_count": len(snapshot.payload["issues"])}
    ]
    assert {k: v for k, v in metrics.items() if k != "versions"} == {
        k: v for k, v in full.items() if k != "versions"
    }
    # The slim catalogue must not weaken staleness detection or cache invalidation.
    changed = deepcopy(snapshot.payload)
    changed["issues"][0]["trip_id"] = "changed physical input"
    db.add(ReleaseIssueSnapshot(release=RELEASE, period_hash="new-observation", payload=changed))
    db.commit()
    assert routes.board(ctx=ctx, view="metrics", db=db)["stale"]


def test_metric_navigation_uses_latest_source_counts_without_loading_json(db):
    other = "gen4-release-20261106"
    for release, period, count in [(RELEASE, "one", 1), (other, "two", 2), (RELEASE, "three", 3)]:
        db.add(
            ReleaseIssueSnapshot(
                release=release, period_hash=period, payload={"issues": [{}] * count}
            )
        )
    db.commit()
    db.expunge_all()
    from sqlalchemy import event

    loaded = []

    def track_load(session, instance):
        loaded.append(instance)

    event.listen(db, "loaded_as_persistent", track_load)
    try:
        assert p.navigation_versions(db) == [
            {"release": other, "source_count": 2},
            {"release": RELEASE, "source_count": 3},
        ]
        assert not loaded
    finally:
        event.remove(db, "loaded_as_persistent", track_load)
