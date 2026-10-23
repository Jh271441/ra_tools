"""Append-only batch ingestion and version projections; original review identities survive."""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from datetime import datetime
from .shared import utc_now
from .version_run_consolidation import VersionRunConsolidationMixin
from .version_dataset_rules import encoded


class DatabaseVersionDatasetsMixin(VersionRunConsolidationMixin):
    def ingest_version_dataset(self, *, family, policy, items, batch_key, actor):
        if (
            not re.fullmatch(r"20\d{6}", family)
            or not actor
            or not batch_key
            or len(batch_key) > 160
        ):
            raise ValueError("Invalid version batch identity")
        datetime.strptime(family, "%Y%m%d")
        if policy.get(
            "sampling_policy"
        ) != "version_probability_v3" or not re.fullmatch(
            r"[0-9a-f]{64}", str(policy.get("seed", ""))
        ):
            raise ValueError("A frozen version probability policy is required")
        if not isinstance(items, list) or len(items) > 5000:
            raise ValueError("Version batch must have at most 5000 items")
        ids = [r.get("issue_id") for r in items]
        if len(ids) != len(set(ids)) or any(
            not isinstance(i, str) or not re.fullmatch(r"cn\d+", i) for i in ids
        ):
            raise ValueError("Expected unique Issue IDs")
        safe = []
        for raw in items:
            item = dict(raw)
            version = item.get("software_version", "")
            if not re.fullmatch(
                r"1\.gen4-release-" + family + r"(?:[.-][A-Za-z0-9][A-Za-z0-9._-]*)?",
                version,
            ):
                raise ValueError("Cross-version batch rejected")
            if item.get("state") not in {
                "ready",
                "waiting_metadata",
                "excluded",
                "running",
                "retry_wait",
                "inferred",
                "published",
                "needs_attention",
                "identity_conflict",
            }:
                raise ValueError("Unknown item state")
            for key in ("is_target", "is_sample", "is_low"):
                if not isinstance(item.get(key, False), bool):
                    raise ValueError("Flags must be boolean")
            if item.get("is_target") and item["state"] in {
                "excluded",
                "waiting_metadata",
                "identity_conflict",
            }:
                raise ValueError("Unadmitted item cannot be an active review target")
            safe.append(item)
        safe.sort(key=lambda r: r["issue_id"])
        payload = {"family": family, "policy": policy, "items": safe}
        fingerprint = hashlib.sha256(encoded(payload).encode()).hexdigest()
        did = "release-" + family + "-odd2"
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            if self.backend == "postgresql":
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (did,))
            old = conn.execute(
                "SELECT * FROM dataset_ingestion_batches WHERE dataset_id=? AND batch_key=?",
                (did, batch_key),
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("Version batch idempotency conflict")
                return {**json.loads(old["receipt_json"]), "replayed": True}
            dataset = conn.execute(
                "SELECT * FROM version_datasets WHERE id=?", (did,)
            ).fetchone()
            if dataset and json.loads(dataset["policy_json"]) != policy:
                raise ValueError("Frozen version sampling policy changed")
            if not dataset:
                conn.execute(
                    "INSERT INTO version_datasets(id,name,release_family,policy_json,revision,created_at,updated_at) VALUES(?,?,?,?,0,?,?)",
                    (did, family[4:] + " 复核集", family, encoded(policy), now, now),
                )
            stream_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "ra-triage:" + did))
            if conn.execute(
                "SELECT 1 FROM model_runs WHERE id=?", (stream_id,)
            ).fetchone():
                conn.execute(
                    "UPDATE version_datasets SET run_id=? WHERE id=?", (stream_id, did)
                )
            added = changed = target_added = target_retired = 0
            for item in safe:
                iid = item["issue_id"]
                old = conn.execute(
                    "SELECT * FROM version_dataset_items WHERE dataset_id=? AND issue_id=?",
                    (did, iid),
                ).fetchone()
                binding = dict(item.get("binding") or {})
                if binding:
                    run_id = str(binding.get("run_id") or "")
                    campaign_id = str(binding.get("campaign_id") or "")
                    prediction = conn.execute(
                        "SELECT 1 FROM model_predictions WHERE model_run_id=? AND issue_id=?",
                        (run_id, iid),
                    ).fetchone()
                    if not prediction:
                        raise ValueError("Prediction binding does not contain Issue")
                    if campaign_id:
                        member = conn.execute(
                            "SELECT 1 FROM campaign_issue_members m JOIN issue_work_splits s ON s.id=m.campaign_id WHERE m.campaign_id=? AND m.issue_id=? AND s.evaluation_run_id=?",
                            (campaign_id, iid, run_id),
                        ).fetchone()
                        if not member:
                            raise ValueError("Invalid original Campaign binding")
                        assigned = conn.execute(
                            "SELECT assignee FROM review_work_assignments WHERE split_id=? AND issue_id=? ORDER BY assignee",
                            (campaign_id, iid),
                        ).fetchall()
                        if len(assigned) > 1:
                            raise ValueError(
                                "Overlapping original assignments require explicit resolution"
                            )
                        if assigned:
                            binding["assignee"] = assigned[0]["assignee"]
                    if old and json.loads(old["binding_json"]).get("campaign_id"):
                        binding = json.loads(old["binding_json"])
                elif old:
                    binding = json.loads(old["binding_json"])
                target_added += int(
                    bool(item.get("is_target")) and not (old and old["is_target"])
                )
                target_retired += int(
                    bool(old and old["is_target"]) and not item.get("is_target")
                )
                body = encoded(item)
                values = (
                    item["state"],
                    int(item.get("is_target", False)),
                    int(item.get("is_sample", False)),
                    int(item.get("is_low", False)),
                    item["software_version"],
                    body,
                    encoded(binding),
                    now,
                )
                if old:
                    if old["source_json"] == body and old["binding_json"] == encoded(
                        binding
                    ):
                        continue
                    conn.execute(
                        "UPDATE version_dataset_items SET state=?,is_target=?,is_sample=?,is_low=?,software_version=?,source_json=?,binding_json=?,updated_at=? WHERE dataset_id=? AND issue_id=?",
                        values + (did, iid),
                    )
                    changed += 1
                else:
                    conn.execute(
                        "INSERT INTO version_dataset_items(dataset_id,issue_id,state,is_target,is_sample,is_low,software_version,source_json,binding_json,updated_at,first_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (did, iid) + values + (now,),
                    )
                    added += 1
                if binding.get("run_id"):
                    conn.execute(
                        "INSERT INTO dataset_item_sources VALUES(?,?,?,?,?,?) ON CONFLICT(dataset_id,issue_id,run_id,campaign_id) DO NOTHING",
                        (
                            did,
                            iid,
                            binding["run_id"],
                            binding.get("campaign_id", ""),
                            encoded(binding),
                            now,
                        ),
                    )
                if binding.get("campaign_id") and binding.get("assignee"):
                    conn.execute(
                        "INSERT INTO dataset_task_bindings VALUES(?,?,?,?,?,?,?) ON CONFLICT(dataset_id,issue_id,workflow) DO NOTHING",
                        (
                            did,
                            iid,
                            "model_review_and_case_label",
                            binding["run_id"],
                            binding["campaign_id"],
                            binding["assignee"],
                            now,
                        ),
                    )
            conn.execute(
                "UPDATE version_datasets SET revision=revision+1,updated_at=? WHERE id=?",
                (now, did),
            )
            receipt = {
                "dataset_id": did,
                "batch_key": batch_key,
                "added": added,
                "target_added": target_added,
                "target_retired": target_retired,
                "changed": changed,
                "count": len(safe),
                "fingerprint": fingerprint,
                "replayed": False,
            }
            conn.execute(
                "INSERT INTO dataset_ingestion_batches VALUES(?,?,?,?,?,?)",
                (did, batch_key, fingerprint, encoded(payload), encoded(receipt), now),
            )
            self._mark_run_collection_change(conn)
            return receipt

    def list_version_datasets(self):
        with self.connect() as conn:
            result = []
            for row in conn.execute(
                "SELECT * FROM version_datasets ORDER BY release_family DESC"
            ).fetchall():
                item = dict(row)
                item.pop("policy_json", None)
                counts = conn.execute(
                    "SELECT COUNT(*) AS total,SUM(is_target) AS targets,SUM(is_sample) AS samples,SUM(CASE WHEN is_target=1 THEN is_sample ELSE 0 END) AS sampled_targets,SUM(CASE WHEN is_target=1 THEN is_low ELSE 0 END) AS low FROM version_dataset_items WHERE dataset_id=?",
                    (row["id"],),
                ).fetchone()
                item.update(
                    {
                        k: int(counts[k] or 0)
                        for k in ("total", "targets", "samples", "sampled_targets", "low")
                    }
                )
                item["low_only"] = item["low"] - int(conn.execute(
                    "SELECT COUNT(*) AS n FROM version_dataset_items WHERE dataset_id=? AND is_target=1 AND is_sample=1 AND is_low=1", (row["id"],)
                ).fetchone()["n"])
                item["states"] = {
                    x["state"]: x["n"]
                    for x in conn.execute(
                        "SELECT state,COUNT(*) AS n FROM version_dataset_items WHERE dataset_id=? GROUP BY state",
                        (row["id"],),
                    ).fetchall()
                }
                item["assigned"] = {
                    x["assignee"]: x["n"]
                    for x in conn.execute(
                        "SELECT a.assignee,COUNT(*) AS n FROM dataset_task_bindings a JOIN version_dataset_items i ON i.dataset_id=a.dataset_id AND i.issue_id=a.issue_id WHERE a.dataset_id=? AND i.is_target=1 GROUP BY a.assignee",
                        (row["id"],),
                    ).fetchall()
                }
                result.append(item)
            return result

    def version_dataset_items(
        self, dataset_id, *, page=1, page_size=50, mode="targets", query="", sort="added"
    ):
        page = max(1, int(page))
        size = max(1, min(200, int(page_size)))
        orders = {"added": "first_seen DESC,issue_id DESC", "updated": "updated_at DESC,issue_id DESC", "issue": "issue_id ASC"}
        if sort not in orders:
            raise ValueError("Invalid version sort")
        where = "dataset_id=?"
        args = [dataset_id]
        if mode == "targets":
            where += " AND is_target=1"
        elif mode == "samples":
            where += " AND is_sample=1 AND state<>'excluded'"
        elif mode == "waiting":
            where += " AND state IN ('waiting_metadata','retry_wait')"
        elif mode != "all":
            raise ValueError("Invalid membership view")
        if query:
            where += " AND issue_id LIKE ?"
            args.append("%" + query + "%")
        with self.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n FROM version_dataset_items WHERE " + where, args
            ).fetchone()["n"]
            rows = conn.execute(
                "SELECT * FROM version_dataset_items WHERE "
                + where
                + " ORDER BY " + orders[sort] + " LIMIT ? OFFSET ?",
                args + [size, (page - 1) * size],
            ).fetchall()
            dataset = conn.execute("SELECT run_id FROM version_datasets WHERE id=?", (dataset_id,)).fetchone()
            predictions = {}
            if rows and dataset and dataset["run_id"]:
                ids = [r["issue_id"] for r in rows]
                predictions = {r["issue_id"]: dict(r) for r in conn.execute(
                    "SELECT issue_id,model_label,model_confidence FROM model_predictions WHERE model_run_id=? AND issue_id IN (" + ",".join("?" for _ in ids) + ")",
                    [dataset["run_id"], *ids],
                ).fetchall()}
            items = []
            for row in rows:
                item = json.loads(row["source_json"])
                item["binding"] = json.loads(row["binding_json"])
                item.update(first_seen=row["first_seen"], updated_at=row["updated_at"], prediction=predictions.get(row["issue_id"]))
                items.append(item)
            return {
                "dataset_id": dataset_id,
                "items": items,
                "total": total,
                "page": page,
                "page_size": size,
            }

    def version_dataset_arrivals(self, family):
        """Small read-only time index for TE sorting; no label authority changes."""
        with self.connect() as conn:
            return {r["issue_id"]: {"first_seen": r["first_seen"], "updated_at": r["updated_at"]}
                    for r in conn.execute("SELECT issue_id,first_seen,updated_at FROM version_dataset_items WHERE dataset_id=?", ("release-" + family + "-odd2",)).fetchall()}

    def version_dataset_batches(self, dataset_id):
        with self.connect() as conn:
            return [
                json.loads(row["receipt_json"]) | {"created_at": row["created_at"]}
                for row in conn.execute(
                    "SELECT receipt_json,created_at FROM dataset_ingestion_batches WHERE dataset_id=? ORDER BY created_at DESC LIMIT 200",
                    (dataset_id,),
                ).fetchall()
            ]

    def version_run_aliases(self):
        with self.connect() as conn:
            return {
                r["run_id"]: r["target_run_id"]
                for r in conn.execute(
                    "SELECT run_id,target_run_id FROM version_run_archives"
                ).fetchall()
            }

    def version_dataset_scopes(self, dataset_id):
        with self.connect() as conn:
            return [
                r["baseline_scope"]
                for r in conn.execute(
                    "SELECT DISTINCT i.baseline_scope FROM issues i JOIN version_dataset_items v ON v.issue_id=i.issue_id WHERE v.dataset_id=? ORDER BY i.baseline_scope",
                    (dataset_id,),
                ).fetchall()
            ]
