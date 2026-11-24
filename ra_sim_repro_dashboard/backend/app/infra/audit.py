"""Database persistence sink for P0 security mutation audit records."""

from __future__ import annotations

import logging
from typing import Any

from app.database import SessionLocal
from app.models import AdminAuditLog
from app.security import register_audit_sink

logger = logging.getLogger(__name__)


def persist_audit_record(record: dict[str, Any]) -> None:
    """Write a security audit record into `admin_audit_logs` in an isolated session."""
    try:
        with SessionLocal() as db:
            db.add(
                AdminAuditLog(
                    actor=str(record.get("actor") or "anonymous")[:128],
                    identity_source=str(record.get("identity_source") or "anonymous")[:64],
                    client_ip=str(record.get("client_ip") or "")[:64],
                    method=str(record.get("method") or "")[:16],
                    path=str(record.get("path") or "")[:256],
                    target_release=str(record.get("target_release") or "")[:64],
                    status_code=int(record.get("status_code") or 0),
                    detail={
                        "latency_ms": record.get("latency_ms"),
                        "reason": record.get("reason") or "",
                        "timestamp": record.get("timestamp") or "",
                    },
                )
            )
            db.commit()
    except Exception:
        logger.debug("Skipping DB audit persistence (table unavailable or DB busy)", exc_info=True)


def install_db_audit_sink() -> None:
    register_audit_sink(persist_audit_record)
