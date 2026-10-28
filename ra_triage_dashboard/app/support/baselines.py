"""Baselines HTTP helpers."""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from fastapi import Request

from ..baseline import daily_baseline_display_label, load_baseline_entry
from ..dataset_partitions import load_partitions, partition_summaries, SOURCE_IDS, SOURCE_SCOPES, PARTITION_IDS
from ..baseline_registry import (
    detect_issue_scope_overlaps,
    ids_to_scopes,
    normalize_baseline_ids,
)
from ..import_parsing import normalize_model_row, parse_source_bytes
from ..runtime import baseline_registry, database, media_registry, runtime_state, settings
from .common import _as_text, _detail


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
    media_memberships: dict[str, frozenset[str]] = {}
    overlap_mode = str(getattr(settings, "baseline_overlap_mode", "fail_skip") or "fail_skip")
    for entry in baseline_registry.entries:
        media_memberships[entry.id] = frozenset()
        loaded = load_baseline_entry(
            loader=entry.loader,
            path=entry.xlsx,
            dataset=entry.dataset,
        )
        item: dict[str, Any] = {
            "id": entry.id,
            "label": daily_baseline_display_label(entry.id, entry.label, loaded.rows),
            "scope": entry.scope,
            "loader": entry.loader,
            "dataset": entry.dataset,
            "path": str(entry.xlsx),
            "source_rows": loaded.source_rows,
            "count": len(loaded.rows),
            "skipped_rows": loaded.skipped_rows,
            "message": loaded.message,
            "status": "registered" if loaded.rows else "blocked",
            "registration_status": "registered" if loaded.rows else "blocked",
            "default_selected": entry.default_selected,
            "media_provider": entry.media.provider,
        }
        if loaded.rows:
            actual_sha256 = (
                hashlib.sha256(entry.xlsx.read_bytes()).hexdigest()
                if entry.members_sha256
                else ""
            )
            expected_count = entry.expected_count or len(loaded.rows)
            count_matches = len(loaded.rows) == expected_count
            sha_matches = not entry.members_sha256 or actual_sha256 == entry.members_sha256
            item["membership"] = {
                "status": "registered" if count_matches and sha_matches else "blocked",
                "registered_count": len(loaded.rows),
                "expected_count": expected_count,
                "sha256": actual_sha256,
                "configured_sha256": entry.members_sha256,
                "count_matches": count_matches,
                "sha_matches": sha_matches,
                "frozen": bool(entry.members_sha256 and count_matches and sha_matches),
            }
            if not count_matches or not sha_matches:
                item["status"] = "blocked"
                item["registration_status"] = "blocked"
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
            media_memberships[entry.id] = frozenset(str(row.get("issue_id") or "").strip() for row in loaded_rows if row.get("issue_id"))
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
    media_registry.set_memberships(media_memberships)
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


def enrich_baseline_lifecycle(
    summary: dict[str, Any], media_ready: dict[str, Any]
) -> dict[str, Any]:
    """Keep frozen membership and incremental media lifecycle independent."""

    item = {**summary, "media_ready": media_ready}
    membership = dict(item.get("membership") or {})
    member_count = int(membership.get("registered_count") or item.get("count") or 0)
    expected = int(membership.get("expected_count") or member_count or 0)
    if item.get("registration_status") != "registered":
        item["status"] = "blocked"
        item["media_status"] = "blocked"
        return item

    if media_ready.get("coverage_status") in {"pending", "error"}:
        item["status"] = "registered"
        item["media_status"] = "checking" if media_ready["coverage_status"] == "pending" else "unavailable"
        return item

    bev = int(media_ready.get("bev_indexed_issues") or 0)
    video = int(media_ready.get("video_indexed_issues") or 0)
    camera = int(media_ready.get("camera_indexed_issues") or 0)
    item["missing_media"] = {key: max(0, expected - count) for key, count in (("bev", bev), ("video", video), ("camera", camera))}
    full_coverage = expected > 0 and not any(item["missing_media"].values())
    if not bool(media_ready.get("lifecycle_enabled")):
        item["status"] = "ready"
        item["media_status"] = "complete" if full_coverage else "partial"
        return item

    published = int(media_ready.get("published_issues") or 0)
    verified = int(media_ready.get("verified_issues") or 0)
    camera = int(media_ready.get("camera_indexed_issues") or 0)
    declared = str(media_ready.get("declared_status") or "").strip().lower()
    errors = int(media_ready.get("failure_count") or 0)
    if declared == "blocked":
        state = "blocked"
    elif (
        declared in {"complete", "verified"}
        and full_coverage
        and expected > 0
        and published >= expected
        and verified >= expected
        and camera >= expected
        and errors == 0
    ):
        state = "complete"
    elif errors > 0 or (expected > 0 and published >= expected and not full_coverage):
        state = "partial"
    elif expected > 0 and published >= expected:
        state = "verifying"
    elif declared in {"capturing", "collecting"}:
        state = "collecting"
    elif published > 0:
        state = "partial"
    else:
        state = "registered"
    item["status"] = state
    item["media_status"] = state
    item["remaining_media"] = max(0, expected - published)
    return item

