"""Initialization phase: schema. Uses the caller-owned lock and connection."""
from __future__ import annotations
from .schema_resources import schema_sql


def initialize_schema(self, conn) -> None:
    conn.executescript(schema_sql("base"))
    if self.backend == "sqlite":
        conn.executescript(schema_sql("run_evaluations"))
