#!/usr/bin/env python3
"""Merge Planning Studio layout updates into an RA layout (base = RA).

Direction
---------
BASE  = RA layout (e.g. RA_stuck_swag)  — default view, active tabs, checks
DONOR = Planning layout                 — new tabs / playground nodes only

Rules
-----
1. Keep RA top-level layout, split ratios, and all activeTabIdx values.
2. Keep every existing RA tab entry and panel config as-is.
3. Append Planning tab titles that RA does not already have (no dual
   "xxx (Planning)" copies; same-title content stays RA).
4. Copy Planning-only panel configs referenced by newly appended tabs.
5. Merge Planning-only userNodes (Node Playground).
6. Voyager3DPanel checkedKeys stay RA (new playground nodes are NOT checked).
7. Voyager3DPanel expandedKeys get playground-related keys from Planning so
   new nodes are discoverable in the topic tree without being drawn.
8. Do not copy Planning-only Voyager3D subscriptions/querySnippets (those
   track checked/subscribed visibility).
9. Additive merge for missing globalVariables / topics / other maps.

Example
-------
  python3 scripts/merge_studio_layout.py \\
    --base "/home/didi/下载/RA_stuck_swag (2).json" \\
    --donor "/home/didi/下载/Planning Layout.json" \\
    --output "/home/didi/下载/RA_stuck_swag_with_planning.json" \\
    --report "/home/didi/下载/RA_stuck_swag_with_planning_REPORT.txt"
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_V3D_PANEL_ID = "Voyager3DPanel!2olm9lp"

# Topic-tree / playground markers used to decide which Planning expandedKeys
# should be unioned into the RA 3D panel (without checking them).
PLAYGROUND_MARKERS = (
    "path_smoother",
    "path_generator",
    "sl_nudge",
    "semantic_corridor",
    "time_corridor",
    "soft_nudge",
    "attraction_manager",
    "reference_arclength",
    "path_warmstarts",
    "path_iteration",
    "path_search_curve",
    "physical_ray",
    "ray_casted",
    "nudge_corridor",
    "cover_disks",
    "ml_path_guider",
    "trimmed_reference",
    "waypoint_assist",
    "open_space",
    "conditional_behavior_prediction",
    "queue_signal",
    "selected_gap",
    "optimal_reasoning_gap",
    "pull_over",
    "mdp_trajectory",
)


def load_layout(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "configById" not in data:
        raise ValueError(f"Not a Studio layout JSON (missing configById): {path}")
    return data


def collect_refs(node: Any, cfg: dict[str, Any], out: set[str]) -> None:
    """Recursively collect panel ids reachable from a layout tree + nested tabs."""
    if isinstance(node, str):
        if node in out:
            return
        out.add(node)
        c = cfg.get(node)
        if isinstance(c, dict) and isinstance(c.get("tabs"), list):
            for tab in c["tabs"]:
                if isinstance(tab, dict):
                    collect_refs(tab.get("layout"), cfg, out)
        return
    if isinstance(node, dict) and "direction" in node:
        collect_refs(node.get("first"), cfg, out)
        collect_refs(node.get("second"), cfg, out)


def topic_path_variants(output_topic: str | None) -> set[str]:
    """Return possible topic-tree keys for a studio-node output topic."""
    if not output_topic or not isinstance(output_topic, str):
        return set()
    t = output_topic.strip()
    keys: set[str] = set()
    if t.startswith("t:"):
        pure = t[2:]
        keys.add(t)
    else:
        pure = t if t.startswith("/") else "/" + t
        keys.add("t:" + pure)
    parts = pure.strip("/").split("/")
    if parts and parts[0] == "studio_node":
        parts = parts[1:]
    acc: list[str] = []
    for p in parts:
        acc.append(p)
        keys.add("&".join(f"name:{x}" for x in acc))
    return keys


def is_playground_related(key: str) -> bool:
    if not isinstance(key, str):
        return False
    return any(m in key for m in PLAYGROUND_MARKERS)


def name_chain_prefixes(keys: set[str]) -> set[str]:
    out = set(keys)
    for k in list(keys):
        if isinstance(k, str) and k.startswith("name:"):
            parts = k.split("&")
            for i in range(1, len(parts) + 1):
                out.add("&".join(parts[:i]))
    return out


def merge_tab_panel(
    panel_id: str,
    merged_cfg: dict[str, Any],
    plan_cfg: dict[str, Any],
    added_tabs: list[tuple[str, str]],
) -> bool:
    """Append only Planning tab titles that RA does not already have."""
    if panel_id not in merged_cfg or panel_id not in plan_cfg:
        return False
    m = merged_cfg[panel_id]
    p = plan_cfg[panel_id]
    if not (isinstance(m, dict) and isinstance(p, dict)):
        return False
    if not (isinstance(m.get("tabs"), list) and isinstance(p.get("tabs"), list)):
        return False

    ra_active = m.get("activeTabIdx")
    existing = {t.get("title") for t in m["tabs"] if isinstance(t, dict)}
    changed = False
    for pt in p["tabs"]:
        if not isinstance(pt, dict):
            continue
        title = pt.get("title")
        if title in existing:
            continue
        m["tabs"].append(copy.deepcopy(pt))
        existing.add(title)
        added_tabs.append((panel_id, title))
        changed = True
    if ra_active is not None:
        m["activeTabIdx"] = ra_active
    return changed


def merge_missing_map(dst: Any, src: Any) -> list[str]:
    """Add keys/items from src that dst lacks. Returns list of added key labels."""
    added: list[str] = []
    if isinstance(dst, dict) and isinstance(src, dict):
        for k, v in src.items():
            if k not in dst:
                dst[k] = copy.deepcopy(v)
                added.append(str(k))
    elif isinstance(dst, list) and isinstance(src, list):
        def item_key(t: Any) -> str:
            if isinstance(t, dict):
                return str(t.get("name") or t.get("topic") or json.dumps(t, sort_keys=True))
            return json.dumps(t, sort_keys=True)

        existing = {item_key(t) for t in dst}
        for t in src:
            k = item_key(t)
            if k not in existing:
                dst.append(copy.deepcopy(t))
                added.append(k)
                existing.add(k)
    return added


def merge_layouts(
    base: dict[str, Any],
    donor: dict[str, Any],
    *,
    v3d_panel_id: str = DEFAULT_V3D_PANEL_ID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge donor (Planning) into a deep copy of base (RA).

    Returns (merged_layout, stats_dict).
    """
    merged = copy.deepcopy(base)
    plan_cfg = donor["configById"]
    merged_cfg = merged["configById"]
    ra_cfg = base["configById"]

    added_tabs: list[tuple[str, str]] = []
    added_configs: list[str] = []
    added_user_nodes: list[tuple[str, str | None, str | None]] = []
    added_expanded: list[tuple[str, str]] = []

    # 1) Append new tab titles on shared Tab panels
    for cid in list(merged_cfg.keys()):
        if isinstance(merged_cfg.get(cid), dict) and "tabs" in merged_cfg[cid]:
            merge_tab_panel(cid, merged_cfg, plan_cfg, added_tabs)

    # 2) Pull missing configs referenced by new tabs (fixed point)
    for _ in range(30):
        refs: set[str] = set()
        collect_refs(merged["layout"], merged_cfg, refs)
        progress = False
        for cid in refs:
            if cid not in merged_cfg and cid in plan_cfg:
                merged_cfg[cid] = copy.deepcopy(plan_cfg[cid])
                added_configs.append(cid)
                progress = True
        for cid in list(merged_cfg.keys()):
            if (
                cid in plan_cfg
                and isinstance(merged_cfg.get(cid), dict)
                and "tabs" in merged_cfg[cid]
            ):
                if merge_tab_panel(cid, merged_cfg, plan_cfg, added_tabs):
                    progress = True
        if not progress:
            break

    refs = set()
    collect_refs(merged["layout"], merged_cfg, refs)
    still_missing = sorted(c for c in refs if c not in merged_cfg)

    # 3) userNodes: Planning-only playground nodes
    m_un = merged.setdefault("userNodes", {})
    if not isinstance(m_un, dict):
        m_un = {}
        merged["userNodes"] = m_un
    for k, v in (donor.get("userNodes") or {}).items():
        if k not in m_un:
            m_un[k] = copy.deepcopy(v)
            cache = (v or {}).get("executableCodeCache") or {}
            name = v.get("name") if isinstance(v, dict) else None
            ot = cache.get("outputTopic") if isinstance(cache, dict) else None
            added_user_nodes.append((k, name, ot))

    # 4) Voyager3D: keep base checkedKeys; expand playground-related donor keys
    if v3d_panel_id in plan_cfg and v3d_panel_id in merged_cfg:
        p3 = plan_cfg[v3d_panel_id]
        m3 = merged_cfg[v3d_panel_id]
        p_ck = p3.get("checkedKeys") or {}
        m_ck = m3.get("checkedKeys") or {}
        p_ek = p3.get("expandedKeys") or {}
        m_ek = m3.setdefault("expandedKeys", {})
        if not isinstance(m_ek, dict):
            m_ek = {}
            m3["expandedKeys"] = m_ek

        wanted: set[str] = set()
        for _, name, ot in added_user_nodes:
            wanted |= topic_path_variants(ot)
            wanted |= topic_path_variants(name)

        if isinstance(p_ck, dict) and isinstance(m_ck, dict):
            for mode, keys in p_ck.items():
                rset = set(m_ck.get(mode) or [])
                for k in keys or []:
                    if k not in rset:
                        wanted.add(k)
                        if isinstance(k, str) and k.startswith("t:"):
                            wanted |= topic_path_variants(k)

        if isinstance(p_ek, dict):
            for mode, keys in p_ek.items():
                for k in keys or []:
                    if is_playground_related(k):
                        wanted.add(k)
                        if isinstance(k, str) and k.startswith("t:"):
                            wanted |= topic_path_variants(k)

        wanted = name_chain_prefixes(wanted)

        modes = set()
        for d in (p_ek, m_ek, p_ck, m_ck):
            if isinstance(d, dict):
                modes.update(d.keys())

        for mode in modes:
            r_exp = list(m_ek.get(mode) or [])
            rset = set(r_exp)
            p_order = list((p_ek or {}).get(mode) or []) if isinstance(p_ek, dict) else []
            to_add: list[str] = []
            for ek in p_order:
                if ek in rset:
                    continue
                if ek in wanted or is_playground_related(ek):
                    to_add.append(ek)
                    rset.add(ek)
            for ek in sorted(wanted):
                if ek not in rset:
                    to_add.append(ek)
                    rset.add(ek)
            m_ek[mode] = r_exp + to_add
            for x in to_add:
                added_expanded.append((mode, x))

    # 5) globalVariables / topics: additive missing keys only
    m_gv = merged.setdefault("globalVariables", {})
    added_gvs = merge_missing_map(m_gv, donor.get("globalVariables") or {})

    m_topics = merged.get("topics")
    p_topics = donor.get("topics")
    added_topics: list[str] = []
    if m_topics is None and p_topics is not None:
        merged["topics"] = copy.deepcopy(p_topics)
        added_topics = ["<all>"]
    else:
        added_topics = merge_missing_map(m_topics, p_topics)

    # 6) Other maps: additive. Skip V3D subscriptions/querySnippets (visibility).
    for field in (
        "linkedGlobalVariables",
        "querySnippets",
        "roleTagToGlobalVariables",
        "subscribers",
        "subscriptions",
    ):
        mv, pv = merged.get(field), donor.get(field)
        if field in ("subscriptions", "querySnippets") and isinstance(mv, dict) and isinstance(
            pv, dict
        ):
            for panel_id, items in pv.items():
                if panel_id == v3d_panel_id:
                    continue
                if panel_id not in mv:
                    mv[panel_id] = copy.deepcopy(items)
                elif isinstance(mv[panel_id], list) and isinstance(items, list):
                    s = set(mv[panel_id])
                    for it in items:
                        if it not in s:
                            mv[panel_id].append(copy.deepcopy(it))
                            s.add(it)
            continue
        if mv is None and pv is not None:
            merged[field] = copy.deepcopy(pv)
        else:
            merge_missing_map(mv, pv)

    # ---- stats / validation ----
    active_bad = [
        cid
        for cid, rc in ra_cfg.items()
        if isinstance(rc, dict)
        and "tabs" in rc
        and merged_cfg.get(cid, {}).get("activeTabIdx") != rc.get("activeTabIdx")
    ]
    duals = [
        (cid, t.get("title"))
        for cid, c in merged_cfg.items()
        if isinstance(c, dict)
        for t in (c.get("tabs") or [])
        if isinstance(t, dict) and "(Planning)" in str(t.get("title"))
    ]
    title_issues: list[tuple[str, int, Any]] = []
    for cid, rc in ra_cfg.items():
        if not (isinstance(rc, dict) and "tabs" in rc):
            continue
        for i, t in enumerate(rc["tabs"]):
            mtabs = (merged_cfg.get(cid) or {}).get("tabs") or []
            if i >= len(mtabs) or mtabs[i] != t:
                title_issues.append((cid, i, t.get("title") if isinstance(t, dict) else t))
                break

    ck_same = True
    if v3d_panel_id in ra_cfg and v3d_panel_id in merged_cfg:
        ck_same = merged_cfg[v3d_panel_id].get("checkedKeys") == ra_cfg[v3d_panel_id].get(
            "checkedKeys"
        )

    ra_un_missing = [
        k for k in (base.get("userNodes") or {}) if k not in (merged.get("userNodes") or {})
    ]

    # dedupe tabs for report
    seen: set[tuple[str, str]] = set()
    tabs_unique: list[tuple[str, str]] = []
    for item in added_tabs:
        if item not in seen:
            seen.add(item)
            tabs_unique.append(item)

    stats: dict[str, Any] = {
        "layout_same": merged["layout"] == base["layout"],
        "active_bad": active_bad,
        "duals": duals,
        "title_issues": title_issues,
        "checked_keys_same": ck_same,
        "ra_user_nodes_missing": ra_un_missing,
        "still_missing_refs": still_missing,
        "config_counts": {
            "base": len(ra_cfg),
            "donor": len(plan_cfg),
            "merged": len(merged_cfg),
            "added_configs": len(set(added_configs)),
        },
        "added_tabs": tabs_unique,
        "added_user_nodes": added_user_nodes,
        "added_expanded_count": len(added_expanded),
        "added_global_variables": added_gvs,
        "added_topics": added_topics,
        "v3d_panel_id": v3d_panel_id,
    }

    if v3d_panel_id in merged_cfg and v3d_panel_id in ra_cfg:
        m3 = merged_cfg[v3d_panel_id]
        r3 = ra_cfg[v3d_panel_id]
        stats["v3d"] = {
            "expanded_all_base": len((r3.get("expandedKeys") or {}).get("all") or []),
            "expanded_all_merged": len((m3.get("expandedKeys") or {}).get("all") or []),
            "checked_all_base": len((r3.get("checkedKeys") or {}).get("all") or []),
            "checked_all_merged": len((m3.get("checkedKeys") or {}).get("all") or []),
        }
        # playground sample probe
        ek = set((m3.get("expandedKeys") or {}).get("all") or [])
        ck = set((m3.get("checkedKeys") or {}).get("all") or [])
        samples = {}
        for s in (
            "semantic_corridor",
            "soft_nudge",
            "sl_nudge",
            "time_corridor",
            "path_warmstarts",
            "path_iteration",
            "new_attraction",
            "reference_path",
        ):
            samples[s] = {
                "expanded": [x for x in ek if s in x][:8],
                "checked": [x for x in ck if s in x][:8],
            }
        stats["playground_samples"] = samples

    return merged, stats


