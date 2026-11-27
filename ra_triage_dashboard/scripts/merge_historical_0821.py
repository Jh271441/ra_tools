"""Consolidate the frozen 0821 historical split receipt into two ordinary Campaigns."""

import argparse
from collections import Counter, defaultdict
from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path
import re
import uuid
from unittest.mock import patch

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.db_parts.campaign_common import _fingerprint
from ra_triage_dashboard.app.db_parts.shared import _json, utc_now
from ra_triage_dashboard.app.group_allocation import grouped_config
from ra_triage_dashboard.app.task_reallocation import bounded_shares


POLICY = "0821-historical-dataset-merge-v1"
DATASETS = {"0821-odd2": "ODD2", "0821-nonodd2": "非 ODD2"}
EVIDENCE = {
    "model_review_revisions": ("campaign_id", "work_split_id", "model_run_id"),
    "model_review_heads": ("campaign_id", "model_run_id"),
    "combined_review_submissions": ("campaign_id", "model_run_id"),
    "combined_review_progress": ("campaign_id",),
    "review_work_assignment_changes": ("split_id",),
}
UNSUPPORTED_LINKS = {
    "label_cases": "task_id",
    "review_comments": "campaign_id",
    "dataset_task_bindings": "campaign_id",
    "human_label_scopes": "campaign_id",
    "annotations": "work_split_id",
    "label_comment_links": "task_id",
}
PROTECTION_FIELDS = (
    "completed", "protected", "forbidden", "model_submitted", "coverage_locked",
    "frozen_cases", "adjudicated_cases",
)


class RehearsalComplete(Exception):
    def __init__(self, receipt):
        self.receipt = receipt


def require(condition, message):
    if not condition:
        raise ValueError(message)


def records(conn, table, column, campaign):
    return [dict(row) for row in conn.execute(
        f"SELECT * FROM {table} WHERE {column}=?", (campaign,),
    ).fetchall()]


def evidence_digest(rows, ignored=()):
    return sorted(_fingerprint({key: val for key, val in row.items() if key not in ignored}) for row in rows)


def read_source(db, conn, partition, expected):
    campaign = expected["task"]
    cfg, split, filters, assignments = db._task_allocation(conn, campaign)
    require(cfg["editable"] and not cfg["role_required"] and not cfg["appendable"]
            and split["workflow_mode"] == "model_review_and_case_label"
            and not split["task_group_id"], f"Unexpected task state: {campaign}")
    require(filters.get("partition_field") == "trip_odd"
            and filters.get("partition_parent_campaign_id")
            and "partition_value" in filters
            and filters["partition_value"] == expected["kind"]
            and filters.get("source_legacy_split_id")
            and split["evaluation_run_id"] == split["model_run_id"] == expected["run"],
            f"Unexpected provenance: {campaign}")
    for table, column in UNSUPPORTED_LINKS.items():
        require(not conn.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (campaign,)).fetchone(),
                f"Source has additional {table} records: {campaign}")
    proof = db._allocation_protection(conn, split, assignments)
    ids = {row["issue_id"] for row in proof["members"]}
    require(len(ids) == expected["cases"], f"Different frozen membership: {campaign}")
    groups, bindings = db._group_history(cfg, assignments, proof)
    refs = records(conn, "campaign_reference_items", "campaign_id", campaign)
    require(len(refs) == 1 and refs[0]["reference_type"] == "gt_snapshot",
            f"Expected one frozen GT reference: {campaign}")
    reference = {key: value for key, value in refs[0].items() if key not in {"campaign_id", "created_at"}}
    require(reference["reference_id"] == split["reference_id"], f"Inconsistent reference: {campaign}")
    linked = {table: records(conn, table, columns[0], campaign) for table, columns in EVIDENCE.items()}
    bound_roles = records(conn, "human_assignment_roles", "campaign_id", campaign)
    card = db.list_review_work_splits(lifecycle="current", split_id=campaign)[0]
    prediction_rows = [dict(row) for row in conn.execute("""
        SELECT p.* FROM model_predictions p JOIN campaign_issue_members m ON m.issue_id=p.issue_id
        WHERE m.campaign_id=? AND p.model_run_id=? ORDER BY p.issue_id
    """, (campaign, split["model_run_id"])).fetchall()]
    require(len(prediction_rows) == len(ids), f"Missing source prediction: {campaign}")
    require(all(row["issue_id"] in ids for rows in linked.values() for row in rows),
            f"Historical record outside task membership: {campaign}")
    require(all(row["issue_id"] in ids for row in bound_roles), f"Unexpected role scope: {campaign}")
    for table, columns in EVIDENCE.items():
        for row in linked[table]:
            require(all(row[column] == (split["model_run_id"] if column == "model_run_id" else campaign)
                        for column in columns), f"Unexpected ownership pointer: {table} / {campaign}")
    fingerprint = _fingerprint({
        "allocation": proof["snapshot"],
        "reference": reference,
        "predictions": evidence_digest(prediction_rows),
        "linked": {table: evidence_digest(rows) for table, rows in linked.items()},
        "roles": evidence_digest(bound_roles),
    })
    return dict(
        campaign=campaign, split=split, assignments=assignments, proof=proof, partition=partition,
        ids=ids, reference=reference, card=card, groups=groups, bindings=bindings, rules=cfg["cross_groups"],
        pairing=cfg["pairing_mode"], linked=linked, roles=bound_roles,
        predictions=prediction_rows, fingerprint=fingerprint,
        provenance=dict(campaign_id=campaign, legacy_split_id=filters["source_legacy_split_id"],
                        run_id=split["model_run_id"], case_count=len(ids)),
        unknown_count=len(ids) if filters["partition_value"] is None else 0,
    )


