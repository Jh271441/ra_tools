"""Version worksets and immutable ingestion history, separate from GT baselines."""
import asyncio, json
from fastapi import APIRouter, HTTPException, Request
from ..runtime import database
from ..support.identity import _admin_identity

router = APIRouter()


@router.get("/api/version-datasets")
async def datasets():
    return {"items": await asyncio.to_thread(database.list_version_datasets)}


@router.get("/api/version-datasets/{dataset_id}/items")
async def items(
    dataset_id: str,
    page: int = 1,
    page_size: int = 40,
    mode: str = "targets",
    q: str = "",
):
    try:
        return await asyncio.to_thread(
            database.version_dataset_items,
            dataset_id,
            page=page,
            page_size=page_size,
            mode=mode,
            query=q[:128],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


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