def format_report(
    *,
    base_path: Path,
    donor_path: Path,
    output_path: Path,
    stats: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("Studio layout merge report")
    lines.append("BASE  = RA layout (default view / checks / active tabs)")
    lines.append("DONOR = Planning layout (new tabs + playground nodes only)")
    lines.append(f"Base:   {base_path}")
    lines.append(f"Donor:  {donor_path}")
    lines.append(f"Output: {output_path}")
    lines.append("")
    lines.append(f"layout == base: {stats['layout_same']}")
    lines.append(f"activeTabIdx preserved: {not stats['active_bad']}")
    if stats["active_bad"]:
        lines.append(f"  BAD: {stats['active_bad'][:20]}")
    lines.append(f"RA tab prefix unchanged: {not stats['title_issues']}")
    if stats["title_issues"]:
        lines.append(f"  issues: {stats['title_issues'][:20]}")
    lines.append(f"no (Planning) dual titles: {not stats['duals']} ({len(stats['duals'])})")
    lines.append(f"Voyager3D checkedKeys == base: {stats['checked_keys_same']}")
    lines.append(f"RA userNodes preserved: {not stats['ra_user_nodes_missing']}")
    cc = stats["config_counts"]
    lines.append(
        f"configById base={cc['base']} donor={cc['donor']} "
        f"merged={cc['merged']} (+{cc['added_configs']} panels)"
    )
    lines.append(f"still missing refs: {stats['still_missing_refs']}")
    lines.append(f"added userNodes: {len(stats['added_user_nodes'])}")
    lines.append(f"added expandedKeys entries: {stats['added_expanded_count']}")
    lines.append(f"added globalVariables: {len(stats['added_global_variables'])}")
    lines.append(f"added topics: {stats['added_topics']}")
    if "v3d" in stats:
        v = stats["v3d"]
        lines.append(
            f"expandedKeys[all]: base={v['expanded_all_base']} merged={v['expanded_all_merged']}"
        )
        lines.append(
            f"checkedKeys[all]:  base={v['checked_all_base']} merged={v['checked_all_merged']}"
        )
    lines.append("")
    lines.append("=== New tabs ===")
    by: dict[str, list[str]] = defaultdict(list)
    for pid, title in stats["added_tabs"]:
        by[pid].append(title)
    if not by:
        lines.append("(none)")
    for pid in sorted(by):
        lines.append(f"{pid}:")
        for title in by[pid]:
            lines.append(f"  + {title!r}")
    lines.append("")
    lines.append("=== Sample new playground userNodes ===")
    shown = 0
    for _k, name, ot in stats["added_user_nodes"]:
        s = f"{name} -> {ot}"
        if any(
            x in s
            for x in (
                "path_smoother",
                "sl_nudge",
                "semantic",
                "nudge",
                "time_corridor",
                "assist",
                "attraction",
                "reference_arc",
                "open_space",
            )
        ):
            lines.append(f"  {name} -> {ot}")
            shown += 1
    if shown == 0:
        lines.append(f"  (total added: {len(stats['added_user_nodes'])})")
    if stats.get("playground_samples"):
        lines.append("")
        lines.append("=== Playground samples (expanded vs checked) ===")
        for s, v in stats["playground_samples"].items():
            lines.append(f"{s}:")
            lines.append(f"  expanded: {v['expanded']}")
            lines.append(f"  checked:  {v['checked']}")
    lines.append("")
    ok = (
        stats["layout_same"]
        and not stats["active_bad"]
        and not stats["title_issues"]
        and not stats["duals"]
        and stats["checked_keys_same"]
        and not stats["ra_user_nodes_missing"]
        and not stats["still_missing_refs"]
    )
    lines.append(f"OVERALL_OK: {ok}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Merge Planning Studio layout updates into an RA layout. "
            "BASE=RA (keep default view); DONOR=Planning (add tabs/playground, unchecked)."
        )
    )
    p.add_argument(
        "--base",
        required=True,
        type=Path,
        help="RA layout JSON (e.g. RA_stuck_swag). Kept as default view.",
    )
    p.add_argument(
        "--donor",
        required=True,
        type=Path,
        help="Planning layout JSON. Source of new tabs and playground nodes.",
    )
    p.add_argument(
        "--output",
        "-o",
        required=True,
        type=Path,
        help="Output merged layout JSON path.",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional text report path (default: <output>.report.txt).",
    )
    p.add_argument(
        "--v3d-panel-id",
        default=DEFAULT_V3D_PANEL_ID,
        help=f"Voyager3D panel id to keep checkedKeys from base (default: {DEFAULT_V3D_PANEL_ID}).",
    )
    p.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON (no indent). Default is indent=2.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_path: Path = args.base.expanduser().resolve()
    donor_path: Path = args.donor.expanduser().resolve()
    output_path: Path = args.output.expanduser().resolve()
    report_path: Path = (
        args.report.expanduser().resolve()
        if args.report
        else output_path.with_suffix(output_path.suffix + ".report.txt")
    )

    if not base_path.is_file():
        print(f"ERROR: base layout not found: {base_path}", file=sys.stderr)
        return 2
    if not donor_path.is_file():
        print(f"ERROR: donor layout not found: {donor_path}", file=sys.stderr)
        return 2

    base = load_layout(base_path)
    donor = load_layout(donor_path)
    merged, stats = merge_layouts(base, donor, v3d_panel_id=args.v3d_panel_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.compact:
        text = json.dumps(merged, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(text, encoding="utf-8")

    report = format_report(
        base_path=base_path,
        donor_path=donor_path,
        output_path=output_path,
        stats=stats,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote layout: {output_path} ({output_path.stat().st_size} bytes)")
    print(f"Wrote report: {report_path}")

    ok = (
        stats["layout_same"]
        and not stats["active_bad"]
        and not stats["title_issues"]
        and not stats["duals"]
        and stats["checked_keys_same"]
        and not stats["ra_user_nodes_missing"]
        and not stats["still_missing_refs"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
