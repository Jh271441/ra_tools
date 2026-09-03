"""Baselines HTTP helpers."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Request

from ..baseline import load_baseline_entry
from ..baseline_registry import (
    detect_issue_scope_overlaps,
    ids_to_scopes,
    normalize_baseline_ids,
)
from ..import_parsing import normalize_model_row, parse_source_bytes
from ..runtime import baseline_registry, database, media_registry, runtime_state, settings
from .common import _as_text


def bootstrap_model_result() -> None:
    path = settings.bootstrap_model_json
    if not path or not path.is_file():
        return
    content = path.read_bytes()
    try:
        source_rows, metadata = parse_source_bytes(path.name, content)
        rows = [normalized for row in source_rows if (normalized := normalize_model_row(row))]
        if not rows:
            return
        experiment = metadata.get("experiment") if isinstance(metadata.get("experiment"), dict) else {}
        name = _as_text(experiment.get("model_name")) or path.stem
        database.import_model_run(
            name=name,
            source_name=str(path),
            source_sha256=hashlib.sha256(content).hexdigest(),
            metadata=metadata,
            rows=rows,
            created_by="system",
            created_by_source="service_bootstrap",
            created_by_verified=False,
        )
    except Exception as exc:
        print(f"[ra_triage_dashboard] bootstrap model result skipped: {exc}", flush=True)

def bootstrap_baseline() -> dict[str, Any]:
    """Load every registry baseline; keep legacy runtime_state["baseline"] = default 0508."""

    return bootstrap_all_baselines()

def bootstrap_all_baselines() -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    memberships: list[tuple[str, str]] = []
    overlap_mode = str(getattr(settings, "baseline_overlap_mode", "fail_skip") or "fail_skip")
    for entry in baseline_registry.entries:
        loaded = load_baseline_entry(
            loader=entry.loader,
            path=entry.xlsx,
            dataset=entry.dataset,
        )
        item: dict[str, Any] = {
            "id": entry.id,
            "label": entry.label,
            "scope": entry.scope,
            "loader": entry.loader,
            "dataset": entry.dataset,
            "path": str(entry.xlsx),
            "source_rows": loaded.source_rows,
            "count": len(loaded.rows),
            "skipped_rows": loaded.skipped_rows,
            "message": loaded.message,
            "status": "ready" if loaded.rows else "unavailable",
            "default_selected": entry.default_selected,
            "media_provider": entry.media.provider,
        }
        if loaded.rows:
            # Overlap detection vs already-accepted memberships.
            proposed = [str(row.get("issue_id") or "").strip() for row in loaded.rows]
            existing_map: dict[str, str] = {issue: scope for issue, scope in memberships}
            conflicts = [
                issue for issue in proposed if issue and issue in existing_map
            ]
            if conflicts and overlap_mode != "last_writer":
                conflict_set = set(conflicts)
                kept = [
                    row
                    for row in loaded.rows
                    if str(row.get("issue_id") or "").strip() not in conflict_set
                ]
                item["conflict_count"] = len(conflicts)
                item["message"] = (
                    f"{loaded.message}；跳过与其它 baseline 重叠的 {len(conflicts)} 条"
                )
                if not kept:
                    item["status"] = "conflict"
                    item["count"] = 0
                    summaries.append(item)
                    continue
                loaded_rows = kept
                item["count"] = len(kept)
            else:
                loaded_rows = list(loaded.rows)
                item["conflict_count"] = len(conflicts)
            item["upsert"] = database.replace_baseline_scope(
                scope=entry.scope,
                rows=loaded_rows,
                source=entry.loader,
            )
            for row in loaded_rows:
                issue = str(row.get("issue_id") or "").strip()
                if issue:
                    memberships.append((issue, entry.scope))
        summaries.append(item)

    overlaps = detect_issue_scope_overlaps(memberships)
    runtime_state["baseline_conflicts"] = [
        {"issue_id": issue, "scopes": scopes} for issue, scopes in sorted(overlaps.items())
    ]
    runtime_state["baselines"] = summaries
    # Legacy primary baseline slot = default selected entry (usually 0508).
    default_ids = baseline_registry.default_ids()
    primary = next(
        (item for item in summaries if item["id"] in default_ids),
        summaries[0] if summaries else {
            "status": "unavailable",
            "message": "无 baseline registry 条目。",
            "count": 0,
            "scope": settings.baseline_scope,
            "dataset": settings.baseline_dataset,
        },
    )
    runtime_state["baseline"] = primary
    return primary

def resolve_request_baseline_ids(
    raw: Any = None,
    *,
    request: Request | None = None,
) -> list[str]:
    """Resolve short baseline ids from query/header; never trust raw scopes."""

    allowed = baseline_registry.allowed_ids()
    default = baseline_registry.default_ids()
    if not allowed:
        return ["0508"]
    candidate = raw
    if (candidate is None or candidate == "") and request is not None:
        candidate = request.query_params.get("baselines") or request.query_params.get(
            "baseline_scopes"
        )
    return normalize_baseline_ids(candidate, allowed=allowed, default=default)

def resolve_request_baseline_scopes(
    raw: Any = None,
    *,
    request: Request | None = None,
) -> list[str]:
    ids = resolve_request_baseline_ids(raw, request=request)
    scopes = ids_to_scopes(ids, baseline_registry)
    if not scopes:
        # Fail closed to default primary scope.
        entry = baseline_registry.by_id(baseline_registry.default_ids()[0]) if baseline_registry.entries else None
        return [entry.scope if entry else settings.baseline_scope]
    return scopes

def media_for_issue(issue_id: str, baseline_scope: str = "") -> Any:
    provider = media_registry.resolve_for_issue(issue_id, baseline_scope=baseline_scope)
    return provider or media_registry.for_baseline_id(baseline_registry.default_ids()[0])

def _infer_baseline_ids_from_scope_coverage(
    coverage: list[dict[str, Any]],
    *,
    dominant_ratio: float = 0.9,
) -> list[str]:
    """Map prediction-per-scope counts to short baseline ids for auto topbar select.

    Evaluation runs almost always target a single GT workset. Prefer the single
    dominant matched scope; fall back to every matched scope when mixed.
    """

    matched: list[tuple[str, int]] = []
    for item in coverage:
        scope = str(item.get("baseline_scope") or "").strip()
        count = int(item.get("prediction_count") or 0)
        if not scope or count <= 0:
            continue
        baseline_id = baseline_registry.scope_to_id(scope)
        if not baseline_id:
            continue
        matched.append((baseline_id, count))
    if not matched:
        return []
    # Merge duplicate ids if registry ever aliases (shouldn't).
    by_id: dict[str, int] = {}
    for baseline_id, count in matched:
        by_id[baseline_id] = by_id.get(baseline_id, 0) + count
    ordered = sorted(by_id.items(), key=lambda pair: (-pair[1], pair[0]))
    total = sum(count for _, count in ordered)
    if len(ordered) == 1:
        return [ordered[0][0]]
    top_id, top_count = ordered[0]
    if total > 0 and top_count / total >= dominant_ratio:
        return [top_id]
    return [baseline_id for baseline_id, _ in ordered]

def enrich_model_run_baseline_hint(
    run: dict[str, Any] | None,
    *,
    coverage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach per-scope coverage + inferred dataset ids for UI auto-select.

    Pass ``coverage`` when the caller already batched
    ``model_run_scope_coverage_map`` so list endpoints stay O(1) SQL.
    """

    if not isinstance(run, dict):
        return {}
    run_id = str(run.get("id") or "").strip()
    if not run_id:
        return run
    if coverage is None:
        coverage = database.model_run_scope_coverage(run_id)
    by_id: list[dict[str, Any]] = []
    unmatched = 0
    for item in coverage:
        scope = str(item.get("baseline_scope") or "").strip()
        count = int(item.get("prediction_count") or 0)
        if not scope:
            unmatched += count
            continue
        baseline_id = baseline_registry.scope_to_id(scope) or ""
        by_id.append(
            {
                "id": baseline_id,
                "scope": scope,
                "label": (
                    baseline_registry.by_id(baseline_id).label
                    if baseline_id and baseline_registry.by_id(baseline_id)
                    else scope
                ),
                "prediction_count": count,
            }
        )
    inferred = _infer_baseline_ids_from_scope_coverage(coverage)
    payload = dict(run)
    payload["baseline_coverage"] = by_id
    payload["unmatched_prediction_count"] = unmatched
    payload["inferred_baseline_ids"] = inferred
    return payload
