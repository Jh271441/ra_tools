"""Compatibility imports for the domain modules in :mod:`app.support`.

Application code should import from the owning support module directly.
"""

from __future__ import annotations

from .filenames import safe_filename as _safe_filename
from .runtime import _public_path
from .support.common import (
    _detail,
    _as_text,
)
from .support.model_source import (
    _model_source_artifact_path,
    _store_model_source,
    _model_source_file,
    _source_preview_value,
    _model_source_filename,
    _reconstructed_model_source,
)
from .support.external_links import (
    _voyager_issue_url,
    _ra_recording_url,
    _case_external_links,
    _case_link_metadata_fallback,
    _autotriage_record_url,
    _public_batch_job,
    _safe_autotriage_batch,
)
from .support.thumbnails import (
    _thumbnail_cache_path,
    _render_case_thumbnail,
)
from .support.identity import (
    _action_actor,
    _can_manage_team_default,
    _admin_identity,
    _intent_identity,
)
from .support.catalogs import (
    _review_tag_catalog,
    _missing_evidence_catalog,
    _csv_filter_values,
    resolve_review_exclusion_filter,
    _parse_issue_id_filter,
    _review_tag_payload,
    _validate_review_tag_input,
    _normalise_review_tags,
    _normalise_missing_evidence,
    _normalise_review_excluded,
)
from .support.filter_parsing import _case_filter_kwargs
from .support.review_payloads import _review_reason_analysis_payload
from .support.autotriage import _fetch_autotriage_snapshot
from .support.attachments import (
    _normalise_review_image,
    _store_review_attachments,
    _store_comment_attachments,
    _store_image_attachments,
    _persist_image_attachments,
    _public_review_attachment,
    _public_comment_attachment,
)
from .support.annotations import _create_annotation_record
from .support.baselines import (
    bootstrap_model_result,
    bootstrap_baseline,
    bootstrap_all_baselines,
    resolve_request_baseline_ids,
    resolve_request_baseline_scopes,
    media_for_issue,
    _infer_baseline_ids_from_scope_coverage,
    enrich_model_run_baseline_hint,
)
from .support.gt_sync import (
    configured_gt_sync_baseline_ids,
    resolve_gt_sync_baseline_ids,
    _gt_sync_item,
    gt_sync_status,
    _mark_authoritative_gt_sync_running,
    reserve_authoritative_gt_sync,
    sync_authoritative_gt,
)
from .support.trail_models import sync_trail_model_fields
