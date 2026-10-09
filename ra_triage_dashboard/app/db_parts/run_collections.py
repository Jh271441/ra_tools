"""Stable facade for Run collection storage and frozen evaluations."""
from .run_collection_rules import RunCollectionConflictError
from .run_collection_rules import RunRulesMixin
from .run_collection_records import RunRecordsMixin
from .run_collection_evaluation_create import RunEvaluationCreateMixin
from .run_collection_evaluation_queries import RunEvaluationQueriesMixin


class DatabaseRunCollectionsMixin(
    RunRulesMixin,
    RunRecordsMixin,
    RunEvaluationCreateMixin,
    RunEvaluationQueriesMixin,
):
    """Compose storage, creation/retry and read projections without changing API."""
