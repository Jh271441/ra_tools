from __future__ import annotations

from typing import Any, List, Optional, Union

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from ..http_support import *  # noqa: F401,F403
from ..runtime import *  # noqa: F401,F403

# Keep FastAPI symbols after star-imports (runtime/http_support may not define them).
from fastapi import APIRouter, File, Form, Request, UploadFile  # noqa: F401
from fastapi.responses import (  # noqa: F401
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

router = APIRouter()

@router.post("/api/inference/jobs")
async def create_inference_job(request: Request) -> dict[str, Any]:
    raise _detail(
        410,
        "浏览器单 Case 自定义模型推理已停用；请使用 /api/prediction-batches，"
        "由 cloud_server 的 ra_auto_triage 默认模型执行。",
    )



@router.get("/api/inference/jobs")
async def list_inference_jobs(
    requested_by: str = "",
    status: str = "",
    page_size: int = 100,
) -> dict[str, Any]:
    return database.list_inference_jobs(
        requested_by=requested_by,
        status=status,
        page_size=page_size,
    )



@router.get("/api/inference/jobs/{job_id}")
async def get_inference_job(job_id: str) -> dict[str, Any]:
    job = database.get_job(job_id)
    if job is None:
        raise _detail(404, "任务不存在。")
    return {"job": job}
