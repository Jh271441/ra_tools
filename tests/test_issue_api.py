import concurrent.futures
from pathlib import Path
import sys
import threading

import pandas as pd
import pytest
import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ra_api.issue_api import TrailInterface


def test_trail_interface_uses_configurable_issue_base_url(monkeypatch):
    monkeypatch.setenv("TRAIL_ISSUE_BASE_URL", "http://trail.example/")

    trail = TrailInterface()

    assert trail.query_issue_pool_url == (
        "http://trail.example/paladin/issue/pool/query/")
    assert trail.query_by_issue_id_url == (
        "http://trail.example/paladin/issue/pool/query_by_issue_id_list/")


def test_get_page_content_does_not_mutate_shared_query(monkeypatch):
    trail = TrailInterface()
    shared_query = {
        "view_id": 2410,
        "page": 1,
        "query_attrs": [{"attr_id": "version", "val": ["release"]}],
    }
    barrier = threading.Barrier(8)
    seen_pages = []
    lock = threading.Lock()

    monkeypatch.setattr("ra_api.issue_api.random.uniform", lambda *_: 0)

    def send_request(url, payload):
        barrier.wait(timeout=2)
        with lock:
            seen_pages.append(payload["page"])
        return {"data": {"data": [{"page": payload["page"]}]}}

    monkeypatch.setattr(trail, "send_request", send_request)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(
            lambda page: trail._get_page_content("url", shared_query, page),
            range(1, 9),
        ))

    assert sorted(seen_pages) == list(range(1, 9))
    assert sorted(row[0]["page"] for row in rows) == list(range(1, 9))
    assert shared_query["page"] == 1


def test_send_request_retries_transient_gateway_errors(monkeypatch):
    trail = TrailInterface()
    calls = []

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("502 Bad Gateway")

        def json(self):
            return {"code": 0, "msg": "success", "data": {"total": 1}}

    def post(**kwargs):
        calls.append(kwargs)
        return Response(502 if len(calls) < 3 else 200)

    sleeps = []
    monkeypatch.setattr("ra_api.issue_api.requests.post", post)
    monkeypatch.setattr("ra_api.issue_api.time.sleep", sleeps.append)

    result = trail.send_request("url", {"page": 1})

    assert result["data"]["total"] == 1
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_query_issue_poll_returns_empty_frame_on_unavailable_first_page(
        monkeypatch):
    trail = TrailInterface()
    monkeypatch.setattr(trail, "send_request", lambda *args, **kwargs: None)

    result = trail.query_issue_poll(2410, [])

    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_query_issue_poll_rejects_partial_pagination_in_strict_mode(
        monkeypatch):
    trail = TrailInterface()
    monkeypatch.setattr(
        trail,
        "send_request",
        lambda *args, **kwargs: {"data": {"total": 2}},
    )
    monkeypatch.setattr(
        trail,
        "_get_page_content",
        lambda *args, **kwargs: [{"issue_id": "only-one"}],
    )

    with pytest.raises(RuntimeError, match="expected 2 rows, received 1"):
        trail.query_issue_poll(
            2410, [], size=2, require_complete=True)
