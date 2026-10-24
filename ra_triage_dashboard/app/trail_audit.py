"""Shared audit boundary for info-only writers; no credentials or model payloads."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy

from .db_parts.trail_history import encoded
from .trail_exclusion_contracts import normalise_trail_info_value

OWNED_KEYS = ("should_exclude", "should_exclude_comment", "operation_id")


def info_object(value):
    value = normalise_trail_info_value(value)
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or not isinstance(value.get("ra_triage_dashboard", {}), dict):
        raise ValueError("Trail info 格式异常 / Invalid Trail info")
    return deepcopy(value)


def owned(value):
    namespace = info_object(value).get("ra_triage_dashboard", {})
    return {key: namespace[key] for key in OWNED_KEYS if key in namespace}


def snapshots(changes, rows, field):
    before = {row["issue_id"]: row for row in rows}
    result = []
    for change in changes:
        issue = change["issue_id"]
        if set(change) != {"issue_id", field} or issue not in before:
            raise ValueError("Only complete info-only changes can enter Trail audit")
        old, new = info_object(before[issue].get(field)), info_object(change[field])
        # Prove that no non-owned JSON path is being changed.
        for obj in (old, new):
            namespace = obj.get("ra_triage_dashboard", {})
            for key in OWNED_KEYS:
                namespace.pop(key, None)
            if not namespace:
                obj.pop("ra_triage_dashboard", None)
        if encoded(old) != encoded(new):
            raise ValueError("Trail audit refuses unowned field changes")
        result.append({"issue_id": issue, "field": field,
                       "before": owned(before[issue].get(field)), "after": owned(change[field])})
    return result


async def audited_write(*, database, settings, identity, operation_id, source,
                        changes, current_rows, info_field, writer, readback,
                        parent_id=None, reason=""):
    """Durable intent precedes external I/O. Failure cannot erase first snapshots."""
    if changes:
        items = snapshots(changes, current_rows, info_field)
        await asyncio.to_thread(database.begin_trail_operation,
            operation_id=operation_id, actor=identity.username,
            actor_source=identity.source, actor_verified=identity.verified,
            source=source, items=items, parent_id=parent_id, reason=reason)
    async def attempt():
        try:
            stats = await asyncio.to_thread(writer, changes,
                ra_root=settings.ra_auto_triage_root, chunk_size=settings.trail_attribute_write_chunk_size)
            verification = await readback(changes, stats, result_field="", info_field=info_field)
        except Exception:
            if changes:
                await asyncio.to_thread(database.append_trail_event, operation_id,
                    "unknown", {item["issue_id"]: "unknown" for item in changes})
            raise
        if changes:
            uncertain = set(stats.get("failed_issue_ids", [])) | set(verification.get("missing_issue_ids", [])) | set(verification.get("mismatched_issue_ids", []))
            if not verification.get("complete"):
                uncertain.update(item["issue_id"] for item in changes)
            outcomes = {item["issue_id"]: "unknown" if item["issue_id"] in uncertain else "succeeded" for item in changes}
            status = "succeeded" if all(v == "succeeded" for v in outcomes.values()) else "partial" if "succeeded" in outcomes.values() else "unknown"
            await asyncio.to_thread(database.append_trail_event, operation_id, status, outcomes)
        return stats, verification
    task = asyncio.create_task(attempt())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A cancelled HTTP request cannot cancel the transport thread. Keep the
        # caller's commit guard held until transport/readback/audit have settled.
        try:
            await task
        finally:
            raise


def restore_changes(operation, current_rows, operation_id):
    """Inverse owned paths only; retain current unowned keys and a NEW operation marker."""
    rows = {row["issue_id"]: row for row in current_rows}
    changes, conflicts = [], []
    for item in operation["items"]:
        issue, field = item["issue_id"], item["field"]
        current = rows.get(issue)
        if current is None or encoded(owned(current.get(field))) != encoded(item["after"]):
            conflicts.append(issue)
            continue
        info = info_object(current.get(field))
        namespace = info.setdefault("ra_triage_dashboard", {})
        for key in OWNED_KEYS:
            if key == "operation_id":
                namespace[key] = operation_id
            elif key in item["before"]:
                namespace[key] = deepcopy(item["before"][key])
            else:
                namespace.pop(key, None)
        changes.append({"issue_id": issue, field: info})
    return changes, conflicts


async def reconcile_existing(database, operation_id, rows, info_field):
    """A retry can confirm an earlier uncertain write without losing its original before."""
    operation = await asyncio.to_thread(database.trail_operation, operation_id)
    if not operation or operation["source"] == "legacy":
        return
    current = {row["issue_id"]: row for row in rows}
    outcomes = {item["issue_id"]: "succeeded" for item in operation["items"]
                if item["issue_id"] in current and item["field"] == info_field
                and encoded(owned(current[item["issue_id"]].get(info_field))) == encoded(item["after"])}
    if outcomes:
        await asyncio.to_thread(database.append_trail_event, operation_id,
            "succeeded" if len(outcomes) == len(operation["items"]) else "partial", outcomes)
