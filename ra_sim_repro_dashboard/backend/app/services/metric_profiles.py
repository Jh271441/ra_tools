"""Immutable, declarative evaluation rules. No executable SQL or Python in configs."""

from contextlib import ExitStack, nullcontext
from copy import deepcopy
from datetime import datetime, timezone

from app.domain.hashing import digest
from app.domain.metrics import (
    BUILTIN,
    BUILTINS,
    DEFAULT_CONFIG,
    DEFAULT_FILTERS,
    EXCLUDED,
    GOOD,
    REVIEW,
    REVIEW_CONFIG,
    membership,
    resolution_for_config as resolution,
    resolve_label_for_config as resolve,
    validate_profile as validate,
)
from app.infra.locks import pipeline_lock
from app.models import ReleaseWorkflowState
from app.repositories import profile_repo
from app.services import evaluation_pipeline as pipeline, release_workflow as w


def now():
    return datetime.now(timezone.utc).isoformat()


def get(db, version=None):
    return profile_repo.get_profile(db, version)


def catalogue(db):
    return profile_repo.list_catalogue(db)


def draft(db, config, name, description, parent=None):
    return profile_repo.create_draft(db, config, name, description, parent)


def publish(db, version, preview_hash, *, activate=None):
    with pipeline_lock("profiles"):
        db.expire_all()
        preview = w.get_state(db, "evpreview:" + preview_hash[:48])
        with pipeline_lock("context:" + digest(preview.get("context", {}))):
            return _publish(db, version, preview_hash, activate=activate)


def _publish(db, version, preview_hash, *, activate=None):
    value = get(db, version)
    if value["status"] == "published":
        return value
    preview = w.get_state(db, "evpreview:" + preview_hash[:48])
    if (
        not preview
        or preview.get("profile_id") != version
        or preview.get("config_hash") != value["config_hash"]
    ):
        raise ValueError("profile_preview_required")
    view = pipeline.board(db, **preview["context"])
    if (
        view["stale"]
        or not view["revision"]
        or view["revision"]["revision_key"] != preview["base_revision"]
    ):
        raise ValueError("plan_stale")
    result = {
        **value,
        "id": "at_" + value["config_hash"][:24],
        "status": "published",
        "published_at": now(),
        "preview_hash": preview_hash,
    }
    key = "evprofile:" + result["id"]
    if not w.get_state(db, key):
        w.put_state(db, key, result)
    # Publication uses the verified preview receipt immediately. A later source
    # refresh may fail without discarding the newly reviewed metrics and plan.
    published = get(db, result["id"])
    ctx = {**preview["context"], "profile_id": published["id"]}
    with pipeline_lock("context:" + digest(ctx)) if ctx != preview["context"] else nullcontext():
        pipeline.publish_profile_revision(db, published, preview)
    # Preserve the legacy API contract. Review policies are staged until an
    # explicit activation validates every requested release/context together.
    if activate is True or activate is None and value["config"]["schema_version"] == 1:
        _activate(db, result["id"], [ctx], get(db)["id"], locked_contexts=[preview["context"]])
    return get(db, result["id"])


def activate(db, version, contexts, expected_active):
    with pipeline_lock("profiles"):
        return _activate(db, version, contexts, expected_active)


def _activate(db, version, contexts, expected_active, *, locked_contexts=()):
    if not isinstance(contexts, list) or not 1 <= len(contexts) <= 100:
        raise ValueError("profile_activation_context_invalid")
    db.expire_all()
    profile = get(db, version)
    if profile["status"] != "published":
        raise ValueError("profile_not_published")
    if get(db)["id"] != expected_active:
        raise ValueError("profile_active_changed")
    canonical = []
    for ctx in contexts:
        if (
            not isinstance(ctx, dict)
            or set(ctx) - {"release", "profile_id", "date_start", "date_end"}
            or ctx.get("profile_id") not in (None, version)
        ):
            raise ValueError("profile_activation_context_invalid")
        resolved, *_ = pipeline.context(db, **{**ctx, "profile_id": version})
        canonical.append(resolved)
    if len({digest(c) for c in canonical}) != len(canonical):
        raise ValueError("profile_activation_context_invalid")
    with ExitStack() as stack:
        stack.enter_context(pipeline_lock("sample-import"))
        for ctx in sorted(canonical, key=digest):
            if digest(ctx) not in {digest(c) for c in locked_contexts}:
                stack.enter_context(pipeline_lock("context:" + digest(ctx)))
        db.expire_all()
        receipts = []
        for ctx in canonical:
            view = pipeline.board(db, **ctx)
            revision = view["revision"]
            if (
                view["stale"]
                or not revision
                or view["sample_source"]["status"] != "ready"
                or revision["reconciliation"]["status"] != "matched"
            ):
                raise ValueError("profile_activation_revision_required")
            receipts.append(
                {
                    "context": ctx,
                    "revision_key": revision["revision_key"],
                    "sample_snapshot_id": view["sample_source"]["snapshot_id"],
                }
            )
        prior = w.get_state(db, "evprofile:active")
        value = {
            "id": version,
            "previous_id": expected_active,
            "activated_at": now(),
            "contexts": receipts,
            "previous_pointer": deepcopy(prior),
        }
        # One commit makes the activation pointer and audit visible atomically.
        audit_key = "evactivation:" + digest(value)[:48]
        pointer = db.get(ReleaseWorkflowState, "evprofile:active") or ReleaseWorkflowState(
            key="evprofile:active"
        )
        pointer.payload = {k: v for k, v in value.items() if k != "previous_pointer"}
        db.add(pointer)
        db.add(ReleaseWorkflowState(key=audit_key, payload=value))
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"active": version, "audit_key": audit_key, "contexts": receipts}
