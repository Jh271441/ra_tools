from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class DashboardError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class DashboardClient:
    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_case(self, issue_id: str) -> dict[str, Any]:
        path = f"/api/cases/{quote(issue_id, safe='')}?{urlencode({'include_media': 'false'})}"
        request = Request(
            self.base_url + path,
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "auto-triage-bot/0.1"},
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise DashboardError("看板返回了非成功状态。")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404:
                raise DashboardError("看板中没有这个 Issue。") from exc
            raise DashboardError("看板暂时不可用。") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DashboardError("看板暂时不可用。") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DashboardError("看板返回内容过大。")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DashboardError("看板返回内容无法解析。") from exc
        if not isinstance(payload, dict) or str(payload.get("issue_id") or "") != issue_id:
            raise DashboardError("看板返回了不匹配的 Issue。")
        return payload


def build_case_context(case: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    predictions = [item for item in case.get("predictions", []) if isinstance(item, dict)]
    selected = None
    if run_id:
        selected = next(
            (item for item in predictions if str(item.get("model_run_id") or "") == run_id),
            None,
        )
    else:
        selected = next((item for item in predictions if item.get("run_is_default")), None)
        if selected is None and predictions:
            selected = predictions[0]

    annotations = [item for item in case.get("annotations", []) if isinstance(item, dict)]
    selected_run_id = str((selected or {}).get("model_run_id") or run_id)
    if selected_run_id:
        review = next(
            (
                item
                for item in annotations
                if str(item.get("model_run_id") or "") == selected_run_id
            ),
            None,
        )
    else:
        review = annotations[0] if annotations else None

    return {
        "issue": {
            "issue_id": str(case.get("issue_id") or ""),
            "trip_id": str(case.get("trip_id") or ""),
            "title": str(case.get("title") or "")[:500],
            "scenario": str(case.get("scenario") or "")[:2000],
            "summary": str(case.get("summary") or "")[:2000],
            "baseline_scope": str(case.get("baseline_scope") or ""),
            "baseline_id": str(case.get("baseline_id") or ""),
            "gt_label": str(case.get("gt_label") or ""),
            "gt_source": str(case.get("gt_source") or ""),
        },
        "prediction": (
            {
                "run_id": str(selected.get("model_run_id") or ""),
                "run_name": str(selected.get("run_name") or "")[:240],
                "run_kind": str(selected.get("run_kind") or ""),
                "is_default": bool(selected.get("run_is_default")),
                "label": str(selected.get("model_label") or ""),
                "reason": str(selected.get("model_reason") or "")[:4000],
                "confidence": selected.get("model_confidence"),
            }
            if selected
            else None
        ),
        "latest_review_for_selected_run": (
            {
                "model_run_id": str(review.get("model_run_id") or ""),
                "expected_output": str(review.get("expected_output") or review.get("label") or ""),
                "review_status": str(review.get("review_status") or ""),
                "is_excluded": bool(review.get("is_excluded")),
                "tags": list(review.get("tags") or [])[:30],
                "missing_evidence": list(review.get("missing_evidence") or [])[:30],
                "note": str(review.get("note") or "")[:4000],
                "author": str(review.get("author") or ""),
                "author_verified": bool(review.get("author_verified")),
                "created_at": str(review.get("created_at") or ""),
            }
            if review
            else None
        ),
    }