def resolve_request_baseline_ids(
    raw: Any = None,
    *,
    request: Request | None = None,
) -> list[str]:
    """Resolve short baseline ids from query/header; never trust raw scopes."""

    partitions = load_partitions(settings.data_dir)
    allowed = baseline_registry.allowed_ids() | set(partitions)
    default = baseline_registry.default_ids()
    if not allowed:
        return ["0508"]
    candidate = raw
    if (candidate is None or candidate == "") and request is not None:
        query = _request_query(request)
        candidate = query.get("baselines") or query.get(
            "baseline_scopes"
        )
    if "version-" in str(candidate or ""):
        allowed |= {"version-"+row["release_family"] for row in database.list_version_datasets()}
    requested = _selection_tokens(candidate)
    if set(requested).intersection(PARTITION_IDS) - set(partitions):
        raise _detail(503, "数据集分区暂不可用 / Dataset partition unavailable")
    return normalize_baseline_ids(candidate, allowed=allowed, default=default)


def _selection_tokens(raw: Any) -> list[str]:
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    return [part.strip() for value in values for part in str(value or "").split(",") if part.strip()]


def _request_query(request):
    # Optional request context is also used by internal non-HTTP callers.
    try:
        return request.query_params if request is not None else {}
    except (AttributeError, KeyError):
        return {}

def resolve_request_baseline_scopes(
    raw: Any = None,
    *,
    request: Request | None = None,
) -> list[str]:
    ids = resolve_request_baseline_ids(raw, request=request)
    scopes = ids_to_scopes([i for i in ids if not i.startswith("version-")], baseline_registry)
    if set(ids).intersection(PARTITION_IDS):
        scopes.extend(SOURCE_SCOPES)
    for version_id in ids:
        if version_id.startswith("version-"):
            scopes.extend(database.version_dataset_scopes("release-"+version_id[8:]+"-odd2"))
    scopes = list(dict.fromkeys(scopes))
    if not scopes:
        # Fail closed to default primary scope.
        entry = baseline_registry.by_id(baseline_registry.default_ids()[0]) if baseline_registry.entries else None
        return [entry.scope if entry else settings.baseline_scope]
    return scopes

def restrict_version_issue_ids(
    raw: Any = None, *, request: Request | None = None,
    issue_ids: Sequence[str] = (), task_id: str = "", target_group: str | None = None,
) -> tuple[str, ...]:
    """Compose live target cohorts with the existing dataset/task/Issue scope."""
    group = target_group if target_group is not None else _request_query(request).get("target_group", "")
    if group not in {"", "all", "sample", "low"}:
        raise _detail(400, "目标集合筛选无效 / Invalid target cohort filter")
    selected = _restrict_version_issue_ids(raw, request=request, issue_ids=issue_ids, task_id=task_id)
    if group in {"", "all"}:
        return selected
    ids = resolve_request_baseline_ids(raw, request=request)
    datasets = ["release-" + key[8:] + "-odd2" for key in ids if key.startswith("version-")]
    task_dataset = database.version_campaign_dataset(task_id) if task_id else ""
    if task_dataset:
        datasets = [task_dataset]
    scopes = resolve_request_baseline_scopes(raw, request=request)
    # These are registry membership flags, not human tags or a new confidence threshold.
    predicate = "v.is_sample=1" if group == "sample" else "v.is_low=1 AND v.is_sample=0"
    sql = "SELECT DISTINCT v.issue_id FROM version_dataset_items v JOIN issues i ON i.issue_id=v.issue_id WHERE v.is_target=1 AND (" + predicate + ")"
    args = []
    if datasets:
        sql += " AND v.dataset_id IN (" + ",".join("?" for _ in datasets) + ")"
        args.extend(datasets)
    if scopes:
        sql += " AND i.baseline_scope IN (" + ",".join("?" for _ in scopes) + ")"
        args.extend(scopes)
    with database.connect() as conn:
        members = {row["issue_id"] for row in conn.execute(sql, args).fetchall()}
    return tuple(sorted(members.intersection(selected) if selected else members)) or ("__empty_target_cohort__",)


