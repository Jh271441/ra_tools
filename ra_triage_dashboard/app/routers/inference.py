from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from ..support.common import _detail
from ..runtime import database

from fastapi import Depends
from ..core.deps import get_container
from ..schemas import BatchDetailResponse, BatchListResponse

router = APIRouter(dependencies=[Depends(get_container)])

@router.post("/api/inference/jobs", responses={200: {"model": BatchListResponse}})
async def create_inference_job(request: Request) -> dict[str, Any]:
    raise _detail(
        410,
        "浏览器单 Case 自定义模型推理已停用；请使用 /api/prediction-batches，"
        "由 cloud_server 的 ra_auto_triage 默认模型执行。",
    )



@router.get("/api/inference/jobs", responses={200: {"model": BatchListResponse}})
async def list_inference_jobs(
    requested_by: str = "",
    status: str = "",
    page_size: int = 100,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        database.list_inference_jobs,
        requested_by=requested_by,
        status=status,
        page_size=page_size,
    )



@router.get("/api/inference/jobs/{job_id}", responses={200: {"model": BatchDetailResponse}})
async def get_inference_job(job_id: str) -> dict[str, Any]:
    job = await asyncio.to_thread(database.get_job, job_id)
    if job is None:
        raise _detail(404, "任务不存在。")
    return {"job": job}
