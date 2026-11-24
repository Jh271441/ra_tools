"""Import verified Scenario publications and serve their revision-bound label groups."""
import json
import re
from hashlib import sha256
from urllib.parse import parse_qs, unquote, urlsplit

from app.services import evaluation_pipeline as pipeline, release_workflow as workflow
from app.services.release_cycle import digest

SCOPES = ("all_business", "nontraffic_business", "traffic_light", "EOL", "traffic_EOL")
OUTCOMES = ("成功", "失败", "无需协助", "误触发", "正确触发")


def state_key(ctx, revision):
    return "evlabel_summary:" + digest([ctx, revision])[:48]


def read(db, ctx, revision):
    canonical, _, _, key = pipeline.context(db, **ctx)
    if workflow.get_state(db, key).get("revision_key") == revision:
        value = workflow.get_state(db, state_key(canonical, revision))
        if value.get("context") == canonical and value.get("revision_key") == revision:
            return value
    return {"status": "missing"}


def issue_ids(url):
    if not url:
        return set()
    parts = urlsplit(url)
    path, sep, query = parts.fragment.partition("?")
    if (parts.scheme, parts.netloc, parts.path, path, sep) != (
            "https", "voyager.intra.xiaojukeji.com", "/static/management/", "/issue/pool", "?"):
        raise ValueError("invalid_trail_issue_link")
    attrs = parse_qs(query)
    descriptors = [k for k in attrs if k.startswith("query_attrs") or k.startswith("query_filters")]
    if descriptors != ["query_attrs.$0"] or len(attrs[descriptors[0]]) != 1:
        raise ValueError("unexpected_trail_filters")
    field, operator, value, kind = attrs[descriptors[0]][0].split("|")
    ids = unquote(value).split(",")
    if ((field, operator, kind) != ("issue_id", "in", "a_s") or len(ids) != len(set(ids))
            or not all(re.fullmatch(r"cn\d+", i) for i in ids)):
        raise ValueError("invalid_trail_issue_filter")
    return set(ids)


def project(data, plan, receipt, revision):
    ctx = {k: data[k] for k in ("release", "date_start", "date_end")}
    ctx["profile_id"] = data["profile"]
    entries = plan["entries"]
    summary, wb = data["scenario_label_summary"], data["workbench"]
    publication = data["scenario_source_publication"]
    plan_hash = sha256(json.dumps({k: v for k, v in plan.items() if k != "plan_id"},
                                 sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if (revision["context"] != ctx or revision["reconciliation"]["status"] != "matched"
            or plan["plan_id"] != receipt["plan_id"] or plan["plan_id"] != data["scenario_source_plan"]
            or plan_hash != plan["plan_id"]
            or plan["snapshot_sha256"] != data["ground_truth_sha256"] or receipt["snapshot_sha256"] != plan["snapshot_sha256"]
            or receipt["verified"] != publication["verified_scenarios"] or len(entries) != receipt["verified"]
            or receipt["completed_at"] != publication["completed_at"]
            or plan["gt_publication_plan"] != receipt["gt_publication_plan"]
            or data["ground_truth_source_priority"] != ["ra_review_result_new", "ra_rd_review_result", "ra_stuck_auto_result", "TO"]
            or wb["revision"] != summary["workbench_revision"] or wb["observed_at"] != summary["workbench_observed_at"]
            or wb["dataset"] != "release-" + ctx["release"].removeprefix("gen4-release-") + "-odd2"):
        raise ValueError("label_summary_receipt_mismatch")
    eligible = {str(sid): (r["issue_id"], r["auto_label"], r["label_source"])
                for r in revision["rows"] if r["eligible"] for sid in r["scenario_ids"]}
    if eligible != {sid: (r["issue_id"], r["label"], r["source"]) for sid, r in entries.items()}:
        raise ValueError("label_summary_evaluation_changed")
    all_issues = issue_ids(wb["all_issue_trail_url"])
    published = issue_ids(wb["published_issue_trail_url"])
    if not published <= all_issues or len(all_issues) != wb["issue_total"] or len(published) != wb["published_issue_count"]:
        raise ValueError("workbench_population_changed")

    def check(row, scenes):
        ids = {s["issue_id"] for s in scenes}
        if (len(scenes), len(ids), len(ids & published), ids) != (
                row["scenario_count"], row["issue_count"], row["published_issue_count"], issue_ids(row["trail_issue_url"])):
            raise ValueError("label_group_membership_changed")

    scopes = {}
    for key in SCOPES:
        scope = summary["scopes"][key]
        label = receipt["scope_label"] if key == "all_business" else receipt["groups"][key]["label"]
        scenes = [s for s in entries.values() if label in s["add_labels"]]
        if key != "all_business" and len(scenes) != publication["verified_source_label_counts"][key]:
            raise ValueError("published_scope_count_changed")
        if scope["scenario_labels_all_of"] != [label]:
            raise ValueError("label_scope_changed")
        check(scope, scenes)
        outcomes = {row["result"]: row for row in scope["outcomes"]}
        if len(scope["outcomes"]) != len(OUTCOMES) or set(outcomes) != set(OUTCOMES):
            raise ValueError("label_outcomes_changed")
        for result, row in outcomes.items():
            labels = [label, receipt["scope_label"] + "_" + result]
            selected = [s for s in scenes if s["label"] == result]
            if row["scenario_labels_all_of"] != labels or any(not set(labels) <= set(s["add_labels"]) for s in selected):
                raise ValueError("label_outcome_tags_changed")
            check(row, selected)
        scopes[key] = {k: scope[k] for k in ("scenario_count", "issue_count", "published_issue_count")}
        fields = ("result", "scenario_labels_all_of", "scenario_count", "published_issue_count", "trail_issue_url")
        scopes[key]["outcomes"] = [{k: outcomes[result][k] for k in fields} for result in OUTCOMES]
    return {"status": "complete", "context": ctx, "revision_key": revision["revision_key"],
            "ground_truth_sha256": data["ground_truth_sha256"], "publication": publication,
            "workbench": {k: wb[k] for k in ("dataset", "revision", "observed_at", "issue_total", "published_issue_count")},
            "scopes": scopes}
