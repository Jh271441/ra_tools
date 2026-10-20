from __future__ import annotations

import asyncio
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..cron_source import cron_snapshot
from ..runtime import settings

router = APIRouter()


@router.get("/api/daily-cron")
async def daily_cron() -> JSONResponse:
    return JSONResponse(
        await asyncio.to_thread(cron_snapshot, settings.ra_auto_triage_root),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