def _restrict_version_issue_ids(
    raw: Any = None, *, request: Request | None = None,
    issue_ids: Sequence[str] = (), task_id: str = "",
) -> tuple[str, ...]:
    """Intersect current version targets; explicit historical tasks stay frozen."""
    selected = tuple(issue_ids)
    query = _request_query(request)
    task_view = query.get("task_view", "")
    progress = set(_selection_tokens(query.get("task_progress", "")))
    # Older version-task links used task_view=pending for joint delivery.
    if task_view == "pending" and not progress:
        progress = {"pending"}
    if progress:
        if not task_id or not progress.issubset({"pending", "completed"}):
            raise _detail(400, "联合复核进度筛选无效 / Invalid combined task progress filter")
        from ..db_parts.assignment_rules import combined_task_progress_ids
        try:
            members = combined_task_progress_ids(
                database, task_id, progress,
                _selection_tokens(query.get("work_assignee", "")),
            )
        except ValueError as exc:
            raise _detail(400, str(exc)) from exc
        selected = tuple(sorted(members.intersection(selected) if selected else members)) or ("__empty_version_membership__",)
    if task_view:
        if task_view not in {"targets", "pending"}:
            raise _detail(400, "Unsupported task view")
        dataset_id = database.version_campaign_dataset(task_id) if task_id else ""
        if not dataset_id:
            raise _detail(400, "Current-target view requires a version task")
        # Use the same live membership and joint completion predicate as the
        # assignment card, never model-review status or a frozen URL ID list.
        members = {
            row["issue_id"] for row in database.version_dataset_gallery_rows(dataset_id)
            if row.get("is_target")
        }
        selected = tuple(sorted(members.intersection(selected) if selected else members)) or ("__empty_version_membership__",)
    requested = raw
    if not requested and request is not None:
        requested = query.get("baselines") or query.get("baseline_scopes")
    partition_selected = set(_selection_tokens(requested)).intersection(PARTITION_IDS)
    if partition_selected:
        partitions = load_partitions(settings.data_dir)
        if not partition_selected.issubset(partitions):
            raise _detail(503, "数据集分区暂不可用 / Dataset partition unavailable")
        ids = resolve_request_baseline_ids(requested, request=request)
        members = set().union(*(partitions[key] for key in partition_selected))
        native = [entry.scope for key in ids if (entry := baseline_registry.by_id(key))]
        with database.connect() as conn:
            if native:
                members.update(row['issue_id'] for row in conn.execute(
                    'SELECT issue_id FROM issues WHERE baseline_scope IN (' + ','.join('?' for _ in native) + ')', native).fetchall())
            for key in ids:
                if key.startswith('version-'):
                    members.update(row['issue_id'] for row in conn.execute(
                        'SELECT issue_id FROM version_dataset_items WHERE dataset_id=? AND is_target=1',
                        ('release-' + key[8:] + '-odd2',)).fetchall())
        return tuple(sorted(members.intersection(selected) if selected else members)) or ('__empty_partition_membership__',)
    if task_view or "version-" not in str(requested) or str(task_id or "").strip():
        return selected
    ids = resolve_request_baseline_ids(requested, request=request)
    native = [entry.scope for i in ids if not i.startswith("version-")
              and (entry := baseline_registry.by_id(i))]
    members = set()
    with database.connect() as conn:
        for version_id in ids:
            if version_id.startswith("version-"):
                members.update(row["issue_id"] for row in conn.execute(
                    "SELECT issue_id FROM version_dataset_items WHERE dataset_id=? AND is_target=1",
                    ("release-" + version_id[8:] + "-odd2",),
                ).fetchall())
        if native:
            members.update(row["issue_id"] for row in conn.execute(
                "SELECT issue_id FROM issues WHERE baseline_scope IN (" + ",".join("?" for _ in native) + ")",
                native,
            ).fetchall())
    # An empty intersection must never be interpreted as an unrestricted query.
    return tuple(sorted(members.intersection(selected) if selected else members)) or ("__empty_version_membership__",)

