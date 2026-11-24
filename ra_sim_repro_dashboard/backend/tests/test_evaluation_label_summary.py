import pytest

from app.services import evaluation_label_summary as summary


def test_frozen_link_requires_the_exact_issue_set():
    base = "https://voyager.intra.xiaojukeji.com/static/management/#/issue/pool?"
    query = "query_attrs.$0=issue_id%7Cin%7Ccn100%252Ccn200%7Ca_s"
    assert summary.issue_ids(base + query) == {"cn100", "cn200"}
    assert summary.issue_ids(None) == set()
    for invalid in [query.replace("cn200", "cn100"), query.replace("issue_id", "version"),
                    query + "&query_attrs.$1=foo", query.replace("cn200", "")]:
        with pytest.raises(ValueError):
            summary.issue_ids(base + invalid)


def test_only_current_matching_scope_and_revision_are_visible(monkeypatch):
    ctx = {"release": "r", "date_end": "2026-11-15"}
    stored = {"status": "complete", "context": ctx, "revision_key": "r1"}
    state = {"pointer": {"revision_key": "r1"}, summary.state_key(ctx, "r1"): stored}
    monkeypatch.setattr(summary.pipeline, "context", lambda db, **c: (c, None, None, "pointer"))
    monkeypatch.setattr(summary.workflow, "get_state", lambda db, key: state.get(key, {}))
    assert summary.read(None, ctx, "r1") == stored
    assert summary.read(None, {**ctx, "date_end": "2026-11-14"}, "r1") == {"status": "missing"}
    state["pointer"]["revision_key"] = "r2"
    assert summary.read(None, ctx, "r1") == {"status": "missing"}
    assert summary.read(None, ctx, "r2") == {"status": "missing"}
