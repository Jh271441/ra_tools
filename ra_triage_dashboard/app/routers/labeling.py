"""Public labeling router and stable handler imports.

Implementations are grouped by HTTP workflow under labeling_api. Permissions,
serialization and active-scope guards have one explicit owner in common.
"""
from fastapi import APIRouter
from .labeling_api.common import _labeling_filter_values, _public_label_attachment, _public_label_case, _public_label_revision, _labeling_actor, _labeling_snapshot_actor, _snapshot_allow_partial, _require_labeling_admin, _require_labeling_writer, _active_labeling_scopes, _require_active_labeling_issue, _require_active_gt_export_batch, _labeling_payload
from .labeling_api.tasks import list_labeling_tasks, create_labeling_task
from .labeling_api.tasks import router as tasks_router
from .labeling_api.queries import list_labeling_cases, labeling_summary, list_labeling_clusters, get_labeling_case
from .labeling_api.queries import router as queries_router
from .labeling_api.decisions import list_issue_label_decisions, adjudicate_issue_label, adjudicate_label_case
from .labeling_api.decisions import router as decisions_router
from .labeling_api.comments import _public_label_comment, _create_label_comment_record, list_labeling_comments, create_labeling_comment, create_labeling_comment_with_attachments
from .labeling_api.comments import router as comments_router
from .labeling_api.revisions import create_label_revision, create_label_revision_with_attachments, get_label_attachment
from .labeling_api.revisions import router as revisions_router
from .labeling_api.snapshots import get_gt_candidates, list_gt_snapshots, get_gt_snapshot, create_label_result_snapshot, get_label_result_snapshot
from .labeling_api.snapshots import router as snapshots_router
from .labeling_api.exports import create_gt_export_preview, get_gt_export_preview, reconcile_gt_export_preview, export_gt_candidates
from .labeling_api.exports import router as exports_router

router = APIRouter()
router.routes.append(next(route for route in tasks_router.routes if route.endpoint is list_labeling_tasks))
router.routes.append(next(route for route in tasks_router.routes if route.endpoint is create_labeling_task))
router.routes.append(next(route for route in queries_router.routes if route.endpoint is list_labeling_cases))
router.routes.append(next(route for route in queries_router.routes if route.endpoint is labeling_summary))
router.routes.append(next(route for route in queries_router.routes if route.endpoint is list_labeling_clusters))
router.routes.append(next(route for route in queries_router.routes if route.endpoint is get_labeling_case))
router.routes.append(next(route for route in decisions_router.routes if route.endpoint is list_issue_label_decisions))
router.routes.append(next(route for route in decisions_router.routes if route.endpoint is adjudicate_issue_label))
router.routes.append(next(route for route in comments_router.routes if route.endpoint is list_labeling_comments))
router.routes.append(next(route for route in comments_router.routes if route.endpoint is create_labeling_comment))
router.routes.append(next(route for route in comments_router.routes if route.endpoint is create_labeling_comment_with_attachments))
router.routes.append(next(route for route in revisions_router.routes if route.endpoint is create_label_revision))
router.routes.append(next(route for route in revisions_router.routes if route.endpoint is create_label_revision_with_attachments))
router.routes.append(next(route for route in revisions_router.routes if route.endpoint is get_label_attachment))
router.routes.append(next(route for route in decisions_router.routes if route.endpoint is adjudicate_label_case))
router.routes.append(next(route for route in snapshots_router.routes if route.endpoint is get_gt_candidates))
router.routes.append(next(route for route in snapshots_router.routes if route.endpoint is list_gt_snapshots))
router.routes.append(next(route for route in snapshots_router.routes if route.endpoint is get_gt_snapshot))
router.routes.append(next(route for route in snapshots_router.routes if route.endpoint is create_label_result_snapshot))
router.routes.append(next(route for route in snapshots_router.routes if route.endpoint is get_label_result_snapshot))
router.routes.append(next(route for route in exports_router.routes if route.endpoint is create_gt_export_preview))
router.routes.append(next(route for route in exports_router.routes if route.endpoint is get_gt_export_preview))
router.routes.append(next(route for route in exports_router.routes if route.endpoint is reconcile_gt_export_preview))
router.routes.append(next(route for route in exports_router.routes if route.endpoint is export_gt_candidates))