def combine_groups(sources):
    bindings = {issue: owners for source in sources for issue, owners in source["bindings"].items()}
    actual = defaultdict(Counter)
    for owners in bindings.values():
        for group_id, member in owners.items():
            actual[group_id][member] += 1
    require(actual and bindings, "No active allocation groups")
    require(len({source["pairing"] for source in sources}) == 1, "Different pairing modes need a separate merge")
    strategies = defaultdict(set)
    for source in sources:
        for group in source["groups"]:
            strategies[group["group_id"]].add(group["coverage_strategy"])
    require(all(len(options) == 1 for options in strategies.values()), "Different coverage strategies")
    groups = [
        dict(group_id=group, coverage_percent=round(100 * sum(weights.values()) / len(bindings), 2),
             coverage_strategy=next(iter(strategies[group])),
             members=[dict(name=name, review_percent=share / 100)
                      for name, share in bounded_shares(dict(sorted(weights.items())), 10000).items()])
        for group, weights in sorted(actual.items())
    ]
    rules = [rule for source in sources for rule in source["rules"]]
    return grouped_config(groups, bindings, rules, "total", pairing_mode=sources[0]["pairing"]), bindings


def create_composed_run(conn, sources, actor):
    predictions = [row for source in sources for row in source["predictions"]]
    run_by_issue = {row["issue_id"]: row["model_run_id"] for row in predictions}
    source_sha = _fingerprint([POLICY, evidence_digest(predictions)])
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{POLICY}:{source_sha}"))
    conn.execute("""
        INSERT INTO model_runs (id,name,source_name,source_sha256,schema_version,kind,is_default,
                                created_by,created_by_source,created_by_verified,metadata_json,created_at)
        VALUES (?,?,?,?,?,'upload',FALSE,?,?,FALSE,?,?)
    """, (run_id, "0821 历史联合复核", POLICY, source_sha, "v1", actor, "authorized_migration",
          _json({"source_run_by_issue": run_by_issue, "migration_policy": POLICY}), utc_now()))
    for source in sources:
        conn.execute("""
            INSERT INTO model_predictions (model_run_id,issue_id,trip_id,model_label,model_reason,
                                           model_confidence,model_extra_json,raw_json,created_at)
            SELECT ?,p.issue_id,p.trip_id,p.model_label,p.model_reason,p.model_confidence,
                   p.model_extra_json,p.raw_json,p.created_at
            FROM model_predictions p JOIN campaign_issue_members m ON m.issue_id=p.issue_id
            WHERE m.campaign_id=? AND p.model_run_id=?
        """, (run_id, source["campaign"], source["split"]["model_run_id"]))
    copied = records(conn, "model_predictions", "model_run_id", run_id)
    require(evidence_digest(copied, {"id", "model_run_id"}) ==
            evidence_digest(predictions, {"id", "model_run_id"}), "Copied predictions changed")
    return run_id


