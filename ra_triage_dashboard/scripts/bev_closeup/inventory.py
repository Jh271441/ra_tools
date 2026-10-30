"""Freeze complete version membership using read-only Workbench APIs."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener

from contract import save

API = "http://127.0.0.1:8785"
ISSUE = re.compile(r"cn\d+")
TRIP = re.compile(r"[A-Za-z0-9_-]{1,100}")


def get(path, **query):
    url = API + path + ("?" + urlencode(query) if query else "")
    for attempt in range(3):
        try:
            with build_opener(ProxyHandler({})).open(url, timeout=45) as response:
                raw = response.read(16 * 1024**2 + 1)
            if len(raw) > 16 * 1024**2:
                raise ValueError("oversized_platform_response")
            return json.loads(raw)
        except (OSError, ValueError) as exc:
            if isinstance(exc, HTTPError) and exc.code in (400, 404, 409):
                raise
            if attempt == 2:
                raise
            time.sleep(2)


def version_members(family):
    path = f"/api/version-datasets/release-{family}-odd2/workbench"
    first = get(path, mode="all", sort="issue", page_size=100)
    rows = list(first["items"])
    revision = first["snapshot_revision"]
    for page in range(2, (first["total"] + 99) // 100 + 1):
        data = get(path, mode="all", sort="issue", page=page, page_size=100, revision=revision)
        if data["snapshot_revision"] != revision:
            raise ValueError("version_snapshot_changed")
        rows.extend(data["items"])
    if len(rows) != first["total"] or len({r["issue_id"] for r in rows}) != len(rows):
        raise ValueError("version_membership_incomplete")
    return revision, rows


def baseline_members(baseline):
    def scan():
        rows, page = [], 1
        while True:
            data = get("/api/cases", baselines=baseline, page=page, page_size=100)
            rows.extend(data["items"])
            if len(rows) >= data["total"]:
                if len(rows) != data["total"]:
                    raise ValueError("baseline_membership_incomplete")
                return rows
            page += 1
    rows = scan()
    if sorted(r["issue_id"] for r in rows) != sorted(r["issue_id"] for r in scan()):
        raise ValueError("baseline_membership_changed")
    return rows


def media_sources(layouts_root, scopes):
    sources = {}
    for scope in scopes:
        root = (Path(layouts_root) / scope).resolve()
        if not root.is_relative_to(Path(layouts_root).resolve()):
            raise ValueError("invalid_media_scope")
        manifest = root / "manifest.jsonl"
        if not manifest.is_file():
            continue
        for line in manifest.read_text().splitlines():
            try:
                row = json.loads(line)
                meta_path = (root / row["meta_path"]).resolve()
                if not meta_path.is_relative_to(root) or meta_path.stat().st_size > 4 * 1024**2:
                    continue
                meta = json.loads(meta_path.read_text())
                source = meta.get("source_row") or {}
                trip = source.get("trip_id") or meta.get("trip_id")
                anchor = source.get("capture_timestamp_ms") or meta.get("request_timestamp_ms")
                if meta.get("status") != "captured" or not isinstance(trip, str) or not TRIP.fullmatch(trip) or type(anchor) is not int or anchor <= 0:
                    continue
                key = (scope, row["issue_id"])
                value = dict(trip_id=trip, capture_timestamp_ms=anchor, anchor_source="existing_media", media_meta_path=str(meta_path))
                if key in sources and sources[key] != value:
                    raise ValueError("conflicting_media_anchors")
                sources[key] = value
            except (KeyError, OSError, json.JSONDecodeError, TypeError):
                continue
    return sources


def add_legacy_scopes(snapshot):
    """Keep a version member's still-registered historical media aliases.

    Only an independently read registered baseline membership can add a scope;
    this never adds an Issue to the frozen target cohort or changes its anchor.
    """
    members = {r['issue_id']: r for r in snapshot['members']}
    cohorts = []
    for baseline in get('/health').get('baselines', []):
        bid = str(baseline.get('id', ''))
        match = re.fullmatch(r'(1009|1016)-\d{4}-\d{2}-\d{2}', bid)
        if not match:
            continue
        rows = baseline_members(bid)
        applied = []
        for alias in rows:
            row = members.get(alias['issue_id'])
            if row is None or row['version'] != match[1]:
                continue
            scope = alias.get('baseline_scope')
            if not scope or scope != baseline.get('scope'):
                raise ValueError('legacy_media_scope_conflict')
            row['scopes'] = sorted(set(row.get('scopes', [])) | {scope})
            applied.append(row['issue_id'])
        cohorts.append(dict(baseline_id=bid, scope=baseline.get('scope'),
                            members_sha256=hashlib.sha256('\n'.join(sorted(r['issue_id'] for r in rows)).encode()).hexdigest(),
                            registered=len(rows), applied_issue_ids=applied))
    snapshot['legacy_scope_evidence'] = cohorts
    return snapshot


def build_snapshot(layouts_root, incremental=False):
    members, cohorts = {}, []
    for baseline in (() if incremental else ("0821", "0821-review-extra")):
        rows = baseline_members(baseline)
        cohorts.append(dict(version="0821", dataset=baseline, count=len(rows)))
        for row in rows:
            iid = row["issue_id"]
            rec = members.setdefault(iid, dict(issue_id=iid, version="0821", state="published", scopes=[], datasets=[]))
            rec["datasets"].append(baseline)
            rec["scopes"].append(row["baseline_scope"])
    families = ("20261009", "20261016")
    if incremental:
        families = sorted({r["release_family"] for r in get("/api/version-datasets")["items"]
                           if re.fullmatch(r"release-20\d{6}-odd2", str(r.get("id", "")))
                           and re.fullmatch(r"20\d{6}", str(r.get("release_family", "")))
                           and r["release_family"] >= "20261009"})
    for family in families:
        revision, rows = version_members(family)
        cohorts.append(dict(version=family[4:], dataset=f"release-{family}-odd2", revision=revision, count=len(rows)))
        for row in rows:
            iid = row["issue_id"]
            if iid in members:
                raise ValueError("cross_version_membership_conflict")
            members[iid] = dict(issue_id=iid, version=family[4:], state=row["state"],
                                scopes=["manual_sidecar_version_" + family], datasets=[f"release-{family}-odd2"],
                                registry_trip_id=row.get("trip_id"), registry_anchor_ms=row.get("ra_start_timestamp"),
                                software_version=row.get("software_version"), source_error=row.get("error"))
    if any(not ISSUE.fullmatch(i) for i in members):
        raise ValueError("invalid_issue_id")
    sources = media_sources(layouts_root, {s for r in members.values() for s in r["scopes"]})
    for iid, row in members.items():
        options = [sources[(s, iid)] for s in row["scopes"] if (s, iid) in sources]
        identities = {(r["trip_id"], r["capture_timestamp_ms"]) for r in options}
        if len(identities) > 1:
            row["source_status"] = "anchor_conflict"
        elif options:
            row.update(options[0], source_status="ready")
            if row.get("registry_anchor_ms") and (row["registry_anchor_ms"] != row["capture_timestamp_ms"] or row["registry_trip_id"] != row["trip_id"]):
                row["source_status"] = "anchor_conflict"
        elif (isinstance(row.get("registry_trip_id"), str) and TRIP.fullmatch(row["registry_trip_id"])
              and type(row.get("registry_anchor_ms")) is int and row["registry_anchor_ms"] > 0):
            row.update(trip_id=row["registry_trip_id"], capture_timestamp_ms=row["registry_anchor_ms"], anchor_source="version_registry_event", source_status="ready")
        else:
            row["source_status"] = "missing_anchor"
        row["scopes"] = sorted(set(row["scopes"]))
    return add_legacy_scopes(dict(created_at=time.time(), platform_sha=get("/health")["build_commit"], cohorts=cohorts,
                membership_sha256=hashlib.sha256("\n".join(sorted(members)).encode()).hexdigest(),
                members=sorted(members.values(), key=lambda r: (r["version"], r["issue_id"])) ))


def freeze(root, layouts_root):
    root = Path(root)
    dest = root / "membership.json"
    if dest.exists():
        return json.loads(dest.read_text())
    data = build_snapshot(layouts_root)
    save(dest, data)
    return data


def resolve_missing(rows):
    """Old registered layouts may live outside the materialized media root.

    Read only their existing public BEV descriptor. A 404 is unresolved media
    registration, never proof that the raw trip or planning source is absent.
    """
    def one(row):
        result = dict(row)
        try:
            capture = (get("/api/cases/" + row["issue_id"] + "/media", kind="bev").get("assets") or {}).get("capture") or {}
            trip, anchor = capture.get("trip_id"), capture.get("timestamp_ms")
            if isinstance(trip, str) and TRIP.fullmatch(trip) and type(anchor) is int and anchor > 0:
                result.update(trip_id=trip, capture_timestamp_ms=anchor, anchor_source="existing_media",
                              source_status="ready", source_api="/api/cases/" + row["issue_id"] + "/media?kind=bev")
        except HTTPError as exc:
            result["source_lookup_status"] = "not_in_manual" if exc.code == 404 else "lookup_failed"
        except (OSError, ValueError, KeyError):
            result["source_lookup_status"] = "lookup_failed"
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(one, rows))
