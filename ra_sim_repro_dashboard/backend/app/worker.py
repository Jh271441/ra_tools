from __future__ import annotations

from app.services.refresh import refresh_dashboard


def run_refresh_job(job_id: str) -> None:
    refresh_dashboard(job_id)
