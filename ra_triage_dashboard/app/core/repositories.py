"""Explicit DbSessionFactory and domain Repository facades for Phase 2B DI.

Provides clean, testable boundaries over the underlying SQLite/PostgreSQL storage
without breaking legacy direct-Database callers or unit tests.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


class DbSessionFactory:
    """Explicit connection and transaction boundary decoupled from runtime globals."""

    def __init__(self, database: Any) -> None:
        self._database = database

    @property
    def backend(self) -> str:
        return str(getattr(self._database, "backend", "sqlite"))

    @property
    def raw_database(self) -> Any:
        return self._database

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self._database.connect() as conn:
            yield conn

    @contextmanager
    def write_transaction(self) -> Iterator[Any]:
        with self._database._write_lock, self._database.connect() as conn:
            yield conn


class _BaseRepository:
    def __init__(self, session_factory: DbSessionFactory) -> None:
        self.sessions = session_factory

    @property
    def db(self) -> Any:
        return self.sessions.raw_database


class CaseRepository(_BaseRepository):
    """Domain repository facade for Issues, Cases, Review Gallery, and Clusters."""

    def list_cases(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.list_cases(*args, **kwargs)

    def get_case(self, issue_id: str) -> Any:
        return self.db.get_case(issue_id)

    def get_issue(self, issue_id: str) -> Any:
        return self.db.get_issue(issue_id)

    def overview(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.overview(*args, **kwargs)

    def review_clusters(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.review_clusters(*args, **kwargs)


class CampaignRepository(_BaseRepository):
    """Domain repository facade for Campaigns, Allocation, and Progress."""

    def list_campaigns(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.list_campaigns(*args, **kwargs)

    def get_campaign(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.get_campaign(*args, **kwargs)

    def create_campaign(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.create_campaign(*args, **kwargs)

    def close_campaign(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.close_campaign(*args, **kwargs)

    def reopen_campaign(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.reopen_campaign(*args, **kwargs)

    def transition_campaign(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.transition_campaign(*args, **kwargs)


class WorkSplitRepository(_BaseRepository):
    """Domain repository facade for Work Splits and Reviewer Assignments."""

    def list_work_assignees(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.list_work_assignees(*args, **kwargs)

    def list_review_work_splits(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.list_review_work_splits(*args, **kwargs)

    def get_review_work_split(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.get_review_work_split(*args, **kwargs)

    def apply_work_split(self, *args: Any, **kwargs: Any) -> Any:
        return self.db.apply_work_split(*args, **kwargs)
