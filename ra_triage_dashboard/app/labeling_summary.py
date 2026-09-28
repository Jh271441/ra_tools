"""Aggregate current Case projections without counting history revisions twice."""
from collections import Counter, defaultdict

LABELS = ("误触发", "正确触发", "无需协助")


def summarize_labeling_cases(items):
    states, outputs, pairs, tags, scenarios = (Counter() for _ in range(5))
    people = defaultdict(set)
    annotated = 0
    for item in items:
        status = item.get("label_state", "pending")
        states[status] += 1
        output, gt = item.get("expected_output"), item.get("gt_label")
        if status == "resolved" and output in LABELS:
            outputs[output] += 1
            if gt in LABELS:
                pairs[(gt, output)] += 1
        case_tags, authors = set(), set()
        for case in item.get("label_cases", []):
            for head in case.get("resolution", {}).get("heads", []):
                case_tags.update(head.get("tags") or [])
                if head.get("author"):
                    authors.add(head["author"].strip().lower())
        if authors:
            annotated += 1
        for author in authors:
            people[author].add(item["issue_id"])
        tags.update(case_tags)
        if item.get("scenario"):
            scenarios[item["scenario"]] += 1
    return {
        "total": len(items), "annotated": annotated,
        "states": dict(states), "outputs": dict(outputs),
        "pairs": [{"gt": gt, "label": output, "count": count}
                  for (gt, output), count in sorted(pairs.items())],
        "tags": dict(tags), "scenarios": dict(scenarios),
        "people": [{"name": name, "count": len(ids)} for name, ids in
                   sorted(people.items(), key=lambda entry: (-len(entry[1]), entry[0]))],
    }
