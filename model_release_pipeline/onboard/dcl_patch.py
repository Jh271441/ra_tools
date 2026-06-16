"""DCL patch step: apply a DCL revision inside Voyager docker."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Dict

from model_release_pipeline.config import ReleaseConfig
from model_release_pipeline.services.voyager_handoff import VoyagerHandoffService
from model_release_pipeline.state_store import StateStore

ConfirmFn = Callable[[str, bool], bool]
ProgressFn = Callable[..., None]


def run_dcl_patch(
    args: argparse.Namespace,
    config: ReleaseConfig,
    store: StateStore,
    record: Dict[str, Any],
    *,
    progress: ProgressFn,
    confirm: ConfirmFn,
    service_cls: Any = VoyagerHandoffService,
) -> Dict[str, Any]:
    revision_id = str(getattr(args, "revision_id", "") or "").strip()
    if not revision_id:
        raise RuntimeError("dcl-patch requires --revision-id.")
    nobranch = bool(getattr(args, "nobranch", True))

    action_text = f"dcl patch --revision {revision_id}"
    if nobranch:
        action_text += " --nobranch"
    if not confirm(f"Run {action_text!r} in Voyager docker?", args.yes):
        raise RuntimeError("dcl-patch cancelled by user.")

    progress(args, "DCL Patch", 1, 1, "🩹", f"revision {revision_id}")

    service = service_cls(config.voyager)
    result = service.dcl_patch_to_docker(
        ifx_config=config.ifx,
        revision_id=revision_id,
        nobranch=nobranch,
        container=str(getattr(args, "docker", "") or ""),
        dry_run=args.dry_run,
    )

    record["dcl_patch"] = result
    # Accumulate every applied CR so multiple patches on one working branch
    # don't overwrite each other (a release branch may stack several CRs).
    record.setdefault("dcl_patch_history", []).append(
        {
            "revision_id": revision_id,
            "nobranch": nobranch,
            "returncode": result.get("returncode"),
            "dry_run": bool(args.dry_run),
        }
    )
    if result.get("returncode") not in (0, None):
        record["stage"] = "dcl_patch_failed"
        record["status"] = "failed"
        store.add_error(record, "dcl-patch failed. See dcl_patch.stderr.")
    elif args.dry_run:
        record["stage"] = "dcl_patch_dry_run"
        record["status"] = "dry_run"
    else:
        record["stage"] = "dcl_patch_complete"
        record["status"] = "completed"
    store.save(record)
    return record
