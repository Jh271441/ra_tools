from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.deps import get_settings, resolve_dep
from ..cron_source import cron_snapshot
from ..runtime import settings
from ..schemas import DailyCronResponse

from fastapi import Depends
from ..core.deps import get_container

router = APIRouter(dependencies=[Depends(get_container)])


@router.get("/api/daily-cron", responses={200: {"model": DailyCronResponse}})
async def daily_cron(
    refresh: bool = False,
    cfg: Any = Depends(get_settings),
) -> JSONResponse:
    cfg = resolve_dep(cfg, lambda: settings)
    return JSONResponse(
        await asyncio.to_thread(
            cron_snapshot,
            cfg.ra_auto_triage_root,
            cfg.data_dir,
            force_refresh=bool(refresh),
        ),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