def media_for_issue(issue_id: str, baseline_scope: str = "") -> Any:
    provider = media_registry.resolve_for_issue(issue_id, baseline_scope=baseline_scope)
    return provider or media_registry.for_baseline_id(baseline_registry.default_ids()[0])


def task_baseline_ids(scopes, task_id):
    """Map exact frozen task members to visible partitions without moving history."""
    ids = [baseline_registry.scope_to_id(scope) or scope for scope in scopes]
    partitions = load_partitions(settings.data_dir)
    if not partitions or not set(ids).intersection(SOURCE_IDS):
        return ids
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT issue_id FROM review_work_assignments WHERE split_id=? "
            "UNION SELECT issue_id FROM campaign_issue_members WHERE campaign_id=?",
            (task_id, task_id),
        ).fetchall()
    members = {row['issue_id'] for row in rows}
    return [key for key in ids if key not in SOURCE_IDS] + [
        key for key in PARTITION_IDS if not members or members.intersection(partitions[key])
    ]


def issue_dataset_id(issue_id, source_id):
    """Public dataset identity is the frozen partition, not import provenance."""
    if source_id in SOURCE_IDS:
        partitions = load_partitions(settings.data_dir)
        for key, members in partitions.items():
            if issue_id in members:
                return key
        if partitions:
            raise _detail(409, "案例不在冻结分区中 / Case missing from frozen dataset partitions")
    return source_id

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
    partition_coverage: dict[str, int] | None = None,
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
    partitions = load_partitions(settings.data_dir)
    if partitions:
        if partition_coverage is None:
            partition_coverage = database.model_run_partition_coverage_map([run_id], partitions).get(run_id, {})
        by_id = [row for row in by_id if row['id'] not in SOURCE_IDS]
        by_id.extend(dict(id=key, scope='partition_' + key, label=row['label'], label_en=row['label_en'],
                          prediction_count=int(partition_coverage.get(key, 0)))
                     for row in partition_summaries(partitions) if (key := row['id']))
        inferred = [key for key in inferred if key not in SOURCE_IDS] + [
            key for key in PARTITION_IDS if partition_coverage.get(key, 0) > 0]
    payload = dict(run)
    payload["baseline_coverage"] = by_id
    payload["unmatched_prediction_count"] = unmatched
    if run.get("kind") == "version_live":
        family = (run.get("metadata") or {}).get("release_family")
        if family:
            inferred = ["version-"+family]
    payload["inferred_baseline_ids"] = inferred
    return payload


def operational_baseline_summaries(existing, db=None):
    db = db or database
    partitions = load_partitions(settings.data_dir)
    if partitions:
        existing = [item for item in existing if item.get('id') not in SOURCE_IDS]
        existing = [*existing, *partition_summaries(partitions)]
    versions = db.list_version_datasets()
    if not versions:
        return existing
    families = {x['release_family'] for x in versions}
    # Historical baseline scopes remain valid provenance; only the visible
    # operational selectors collapse their daily entries after consolidation.
    result = [x for x in existing if not (('20261009' in families) and (str(x.get('id','')).startswith('1009-') or str(x.get('id','')).startswith('review-2026-') or str(x.get('label','')).startswith('1009 ')))]
    for item in versions:
        result.append(dict(id='version-'+item['release_family'],label=item['name'],scope='manual_sidecar_version_'+item['release_family'],loader='version_projection',count=item['targets'],source_rows=item['targets'],status='registered',registration_status='registered',default_selected=False,operational=True,gt_mode='sparse',membership=dict(frozen=False,registered_count=item['targets'])))
    return result
