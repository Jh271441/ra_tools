"""Compatibility facade for labeling storage.

Own implementations live in the domain mixins; Database keeps its established
method surface and transaction ownership. Shared helper imports remain available
for existing internal callers.
"""
from .labeling_scope import LabelingScopeMixin
from .labeling_records import LabelingRecordsMixin
from .labeling_decisions import LabelingDecisionsMixin
from .labeling_projection import LabelingProjectionMixin
from .labeling_queries import LabelingQueriesMixin
from .labeling_exports import LabelingExportsMixin
from .labeling_reconciliation import LabelingReconciliationMixin
from .labeling_migration import LabelingMigrationMixin
from .labeling_shared import ISSUE_LABEL_GT_RELATIONS, ISSUE_LABEL_STATES, ISSUE_LABEL_STATE_FILTERS, LABEL_TASK_KINDS, _clean_values, _filter_values, _issue_decision_source_payload, _issue_label_gt_relation, _parse_labeling_cluster, _source_fingerprint


class DatabaseLabelingMixin(
    LabelingScopeMixin,
    LabelingRecordsMixin,
    LabelingDecisionsMixin,
    LabelingProjectionMixin,
    LabelingQueriesMixin,
    LabelingExportsMixin,
    LabelingReconciliationMixin,
    LabelingMigrationMixin,
):
    """Versioned labels, decisions, queries and export workflows."""
