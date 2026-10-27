"""Read-only Issue subtag selection: OR within a group, AND across groups."""

GROUPS = ("environment", "self_intent", "false_trigger", "true_trigger", "ra", "no_assist")


def parse_issue_tag_groups(value, catalog, aliases):
    values = [item.strip() for item in str(value or "").split(",") if item.strip()]
    if len(values) > 256 or len(str(value or "")) > 16384:
        raise ValueError("Issue 标签筛选过多 / Too many Issue tag filters")
    by_key = {str(item["key"]): item for item in catalog}
    groups = {}
    for raw in values:
        key = aliases.get(raw, raw)
        item = by_key.get(key)
        if not item or item.get("group") not in GROUPS:
            raise ValueError("不支持的 Issue 标签筛选 / Unsupported Issue tag filter")
        groups.setdefault(item["group"], set()).add(key)
    return tuple(tuple(sorted(groups[group])) for group in GROUPS if group in groups)


def matches_issue_tag_groups(tags, groups, aliases):
    actual = {aliases.get(str(tag), str(tag)) for tag in tags or []}
    return all(actual.intersection(group) for group in groups)
