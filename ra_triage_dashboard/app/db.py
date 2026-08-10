from __future__ import annotations

from .db_parts.shared import (
    ACCESS_ROLES,
    BATCH_JOB_STATUSES,
    BATCH_PUBLISH_STATUSES,
    COMPARISON_STATUSES,
    LABELS,
    REVIEW_STATUSES,
    AnnotationConflictError,
    _CompatRow,
    _EXPECTED_ANNOTATION_UNSET,
    _json,
    _json_load,
    _postgres_sql,
    _PostgresConnection,
    _PostgresCursor,
    _NoopCursor,
    redact_sensitive_fields,
    utc_now,
)

from .db_parts.access import DatabaseAccessMixin
from .db_parts.batch import DatabaseBatchMixin
from .db_parts.cases import DatabaseCasesMixin
from .db_parts.core import DatabaseCoreMixin
from .db_parts.gt_sync import DatabaseGtSyncMixin
from .db_parts.review import DatabaseReviewMixin
from .db_parts.runs import DatabaseRunsMixin

class Database(
    DatabaseAccessMixin,
    DatabaseBatchMixin,
    DatabaseCasesMixin,
    DatabaseCoreMixin,
    DatabaseGtSyncMixin,
    DatabaseReviewMixin,
    DatabaseRunsMixin,
):
    """SQLite/PostgreSQL storage with versioned review history.

    ``baseline_scope`` is intentionally stored on the issue rather than
    deleting old imports.  This lets the active 0508/1071 evaluation set stay
    stable while uploaded model runs and prior reviews remain recoverable.
    """
