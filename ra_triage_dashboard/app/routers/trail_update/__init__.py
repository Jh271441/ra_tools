"""Trail attribute-update router and compatibility surface."""

from ...runtime import database, settings
from ...trail_exclusion_contracts import (
    TRAIL_INFO_FIELD,
    TRAIL_ISSUE_EXCLUSION_COMMENT,
    TRAIL_RESULT_FIELD,
    TRAIL_TARGET_PATH,
    normalise_issue_entries as _normalise_issue_entries,
    trail_update_statuses as _trail_update_statuses,
)
from .imports import (
    _append_historical_source_note,
    _historical_source_payload,
    _resolve_historical_exclusion_entries,
    _issue_import_header_key,
    _issue_import_normalized_row,
    _issue_import_field,
    _issue_import_has_column,
    _issue_import_exclusion_value,
    _issue_import_issue_ids,
    _issue_import_display_filename,
    _issue_import_excel_source_note,
    _issue_import_json_rows,
    build_trail_issue_import_preview,
)
from .preview import (
    _field_names,
    _review_exclusion_candidate_rows,
    _capability_not_checked,
    _capability_payload,
    _capability_for_required_field,
    _capability_for_info_write,
    _remember_preview_status_expectations,
    _preview_status_expectations,
    _read_preview_trail_status_sync,
    _read_preview_trail_status,
    build_trail_attribute_update_payload,
    build_trail_issue_exclusion_payload,
    _build_preview,
    _build_direct_preview,
)
from .commit import (
    _append_exclusion_note,
    _mark_local_review_exclusions,
    _readback_changes,
    _save_issue_exclusion_history,
)
from .routes import (
    trail_attribute_update_preview,
    trail_attribute_update_status,
    trail_issue_exclusion_history,
    trail_historical_exclusions,
    trail_issue_json_import_preview,
    trail_issue_excel_import_preview,
    trail_issue_exclusion_preview,
    trail_attribute_update_commit,
    trail_issue_exclusion_commit,
)
from .preview import _preview_capability_cache
from .routes import router
