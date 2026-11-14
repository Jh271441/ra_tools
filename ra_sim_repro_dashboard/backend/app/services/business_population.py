"""Read-only publication scope against the latest collected release population.

A publication proves its immutable execution population. It does not prove that
later release collection has stopped or that new Issues have been evaluated.
Keep that distinction out of publication approvals and physical result audits.
"""
from datetime import datetime
import re

from sqlalchemy import select

from app.models import ReleaseIssueSnapshot


def _identity(rows, release):
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty population")
    values = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid Issue")
        issue_id = row.get("issue_id")
        ra_type = row.get("ra_type")
        issue_time = row.get("issue_time")
        version = row.get("version")
        if (not isinstance(issue_id, str) or not issue_id.strip() or issue_id in values
                or isinstance(ra_type, bool) or str(ra_type) not in ("2", "3")
                or isinstance(issue_time, bool) or not str(issue_time).isdigit()
                or int(issue_time) <= 0 or not isinstance(version, str)
                or not re.fullmatch(r"(?:1\.)?" + re.escape(release) + r"(?:\.\d+)?", version)):
            raise ValueError("invalid or duplicate population identity")
        # GT is intentionally absent. The separate label-cycle audit decides
        # whether changed labels can reuse existing physical executions.
        values[issue_id] = (int(ra_type), version, int(issue_time))
    return values


def _period_bounds(period, release):
    if (not isinstance(period, dict) or period.get("release") != release
            or period.get("verified") is not True or period.get("status") != "completed"):
        raise ValueError("unverified period")
    start = datetime.fromisoformat(period["case_start"])
    end = datetime.fromisoformat(period["case_end_exclusive"])
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("invalid period boundaries")
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _full_source(payload, release):
    if (not isinstance(payload, dict) or payload.get("population_complete") is not True
            or payload.get("source_scope", "full_period") != "full_period"):
        raise ValueError("source is not a complete full population")
    identity = _identity(payload.get("issues"), release)
    lo, hi = _period_bounds(payload.get("period"), release)
    if any(not lo <= row[2] < hi for row in identity.values()):
        raise ValueError("source is outside the verified period")
    return identity


def _evaluated_count(payload):
    for summary in ((payload.get("result_import") or {}).get("subset_summary"), payload.get("summary")):
        count = summary.get("eligible") if isinstance(summary, dict) else None
        if type(count) is int and count >= 0:
            return count
    return 0


def _counts(identity):
    return {"collected_issue_count": len(identity),
            "auto_count": sum(row[0] == 2 for row in identity.values()),
            "manual_count": sum(row[0] == 3 for row in identity.values())}


def _validate_batch_population(rows, frozen):
    # make_plan deliberately stores only Issue ID/type/GT in execution plans.
    # Version/time identity comes from the matching immutable source snapshot.
    if not isinstance(rows, list) or len(rows) != len(frozen):
        raise ValueError("batch population is not the frozen source")
    seen = set()
    for row in rows:
        issue_id = row.get("issue_id") if isinstance(row, dict) else None
        if (not isinstance(issue_id, str) or issue_id not in frozen or issue_id in seen
                or isinstance(row.get("ra_type"), bool) or str(row.get("ra_type")) not in ("2", "3")
                or int(row["ra_type"]) != frozen[issue_id][0]):
            raise ValueError("batch Issue identity differs from its source")
        seen.add(issue_id)
        if "version" in row and row["version"] != frozen[issue_id][1]:
            raise ValueError("batch version differs from its source")
        if "issue_time" in row and (isinstance(row["issue_time"], bool)
                or not str(row["issue_time"]).isdigit() or int(row["issue_time"]) != frozen[issue_id][2]):
            raise ValueError("batch Issue time differs from its source")


def scope_for_batch(db, batch):
    """Explain whether a native frozen publication covers current collection.

    This function neither queries upstream nor changes snapshots, approvals,
    execution state or label revisions. Missing evidence fails closed.
    """
    from app.services.read_views import read_projection
    return read_projection(db, ("business-population", batch.fingerprint, batch.updated_at),
                           lambda: _scope_for_batch(db, batch))


