from ra_triage_dashboard.app.support.baselines import enrich_baseline_lifecycle


def _registered(count: int) -> dict:
    return {
        "id": "dataset",
        "count": count,
        "registration_status": "registered",
        "membership": {
            "status": "registered",
            "registered_count": count,
            "expected_count": count,
            "frozen": True,
        },
    }


def test_complete_requires_declared_verification_and_all_media() -> None:
    result = enrich_baseline_lifecycle(
        _registered(100),
        {
            "lifecycle_enabled": True,
            "declared_status": "complete",
            "published_issues": 100,
            "verified_issues": 100,
            "bev_indexed_issues": 100,
            "video_indexed_issues": 100,
            "camera_indexed_issues": 100,
            "failure_count": 0,
        },
    )
    assert result["status"] == "complete"
    assert result["remaining_media"] == 0


def test_collecting_remains_selectable_and_reports_remaining() -> None:
    result = enrich_baseline_lifecycle(
        _registered(1242),
        {
            "lifecycle_enabled": True,
            "declared_status": "capturing",
            "published_issues": 1158,
            "verified_issues": 0,
            "camera_indexed_issues": 1242,
            "failure_count": 0,
        },
    )
    assert result["registration_status"] == "registered"
    assert result["status"] == "collecting"
    assert result["remaining_media"] == 84


def test_full_coverage_waits_in_verifying_without_complete_audit() -> None:
    result = enrich_baseline_lifecycle(
        _registered(10),
        {
            "lifecycle_enabled": True,
            "declared_status": "capturing",
            "published_issues": 10,
            "verified_issues": 0,
            "bev_indexed_issues": 10,
            "video_indexed_issues": 10,
            "camera_indexed_issues": 10,
        },
    )
    assert result["status"] == "verifying"


def test_membership_failure_blocks_media_lifecycle() -> None:
    summary = _registered(10)
    summary["registration_status"] = "blocked"
    result = enrich_baseline_lifecycle(summary, {"lifecycle_enabled": True})
    assert result["status"] == "blocked"


def test_verified_audit_finishes_but_missing_video_and_errors_stay_partial() -> None:
    media = {"lifecycle_enabled": True, "declared_status": "verified", "published_issues": 10,
             "verified_issues": 10, "bev_indexed_issues": 10, "video_indexed_issues": 10,
             "camera_indexed_issues": 10, "failure_count": 0}
    assert enrich_baseline_lifecycle(_registered(10), media)["media_status"] == "complete"
    missing = enrich_baseline_lifecycle(_registered(10), dict(media, video_indexed_issues=9))
    assert missing["media_status"] == "partial"
    assert missing["missing_media"] == {"bev": 0, "video": 1, "camera": 0}
    assert enrich_baseline_lifecycle(_registered(10), dict(media, failure_count=1))["media_status"] == "partial"
    assert enrich_baseline_lifecycle(_registered(10), dict(media, lifecycle_enabled=False, camera_indexed_issues=9))["media_status"] == "partial"
