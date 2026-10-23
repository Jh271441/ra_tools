"""Explicit physical Run consolidation and additive version stream predictions."""
import hashlib, json, re, uuid
from datetime import datetime
from .shared import utc_now
from .version_dataset_rules import encoded


class VersionRunConsolidationMixin:
    def consolidate_version_runs(self, *, family, run_ids, backup_sha256, actor):
        """Explicit user-authorized physical consolidation after a verified DB backup.

        Human row IDs, labels, authors, timestamps and Campaign IDs stay intact.
        Old Run rows/predictions move into the archive; current foreign keys move
        to one version_live Run in the same transaction. Frozen source snapshots
        remain historical facts and resolve through the archive mapping.
        """
        if (
            not re.fullmatch(r"20\d{6}", family)
            or not re.fullmatch(r"[0-9a-f]{64}", backup_sha256)
            or not actor
        ):
            raise ValueError("A verified backup receipt is required")
        did = "release-" + family + "-odd2"
        rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "ra-triage:" + did))
        now = utc_now()
        ids = sorted(set(run_ids))
        marks = ",".join("?" for _ in ids)
        if not ids or rid in ids:
            raise ValueError("Invalid source Run list")
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (did,))
            archives = conn.execute(
                "SELECT run_id,target_run_id FROM version_run_archives WHERE run_id IN ("
                + marks
                + ")",
                ids,
            ).fetchall()
            if len(archives) == len(ids):
                if {r["target_run_id"] for r in archives} != {rid}:
                    raise ValueError("Conflicting previous consolidation")
                return {"run_id": rid, "archived_runs": ids, "replayed": True}
            if archives:
                raise ValueError(
                    "Partially consolidated source set requires reconciliation"
                )
            runs = conn.execute(
                "SELECT * FROM model_runs WHERE id IN (" + marks + ")", ids
            ).fetchall()
            if len(runs) != len(ids) or any(r["is_default"] for r in runs):
                raise ValueError("Missing source or protected default Run")
            predictions = conn.execute(
                "SELECT * FROM model_predictions WHERE model_run_id IN ("
                + marks
                + ") ORDER BY issue_id",
                ids,
            ).fetchall()
            if len({r["issue_id"] for r in predictions}) != len(predictions):
                raise ValueError(
                    "Duplicate Issue predictions require explicit conflict resolution"
                )
            for row in predictions:
                raw = (
                    json.loads(row["raw_json"])
                    if isinstance(row["raw_json"], str)
                    else row["raw_json"]
                )
                extra = (
                    json.loads(row["model_extra_json"])
                    if isinstance(row["model_extra_json"], str)
                    else row["model_extra_json"]
                )
                version = (
                    (extra or {}).get("software_version")
                    or (raw or {}).get("software_version")
                    or ((raw or {}).get("model_extra") or {}).get("software_version")
                )
                if not re.fullmatch(
                    r"1\.gen4-release-"
                    + family
                    + r"(?:[.-][A-Za-z0-9][A-Za-z0-9._-]*)?",
                    str(version or ""),
                ):
                    raise ValueError(
                        "Source prediction is outside the requested release"
                    )
            campaigns = conn.execute(
                "SELECT * FROM issue_work_splits WHERE evaluation_run_id IN ("
                + marks
                + ")",
                ids,
            ).fetchall()
            if any(c["lifecycle"] not in ("active", "draft") for c in campaigns):
                raise ValueError(
                    "Closed source Campaign requires a separate archival transition"
                )
            group_rows = conn.execute(
                "SELECT group_id,evaluation_run_id FROM review_task_group_campaigns WHERE evaluation_run_id IN ("
                + marks
                + ")",
                ids,
            ).fetchall()
            if len({r["group_id"] for r in group_rows}) != len(group_rows):
                raise ValueError(
                    "Multiple source children in one task group need explicit mapping"
                )
            metadata = {
                "schema_version": "version-stream-v1",
                "release_family": family,
                "dataset_id": did,
                "mutable_membership": True,
                "source_hash_contract": "immutable stream identity; each ingestion batch has its own content SHA",
                "consolidated_source_run_ids": ids,
                "backup_sha256": backup_sha256,
            }
            source_sha = hashlib.sha256(
                encoded({"kind": "version_live", "dataset_id": did}).encode()
            ).hexdigest()
            conn.execute(
                "INSERT INTO model_runs(id,name,source_name,source_sha256,schema_version,kind,is_default,created_by,created_by_source,created_by_verified,metadata_json,created_at) VALUES(?,?,?,?,?,?,FALSE,?,?,?,?,?)",
                (
                    rid,
                    family[4:] + " 联合复核",
                    "version-stream-" + family + ".json",
                    source_sha,
                    "version-stream-v1",
                    "version_live",
                    actor,
                    "authorized_version_migration",
                    False,
                    encoded(metadata),
                    now,
                ),
            )
            for row in predictions:
                conn.execute(
                    "INSERT INTO model_predictions(model_run_id,issue_id,trip_id,model_label,model_reason,model_confidence,model_extra_json,raw_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        rid,
                        row["issue_id"],
                        row["trip_id"],
                        row["model_label"],
                        row["model_reason"],
                        row["model_confidence"],
                        row["model_extra_json"]
                        if isinstance(row["model_extra_json"], str)
                        else encoded(row["model_extra_json"]),
                        row["raw_json"]
                        if isinstance(row["raw_json"], str)
                        else encoded(row["raw_json"]),
                        row["created_at"],
                    ),
                )
            for run in runs:
                body = {
                    "run": dict(run),
                    "predictions": [
                        dict(r) for r in predictions if r["model_run_id"] == run["id"]
                    ],
                    "backup_sha256": backup_sha256,
                    "target_run_id": rid,
                }
                content = json.dumps(
                    body, ensure_ascii=False, sort_keys=True, default=str
                )
                conn.execute(
                    "INSERT INTO version_run_archives VALUES(?,?,?,?,?,?)",
                    (
                        run["id"],
                        did,
                        rid,
                        content,
                        hashlib.sha256(content.encode()).hexdigest(),
                        now,
                    ),
                )
            moved = {}
            for table, column in [
                ("annotations", "model_run_id"),
                ("model_review_revisions", "model_run_id"),
                ("model_review_heads", "model_run_id"),
                ("combined_review_submissions", "model_run_id"),
                ("review_comments", "model_run_id"),
                ("review_comments", "evaluation_run_id"),
                ("batch_prediction_jobs", "model_run_id"),
            ]:
                n = conn.execute(
                    "UPDATE "
                    + table
                    + " SET "
                    + column
                    + "=? WHERE "
                    + column
                    + " IN ("
                    + marks
                    + ")",
                    [rid] + ids,
                ).rowcount
                moved[table + "." + column] = n
            conn.execute(
                "UPDATE review_task_group_campaigns SET evaluation_run_id=? WHERE evaluation_run_id IN ("
                + marks
                + ")",
                [rid] + ids,
            )
            for campaign in campaigns:
                conn.execute(
                    "UPDATE issue_work_splits SET evaluation_run_id=?,model_run_id=?,config_revision=config_revision+1,updated_by=?,updated_by_source=?,updated_at=? WHERE id=?",
                    (
                        rid,
                        rid,
                        actor,
                        "authorized_version_migration",
                        now,
                        campaign["id"],
                    ),
                )
                self._campaign_insert_revision(
                    conn,
                    campaign_id=campaign["id"],
                    revision_no=int(campaign["config_revision"]) + 1,
                    changed_by=actor,
                    changed_by_source="authorized_version_migration",
                    changed_by_verified=False,
                    change_source="version_consolidation",
                    idempotency_key="version-consolidation-" + family,
                )
            conn.execute("DELETE FROM model_runs WHERE id IN (" + marks + ")", ids)
            self._mark_run_collection_change(conn)
            return {
                "run_id": rid,
                "archived_runs": ids,
                "predictions": len(predictions),
                "moved": moved,
                "backup_sha256": backup_sha256,
                "replayed": False,
            }

    def append_version_predictions(self, *, run_id, rows):
        """Only version_live Runs permit additive results; existing values never overwrite."""
        with self._write_lock, self.connect() as conn:
            run = conn.execute(
                "SELECT * FROM model_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run or run["kind"] != "version_live":
                raise ValueError("Expected a version stream Run")
            if self.backend == "postgresql":
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (run_id,))
            added = 0
            for row in rows:
                iid = row["issue_id"]
                old = conn.execute(
                    "SELECT * FROM model_predictions WHERE model_run_id=? AND issue_id=?",
                    (run_id, iid),
                ).fetchone()
                if old:
                    if (
                        old["model_label"] != row["model_label"]
                        or old["model_confidence"] != row["model_confidence"]
                    ):
                        raise ValueError("Conflicting version prediction")
                    continue
                now = utc_now()
                if not conn.execute(
                    "SELECT 1 FROM issues WHERE issue_id=?", (iid,)
                ).fetchone():
                    scope = (
                        "manual_sidecar_version_"
                        + (
                            json.loads(run["metadata_json"])
                            if isinstance(run["metadata_json"], str)
                            else run["metadata_json"]
                        )["release_family"]
                    )
                    conn.execute(
                        "INSERT INTO issues(issue_id,trip_id,source,baseline_scope,created_at,updated_at) VALUES(?,?,'version_incremental',?,?,?)",
                        (iid, row.get("trip_id", ""), scope, now, now),
                    )
                conn.execute(
                    "INSERT INTO model_predictions(model_run_id,issue_id,trip_id,model_label,model_reason,model_confidence,model_extra_json,raw_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        iid,
                        row.get("trip_id", ""),
                        row["model_label"],
                        row.get("model_reason", ""),
                        row["model_confidence"],
                        encoded(row.get("model_extra", {})),
                        encoded(row),
                        now,
                    ),
                )
                added += 1
            self._mark_run_collection_change(conn)
            return {"run_id": run_id, "added": added}

    def ensure_version_stream(self, family, actor):
        if not re.fullmatch(r"20\d{6}", family):
            raise ValueError("Invalid release")
        datetime.strptime(family, "%Y%m%d")
        did = "release-" + family + "-odd2"
        rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "ra-triage:" + did))
        with self._write_lock, self.connect() as conn:
            if conn.execute("SELECT 1 FROM model_runs WHERE id=?", (rid,)).fetchone():
                return rid
            for old in conn.execute(
                "SELECT metadata_json FROM model_runs WHERE kind='upload'"
            ).fetchall():
                metadata = (
                    json.loads(old["metadata_json"])
                    if isinstance(old["metadata_json"], str)
                    else old["metadata_json"]
                )
                if metadata.get("release_family") == family:
                    raise ValueError("Existing Runs must be consolidated first")
            like = "%1.gen4-release-" + family + "%"
            if conn.execute(
                "SELECT 1 FROM model_predictions WHERE CAST(model_extra_json AS TEXT) LIKE ? OR CAST(raw_json AS TEXT) LIKE ? LIMIT 1",
                (like, like),
            ).fetchone():
                raise ValueError(
                    "Existing version predictions require explicit consolidation"
                )
            metadata = {
                "schema_version": "version-stream-v1",
                "release_family": family,
                "dataset_id": did,
                "mutable_membership": True,
                "source_hash_contract": "stream identity; content hashes belong to ingestion batches",
            }
            source_sha = hashlib.sha256(
                encoded({"kind": "version_live", "dataset_id": did}).encode()
            ).hexdigest()
            conn.execute(
                "INSERT INTO model_runs(id,name,source_name,source_sha256,schema_version,kind,is_default,created_by,created_by_source,created_by_verified,metadata_json,created_at) VALUES(?,?,?,?,?,?,FALSE,?,?,?,?,?)",
                (
                    rid,
                    family[4:] + " 联合复核",
                    "version-stream-" + family + ".json",
                    source_sha,
                    "version-stream-v1",
                    "version_live",
                    actor,
                    "authorized_version_ingestion",
                    False,
                    encoded(metadata),
                    utc_now(),
                ),
            )
            self._mark_run_collection_change(conn)
            return rid
