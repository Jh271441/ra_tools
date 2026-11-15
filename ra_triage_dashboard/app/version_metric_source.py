"""Source binding for actual published version predictions and Trail reference lanes."""
from __future__ import annotations

import json
import math
import threading
import time

from .version_metrics import FIELDS, LABELS, normalize, digest
from .version_metric_store import now

_query_lock = threading.Lock()
_last_query = 0.


def read_only_client(root):
    from .rd_results import adapter
    delegate = adapter(root)
    transport = delegate.client

    class QueryOnly:
        def send_request(self, url, data, timeout=None):
            global _last_query
            if url not in ("https://voyager.intra.xiaojukeji.com/paladin/issue/pool/query/",
                           "http://voyager.intra.xiaojukeji.com/paladin/issue/pool/query/"):
                raise ValueError("Metric source is query-only")
            with _query_lock:
                time.sleep(max(0., 1.-(time.monotonic()-_last_query)))
                _last_query = time.monotonic()
                return transport.send_request(url.replace("http://", "https://", 1), data, timeout)

    delegate.client = QueryOnly()
    return delegate


def source(db, family, client):
    dataset_id = "release-"+family+"-odd2"
    dataset, inventory = inventory_rows(db, dataset_id)
    admitted = [r for r in inventory if r["state"] == "published"]
    exclusions = db.project_issue_exclusions([r["issue_id"] for r in admitted if r.get("is_sample")])
    observed = {}
    started = now()
    for offset in range(0, len(admitted), 20):
        ids = [r["issue_id"] for r in admitted[offset:offset+20]]
        rows = client.fetch(ids)
        if len(rows) != len(ids) or {r.get("issue_id") for r in rows} != set(ids):
            raise ValueError("Incomplete metric source")
        observed.update({r["issue_id"]: r for r in rows})
    result = []
    for row in admitted:
        raw = observed[row["issue_id"]]
        info = raw.get("ra_stuck_auto_result_info") or {}
        if isinstance(info, str):
            info = json.loads(info)
        daily = info.get("daily_auto_triage", {}) if isinstance(info, dict) else {}
        label = normalize(raw.get("ra_stuck_auto_result"))
        confidence = daily.get("model_confidence")
        kind = daily.get("prediction_source", "model" if daily.get("probabilities") else "unknown")
        if label not in LABELS or kind not in ("model", "pre_rule", "unknown"):
            raise ValueError("Incomplete published prediction")
        if confidence is not None and (type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Invalid published confidence")
        if kind == "pre_rule" and (daily.get("confidence_source") != "rule_constant" or daily.get("model_forward_performed") is not False):
            raise ValueError("Unqualified rule source")
        if daily.get("model_result") is not None and daily["model_result"] != label:
            raise ValueError("Published prediction metadata disagree")
        if kind == "model" and daily.get("confidence_source") == "rule_constant":
            raise ValueError("Rule confidence cannot identify a model forward")
        if row.get("model_label") is not None and (row["model_label"] != label or row["model_confidence"] != confidence):
            raise ValueError("Published source and frozen Run disagree")
        refs = {key: dict(observed=field in raw, value=raw.get(field)) for key, field in FIELDS.items()}
        if any(f["value"] is not None and not isinstance(f["value"], str) for f in refs.values()):
            raise ValueError("Invalid reference field")
        item = dict(issue_id=row["issue_id"], published=True, sample=bool(row.get("is_sample")),
                    excluded=bool(exclusions.get(row["issue_id"], {}).get("is_excluded")),
                    label=label, confidence=confidence, source=kind, references=refs,
                    routed_to_human=bool(row.get("is_low")))
        # Only an independently observed, current formal result is eligible.
        # Old releases retain the observed RD lane; newer ones validate formal heads.
        if family < "20261106" and normalize(refs["rd"]["value"]) in LABELS:
            item.update(human_label=normalize(refs["rd"]["value"]), human_reference="rd")
        elif item["sample"] and family >= "20261106":
            context = db.human_label_context(row["issue_id"])
            lanes = (context or {}).get("lanes", {})
            for lane, ref in (("arbitrated", "arbitrated"), ("te", "te_prime"), ("rd", "rd")):
                formal = lanes.get(lane, {})
                if formal.get("state") == "resolved" and formal.get("label") == normalize(refs[ref]["value"]):
                    item.update(human_label=formal["label"], human_reference=ref)
                    break
        result.append(item)
    after, after_rows = inventory_rows(db, dataset_id)
    after_exclusions = db.project_issue_exclusions([r["issue_id"] for r in admitted if r.get("is_sample")])
    if digest(exclusions) != digest(after_exclusions):
        raise ValueError("Exclusion sources changed while reading")
    if digest([dataset, inventory]) != digest([after, after_rows]):
        raise ValueError("Version membership changed while reading")
    return dict(rows=result, observed_at=now(), started_at=started, run_id=dataset.get("run_id") or "",
                registry_revision=dataset["revision"], provenance=dict(reference_source="Trail", prediction_source="published_run_and_trail",
                    inventory_sha256=digest(inventory), source_sha256=digest(result),
                    requested_total=len(admitted), returned_total=len(observed), independent_human_accuracy=False))


def inventory_rows(db, dataset_id):
    """Read the actual stream, including non-target published predictions."""
    with db.connect() as conn:
        dataset = conn.execute("SELECT id,run_id,revision,policy_json FROM version_datasets WHERE id=?", (dataset_id,)).fetchone()
        if dataset is None:
            raise ValueError("Unknown version dataset")
        rows = conn.execute(
            "SELECT i.source_json,p.model_label,p.model_confidence FROM version_dataset_items i "
            "JOIN version_datasets d ON d.id=i.dataset_id LEFT JOIN model_predictions p "
            "ON p.model_run_id=d.run_id AND p.issue_id=i.issue_id WHERE i.dataset_id=? ORDER BY i.issue_id LIMIT 20001",
            (dataset_id,)).fetchall()
    if len(rows) > 20000:
        raise ValueError("Version exceeds bounded metric population")
    output = []
    for r in rows:
        raw = json.loads(r["source_json"]) if isinstance(r["source_json"], str) else r["source_json"]
        output.append(dict(raw, model_label=r["model_label"], model_confidence=r["model_confidence"]))
    return dict(dataset), output
