"""Domain sub-routers decomposed from routers/cases.py."""
from __future__ import annotations

from .naming import router as naming_router, suggest_assignment_name
from .work_splits import (
    get_case_work_split,
    list_case_work_splits,
    reassign_case_work_item,
    review_work_split_options,
    reviewers,
    router as work_splits_router,
)

__all__ = [
    "get_case_work_split",
    "list_case_work_splits",
    "naming_router",
    "reassign_case_work_item",
    "review_work_split_options",
    "reviewers",
    "suggest_assignment_name",
    "work_splits_router",
]
