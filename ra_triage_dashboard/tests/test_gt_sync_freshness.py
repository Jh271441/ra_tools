from datetime import datetime, timedelta, timezone

import pytest

from ra_triage_dashboard.app.gt_sync import gt_refresh_due


NOW = datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)


def snapshot(age=0, **overrides):
    return {"status": "ready", "last_checked_at": (NOW - timedelta(seconds=age)).isoformat(),
            "last_applied_at": "2026-09-01T00:00:00+00:00", "source_row_count": 0,
            **overrides}


def due(items, status="ready"):
    return gt_refresh_due({"status": status, "baselines": items}, interval_seconds=1800, now=NOW)


@pytest.mark.parametrize("age,expected", [(0, False), (1799, False), (1800, True), (86400, True), (-1, True)])
def test_ready_snapshot_expires(age, expected):
    assert due([snapshot(age)]) is expected


@pytest.mark.parametrize("stamp", [None, "", "invalid", "2026-10-27T03:00:00"])
def test_unknown_check_time_is_due(stamp):
    assert due([snapshot(last_checked_at=stamp)])


def test_cst_and_utc_are_equivalent():
    assert not due([snapshot(last_checked_at="2026-10-27T11:00:00+08:00")])
    assert not due([snapshot(last_checked_at="2026-10-27T03:00:00Z")])


def test_sparse_zero_and_unchanged_success_are_fresh():
    assert not due([snapshot()])  # Last apply is old, but successful check is fresh.


def test_any_expired_scope_requires_refresh():
    assert due([snapshot(), snapshot(1800)])
    assert due([snapshot(), snapshot(status="failed")])


@pytest.mark.parametrize("status", ["failed", "not_started", "unavailable"])
def test_unsuccessful_sync_retries_at_next_worker_tick(status):
    assert due([snapshot()], status=status)


def test_empty_configuration_and_running_sync():
    assert due([])
    assert not due([snapshot(86400)], status="running")


def test_periodic_worker_uses_check_time_policy(monkeypatch):
    from ra_triage_dashboard.app import main
    from ra_triage_dashboard.app.support import gt_sync

    monkeypatch.setattr(gt_sync, "gt_sync_status", lambda: {
        "status": "ready", "baselines": [snapshot(last_checked_at="2000-01-01T00:00:00Z")]
    })
    assert main._gt_sync_needs_remote_refresh()
    monkeypatch.setattr(gt_sync, "gt_sync_status", lambda: {
        "status": "ready", "baselines": [snapshot(last_checked_at=datetime.now(timezone.utc).isoformat())]
    })
    assert not main._gt_sync_needs_remote_refresh()
