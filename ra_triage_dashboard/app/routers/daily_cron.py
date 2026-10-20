from __future__ import annotations

import asyncio
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..cron_source import cron_snapshot

router = APIRouter()


@router.get("/api/daily-cron")
async def daily_cron() -> JSONResponse:
    return JSONResponse(
        await asyncio.to_thread(cron_snapshot),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
