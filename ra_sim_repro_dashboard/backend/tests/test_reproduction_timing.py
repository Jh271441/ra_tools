from copy import deepcopy
import pytest
from app.services.reproduction_timing import classify, summarize

T = 1790000020000


def scene(triggered=True, events=None, start=None, end=None):
    return {
        "scenario_id": "1",
        "start_timestamp": start or T - 20000,
        "end_timestamp": end or T + 10000,
        "sim_triggered": triggered,
        "trigger_events": events,
    }


def event(generated, published=None):
    return {
        "request_timestamp": T + generated,
        "publish_timestamp": T + (generated if published is None else published),
    }


def test_after_manual_request_is_reproduced_without_changing_whole_window_trigger():
    source = [scene(events=[event(674)])]
    original = deepcopy(source)
    value = classify(3, T, source)
    assert value["status"] == "after_manual_trigger" and value["matched"] is True
    assert value["whole_window_triggered"] is True
    assert source == original


def test_before_manual_request_remains_a_real_reproduction_difference():
    value = classify(3, T, [scene(events=[event(-6423)])])
    assert value["status"] == "before_manual_trigger" and value["matched"] is False


def test_event_and_publication_on_opposite_sides_require_review():
    value = classify(3, T, [scene(events=[event(-12, 14)])])
    assert value["status"] == "boundary_review" and value["matched"] is None


def test_clipped_scene_uses_event_anchor_instead_of_assuming_twenty_seconds():
    value = classify(3, T, [scene(events=[event(1777)], start=T - 8080)])
    assert value["status"] == "after_manual_trigger" and value["matched"] is True


def test_positive_without_verified_timestamps_is_pending_not_reproduced():
    value = classify(3, T, [scene()])
    assert value["status"] == "timing_missing" and value["matched"] is None
    assert classify(3, None, [scene(events=[event(500)])])["status"] == "manual_time_missing"
    assert classify(3, T, [scene(events=[])])["status"] == "signal_conflict"


def test_negative_whole_window_result_needs_no_new_bag_download():
    value = classify(3, T, [scene(False)])
    assert value["matched"] is True and value["whole_window_triggered"] is False


def test_automatic_cases_keep_whole_window_behavior():
    assert classify(2, None, [scene(True)])["matched"] is True
    assert classify(2, None, [scene(False)])["matched"] is False


def test_multiple_scenes_never_hide_an_early_request_or_incomplete_late_evidence():
    assert classify(3, T, [scene(events=[event(-500)]), scene()])["matched"] is False
    assert classify(3, T, [scene(events=[event(500)]), scene()])["status"] == "timing_missing"
    assert classify(3, T, [scene(events=[event(500)]), scene(False)])["matched"] is True


def test_invalid_window_and_inconsistent_negative_signal_remain_unverified():
    assert classify(3, T, [scene(False, end=T - 1)])["status"] == "manual_window_unverified"
    assert classify(3, T, [scene(False, events=[event(500)])])["status"] == "signal_conflict"
    assert classify(3, T, [scene(events=["invalid"])])["status"] == "signal_unverified"


def test_decimal_timestamp_strings_are_normalized_without_mutating_source():
    value = scene(events=[event(500)])
    value.update(start_timestamp=str(T - 8080), end_timestamp=str(T + 10000))
    assert classify(3, str(T), [value])["matched"] is True


def test_different_boundary_policies_cannot_be_aggregated():
    one = classify(3, T, [scene(False)])
    two = classify(3, T, [scene(False)], boundary_band_ms=0)
    with pytest.raises(ValueError, match="policy_mixed"):
        summarize([one, two])


def test_pending_boundary_is_not_counted_as_failure_or_complete_coverage():
    result = summarize(
        [
            classify(3, T, [scene(events=[event(500)])]),
            classify(3, T, [scene(events=[event(-12, 14)])]),
            classify(2, None, [scene(False)]),
        ]
    )
    assert result["evaluated"] == 2 and result["matched"] == 1 and result["pending"] == 1
    assert result["covered_rate"] == 0.5 and result["rate"] is None
    assert result["available"] is False


def test_dpe_source_explicitly_uses_request_time_only():
    def dpe(offset):
        return {"request_timestamp": T + offset, "timestamp_source": "dpe_request_event"}

    assert classify(3, T, [scene(events=[dpe(674)])])["status"] == "after_manual_trigger"
    assert classify(3, T, [scene(events=[dpe(-6423)])])["status"] == "before_manual_trigger"
    assert classify(3, T, [scene(events=[dpe(-12)])])["status"] == "boundary_review"
    assert (
        classify(3, T, [scene(events=[{"request_timestamp": T + 500}])])["status"]
        == "signal_unverified"
    )