def archive_and_move(db, conn, source, target, run_id, backup_sha, actor):
    campaign = source["campaign"]
    closed = db.close_campaign(
        campaign_id=campaign, actor=actor, actor_source="authorized_migration",
        expected_revision=int(source["split"]["config_revision"]),
        idempotency_key=POLICY, reason="合并到 0821 对应数据集的联合复核任务。",
    )
    require(closed["snapshot_id"], f"Missing archive snapshot: {campaign}")
    for table, columns in EVIDENCE.items():
        assignment = ", ".join(f"{column}=?" for column in columns)
        changed = conn.execute(
            f"UPDATE {table} SET {assignment} WHERE {columns[0]}=?",
            (*(run_id if column == "model_run_id" else target for column in columns), campaign),
        ).rowcount
        require(changed == len(source["linked"][table]), f"Concurrent change: {campaign} / {table}")
    for row in source["roles"]:
        conn.execute("""
            INSERT INTO human_assignment_roles (campaign_id,issue_id,username,role,captured_at)
            VALUES (?,?,?,?,?)
        """, (target, row["issue_id"], row["username"], row["role"], row["captured_at"]))
    for row in source["assignments"]:
        conn.execute("""
            UPDATE review_work_assignments SET assigned_by=?,assigned_at=?
            WHERE split_id=? AND issue_id=? AND assignee=?
        """, (row["assigned_by"], row["assigned_at"], target, row["issue_id"], row["assignee"]))
    conn.execute("""
        INSERT INTO campaign_migration_map (source_table,source_id,campaign_id,purpose,mapping_status,
            mapping_evidence_json,source_inventory_sha256,policy_version,created_at)
        VALUES ('issue_work_splits',?,?,'model_review','archived_assignment',?,?,?,?)
    """, (campaign, campaign, _json(dict(
        target=target, source_run=source["split"]["model_run_id"], target_run=run_id,
        close_snapshot=closed["snapshot_id"], backup_sha256=backup_sha,
    )), source["fingerprint"], POLICY, utc_now()))


def merge_partition(db, conn, partition, sources, run_id, backup_sha, actor):
    config, bindings = combine_groups(sources)
    refs = {source["reference"]["reference_id"] for source in sources}
    require(len(refs) == 1, "Frozen GT references differ")
    reference = sources[0]["reference"]
    assignments = defaultdict(list)
    for source in sources:
        for row in source["assignments"]:
            assignments[row["issue_id"]].append(row)
    ids = sorted(assignments)
    filters = dict(
        baselines=[partition], manual_task=True, merged_review_sources=[source["provenance"] for source in sources],
        task_allocation=config, migration_policy=POLICY,
    )
    title = f"0821 历史 · {DATASETS[partition]} · 联合复核"
    workset = db.create_review_workset(
        baseline_scope=reference["baseline_scope"], issue_ids=ids, name=title,
        selection_source_run_id=run_id, source_filter={"baselines": [partition], "issue_ids": ids},
        created_by=actor, created_by_source="authorized_migration",
    )
    conflicts = db._review_overlap_conflicts(conn, [source["campaign"] for source in sources])
    target = db._campaign_create_in_connection(conn, spec=dict(
        name=title, purpose="model_review", workflow_mode="model_review_and_case_label",
        workset_id=workset["id"], evaluation_run_id=run_id, references=[reference],
        filters=filters, overlap_ratio=config["overlap_ratio"], idempotency_key=f"{POLICY}:{partition}",
        members=[dict(issue_id=issue, assignees=assignments[issue]) for issue in ids],
    ), actor=actor, actor_source="authorized_migration", actor_verified=False)

    # Assignment triggers populate default roles; use the original captured roles.
    conn.execute("DELETE FROM human_assignment_roles WHERE campaign_id=?", (target,))
    for source in sources:
        archive_and_move(db, conn, source, target, run_id, backup_sha, actor)
    current, split, _, rows = db._task_allocation(conn, target)
    proof = db._allocation_protection(conn, split, rows)
    for field in PROTECTION_FIELDS:
        require(proof[field] == set().union(*(source["proof"][field] for source in sources)),
                f"Protection changed: {partition} / {field}")
    for field in ("case_outputs", "captured_roles"):
        require(proof[field] == {k: v for source in sources for k, v in source["proof"][field].items()},
                f"Evidence changed: {partition} / {field}")
    require(db._group_history(current, rows, proof)[1] == bindings, "Group assignments changed")
    require(evidence_digest(rows, {"split_id", "ordinal"}) ==
            evidence_digest([row for source in sources for row in source["assignments"]], {"split_id", "ordinal"}),
            "Assignment ownership changed")
    for table, columns in EVIDENCE.items():
        require(evidence_digest(records(conn, table, columns[0], target), columns) ==
                evidence_digest([row for source in sources for row in source["linked"][table]], columns),
                f"Original record changed: {partition} / {table}")
    expected_conflicts = sorted({issue for ids in conflicts.values() for issue in ids})
    require(db._review_overlap_conflicts(conn, [target])[target] == expected_conflicts, "Conflict set changed")
    card = db.list_review_work_splits(lifecycle="current", split_id=target)[0]
    require(card["total_count"] == len(ids), "Incorrect card membership")
    for field in ("pending_count", "completed_count", "assignment_count"):
        require(card[field] == sum(source["card"][field] for source in sources),
                f"Task count changed: {partition} / {field}")
    return dict(task=target, cases=len(ids), overlap=config["overlap_ratio"], conflicts=len(expected_conflicts),
                pending=card["pending_count"], completed=card["completed_count"], assigned=card["assignment_count"],
                missing_odd=sum(source["unknown_count"] for source in sources))


