"""Pure, versioned scoring of frozen probability samples. No GT or network writes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import math
import re

LABELS = ("正确触发", "误触发", "无需协助")
FIELDS = {"te": "ra_review_result_new", "rd": "ra_rd_review_result",
          "te_prime": "ra_review_result_sampling", "arbitrated": "ra_review_result_arbitrated"}
SCHEMES = ("model", "chain", "model_human_sim", "chain_human_sim", "chain_post_human_sim")
THRESHOLDS = (.90, .85, .80, .76, .75, .65)
POLICY = "version-probability-sample-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def is_trail_snapshot(snapshot):
    """Only complete server-collected Trail receipts qualify for current metrics."""
    provenance = snapshot.get("provenance", {})
    rows = snapshot.get("rows", [])
    if not isinstance(provenance, dict) or not isinstance(rows, list):
        return False
    try:
        started = datetime.fromisoformat(snapshot["started_at"])
        finished = datetime.fromisoformat(snapshot["observed_at"])
        if started.tzinfo is None or finished.tzinfo is None or started > finished:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return (provenance.get("reference_source") == "Trail"
            and provenance.get("prediction_source") == "published_run_and_trail"
            and provenance.get("requested_total") == len(rows)
            and provenance.get("returned_total") == len(rows)
            and provenance.get("source_sha256") == digest(rows)
            and not provenance.get("preview"))


def normalize(value):
    return {"成功": "正确触发", "失败": "正确触发"}.get(value, value) if isinstance(value, str) else None


def filled(value):
    return value is not None and value not in ("", "未填写")


def validate_snapshot(snapshot):
    if snapshot.get("schema_version") != 1 or snapshot.get("policy") != POLICY:
        raise ValueError("Unsupported metric snapshot")
    if not re.fullmatch(r"20\d{6}", str(snapshot.get("family", ""))):
        raise ValueError("Invalid release family")
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or len(rows) > 20000:
        raise ValueError("Invalid metric population")
    ids = set()
    for row in rows:
        iid = row.get("issue_id")
        if not isinstance(iid, str) or not re.fullmatch(r"cn\d{1,30}", iid) or iid in ids:
            raise ValueError("Duplicate or invalid metric Issue")
        ids.add(iid)
        for flag in ("sample", "published", "excluded"):
            if type(row.get(flag)) is not bool:
                raise ValueError("Invalid metric flag")
        if row.get("source") not in ("model", "pre_rule", "unknown"):
            raise ValueError("Invalid prediction source")
        if row.get("label") is not None and row["label"] not in LABELS:
            raise ValueError("Invalid frozen prediction")
        confidence = row.get("confidence")
        if confidence is not None and (type(confidence) not in (int, float)
                                      or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Invalid model confidence")
        if "routed_to_human" in row and type(row["routed_to_human"]) is not bool:
            raise ValueError("Invalid recorded routing")
        refs = row.get("references")
        if not isinstance(refs, dict) or set(refs) != set(FIELDS):
            raise ValueError("Invalid reference lanes")
        for fact in refs.values():
            if (not isinstance(fact, dict) or type(fact.get("observed")) is not bool
                    or fact.get("value") is not None and not isinstance(fact["value"], str)):
                raise ValueError("Invalid reference observation")
    return snapshot


def score(rows, predictions):
    """Coverage and conditional ACC stay separate; missing output is never filled."""
    covered = [(row, prediction) for row, prediction in zip(rows, predictions) if prediction in LABELS]
    matrix = [[sum(r["truth"] == a and p == b for r, p in covered) for b in LABELS] for a in LABELS]
    n = len(covered)
    per = []
    for i, label in enumerate(LABELS):
        tp = matrix[i][i]
        support = sum(matrix[i])
        predicted = sum(row[i] for row in matrix)
        per.append(dict(label=label, tp=tp, support=support, predicted=predicted,
                        precision=tp/predicted if predicted else None,
                        recall=tp/support if support else None,
                        f1=2*tp/(support+predicted) if support+predicted else 0.))
    correct = sum(matrix[i][i] for i in range(3))
    return dict(total=n, reference_total=len(rows), correct=correct,
                accuracy=correct/n if n else None, coverage=n/len(rows) if rows else None,
                macro_f1=sum(c["f1"] for c in per)/3 if n else None,
                missing=len(rows)-n, confusion_matrix=matrix, per_class=per)


def prediction(row, scheme, threshold):
    low = row["source"] == "model" and row.get("confidence") is not None and row["confidence"] < threshold
    if scheme == "model":
        return row["label"] if row["source"] == "model" else None
    if scheme == "chain":
        return row["label"]
    if scheme == "model_human_sim" and row["source"] != "model":
        return None
    if scheme == "observed_human":
        # Actual published low-confidence routing uses its recorded threshold,
        # never the UI's sensitivity-analysis threshold.
        if row["source"] == "pre_rule":
            return row["label"]
        routed = row.get("routed_to_human")
        if type(routed) is not bool:
            return None
        return row.get("human_label") if routed else row["label"]
    return row["truth"] if low else row["label"]


def evaluate(snapshot, *, reference="te", exclusion="all", threshold=.9):
    if reference not in FIELDS or exclusion not in ("all", "exclude") or threshold not in THRESHOLDS:
        raise ValueError("Invalid metric policy")
    validate_snapshot(snapshot)
    population = [r for r in snapshot["rows"] if r["published"]]
    sample = [r for r in population if r["sample"]]
    rows = []
    invalid = Counter()
    for r in sample:
        fact = r["references"][reference]
        truth = normalize(fact["value"]) if fact["observed"] else None
        if truth not in LABELS:
            value = fact["value"]
            kind = ("unknown" if not fact["observed"] else "missing" if not filled(value)
                    else "oos" if value in ("oos", "out_of_scope") else "unanswered" if value == "未接起" else "other")
            invalid[kind] += 1
            continue
        if exclusion == "exclude" and r["excluded"]:
            continue
        rows.append(dict(r, truth=truth))
    metrics = {}
    observed_available = any(r.get("human_label") in LABELS and r.get("routed_to_human") is True for r in rows)
    for scheme in (*SCHEMES, *(("observed_human",) if observed_available else ())):
        m = score(rows, [prediction(r, scheme, threshold) for r in rows])
        m.update(scheme=scheme, simulated=scheme.endswith("_sim"), human_count=sum(
            r["source"] == "model" and r.get("confidence") is not None and r["confidence"] < threshold
            for r in rows if scheme.endswith("_sim")))
        if scheme == "observed_human":
            m["human_count"] = sum(r.get("human_label") in LABELS and r.get("routed_to_human") is True for r in rows)
            m["same_reference_count"] = sum(r.get("human_reference") == reference for r in rows if r.get("human_label") in LABELS and r.get("routed_to_human") is True)
        metrics[scheme] = m
    coverage = {}
    for key, field in FIELDS.items():
        known = sum(r["references"][key]["observed"] for r in sample)
        count = sum(r["references"][key]["observed"] and filled(r["references"][key]["value"]) for r in sample)
        coverage[key] = dict(field=field, filled=count, observed=known, total=len(sample), rate=count/len(sample) if sample else None)
    thresholds = []
    base = sum(r["source"] == "model" and r.get("confidence") is not None and r["confidence"] < .9 for r in population)
    for t in THRESHOLDS:
        low = sum(r["source"] == "model" and r.get("confidence") is not None and r["confidence"] < t for r in population)
        simulation = score(rows, [prediction(r, "chain_human_sim", t) for r in rows])
        thresholds.append(dict(threshold=t, full_low=low, full_total=len(population), reduction=base-low,
                               human_count=sum(r["source"] == "model" and r.get("confidence") is not None and r["confidence"] < t for r in rows),
                               correct=simulation["correct"], total=simulation["total"], accuracy=simulation["accuracy"]))
    return dict(family=snapshot["family"], dataset_id="release-"+snapshot["family"]+"-odd2",
                run_id=snapshot.get("run_id", ""), snapshot_id=snapshot["id"], observed_at=snapshot["observed_at"],
                started_at=snapshot.get("started_at", snapshot["observed_at"]),
                policy=POLICY, reference=reference, reference_field=FIELDS[reference], exclusion=exclusion, threshold=threshold,
                sample_total=len(sample), valid_total=len(rows), invalid=dict(invalid),
                excluded=sum(r["excluded"] for r in sample), coverage=coverage, metrics=metrics,
                class_distribution=[dict(label=l, count=sum(r["truth"] == l for r in rows)) for l in LABELS],
                published_total=len(population), unknown_prediction_source=sum(r["source"] == "unknown" for r in population),
                thresholds=thresholds, changes=snapshot.get("changes", {}), provenance=snapshot.get("provenance", {}))


def case_page(snapshot, *, reference="te", exclusion="all", threshold=.9, scheme="chain", status="errors",
              truth="", predicted="", page=1, page_size=20):
    if scheme not in (*SCHEMES, "observed_human") or status not in ("all", "errors", "invalid"):
        raise ValueError("Invalid case filter")
    if truth and truth not in LABELS or predicted and predicted not in LABELS:
        raise ValueError("Invalid class filter")
    if type(page) is not int or not 1 <= page <= 10000 or page_size not in (10, 20, 50, 100):
        raise ValueError("Invalid pagination")
    evaluate(snapshot, reference=reference, exclusion=exclusion, threshold=threshold)
    selected = []
    for raw in snapshot["rows"]:
        if not raw["published"] or not raw["sample"] or exclusion == "exclude" and raw["excluded"]:
            continue
        fact = raw["references"][reference]
        label = normalize(fact["value"]) if fact["observed"] else None
        row = dict(raw, truth=label)
        output = prediction(row, scheme, threshold)
        valid = label in LABELS
        if status == "invalid" and valid or status != "invalid" and not valid:
            continue
        if status == "errors" and output == label or truth and truth != label or predicted and predicted != output:
            continue
        selected.append(dict(issue_id=raw["issue_id"], reference_value=fact["value"], truth=label,
                             prediction=output, confidence=raw.get("confidence"), source=raw["source"], excluded=raw["excluded"]))
    selected.sort(key=lambda r: int(r["issue_id"][2:]))
    total = len(selected)
    pages = max(1, math.ceil(total/page_size))
    page = min(page, pages)
    return dict(items=selected[(page-1)*page_size:page*page_size], total=total, pages=pages, page=page, page_size=page_size)
