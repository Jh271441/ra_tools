"""Version metrics read frozen receipts; explicit refresh only queries sources."""
import asyncio
import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, validator

from ..runtime import database, settings
from ..support.identity import _writer_identity
from ..auth import has_same_origin_mutation_marker
from ..version_metric_store import VersionMetricStore
from ..version_metric_source import source, read_only_client
from ..version_metrics import evaluate, case_page, FIELDS, THRESHOLDS

router = APIRouter()


def store():
    return VersionMetricStore(settings.data_dir)


def catalog():
    return sorted(database.list_version_datasets(), key=lambda r: r["release_family"], reverse=True)


def validate_policy(reference, exclusion, threshold):
    if reference not in FIELDS or exclusion not in ("all", "exclude") or threshold not in THRESHOLDS:
        raise ValueError("Invalid metric policy")


def families_for(value):
    available = catalog()
    known = {r["release_family"] for r in available}
    families = sorted(known) if value == "all" else value.split(",") if value else [r["release_family"] for r in available[:6]]
    if len(families) > 50 or len(families) != len(set(families)) or any(f not in known for f in families):
        raise ValueError("Invalid metric versions")
    return sorted(families), available


def overview(families, reference, exclusion, threshold, page, page_size):
    validate_policy(reference, exclusion, threshold)
    if page_size not in (10, 20, 50, 100):
        raise ValueError("Invalid page size")
    selected, available = families_for(families)
    service = store()
    results = []
    for family in selected:
        try:
            saved = service.latest_trail(family)
            if saved:
                value = evaluate(saved, reference=reference, exclusion=exclusion, threshold=threshold)
                current = next(d for d in available if d["release_family"] == family)
                value.update(status="ready", membership_changed=saved.get("registry_revision") != current["revision"])
            else:
                value = dict(family=family, status="unavailable", reason="trail_snapshot_required")
        except (ValueError, OSError, KeyError, TypeError):
            value = dict(family=family, status="error")
        results.append(value)
    pages = max(1, (len(results)+page_size-1)//page_size)
    page = min(page, pages)
    return dict(items=results, catalog=[dict(family=d["release_family"], dataset_id=d["id"]) for d in available],
                selected=selected, table=dict(items=list(reversed(results))[(page-1)*page_size:page*page_size],
                total=len(results), page=page, pages=pages, page_size=page_size), refresh=service.job())


@router.get("/api/version-metrics")
async def metrics(families: str = Query("", max_length=1000), reference: str = "te", exclusion: str = "all",
                  threshold: float = .9, page: int = Query(1, ge=1, le=10000), page_size: int = 20):
    try:
        return await asyncio.to_thread(overview, families, reference, exclusion, threshold, page, page_size)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def detail(family, snapshot, reference, exclusion, threshold, scheme, status, truth, predicted, page, page_size):
    validate_policy(reference, exclusion, threshold)
    if family not in {r["release_family"] for r in catalog()}:
        raise ValueError("Unknown metric version")
    service = store()
    saved = service.latest_trail(family, snapshot)
    if not saved:
        raise ValueError("Version has no metric snapshot")
    return dict(summary=evaluate(saved, reference=reference, exclusion=exclusion, threshold=threshold),
                history=service.history(family), cases=case_page(saved, reference=reference, exclusion=exclusion,
                    threshold=threshold, scheme=scheme, status=status, truth=truth, predicted=predicted, page=page, page_size=page_size))


@router.get("/api/version-metrics/{family}")
async def metric_detail(family: str, snapshot: str = Query("", max_length=64), reference: str = "te", exclusion: str = "all",
                        threshold: float = .9, scheme: str = "chain", status: str = "errors", truth: str = "", predicted: str = "",
                        page: int = Query(1, ge=1, le=10000), page_size: int = 20):
    try:
        return await asyncio.to_thread(detail, family, snapshot, reference, exclusion, threshold, scheme, status, truth, predicted, page, page_size)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


class Refresh(BaseModel):
    families: list[str]
    @validator("families")
    def bounded_families(cls, value):
        if not 1 <= len(value) <= 50:
            raise ValueError("Select 1 to 50 versions")
        return value
    class Config:
        extra = "forbid"


@router.post("/api/version-metrics/refresh", status_code=202)
async def refresh(request: Request, body: Refresh):
    await asyncio.to_thread(_writer_identity, request)
    if not has_same_origin_mutation_marker(request):
        raise HTTPException(403, "Request marker required")
    try:
        selected, _ = await asyncio.to_thread(families_for, ",".join(body.families))
        if not selected:
            raise ValueError("Select at least one version")
        # Authentication/SDK setup belongs to the worker, not the HTTP path.
        clients = []
        def factory(family):
            if not clients:
                clients.append(read_only_client(settings.ra_auto_triage_root))
            return source(database, family, clients[0])
        return await asyncio.to_thread(store().refresh, selected, factory)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
