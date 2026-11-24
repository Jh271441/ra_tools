"""Versioned, additive Scenario annotations, independent of simulation inputs.

Only the explicit offline publisher writes upstream. Browser APIs read receipts.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from app.repositories import state_store
from app.services.release_cycle import digest
from app.services import release_workflow as w

MEMBERSHIPS = (
    "precision_numerator",
    "precision_denominator",
    "recall_numerator",
    "recall_denominator",
)
PHYSICAL_FIELDS = (
    "id",
    "version",
    "name",
    "scenario",
    "start_timestamp",
    "end_timestamp",
    "trip_id",
    "scenario_tags",
    "review_status",
    "is_deleted",
    "description",
    "car_id",
    "platform",
    "support_platform",
    "scenario_type",
    "tag",
)


def now():
    return datetime.now(timezone.utc).isoformat()


def labels(row):
    values = row.get("labels")
    if isinstance(values, str):
        values = json.loads(values) if values.startswith("[") else values.split(",")
    if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
        raise ValueError("invalid_scenario_labels")
    return set(values)


def physical(row):
    return {k: row.get(k) for k in PHYSICAL_FIELDS}


def build_plan(revision):
    if not revision or revision.get("reconciliation", {}).get("status") != "matched":
        raise ValueError("evaluation_not_reconciled")
    ctx, profile = revision["context"], revision["profile"]
    if profile.get("status") != "published":
        raise ValueError("published_profile_required")
    scene_index = {str(s["scenario_id"]): s for s in revision["payload"]["scenarios"]}
    if len(scene_index) != len(revision["payload"]["scenarios"]):
        raise ValueError("duplicate_scenario_identity")
    issue_index = {str(i["issue_id"]): i for i in revision["payload"]["issues"]}
    members, scenes, pending = [], {}, []
    for row in sorted(revision["rows"], key=lambda r: r["issue_id"]):
        flags = row["auto_memberships"]
        if set(flags) != set(MEMBERSHIPS) or any(
            type(v) is not int or v not in (0, 1) for v in flags.values()
        ):
            raise ValueError("invalid_memberships")
        eligible = bool(flags["precision_denominator"] or flags["recall_denominator"])
        if row["eligible"] is not eligible:
            raise ValueError("membership_scope_mismatch")
        if not eligible:
            continue
        if row["ra_type"] not in (2, 3):
            raise ValueError("invalid_source_trigger")
        item = {
            "issue_id": row["issue_id"],
            "label": row["auto_label"],
            "ra_type": row["ra_type"],
            "memberships": deepcopy(flags),
            "scenario_ids": sorted(set(row["scenario_ids"])),
        }
        members.append(item)
        if not item["scenario_ids"]:
            pending.append(row["issue_id"])
        for sid in item["scenario_ids"]:
            if (
                sid not in scene_index
                or str(scene_index[sid]["issue_id"]) != row["issue_id"]
                or sid in scenes
            ):
                raise ValueError("scenario_identity_mismatch")
            scene = scene_index[sid]
            if type(scene.get("scenario_revision")) is not int or any(
                type(scene.get(k)) is not int for k in ("start_timestamp", "end_timestamp")
            ):
                raise ValueError("unverified_scenario_input")
            scenes[sid] = {
                "scenario_id": sid,
                "issue_id": row["issue_id"],
                "scenario_revision": scene["scenario_revision"],
                "start_timestamp": scene["start_timestamp"],
                "end_timestamp": scene["end_timestamp"],
                "trip_id": issue_index[row["issue_id"]].get("trip_id"),
                "memberships": deepcopy(flags),
                "ra_type": row["ra_type"],
            }
    identity = {
        "context": ctx,
        "config_hash": profile["config_hash"],
        "members": members,
        "scenarios": [scenes[sid] for sid in sorted(scenes)],
    }
    identifier = digest(identity)
    namespace = f"ra_autotriage_{ctx['release'][-8:]}_{identifier[:16]}"
    for scene in scenes.values():
        scene["add_labels"] = [
            namespace,
            namespace + ("_AutoTrigger" if scene["ra_type"] == 2 else "_ManualTrigger"),
            *[namespace + "_" + key for key in MEMBERSHIPS if scene["memberships"][key]],
        ]
    return {
        "schema": "autotriage_scenario_labels_v1",
        "id": identifier,
        "namespace": namespace,
        "context": deepcopy(ctx),
        "revision_key": revision["revision_key"],
        "config_hash": profile["config_hash"],
        "eligible_issues": len(members),
        "mapped_issues": len(members) - len(pending),
        "pending_issues": pending,
        "scenarios": [scenes[sid] for sid in sorted(scenes)],
    }


def verify_identity(scene, expected):
    if (
        str(scene.get("id")) != expected["scenario_id"]
        or scene.get("is_deleted")
        or scene.get("version") != expected["scenario_revision"]
        or any(scene.get(k) != expected[k] for k in ("start_timestamp", "end_timestamp"))
        or (
            expected.get("trip_id") is not None
            and str(scene.get("trip_id")) != str(expected["trip_id"])
        )
    ):
        raise ValueError("scenario_input_changed")
    namespace = expected["add_labels"][0]
    if {v for v in labels(scene) if v == namespace or v.startswith(namespace + "_")} - set(
        expected["add_labels"]
    ):
        raise ValueError("scenario_namespace_membership_mismatch")
    source = {v for v in labels(scene) if v.startswith("#") and v[1:].isdigit()}
    if source != {"#" + expected["issue_id"].removeprefix("cn")}:
        raise ValueError("scenario_source_changed")


def verify_after(before, after, expected):
    verify_identity(after, expected)
    if physical(before) != physical(after):
        raise ValueError("scenario_physical_revision_changed")
    if not labels(before) <= labels(after) or not set(expected["add_labels"]) <= labels(after):
        raise ValueError("scenario_labels_not_preserved")
    namespace = expected["add_labels"][0]
    actual = {v for v in labels(after) if v == namespace or v.startswith(namespace + "_")}
    if actual != set(expected["add_labels"]):
        raise ValueError("scenario_namespace_membership_mismatch")


def index_key(ctx):
    return "evscene_labels:" + digest(ctx)[:48]


def issue_key(ctx, issue_id):
    return "evscene_tags:" + digest([ctx, issue_id])[:48]


def save_verified(db, plan, verified):
    if set(verified) != {s["scenario_id"] for s in plan["scenarios"]}:
        raise ValueError("scenario_label_coverage_incomplete")
    grouped = {}
    for expected in plan["scenarios"]:
        sid = expected["scenario_id"]
        row = verified[sid]
        verify_identity(row, expected)
        if not set(expected["add_labels"]) <= labels(row):
            raise ValueError("scenario_labels_missing")
        grouped.setdefault(expected["issue_id"], []).append(
            {
                "issue_id": expected["issue_id"],
                "scenario_id": sid,
                "scenario_labels": sorted(labels(row)),
                "autotriage_labels": expected["add_labels"],
                "scenario_revision": row["version"],
            }
        )
    stamp = now()
    ctx_hash = digest(plan["context"])
    state_store.batch_upsert_scenario_tags(
        db,
        context_hash=ctx_hash,
        plan_id=plan["id"],
        revision_key=plan["revision_key"],
        namespace=plan["namespace"],
        checked_at=stamp,
        grouped_items=grouped,
        commit=False,
    )
    summary = {
        k: deepcopy(plan[k])
        for k in (
            "id",
            "namespace",
            "context",
            "revision_key",
            "config_hash",
            "eligible_issues",
            "mapped_issues",
            "pending_issues",
        )
    }
    summary.update(
        status="complete", checked_at=stamp, scenario_count=len(verified), query_verified=True
    )
    w.put_state(db, index_key(plan["context"]), summary)
    return summary


def issue_labels(db, ctx, issue_id, current_revision_key, current_plan_id=None):
    index = w.get_state(db, index_key(ctx))
    record = state_store.get_scenario_tag(
        db, digest(ctx), issue_id, legacy_key=issue_key(ctx, issue_id)
    )
    status = "missing"
    if index:
        status = index.get("status", "missing")
        changed = (
            index.get("id") != current_plan_id
            if current_plan_id is not None
            else index.get("revision_key") != current_revision_key
        )
        if status == "complete" and (changed or record.get("plan_id") != index.get("id")):
            status = (
                "pending"
                if issue_id in index.get("pending_issues", [])
                else "excluded"
                if not record
                else "stale"
            )
    return {
        "status": status,
        "namespace": index.get("namespace"),
        "checked_at": record.get("checked_at"),
        "revision_key": record.get("revision_key"),
        "items": record.get("items", []) if status == "complete" else [],
    }
