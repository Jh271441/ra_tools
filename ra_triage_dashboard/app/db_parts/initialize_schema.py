"""Initialization phase: schema. Uses the caller-owned lock and connection."""
from __future__ import annotations
from .schema_resources import schema_sql
from pathlib import Path


def initialize_schema(self, conn) -> None:
    conn.executescript(schema_sql("base"))
    if self.backend == "sqlite":
        conn.executescript((Path(__file__).with_name("sqlite_schema") / "trail_history.sql").read_text())
        conn.executescript(schema_sql("run_evaluations"))
        conn.executescript((Path(__file__).with_name("sqlite_schema") / "version_datasets.sql").read_text())
