"""Version worksets and immutable ingestion history, separate from GT baselines."""
import asyncio, json
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import Response, JSONResponse
from ..version_workbench import workbench, historical_dataset, gallery_csv
from ..daily_review_source import SnapshotChanged
from ..runtime import database, settings
from ..support.identity import _admin_identity

router = APIRouter()


@router.get("/api/version-datasets")
async def datasets(include_legacy: bool = False):
    result=await asyncio.to_thread(database.list_version_datasets)
    if include_legacy:result.append(await asyncio.to_thread(historical_dataset,settings.ra_auto_triage_root))
    return {"items": result}


@router.get("/api/version-datasets/{dataset_id}/items")
async def items(
    dataset_id: str,
    page: int = 1,
    page_size: int = 40,
    mode: str = "targets",
    q: str = "",
    sort: str = "added",
):
    try:
        return await asyncio.to_thread(
            database.version_dataset_items,
            dataset_id,
            page=page,
            page_size=page_size,
            mode=mode,
            query=q[:128],
            sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/version-datasets/{dataset_id}/workbench")
@router.get("/api/version-datasets/{dataset_id}/workbench.csv")
async def gallery(request: Request, dataset_id: str, page: int = Query(1,ge=1,le=10000), page_size: int = Query(24,ge=1,le=100),
                  mode: str = "targets", q: str = Query('',max_length=128), sort: str = "added", date: str = '',
                  te_status: str = 'all', revision: str = Query('',max_length=64),assignee:str='',review_status:str='all'):
    try:
        result,rows=await asyncio.to_thread(workbench,database,settings.ra_auto_triage_root,dataset_id,
            page=page,page_size=page_size,mode=mode,q=q,sort=sort,date=date,te_status=te_status,revision=revision,assignee=assignee,review_status=review_status)
    except SnapshotChanged as exc:raise HTTPException(409,str(exc)) from None
    except ValueError as exc:raise HTTPException(400,str(exc)) from None
    if request.url.path.endswith('.csv'):
        if not revision:raise HTTPException(400,'A gallery revision is required')
        return Response(gallery_csv(rows),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="version-cases.csv"','Cache-Control':'no-store'})
    return JSONResponse(result,headers={'Cache-Control':'no-store'})


@router.get("/api/version-datasets/{dataset_id}/batches")
async def batches(dataset_id: str):
    return {
        "items": await asyncio.to_thread(database.version_dataset_batches, dataset_id)
    }


@router.post("/api/version-datasets/ingest")
async def ingest(request: Request):
    actor = await asyncio.to_thread(_admin_identity, request)
    raw = await request.body()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "Version batch is too large")
    try:
        body = json.loads(raw)
        if set(body) - {"family", "policy", "items", "batch_key"}:
            raise ValueError("Unknown batch fields")
        return await asyncio.to_thread(
            database.ingest_version_dataset, actor=actor.username, **body
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