def historical_scope(scope, *, is_current):
    """Retain an audited past cutoff without calling it current full coverage."""
    if (not is_current and scope.get('reason_code') == 'population_changed'
            and scope.get('frozen_issue_count') is not None
            and scope.get('collection_status') == 'stable'
            and scope.get('collection_completed') is True and not scope.get('stale')):
        return {**scope, 'historical_frozen': True}
    return scope


def _scope_for_batch(db, batch):
    from app.services import release_workflow as workflow
    from app.services.release_inventory import inventory
    from app.services.read_views import read_projection

    payload = batch.payload if isinstance(batch.payload, dict) else {}
    release = batch.release
    result = {"available": False, "reason_code": "invalid_population",
              "collection_status": "pending", "collection_completed": False,
              "collected_issue_count": None, "auto_count": None, "manual_count": None,
              "evaluated_issue_count": _evaluated_count(payload), "frozen_issue_count": None,
              "observed_at": None, "stale": False}
    try:
        if payload.get("acceptance_only") or payload.get("release") != release:
            return result
        lo, hi = _period_bounds(payload.get("period"), release)
        snapshots = db.scalars(select(ReleaseIssueSnapshot).where(
            ReleaseIssueSnapshot.release == release).order_by(ReleaseIssueSnapshot.id.desc())
            .execution_options(yield_per=1))
        try:
            latest = next(snapshots, None)
            original = None
            for snapshot in ([latest] if latest is not None else []):
                if workflow.population_identity(snapshot.payload) == payload.get("population_hash"):
                    original = snapshot
            if original is None:
                original = next((snapshot for snapshot in snapshots
                                 if workflow.population_identity(snapshot.payload) == payload.get("population_hash")), None)
            if latest is None or original is None:
                return result
            frozen = _full_source(original.payload, release)
            _validate_batch_population(payload.get("issues"), frozen)
            if _period_bounds(original.payload.get("period"), release) != (lo, hi):
                return result
            result["frozen_issue_count"] = len(frozen)
            latest_payload = latest.payload
        finally:
            snapshots.close()

        observation = workflow.get_state(db, "release_observation:" + release)
        if observation:
            if observation.get("release") != release:
                return result
            current = _identity(observation.get("issues"), release)
            result.update(_counts(current), observed_at=observation.get("observed_at"))
            observed_at = datetime.fromisoformat(observation["observed_at"])
            if observed_at.tzinfo is None:
                return result
            collections = read_projection(db, "business-population-inventory", lambda: inventory(db))
            collection = next((item for item in collections["versions"] if item["release"] == release), None)
            if collection:
                result.update(collection_status=collection.get("collection_status", "pending"),
                              collection_completed=collection.get("collection_completed") is True,
                              stale=collection.get("stale") is not False)
            # An any-old-batch change flag is not a population identity check.
            if current != frozen or any(not lo <= row[2] < hi for row in current.values()):
                result["reason_code"] = "population_changed"
                return result
            monitor = workflow.get_state(db, "release_monitor:" + release)
            if not monitor:
                legacy = workflow.get_state(db, "release_monitor")
                monitor = legacy if legacy.get("release") == release else {}
            same_observation = (bool(observation.get("activity_hash"))
                                and monitor.get("activity_hash") == observation["activity_hash"])
            if not collection or result["stale"] or not result["collection_completed"] or not same_observation:
                result["reason_code"] = "collecting"
                return result
        else:
            # Legacy full releases may have no observer. Their original complete
            # source and latest full source must still cover the same population.
            current = _full_source(latest_payload, release)
            result.update(_counts(current), collection_status="stable", collection_completed=True,
                          observed_at=latest.created_at.isoformat() if latest.created_at else None)
            if current != frozen:
                result["reason_code"] = "population_changed"
                return result
        result.update(available=True, reason_code="")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        # Malformed local evidence cannot promote a subset to current business
        # metrics. Operational/database errors are not disguised as valid data.
        pass
    return result