def merge(db, split_receipt, backup_sha, actor, expected_fingerprint=None):
    expected = [child for source in split_receipt.values() for child in source["children"]]
    require(expected and len({row["task"] for row in expected}) == len(expected), "Invalid split receipt")
    require({row["kind"] for row in expected} <= {"ODD2", "ODD3", None}
            and any(row["kind"] == "ODD2" for row in expected)
            and any(row["kind"] != "ODD2" for row in expected), "Expected both 0821 partitions")
    with db.connect() as conn, patch.object(db, "connect", lambda: nullcontext(conn)):
        if db.backend == "postgresql":
            conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            conn.execute("SET LOCAL lock_timeout='6s'")
            conn.execute("SET LOCAL statement_timeout='90s'")
        db._lock_task_work(conn)
        sources = [
            read_source(db, conn, "0821-odd2" if row["kind"] == "ODD2" else "0821-nonodd2", row)
            for row in sorted(expected, key=lambda row: row["task"])
        ]
        require(sum(len(source["ids"]) for source in sources) ==
                len(set().union(*(source["ids"] for source in sources))), "Duplicate Issue across source tasks")
        source_sha = _fingerprint([source["fingerprint"] for source in sources])
        require(not expected_fingerprint or source_sha == expected_fingerprint,
                "Source differs from rehearsal. Rehearse with a fresh verified backup.")
        run = create_composed_run(conn, sources, actor)
        result = dict(run=run, source_sha256=source_sha, backup_sha256=backup_sha, datasets={
            partition: merge_partition(
                db, conn, partition, [source for source in sources if source["partition"] == partition],
                run, backup_sha, actor,
            )
            for partition in DATASETS
        })
        db._mark_change_topic(conn, "review")
        db._mark_labeling_change(conn)
        if not expected_fingerprint:
            raise RehearsalComplete(result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--database-url-file", type=Path)
    location.add_argument("--sqlite", type=Path)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--backup-sha256", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--apply-source-sha256", help="Commit only against the exact rehearsed source fingerprint.")
    args = parser.parse_args()
    for value in (args.backup_sha256, args.apply_source_sha256):
        require(value is None or re.fullmatch("[a-f0-9]{64}", value), "Expected a full SHA-256")
    digest = sha256()
    with args.backup.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    require(digest.hexdigest() == args.backup_sha256, "Backup checksum mismatch")
    path = args.sqlite if args.sqlite else args.database_url_file.read_text().strip()
    db = Database(path, pool_size=2)
    try:
        receipt = merge(db, json.loads(args.source_receipt.read_text()), args.backup_sha256,
                        args.actor, args.apply_source_sha256)
        receipt["mode"] = "applied"
    except RehearsalComplete as done:
        receipt = dict(done.receipt, mode="rolled_back")
    finally:
        db.close()
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
