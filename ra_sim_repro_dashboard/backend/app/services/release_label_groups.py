"""Version-wide physical Scenario labels and the corresponding live road Issue queries."""

import csv
from collections import defaultdict
from datetime import datetime, timezone
import json
from urllib.parse import quote

from app.config import settings
from app.domain.labels import full_scene_label, real_labels
from app.domain.metrics import GOOD_RESULTS
from app.models import Version
from app.services import auto_triage_metrics, ordinary_evaluation
from app.services.release_source import complete_query, fetch_scenarios, trail_credentials
from app.services.report_artifacts import (
    canonical_scenario_id,
    resolve_report_path,
    VALID_UPLOAD_STATUSES,
)


# Trail's hash router applies decodeURI once to the whole query, then decodes
# each descriptor value. Keep array indices (.$0) and the two layers distinct.
def trail_url(attrs, subqueries):
    params = [
        "__fmt=1",
        "view_id~d=2410",
        "page~d=1",
        "size~d=20",
        "is_us_engineer~b=0",
        "filter_operator=AND",
    ]
    for index, attr in enumerate(attrs):
        value = attr["val"]
        if isinstance(value, dict):
            kind, wire = "o", json.dumps(value, separators=(",", ":"))
        elif all(isinstance(v, int) for v in value):
            kind, wire = "a_d", ",".join(map(str, value))
        else:
            kind, wire = "a_s", ",".join(quote(v, safe="") for v in value)
        descriptor = "|".join((attr["attr_id"], attr["operator"], quote(wire, safe=""), kind))
        params.append(f"query_attrs.${index}={descriptor}")
    if subqueries:
        params.append(
            "query_filters~o=" + json.dumps(subqueries, ensure_ascii=False, separators=(",", ":"))
        )
    return "https://voyager.intra.xiaojukeji.com/static/management/#/issue/pool?" + quote(
        "&".join(params), safe=";/?:@&=+$,#"
    )


def in_filter(field, values):
    return {"attr_id": field, "operator": "in", "val": values}


def release_namespaces(labels, release):
    suffix = "_" + release
    return {label[: -len(suffix)] for label in labels if label.endswith(suffix)}


def historical_namespaces(metadata, release):
    filename = metadata.get("source_manifest")
    if not filename:
        labels = {
            label
            for group in metadata.get("scenario_sets", {}).values()
            for key, values in group.items()
            if key.endswith("labels")
            for label in values
        }
        return release_namespaces(labels, release)

    path = resolve_report_path(filename)
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        bases = set()
        unlabelled = set()
        for row in reader:
            if row["release"] != release or row["upload_status"] not in VALID_UPLOAD_STATUSES:
                continue
            stored = release_namespaces(real_labels(row), release)
            if stored:
                bases.update(stored)
            elif sid := canonical_scenario_id(row.get("scenario_id")):
                unlabelled.add(sid)
    # Early manifests stored only IDs. Batch-read the actual tags so renamed
    # namespaces and releases split across uploads are discovered independently.
    if unlabelled:
        ids = sorted(unlabelled)
        url = settings.scenario_base_url.rstrip("/") + "/simulation/scenario/query/"
        credentials = trail_credentials(scenario=True)
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            scenes = complete_query(url, {"id": ",".join(chunk)}, *credentials, "id")
            if any(str(scene["id"]) not in chunk for scene in scenes):
                raise ValueError("scenario_id_query_mismatch")
            for scene in scenes:
                bases.update(release_namespaces(real_labels(scene), release))
    return bases


GROUPS = (
    "full",
    "release",
    "positive_auto",
    "negative_auto",
    "positive_manual",
    "pos",
    "neg",
    "normal_stop",
    "source_auto",
    "source_manual",
    "AutoTrigger",
    "ManualTrigger",
)


def road_link(release, group, common, canonical):
    auto = group in ("positive_auto", "negative_auto", "source_auto", "AutoTrigger")
    manual = group in ("positive_manual", "source_manual", "ManualTrigger")
    triggers = [2] if auto else [3] if manual else [2, 3]
    attrs = [
        *(common or [{"attr_id": "version", "operator": "like", "val": [release]}]),
        in_filter("ra_type", triggers),
    ]
    nested = []
    positive = sorted(GOOD_RESULTS)
    if canonical:
        results = (
            ["误触发"]
            if group == "negative_auto"
            else positive
            if group in ("positive_auto", "positive_manual", "ManualTrigger")
            else [*positive, "误触发"]
        )
        attrs.append(in_filter("ra_merge_result", results))
        if len(triggers) == 2:
            nested.append(
                {
                    "filter_operator": "OR",
                    "query_attrs": [
                        in_filter("ra_type", [2]),
                        in_filter("ra_merge_result", positive),
                    ],
                }
            )
    elif group in ("positive_auto", "positive_manual", "negative_auto"):
        attrs.append(
            in_filter("ra_merge_result", ["误触发"] if group == "negative_auto" else positive)
        )
    return trail_url(attrs, nested)


def platform_summary(release, queries, common=None, frozen_count=None):
    members = defaultdict(set)
    groups = {}
    all_ids = set()
    for base, query in sorted(queries.items()):
        expected = {
            (
                base if group == "full" else f"{base}_{release if group == 'release' else group}"
            ): group
            for group in GROUPS
        }
        for scene in fetch_scenarios({"scenario_query_labels": [query]}):
            labels = set(real_labels(scene))
            if query not in labels:
                raise ValueError("scenario_label_query_mismatch")
            sid = str(scene["scenario_id"])
            all_ids.add(sid)
            for label in expected.keys() & labels:
                members[label].add(sid)
                groups[label] = expected[label]
    rows = [
        {
            "group": groups[label],
            "label": label,
            "count": len(members[label]),
            "trail_url": road_link(release, groups[label], common, bool(common)),
        }
        for label in sorted(members, key=lambda name: (GROUPS.index(groups[name]), name))
    ]
    return {
        "rows": rows,
        "total_scenarios": len(all_ids),
        "frozen_count": frozen_count,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }


def for_release(db, release):
    revision = ordinary_evaluation.read(db, release)
    if revision is not None:
        scenes = revision["payload"]["scenarios"]
        bases = {
            base for scene in scenes for base in release_namespaces(real_labels(scene), release)
        }
        queries = {base: f"{base}_{release}" for base in bases}
        return platform_summary(
            release, queries, frozen_count=len({str(s["scenario_id"]) for s in scenes})
        )

    snapshot = auto_triage_metrics._snapshot(db, release)
    if (
        snapshot
        and snapshot.payload.get("scenarios")
        and snapshot.payload.get("population_complete")
        and not snapshot.payload.get("mapping_error")
    ):
        payload = snapshot.payload
        base = full_scene_label(payload["period"])
        common = [
            attr
            for attr in payload["query_attrs"]
            if attr["attr_id"] not in ("ra_type", "ra_merge_result")
        ]
        return platform_summary(release, {base: base}, common)

    version = db.get(Version, release)
    bases = historical_namespaces(version.metadata_json, release) if version else set()
    return platform_summary(release, {base: f"{base}_{release}" for base in bases})
